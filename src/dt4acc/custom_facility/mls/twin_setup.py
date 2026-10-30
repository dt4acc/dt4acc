"""MLS storage ring: lattice, device database, liaison and translation

Inputs (``resources/input``):

* ``accelerator_setup.json``: magnets, the supply that drives each (``pc``)
  and MML's calibration (``amp2k``), written by
  ``scripts/mls/make_accelerator_setup.py`` from ``ao_mls.json`` (MML's
  accelerator object, HZB MML fork)
* the lattice: lat2db's ``mls_sr_reflat.mlsLattice`` (629 MeV)

Supplies drive magnets: one supply per quadrupole and steerer, one per
sextupole family string (``S1P1RP`` drives 4 S1). A steerer kicks the magnet
it is wound on (``HS3M2K1RP`` kicks the sextupole ``S3M2K1RP``).

Calibration, as MML's ``amp2k.m``: ``K = polyval(amp2k, I / scale) / Brho``.
For a linear ``amp2k`` (quadrupoles, steerers) it is a linear conversion,
exact; for the sextupoles (a 5th-order term, up to 5 % at 60 A) the
polynomial itself (dt4acc-lib's ``PolynomialCalibration``, which divides by
the beam's brho as amp2k does and inverts it as MML's ``k2amp``).
"""
import json
from collections import defaultdict
from importlib.resources import files
from typing import List, Sequence, Tuple, Union

import at
import numpy as np
from scipy.constants import c

from dt4acc_lib.bl.liaison_manager import LiaisonManager
from dt4acc_lib.bl.translator_service import TranslatorService
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
    PolynomialCalibration,
    Range,
    TranslatorLookupTable,
    TranslatorLookupTableElement,
)

#: MLS runs at 629 MeV
ENERGY = 629e6
#: magnetic rigidity [T m] (ultra relativistic electrons)
#: Todo: clear up brho / energy: ENERGY / c ignores the rest mass, dt4acc-lib's
#:       calculate_brho does not; MML's getbrho for the MLS to be checked.
#:       Needs to be done for the MLS
BRHO = ENERGY / c
#: RF buckets (harmonic number)
HARMONIC_NUMBER = 80

ACCELERATOR_SETUP = ("custom_facility", "mls", "resources", "input", "accelerator_setup.json")

#: results of the simulation engine, passed through unchanged
RESULT_ELEMENTS = (("twiss", "parameters"), ("track", "pos"), ("survey", "s"))
#: the RF: master clock [kHz] -> cavity frequency [Hz]
CAVITIES = ("CAV",)
KHZ_PER_HZ = PolynomCoefficients([0.0, 1e-3], energy_dependent=False)


def resource(path: Tuple[str, ...]):
    return files("dt4acc").joinpath(*path)


def load_accelerator_setup() -> List[dict]:
    with open(resource(ACCELERATOR_SETUP), "rt") as fp:
        return json.load(fp)


def mls_lattice() -> at.Lattice:
    """The MLS storage ring at its design settings (lat2db)"""
    from lat2db.tools.pyat.mls_sr_reflat import mlsLattice

    ring = mlsLattice()
    assert ring.energy == ENERGY, f"MLS lattice at {ring.energy} eV, the twin expects {ENERGY}"
    return ring


def lattice_element(magnet: dict) -> str:
    """The lattice element a magnet acts on: a steerer kicks its host"""
    return magnet["name"][1:] if magnet["type"] == "Steerer" else magnet["name"]


def lattice_property(magnet: dict) -> str:
    if magnet["type"] == "Steerer":
        plane = {"HCM": "x_kick", "VCM": "y_kick"}.get(magnet["family"])
        if plane is None:
            raise ValueError(f"steerer {magnet['name']}: family {magnet['family']}, expected HCM or VCM")
        return plane
    if magnet["type"] in ("Quadrupole", "Sextupole"):
        return "main_strength"
    raise ValueError(f"{magnet['name']}: no lattice property for type {magnet['type']}")


