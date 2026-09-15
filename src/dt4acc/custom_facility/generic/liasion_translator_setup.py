"""Generic EPICS liaison/translator setup — built dynamically from the
configured accelerator_setup.json catalog and the loaded lattice.

Unlike the SOLEIL Tango design-view (no power converters, magnet devices
write straight to the lattice element), this generic EPICS schema mirrors a
simple "one power converter per magnet" facility: Quadrupole/Sextupole map
1:1 to a power converter, and each AT ``Multipole`` corrector element hosts
two independent power-converter-driven steerers (horizontal on
``PolynomB[0]``/``B1``, vertical on ``PolynomA[0]``/``A1``).

The catalog (``accelerator_setup.json``) is read through
``dt4acc.config.data.querries`` (configurable via
``DT4ACC_ACCELERATOR_SETUP_FILE``/``configure_data_file()``); cavity names
are not part of the catalog (no power converter of their own) and are taken
directly from the loaded lattice instead.
"""

from collections import defaultdict

import at

from dt4acc_lib.bl.liaison_manager import LiaisonManager
from dt4acc_lib.bl.translator_service import TranslatorService
from dt4acc_lib.bl.yellow_pages import YellowPages
from dt4acc_lib.interfaces.utils.liaison_manager import LiaisonManagerBase
from dt4acc_lib.interfaces.utils.translator_service import TranslatorServiceBase
from dt4acc_lib.interfaces.utils.yellow_pages import YellowPagesBase
from dt4acc_lib.model.utils.identifiers import ConversionID, DevicePropertyID, LatticeElementPropertyID
from dt4acc_lib.model.utils.liaison_manager_lookup_table import (
    LiaisonManagerForwardLookupElement,
    LiaisonManagerForwardLookupTable,
    LiaisonManagerInverseLookupElement,
    LiaisonManagerInverseLookupTable,
)
from dt4acc_lib.model.utils.translator_manager_lookup_table import (
    IdentityMapper,
    PolynomCoefficients,
    TranslatorLookupTable,
    TranslatorLookupTableElement,
    TuneConversionCoefficients,
)

from dt4acc.config.data.querries import get_controlled_elements

_FALLBACK_BRHO = 5.4


def _yellow_pages_lut(magnets, acc) -> dict:
    quadrupoles = [m["name"] for m in magnets if m["type"] == "Quadrupole"]
    sextupoles = [m["name"] for m in magnets if m["type"] == "Sextupole"]
    steerers = [m["name"] for m in magnets if m["type"] == "Steerer"]

    horizontal_steerers = [s for s in steerers if s.startswith("H")]
    vertical_steerers = [s for s in steerers if s.startswith("V")]
    horizontal_steerers_host = [s[1:] for s in horizontal_steerers]
    vertical_steerers_host = [s[1:] for s in vertical_steerers]

    cavities = [elem.FamName for elem in acc if isinstance(elem, at.RFCavity)]

    return dict(
        quadrupoles=quadrupoles,
        sextupoles=sextupoles,
        steerers=steerers,
        horizontal_steerers=horizontal_steerers,
        horizontal_steerers_host=horizontal_steerers_host,
        vertical_steerers=vertical_steerers,
        vertical_steerers_host=vertical_steerers_host,
        cavities=cavities,
    )


