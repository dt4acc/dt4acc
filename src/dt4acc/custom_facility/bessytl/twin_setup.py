"""BESSY II transfer line: lattice, beam entering it, liaison and translation

The transfer line (booster -> storage ring) is an open line: its optics and
trajectory follow from the beam entering it at the booster extraction septum
(dt4acc-lib line mode, ``twiss_in``).

Inputs (``resources/input`` and ``custom_epics/data/transfer_line``):

* ``accelerator_setup.json``: magnets, their supply (``pc``) and calibration
  (``magnetic_strength``): quadrupoles gradient per current [T/m/A],
  steerers kick per current [rad/A] at the design energy
* ``operating_currents.yaml``: supply currents the twin starts with
* ``twiss_in.yaml``: beam entering the line
"""
import json
import logging
from collections import defaultdict
from importlib.resources import files
from typing import Dict, List, Sequence, Tuple

import at
import yaml
from scipy.constants import c

from dt4acc_lib.bl.liaison_manager import LiaisonManager
from dt4acc_lib.bl.translator_service import TranslatorService
from dt4acc_lib.model.input.twiss_in import TwissIn
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
)

logger = logging.getLogger("dt4acc-bessytl")

#: BESSY II injects at full energy
ENERGY = 1.7185e9
#: magnetic rigidity [T m] (ultra relativistic electrons)
BRHO = ENERGY / c

ACCELERATOR_SETUP = ("custom_epics", "data", "transfer_line", "accelerator_setup.json")
INPUT_DIR = ("custom_facility", "bessytl", "resources", "input")

#: results of the simulation engine, passed through unchanged
RESULT_ELEMENTS = (("twiss", "parameters"), ("track", "pos"), ("survey", "s"))


def resource(path: Tuple[str, ...]):
    return files("dt4acc").joinpath(*path)


def load_accelerator_setup() -> List[dict]:
    with open(resource(ACCELERATOR_SETUP), "rt") as fp:
        return json.load(fp)


def load_operating_currents() -> Dict[str, float]:
    with open(resource(INPUT_DIR + ("operating_currents.yaml",)), "rt") as fp:
        return {k: float(v) for k, v in yaml.safe_load(fp).items()}


def load_twiss_in(path=None) -> TwissIn:
    path = path or resource(INPUT_DIR + ("twiss_in.yaml",))
    with open(path, "rt") as fp:
        return TwissIn(**yaml.safe_load(fp))


def kick_plane(magnet_name: str) -> str:
    """Steerers are named H<n>MT (horizontal) and V<n>MT (vertical)"""
    plane = {"H": "x_kick", "V": "y_kick"}.get(magnet_name[0])
    if plane is None:
        raise ValueError(f"steerer {magnet_name}: expected a name starting with H or V")
    return plane


def slope(magnet: dict) -> float:
    """Field per current of a magnet: [T/m/A] for quadrupoles, [T m/A] for steerers

    ``K = slope * I / brho`` (quadrupoles), ``kick = slope * I / brho`` (steerers).
    The setup gives steerers as kick per current at the design energy.
    """
    if magnet["type"] == "Quadrupole":
        return magnet["magnetic_strength"]
    if magnet["type"] == "Steerer":
        return magnet["magnetic_strength"] * BRHO
    raise ValueError(f"{magnet['name']}: no calibration for type {magnet['type']}")


def bessytl_lattice(
    setup: Sequence[dict] = None, currents: Dict[str, float] = None, end_after: str = None
) -> at.Lattice:
    """The transfer line with the quadrupoles set from the supply currents

    Element positions, lengths and bends: lat2db's ``bessy2_TL`` (quadrupoles
    there have K = 0, i.e. no currents). ``end_after``: cut the line after
    this element (e.g. the injection septum, where the ring takes over).
    """
    from lat2db.tools.pyat.bessy2_TL_reflat import bessy2_TL

    setup = load_accelerator_setup() if setup is None else setup
    currents = load_operating_currents() if currents is None else currents
    line = bessy2_TL()
    if end_after is not None:
        (last,) = [i for i, elem in enumerate(line) if elem.FamName == end_after]
        line = line[: last + 1]
    line.energy = ENERGY
    for elem in line:
        if hasattr(elem, "Energy"):
            elem.Energy = ENERGY
    by_name = {elem.FamName: elem for elem in line}
    for magnet in setup:
        if magnet["type"] != "Quadrupole":
            continue
        elem = by_name[magnet["name"]]
        elem.update(K=slope(magnet) * currents.get(magnet["pc"], 0.0) / BRHO)
    return line


