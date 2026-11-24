"""
liasion_translator_setup.py  —  SOLEIL II liaison & translator
==============================================================

Design-view architecture: the magnet Tango device IS the control source.
There are no power converters — the magnet device writes main_strength/kicks
directly to the AT element via the new property proxy architecture.

Property name conventions (must match ElementPropertyInterface.handles_property()):
    Quadrupole  → "main_strength"  (MainStrengthForQuadrupole → K / PolynomB[1])
    Sextupole   → "main_strength"  (MainStrengthForSextupole  → H / PolynomB[2])
    Octupole    → "B4"             (Multipole(normal, 4)       → PolynomB[3])
    H-steerer   → "B1"            (Multipole normal order 1   → PolynomB[0])
    V-steerer   → "A1"            (Multipole skew order 1     → PolynomA[0])
    SkewQuad    → "A2"             (Multipole(skew, 2)         → PolynomA[1])
    Cavity      → "frequency"     (Frequency                  → obj.Frequency)

The liaison maps device properties to lattice element properties.
The proxy (in dt4acc_lib) then knows how to read/write each property on the AT object.

build_managers() always returns (yp, lm, tm) — three values.

The engine translates the magnets' commands (device name -> host element)
through these, the one conversion path of the twin (engine in the device
view, see mexec_server_for_physics_engine.translated_design_view): the
magnets' slopes are 1 (lattice coefficients) or, if enabled
(DT4ACC_INTEGRATED_STRENGTH=1), their integrated strength factors (see
dt4acc.custom_facility.model.at_integrated_strength). The cavities' lattice
elements are also addressed directly by their UUID (identity conversions):
the cavity devices, the cavity power converter and the ring simulator write
these.
"""

import functools
import logging
from typing import Dict, Sequence

from dt4acc_lib.bl.yellow_pages import YellowPages
from dt4acc_lib.bl.liaison_manager import LiaisonManager
from dt4acc_lib.bl.translator_service import TranslatorService
from dt4acc_lib.interfaces.utils.yellow_pages import YellowPagesBase
from dt4acc_lib.model.utils.identifiers import (
    LatticeElementPropertyID, DevicePropertyID, ConversionID
)
from dt4acc_lib.model.utils.liaison_manager_lookup_table import (
    LiaisonManagerInverseLookupTable,
    LiaisonManagerInverseLookupElement,
)
from dt4acc_lib.model.utils.translator_manager_lookup_table import (
    TranslatorLookupTable,
    TranslatorLookupTableElement,
    PolynomCoefficients,
    IdentityMapper,
)

from dt4acc.config.data.constants import ring_parameters
from dt4acc.core.bl.handle_lattice import lattice_loader
from dt4acc.custom_facility.model import at_integrated_strength
from dt4acc.custom_facility.model.config.elementmodel import MagnetElementSetup
from dt4acc.config.data.querries import get_controlled_elements, get_unique_power_converters_for_types, get_elements_per_power_converter
from dt4acc.custom_facility.soleil.soleil_yellow_pages import soleil_yellow_pages

logger = logging.getLogger("dt4acc_lm")


# ---------------------------------------------------------------------------
# TranslatorService and LiaisonManager both imported from dt4acc_lib
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _remove_id(d: Dict) -> Dict:
    """Strip _id and normalise uuid → uuids for MagnetElementSetup."""
    nd = d.copy()
    nd.pop("_id", None)
    if "uuid" in nd and "uuids" not in nd:
        nd["uuids"] = [nd.pop("uuid")]
    elif "uuid" in nd:
        nd.pop("uuid")
    return nd


def _get_cavity_names() -> list:
    """Return cavity device names directly from the setup JSON."""
    return [m["name"] for m in get_controlled_elements() if m.get("type") == "RFCavity"]


def _get_cavity_uuids() -> dict:
    """Cavity device name -> its lattice element (UUID, else the name)."""
    return {
        m["name"]: (m.get("uuid") or m["name"])
        for m in get_controlled_elements() if m.get("type") == "RFCavity"
    }