def _build_liaison_manager_lut(magnets, yp: YellowPages):
    pc_of = {m["name"]: m["pc"] for m in magnets}

    inv_d = defaultdict(list)
    fwd_d = defaultdict(list)

    # --- quadrupoles / sextupoles: main_strength <-> PC set_current -----
    for family_name in ("quadrupoles", "sextupoles"):
        for name in yp.get(family_name):
            dev_name = pc_of[name]
            lat_p = LatticeElementPropertyID(element_name=name, property="main_strength")
            pc_dev_p = DevicePropertyID(device_name=dev_name, property="set_current")
            mag_dev_p = DevicePropertyID(device_name=name, property="main_strength")
            fwd_d[lat_p].append(pc_dev_p)
            inv_d[pc_dev_p].append(lat_p)
            inv_d[mag_dev_p].append(lat_p)
            inv_d[DevicePropertyID(device_name=dev_name, property="rdbk_current")].append(lat_p)
            inv_d[DevicePropertyID(device_name=name, property="main_strength_rdbk")].append(lat_p)

    lut_fwd = []
    lut_inv = []

    # --- steerers: B1 / A1 (PolynomB[0] / PolynomA[0]) <-> PC set_current -
    # host = the corrector lattice element the steerer's kick acts on.
    # AT's ThinMultipole uses the European multipole convention (dipole=1,
    # quadrupole=2, sextupole=3, ...), so the dipole/kick term at Python
    # index PolynomB[0]/PolynomA[0] is addressed as "B1"/"A1", not "B0"/"A0"
    # (index 0 isn't a valid European order at all) and not "x_kick"/
    # "y_kick" (which would instead go through the element's KickAngle
    # attribute, which our Multipole-class correctors don't carry).
    for family_name, host_family, lattice_property, co_wound_prefix in (
        ("horizontal_steerers", "horizontal_steerers_host", "B1", "H"),
        ("vertical_steerers", "vertical_steerers_host", "A1", "V"),
    ):
        for name, host in zip(yp.get(family_name), yp.get(host_family)):
            assert name[0] == co_wound_prefix
            assert name[1:] == host
            dev_name = pc_of[name]
            lat_p = LatticeElementPropertyID(element_name=host, property=lattice_property)
            pc_dev_p = DevicePropertyID(device_name=dev_name, property="set_current")
            mag_dev_p = DevicePropertyID(device_name=name, property="main_strength")
            fwd_d[lat_p].append(pc_dev_p)
            inv_d[pc_dev_p].append(lat_p)
            inv_d[mag_dev_p].append(lat_p)
            inv_d[DevicePropertyID(device_name=dev_name, property="rdbk_current")].append(lat_p)

    lut_fwd += [LiaisonManagerForwardLookupElement(lat_id=k, dev_ids=v) for k, v in fwd_d.items()]
    lut_inv += [LiaisonManagerInverseLookupElement(dev_id=k, lat_ids=v) for k, v in inv_d.items()]
    del fwd_d, inv_d

    # --- identity x/y bookkeeping on quadrupoles & sextupoles -----------
    for family in ("quadrupoles", "sextupoles"):
        for prop in ("x", "y"):
            lut_inv += [
                LiaisonManagerInverseLookupElement(
                    dev_id=DevicePropertyID(device_name=name, property=prop),
                    lat_ids=[LatticeElementPropertyID(element_name=name, property=prop)],
                )
                for name in yp.get(family)
            ]

    # --- cavities <-> master clock ---------------------------------------
    lut_inv.append(
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name="master_clock", property="reference_frequency"),
            lat_ids=[
                LatticeElementPropertyID(element_name=cav, property="frequency")
                for cav in yp.get("cavities")
            ],
        )
    )
    lut_fwd += [
        LiaisonManagerForwardLookupElement(
            lat_id=LatticeElementPropertyID(element_name=cav, property="frequency"),
            dev_ids=[DevicePropertyID(device_name="master_clock", property="reference_frequency")],
        )
        for cav in yp.get("cavities")
    ]

    # --- generic virtual quantities (facility independent) ---------------
    lut_fwd.append(
        LiaisonManagerForwardLookupElement(
            lat_id=LatticeElementPropertyID(element_name="tune", property="transversal"),
            dev_ids=[
                DevicePropertyID(device_name="tune", property=prop)
                for prop in ("x", "y", "flq_x", "flq_y", "transversal", "transversal_frequency")
            ],
        )
    )
    lut_inv += [
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name="tune", property=prop),
            lat_ids=[LatticeElementPropertyID(element_name="tune", property="transversal")],
        )
        for prop in ("x", "y", "flq_x", "flq_y", "transversal", "transversal_frequency")
    ]
    lut_inv.append(
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name="orbit", property="pos"),
            lat_ids=[LatticeElementPropertyID(element_name="orbit", property="pos")],
        )
    )
    for name, prop in (("twiss", "parameters"), ("track", "pos"), ("survey", "s")):
        lut_inv.append(
            LiaisonManagerInverseLookupElement(
                dev_id=DevicePropertyID(device_name=name, property=prop),
                lat_ids=[LatticeElementPropertyID(element_name=name, property=prop)],
            )
        )
        lut_fwd.append(
            LiaisonManagerForwardLookupElement(
                lat_id=LatticeElementPropertyID(element_name=name, property=prop),
                dev_ids=[DevicePropertyID(device_name=name, property=prop)],
            )
        )

    return lut_fwd, lut_inv


