"""
liasion_translator_setup.py  —  SOLEIL TL2 liaison & translator
===============================================================

As the SOLEIL ring's (``custom_facility/soleil/liasion_translator_setup``):
the device properties map to the lattice element property of the same name,
the conversions have slope 1.0, the yellow pages are ``soleil_yellow_pages``.

What differs, a transfer line:

* correctors are ``at.Corrector`` elements: their properties are ``x_kick`` /
  ``y_kick``, not a multipole coefficient of a host magnet
* no cavities, no master clock
* TL2's database names the supplies, served in device view (``--view device``):
  ``set_current`` drives its magnets' property, slope 1.0 (no current to
  strength data yet: the same value goes into the magnet's strength). So the
  magnet devices, addressing themselves by their element's id
  (``BaseMagnetDevice._send``), are mapped by that id too

Bends (and the kickers and septa, bends in the lattice) are not controlled,
as in the ring.

build_managers() always returns (yp, lm, tm) — three values.
"""

import functools

from dt4acc_lib.bl.liaison_manager import LiaisonManager
from dt4acc_lib.bl.translator_service import TranslatorService
from dt4acc_lib.bl.yellow_pages import YellowPages
from dt4acc_lib.model.utils.identifiers import ConversionID, DevicePropertyID, LatticeElementPropertyID
from dt4acc_lib.model.utils.liaison_manager_lookup_table import (
    LiaisonManagerInverseLookupElement,
    LiaisonManagerInverseLookupTable,
)
from dt4acc_lib.model.utils.translator_manager_lookup_table import (
    IdentityMapper,
    PolynomCoefficients,
    TranslatorLookupTable,
    TranslatorLookupTableElement,
)

from dt4acc.config.data.constants import ring_parameters
from dt4acc.custom_facility.soleil.liasion_translator_setup import _build_name_to_uuid, magnet_infos_from_db
from dt4acc.custom_facility.soleil.soleil_yellow_pages import soleil_yellow_pages

#: magnet types with a control interface (as the ring: not the bends)
_CONTROLLED_TYPES = {"Quadrupole", "Steerer"}
SUPPLY_PROPERTY = "set_current"


def _lattice_property(element_name: str, yp: YellowPages) -> str:
    """
    Quadrupole  → "main_strength"  (MainStrengthForQuadrupole)
    H-corrector → "x_kick"         (XKick, at.Corrector)
    V-corrector → "y_kick"         (YKick, at.Corrector)
    """
    if element_name in yp.horizontal_steerer_names():
        return "x_kick"
    elif element_name in yp.vertical_steerer_names():
        return "y_kick"
    elif element_name in yp.quadrupole_names():
        return "main_strength"
    else:
        raise AssertionError(f"Don't know how to handle {element_name!r}")


def build_managers():
    """Build and return (yp, lm, tm) for the SOLEIL TL2 twin."""
    yp = soleil_yellow_pages()
    infos = magnet_infos_from_db()
    name_to_uuid = _build_name_to_uuid(infos)

    magnet_names = [info.name for info in infos]
    if len(set(magnet_names)) != len(infos):
        raise AssertionError("Magnet names are not unique — required for LUT correctness")

    # intercept=0.0, slope=1.0 → PolynomCoefficients(coeffs=[0.0, 1.0], energy_dependent=False)
    _poly = lambda: PolynomCoefficients(coeffs=[0.0, 1.0], energy_dependent=False)

    inverse_lut: dict = {}
    translator_lut: dict = {}
    by_supply: dict = {}

    for info in infos:
        if info.type not in _CONTROLLED_TYPES:
            # readback only (device view polls it): no liaison, so writes are refused
            host = name_to_uuid[info.name]
            translator_lut[ConversionID(
                LatticeElementPropertyID(element_name=host, property="main_strength"),
                DevicePropertyID(device_name=host, property="main_strength"),
            )] = _poly()
            continue
        prop = _lattice_property(info.name, yp)
        host = name_to_uuid[info.name]
        lattice = LatticeElementPropertyID(element_name=host, property=prop)
        # by the device's name and by its element's id (as it addresses itself)
        for device_name in (info.name, host):
            device = DevicePropertyID(device_name=device_name, property=prop)
            inverse_lut[device] = (lattice,)
            translator_lut[ConversionID(lattice, device)] = _poly()
        by_supply.setdefault(info.pc, []).append(lattice)

    # Power converters → the properties of the magnets they drive
    for supply, lattice_ids in by_supply.items():
        device = DevicePropertyID(device_name=supply, property=SUPPLY_PROPERTY)
        inverse_lut[device] = tuple(lattice_ids)
        for lattice in lattice_ids:
            translator_lut[ConversionID(lattice, device)] = _poly()

    # Virtual result IDs — passthrough (tune, twiss, track, orbit, chromaticity)
    for virtual_id, prop in [
        ("twiss",        "parameters"),
        ("tune",         "transversal"),
        ("chromaticity", "transversal"),
        ("track",        "pos"),
        ("orbit",        "pos"),
    ]:
        device = DevicePropertyID(device_name=virtual_id, property=prop)
        lattice = LatticeElementPropertyID(element_name=virtual_id, property=prop)
        inverse_lut[device] = (lattice,)
        translator_lut[ConversionID(lattice, device)] = IdentityMapper()

    lm = LiaisonManager(
        forward_lut=None,
        inverse_lut=LiaisonManagerInverseLookupTable(lut=[
            LiaisonManagerInverseLookupElement(dev_id=k, lat_ids=v)
            for k, v in inverse_lut.items()
        ])
    )
    tm = TranslatorService(
        lut=TranslatorLookupTable(lut=[
            TranslatorLookupTableElement(conversion_id=k, conversion_info=v)
            for k, v in translator_lut.items()
        ]),
        brho=ring_parameters.brho,
    )
    return yp, lm, tm


@functools.lru_cache(maxsize=1)
def load_managers():
    """Cached entry point."""
    return build_managers()


if __name__ == "__main__":
    build_managers()