def build_lookup_tables(
    setup: Sequence[dict],
) -> Tuple[
    Sequence[LiaisonManagerForwardLookupElement],
    Sequence[LiaisonManagerInverseLookupElement],
    Sequence[TranslatorLookupTableElement],
]:
    """Supplies drive magnets one to one: supply current <-> magnet strength"""
    fwd = defaultdict(list)
    inv = defaultdict(list)
    conversions = []

    def add(dev_p, lat_p, conversion, *, forward: bool):
        if forward:
            fwd[lat_p].append(dev_p)
        inv[dev_p].append(lat_p)
        conversions.append(TranslatorLookupTableElement(ConversionID(lat_p, dev_p), conversion))

    for magnet in setup:
        if magnet["type"] == "Quadrupole":
            lattice_property = "main_strength"
        elif magnet["type"] == "Steerer":
            lattice_property = kick_plane(magnet["name"])
        else:
            continue
        name, pc = magnet["name"], magnet["pc"]
        lat_p = LatticeElementPropertyID(element_name=name, property=lattice_property)
        # supply current: I = K * brho / slope
        per_current = PolynomCoefficients([0.0, 1.0 / slope(magnet)], energy_dependent=True)
        add(DevicePropertyID(device_name=pc, property="set_current"), lat_p, per_current, forward=True)
        add(DevicePropertyID(device_name=pc, property="rdbk_current"), lat_p, per_current, forward=False)
        # magnet strength in lattice units
        same = PolynomCoefficients([0.0, 1.0], energy_dependent=False)
        add(DevicePropertyID(device_name=name, property="main_strength"), lat_p, same, forward=False)
        add(DevicePropertyID(device_name=name, property="main_strength_rdbk"), lat_p, same, forward=False)
        # pyAT correctors only kick; quadrupoles can be displaced
        for offset, lattice_offset in (("x", "dx"), ("y", "dy")) if magnet["type"] == "Quadrupole" else ():
            add(
                DevicePropertyID(device_name=name, property=offset),
                LatticeElementPropertyID(element_name=name, property=lattice_offset),
                same,
                forward=False,
            )

    for elem, prop in RESULT_ELEMENTS:
        add(
            DevicePropertyID(device_name=elem, property=prop),
            LatticeElementPropertyID(element_name=elem, property=prop),
            IdentityMapper(),
            forward=True,
        )

    lut_fwd = [LiaisonManagerForwardLookupElement(lat_id=k, dev_ids=v) for k, v in fwd.items()]
    lut_inv = [LiaisonManagerInverseLookupElement(dev_id=k, lat_ids=v) for k, v in inv.items()]
    return lut_fwd, lut_inv, conversions


def build_managers(setup: Sequence[dict] = None) -> Tuple[LiaisonManager, TranslatorService]:
    setup = load_accelerator_setup() if setup is None else setup
    lut_fwd, lut_inv, conversions = build_lookup_tables(setup)
    fwd = LiaisonManagerForwardLookupTable(lut_fwd)
    inv = LiaisonManagerInverseLookupTable(lut_inv)
    fwd.verify()
    inv.verify()
    assert not inv.non_unique_entries(), inv.non_unique_entries()
    lm = LiaisonManager(forward_lut=fwd, inverse_lut=inv)
    ts = TranslatorService(lut=TranslatorLookupTable(lut=conversions), brho=BRHO)
    return lm, ts


def monitor_names(line: at.Lattice) -> List[str]:
    return [line[i].FamName for i in line.get_uint32_index(at.Monitor)]