def amp2k(magnet: dict) -> np.ndarray:
    return np.trim_zeros(np.asarray(magnet["amp2k"], dtype=float), "f")


def is_linear(magnet: dict) -> bool:
    return len(amp2k(magnet)) <= 2


def calibration(magnet: dict) -> Union[PolynomCoefficients, PolynomialCalibration]:
    """A linear amp2k: ``I = Brho * (intercept + slope * K)``, with ``K * Brho =
    c1 * I / scale + c0``; else amp2k's polynomial ``K * Brho = polyval(amp2k,
    I / scale)``"""
    coeffs = amp2k(magnet)
    scale = magnet.get("amp2k_scale", 1.0)
    if is_linear(magnet):
        c1, c0 = (coeffs[0], coeffs[1]) if len(coeffs) == 2 else (coeffs[0], 0.0)
        c1 = c1 / scale
        return PolynomCoefficients([-c0 / c1 / BRHO, 1.0 / c1], energy_dependent=True)
    rng = Range(*magnet["range"]) if magnet.get("range") else None
    return PolynomialCalibration(coeffs=[float(v) for v in coeffs], energy_dependent=True, scale=scale, range=rng)


def build_lookup_tables(setup: Sequence[dict]):
    fwd = defaultdict(list)
    inv = defaultdict(list)
    conversions = []

    def add(dev_p, lat_p, conversion, *, forward: bool):
        if forward:
            fwd[lat_p].append(dev_p)
        inv[dev_p].append(lat_p)
        conversions.append(TranslatorLookupTableElement(ConversionID(lat_p, dev_p), conversion))

    same = PolynomCoefficients([0.0, 1.0], energy_dependent=False)
    for magnet in setup:
        name, pc = magnet["name"], magnet["pc"]
        lat_p = LatticeElementPropertyID(element_name=lattice_element(magnet), property=lattice_property(magnet))
        per_current = calibration(magnet)
        add(DevicePropertyID(device_name=pc, property="set_current"), lat_p, per_current, forward=True)
        add(DevicePropertyID(device_name=pc, property="rdbk_current"), lat_p, per_current, forward=False)
        # the magnet in lattice units (twin only)
        add(DevicePropertyID(device_name=name, property="main_strength"), lat_p, same, forward=False)
        add(DevicePropertyID(device_name=name, property="main_strength_rdbk"), lat_p, same, forward=False)
        # quadrupoles and sextupoles can be displaced; a steerer is wound on its host
        if magnet["type"] != "Steerer":
            for offset, lattice_offset in (("x", "dx"), ("y", "dy")):
                add(DevicePropertyID(device_name=name, property=offset),
                    LatticeElementPropertyID(element_name=name, property=lattice_offset), same, forward=False)

    for cavity in CAVITIES:
        lat_p = LatticeElementPropertyID(element_name=cavity, property="frequency")
        add(DevicePropertyID(device_name="master_clock", property="frequency"), lat_p, KHZ_PER_HZ, forward=True)
        add(DevicePropertyID(device_name="master_clock", property="reference_frequency"), lat_p, KHZ_PER_HZ,
            forward=False)
        add(DevicePropertyID(device_name=cavity, property="frequency"), lat_p, KHZ_PER_HZ, forward=False)

    for elem, prop in RESULT_ELEMENTS:
        add(DevicePropertyID(device_name=elem, property=prop),
            LatticeElementPropertyID(element_name=elem, property=prop), IdentityMapper(), forward=True)

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
    lm = LiaisonManager(forward_lut=fwd, inverse_lut=inv)
    ts = TranslatorService(lut=TranslatorLookupTable(lut=conversions), brho=BRHO)
    return lm, ts


def bpm_names(ring: at.Lattice) -> List[str]:
    return [ring[i].FamName for i in ring.get_uint32_index(at.Monitor)]


__all__ = ["ENERGY", "BRHO", "HARMONIC_NUMBER", "ACCELERATOR_SETUP", "mls_lattice", "build_managers",
           "calibration", "is_linear", "bpm_names", "load_accelerator_setup"]