def _build_translator_manager_lut(magnets, yp: YellowPages, lm_inv: LiaisonManagerInverseLookupTable):
    lut = []

    for cavity_name in yp.get("cavities"):
        lut.append(
            TranslatorLookupTableElement(
                ConversionID(
                    lattice_property_id=LatticeElementPropertyID(element_name=cavity_name, property="frequency"),
                    device_property_id=DevicePropertyID(device_name="master_clock", property="reference_frequency"),
                ),
                PolynomCoefficients([0.0, 1.0], energy_dependent=False),
            )
        )

    pc_of = {m["name"]: m["pc"] for m in magnets}
    steerers = set(yp.get("steerers"))
    quadrupoles = set(yp.get("quadrupoles"))
    sextupoles = set(yp.get("sextupoles"))
    quad_sext_names = quadrupoles | sextupoles
    steerer_pcs = {pc_of[name] for name in steerers}
    quad_sext_pcs = {pc_of[name] for name in quad_sext_names}

    all_keys = list(lm_inv.keys())
    unhandled = []

    # No calibration curve for this generic schema yet -> identity, but
    # flagged energy dependent since a real PC-current-to-strength
    # conversion would be.
    for dev_p in all_keys:
        if dev_p.device_name in steerer_pcs and dev_p.property in ("set_current", "rdbk_current"):
            for lat_p in lm_inv.get(dev_p):
                lut.append(
                    TranslatorLookupTableElement(
                        ConversionID(lat_p, dev_p),
                        PolynomCoefficients([0.0, 1.0], energy_dependent=True),
                    )
                )
        else:
            unhandled.append(dev_p)

    all_keys, unhandled = unhandled, []
    for dev_p in all_keys:
        if dev_p.device_name in quad_sext_pcs and dev_p.property in ("set_current", "rdbk_current"):
            for lat_p in lm_inv.get(dev_p):
                lut.append(
                    TranslatorLookupTableElement(
                        ConversionID(lat_p, dev_p),
                        PolynomCoefficients([0.0, 1.0], energy_dependent=True),
                    )
                )
        else:
            unhandled.append(dev_p)

    all_keys, unhandled = unhandled, []
    for dev_p in all_keys:
        if dev_p.property in ("x", "y") and dev_p.device_name in quad_sext_names:
            (lat_p,) = lm_inv.get(dev_p)
            lut.append(
                TranslatorLookupTableElement(
                    ConversionID(lat_p, dev_p),
                    PolynomCoefficients([0.0, 1.0], energy_dependent=False),
                )
            )
        else:
            unhandled.append(dev_p)

    all_keys, unhandled = unhandled, []
    for dev_p in all_keys:
        if dev_p.device_name in steerers and dev_p.property == "main_strength":
            (lat_p,) = lm_inv.get(dev_p)
            assert lat_p.property in ("B1", "A1")
            lut.append(
                TranslatorLookupTableElement(
                    ConversionID(lat_p, dev_p),
                    PolynomCoefficients([0.0, 1.0], energy_dependent=False),
                )
            )
        else:
            unhandled.append(dev_p)

    all_keys, unhandled = unhandled, []
    for dev_p in all_keys:
        if dev_p.property in ("main_strength", "main_strength_rdbk") and dev_p.device_name in quad_sext_names:
            (lat_p,) = lm_inv.get(dev_p)
            lut.append(
                TranslatorLookupTableElement(
                    ConversionID(lat_p, dev_p),
                    PolynomCoefficients([0.0, 1.0], energy_dependent=False),
                )
            )
        else:
            unhandled.append(dev_p)

    # --- generic virtual quantities (facility independent) ---------------
    lat_p = LatticeElementPropertyID(element_name="tune", property="transversal")
    lut.extend(
        TranslatorLookupTableElement(
            ConversionID(lat_p, DevicePropertyID(device_name="tune", property=prop)),
            IdentityMapper(),
        )
        for prop in ("flq_x", "flq_y", "transversal")
    )
    floquet_to_frequency = 500e3 / 400.0
    lut.extend(
        TranslatorLookupTableElement(
            ConversionID(lat_p, DevicePropertyID(device_name="tune", property=prop)),
            TuneConversionCoefficients(PolynomCoefficients([0.0, floquet_to_frequency], energy_dependent=False)),
        )
        for prop in ("x", "y", "transversal_frequency")
    )
    lut.extend(
        TranslatorLookupTableElement(
            ConversionID(
                LatticeElementPropertyID(element_name=name, property=prop),
                DevicePropertyID(device_name=name, property=prop),
            ),
            IdentityMapper(),
        )
        for name, prop in (("twiss", "parameters"), ("track", "pos"), ("survey", "s"))
    )

    return lut


def _brho(acc) -> float:
    try:
        return float(acc.BRho)
    except Exception:
        import logging

        logging.getLogger("dt4acc-generic-epics").warning(
            "Could not compute BRho from the loaded lattice, falling back to %s", _FALLBACK_BRHO
        )
        return _FALLBACK_BRHO


def build_managers(acc) -> "tuple[YellowPagesBase, LiaisonManagerBase, TranslatorServiceBase]":
    """Build ``(yp, lm, ts)`` dynamically from the configured catalog and lattice.

    Reads the magnet/power-converter catalog through
    ``dt4acc.config.data.querries.get_controlled_elements()`` (configured via
    ``DT4ACC_ACCELERATOR_SETUP_FILE``/``configure_data_file()``) and RF
    cavity names from ``acc``, the already-loaded pyAT lattice.
    """
    magnets = list(get_controlled_elements())
    yp = YellowPages(_yellow_pages_lut(magnets, acc))

    lut_fwd_, lut_inv_ = _build_liaison_manager_lut(magnets, yp)
    lut_fwd = LiaisonManagerForwardLookupTable(lut_fwd_)
    lut_inv = LiaisonManagerInverseLookupTable(lut_inv_)
    lut_fwd.verify()
    lut_inv.verify()
    lm = LiaisonManager(forward_lut=lut_fwd, inverse_lut=lut_inv)

    tlut = TranslatorLookupTable(lut=_build_translator_manager_lut(magnets, yp, lut_inv))
    tlut.verify()
    ts = TranslatorService(lut=tlut, brho=_brho(acc))

    return yp, lm, ts


def load_managers(acc):
    """Entry point. ``acc`` must be the already-loaded pyAT lattice.

    Not cached: a pyAT ``Lattice`` is unhashable, so ``functools.lru_cache``
    cannot key on it, and ``run_epics_twin.main`` only calls this once per
    process anyway.
    """
    return build_managers(acc)