def magnet_infos_from_db() -> Sequence[MagnetElementSetup]:
    known = {
        "name", "magnetic_strength", "uuids", "curves", "length",
        "subtype", "type", "pc", "k", "FamName",
    }
    result = []
    for raw in get_controlled_elements():
        d = _remove_id(raw)
        filtered = {k: v for k, v in d.items() if k in known}
        try:
            result.append(MagnetElementSetup(**filtered))
        except Exception as e:
            logger.error("Failed to create MagnetElementSetup for %s: %s",
                         d.get("name"), e)
    return result


def _lattice_property(element_name: str, yp: YellowPages) -> str:
    """
    Return the lattice element property name for a given magnet.
    These names must match ElementPropertyInterface.handles_property()
    in the dt4acc_lib property proxy classes.

        Quadrupole  → "main_strength"  (MainStrengthForQuadrupole)
        Sextupole   → "main_strength"  (MainStrengthForSextupole)
        Octupole    → "B4"             (Multipole(normal, 4))
        H-steerer   → "B1"            (PolynomB[0])
        V-steerer   → "A1"            (PolynomA[0])
        SkewQuad    → "A2"             (Multipole(skew, 2))
        Cavity      → "frequency"     (Frequency)
    """
    if element_name in yp.horizontal_steerer_names():
        return "B1"
    elif element_name in yp.vertical_steerer_names():
        return "A1"
    elif element_name in yp.quadrupole_names():
        return "main_strength"
    elif element_name in yp.sextupole_names():
        return "main_strength"
    elif element_name in yp.octupole_names():
        # Octupole in AT is a Multipole element — liaison maps to B4
        # Multipole(normal_skew=NormalSkew.normal, n_multipole=4).handles_property() == "B4"
        return "B4"
    elif element_name in yp.quadrupole_corrector_names():
        # CQLN: normal quadrupole corrector on octupole → PolynomB[1]
        # Multipole(normal_skew=NormalSkew.normal, n_multipole=2).handles_property() == "B2"
        return "B2"
    elif element_name in yp.skew_quadrupole_corrector_names():
        # CQLT: skew quadrupole corrector on octupole → PolynomA[1]
        # Multipole(normal_skew=NormalSkew.skew, n_multipole=2).handles_property() == "A2"
        return "A2"
    elif element_name in yp.cavity_names():
        return "frequency"
    else:
        raise AssertionError(f"Don't know how to handle {element_name!r}")


def _build_name_to_uuid(infos) -> dict:
    """Map Tango device name → uuid for host element lookup."""
    return {info.name: (info.uuids[0] if info.uuids else info.name) for info in infos}


def _host_element_name(element_name: str, yp: YellowPages, name_to_uuid: dict = None) -> str:
    if (element_name in yp.horizontal_steerer_names()
            or element_name in yp.vertical_steerer_names()):
        if name_to_uuid:
            return name_to_uuid.get(element_name, element_name)
        return element_name

    if element_name in yp.skew_quadrupole_corrector_names():
        return yp.skew_quadrupole_corrector_host_id(element_name)

    if element_name in yp.quadrupole_corrector_names():
        return yp.quadrupole_corrector_host_id(element_name)

    if name_to_uuid:
        return name_to_uuid.get(element_name, element_name)

    return element_name
# Magnet types that have a control interface in SOLEIL design view.
_CONTROLLED_TYPES = {
    "Quadrupole", "Sextupole", "Octupole", "Multipole", "Steerer", "Corrector",
    "SkewQuadrupoleCorrector", "RFCavity", "QuadrupoleCorrector"
}


def _magnet_entries(infos, yp: YellowPages, name_to_uuid: dict):
    """(info, device property, host element, lattice property) of the magnets

    The controlled types, and the main dipoles ("Bend": their devices read
    and write their main_strength, the bending field, unchanged by the
    integrated strengths).
    """
    for info in infos:
        if info.type == "Bend":
            host = name_to_uuid.get(info.name, info.name)
            yield info, "main_strength", host, "main_strength"
            continue
        if info.type not in _CONTROLLED_TYPES:
            continue
        dev_prop = _lattice_property(info.name, yp)  # device exposes same name as proxy
        lat_prop = _lattice_property(info.name, yp)  # proxy property name
        yield info, dev_prop, _host_element_name(info.name, yp, name_to_uuid), lat_prop


# ---------------------------------------------------------------------------
# build_managers
# ---------------------------------------------------------------------------
def build_managers(strength_factors: dict = None):
    """
    Build and return (yp, lm, tm) for the SOLEIL II design-view twin.

    Design-view: no power converters. Magnet devices map device properties
    directly to lattice element properties via the new property proxy architecture.
    Unit conversions are linear, no energy dependence: slope 1, but for the
    magnets ``strength_factors`` {(element, lattice property): factor}
    (integrated strengths, see strength_factors_from_lattice).
    """
    strength_factors = strength_factors or {}
    yp = soleil_yellow_pages()
    infos = magnet_infos_from_db()
    cavity_names = _get_cavity_names()
    cavity_uuids = _get_cavity_uuids()

    cavity_pc_names = get_unique_power_converters_for_types(["RFCavity"])

    magnet_names = [info.name for info in infos]
    if len(set(magnet_names)) != len(infos):
        raise AssertionError("Magnet names are not unique — required for LUT correctness")

    # Map Tango name → UUID for host element resolution
    name_to_uuid = _build_name_to_uuid(infos)

    # intercept=0.0, slope=1.0 → PolynomCoefficients(coeffs=[0.0, 1.0], energy_dependent=False)
    _poly = lambda: PolynomCoefficients(coeffs=[0.0, 1.0], energy_dependent=False)

    # ------------------------------------------------------------------
    # Inverse LUT  (DevicePropertyID → LatticeElementPropertyID)
    # ------------------------------------------------------------------
    inverse_lut: dict = {}

    # All magnets — device property → lattice element property
    # The device property name is what the Tango device exposes (e.g. "main_strength")
    # The lattice property name is what the proxy handles (e.g. "main_strength", "B4", "A2")
    magnet_entries = list(_magnet_entries(infos, yp, name_to_uuid))
    for info, dev_prop, host, lat_prop in magnet_entries:
        inverse_lut[
            DevicePropertyID(device_name=info.name, property=dev_prop)
        ] = (LatticeElementPropertyID(element_name=host, property=lat_prop),)

    # Cavities → frequency and voltage of their lattice element, by name and
    # (identity: the devices writing the lattice element) by UUID
    for name in cavity_names:
        uuid = cavity_uuids[name]
        for prop in ("frequency", "voltage"):
            for dev_name in (name, uuid):
                inverse_lut[
                    DevicePropertyID(device_name=dev_name, property=prop)
                ] = (LatticeElementPropertyID(element_name=uuid, property=prop),)

    # Master clock → all cavity frequencies
    inverse_lut[
        DevicePropertyID(device_name="master_clock", property="reference_frequency")
    ] = tuple(
        LatticeElementPropertyID(element_name=cavity_uuids[name], property="frequency")
        for name in cavity_names
    )

    # Cavity power converter(s) → controlled cavity voltages (each PC maps to its own cavities)
    for cavity_pc_name in cavity_pc_names:
        controlled = [m["name"] for m in get_elements_per_power_converter(cavity_pc_name)
                      if m.get("type") == "RFCavity"]
        if controlled:
            inverse_lut[
                DevicePropertyID(device_name=cavity_pc_name, property="set_current")
            ] = tuple(
                LatticeElementPropertyID(element_name=cavity_uuids.get(name, name), property="voltage")
                for name in controlled
            )

    # Virtual result IDs — passthrough (tune, twiss, track, orbit, chromaticity)
    for virtual_id, prop in [
        ("twiss",        "parameters"),
        ("tune",         "transversal"),
        ("chromaticity", "transversal"),
        ("track",        "pos"),
        ("orbit",        "pos"),
    ]:
        inverse_lut[
            DevicePropertyID(device_name=virtual_id, property=prop)
        ] = (LatticeElementPropertyID(element_name=virtual_id, property=prop),)

    lm = LiaisonManager(
        forward_lut=None,
        inverse_lut=LiaisonManagerInverseLookupTable(lut=[
            LiaisonManagerInverseLookupElement(dev_id=k, lat_ids=v)
            for k, v in inverse_lut.items()
        ])
    )

    # ------------------------------------------------------------------
    # Translator LUT  (ConversionID → StateConversion)
    # slope=1.0 for all SOLEIL magnets — design view, no current→field conversion.
    # ------------------------------------------------------------------
    translator_lut: dict = {}

    # All magnets — same set as inverse_lut
    for info, dev_prop, host, lat_prop in magnet_entries:
        # device = factor * lattice: 1, or the integrated strength factor
        factor = strength_factors.get((host, lat_prop), 1.0)
        translator_lut[ConversionID(
            LatticeElementPropertyID(element_name=host, property=lat_prop),
            DevicePropertyID(device_name=info.name, property=dev_prop),
        )] = PolynomCoefficients(coeffs=[0.0, factor], energy_dependent=False)

    # Cavities — Hz ↔ Hz, V ↔ V, slope=1.0, by name and by UUID
    for name in cavity_names:
        uuid = cavity_uuids[name]
        for prop in ("frequency", "voltage"):
            for dev_name in (name, uuid):
                translator_lut[ConversionID(
                    LatticeElementPropertyID(element_name=uuid, property=prop),
                    DevicePropertyID(device_name=dev_name, property=prop),
                )] = _poly()

    # Master clock — kHz on master clock device
    for name in cavity_names:
        translator_lut[ConversionID(
            LatticeElementPropertyID(element_name=cavity_uuids[name], property="frequency"),
            DevicePropertyID(device_name="master_clock", property="reference_frequency"),
        )] = PolynomCoefficients(coeffs=[0.0, 1e-3], energy_dependent=False)  # kHz on master clock

    # Cavity power converter — V on both sides, slope=1.0 (design view: no current→voltage conversion)
    for cavity_pc_name in cavity_pc_names:
        controlled = [m["name"] for m in get_elements_per_power_converter(cavity_pc_name)
                      if m.get("type") == "RFCavity"]
        for name in controlled:
            translator_lut[ConversionID(
                LatticeElementPropertyID(element_name=cavity_uuids.get(name, name), property="voltage"),
                DevicePropertyID(device_name=cavity_pc_name, property="set_current"),
            )] = _poly()

    # Virtual result IDs — identity passthrough (no conversion)
    for virtual_id, prop in [
        ("twiss",        "parameters"),
        ("tune",         "transversal"),
        ("chromaticity", "transversal"),
        ("track",        "pos"),
        ("orbit",        "pos"),
    ]:
        translator_lut[ConversionID(
            LatticeElementPropertyID(element_name=virtual_id, property=prop),
            DevicePropertyID(device_name=virtual_id, property=prop),
        )] = IdentityMapper()

    tm = TranslatorService(
        lut=TranslatorLookupTable(lut=[
            TranslatorLookupTableElement(conversion_id=k, conversion_info=v)
            for k, v in translator_lut.items()
        ]),
        brho=ring_parameters.brho,
    )
    return yp, lm, tm


def strength_factors_from_lattice() -> dict:
    """The magnets' integrated strength factors, from the lengths of their
    lattice elements (the twin's lattice file), if enabled
    (DT4ACC_INTEGRATED_STRENGTH=1), else none: the magnets publish the
    lattice coefficients."""
    if not at_integrated_strength.enabled():
        return {}
    _, lm, _ = build_managers()
    lat_ids = [lat_p for elem in lm.inverse_lut.lut for lat_p in elem.lat_ids]
    return at_integrated_strength.strength_factors(lattice_loader.load(), lat_ids)


@functools.lru_cache(maxsize=1)
def load_managers():
    """Cached entry point."""
    return build_managers(strength_factors_from_lattice())


if __name__ == "__main__":
    build_managers()
