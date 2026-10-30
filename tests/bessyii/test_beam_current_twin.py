"""The beam current of a running BESSY II twin (``TOPUPCC:rdCur``,
``MDIZ3T5G:current``)

300 mA while the beam is stored: a closed orbit, and the particles tracked
around it (closed orbit, +- 5 sigma in x and y) survive 1000 turns. Without
apertures in the lattice the dynamic aperture decides:

* all sextupoles x 4 (through their supplies): a closed orbit, but the
  particles at +- 5 sigma in x are lost -> 0 mA; back at nominal -> 300 mA
* a ~10 mrad kick (one steerer supply): no closed orbit -> 0 mA,
  ``beam:orbit:found`` 0; ``simulator_ring:reinit`` -> 300 mA

Needs a running twin (``dt4acc_bessyii``) and ``DT4ACC_PREFIX``; skipped
otherwise. On z3: ``TWIN_CMD="python -m pytest tests/bessyii/test_beam_current_twin.py"
sbatch slurm/z3_bessyii_twin.sbatch``. Every test leaves the twin at nominal.
"""
import json
import os
import time
from importlib import resources

import pytest

p4p_client = pytest.importorskip("p4p.client.thread")

from dt4acc.custom_facility.bessyii.run_bessyii_twin import ACCELERATOR_SETUP

pytestmark = pytest.mark.integration

PREFIX = os.environ.get("DT4ACC_PREFIX")
CURRENT_PVS = ("TOPUPCC:rdCur", "MDIZ3T5G:current")
STORED = 300.0
#: a recalculation includes 1000 turns of tracking (~1.5 s); many supplies are written
TIMEOUT_S = 120.0
SEXTUPOLE_SCALE = 4.0
#: steerer supply of HS4M2D1R (kicks S4M2D1R): -224.7 A per rad and Brho
STEERER_SUPPLY = "HS4P2D1R"
#: ~10 mrad at 1.7 GeV (Brho 5.67 T m); 1 mrad already leaves no closed orbit
LETHAL_STEP = 13.0  # A


def sextupole_supplies():
    with open(resources.files("dt4acc").joinpath(*ACCELERATOR_SETUP)) as fp:
        db = json.load(fp)
    return sorted({e["pc"] for e in db if e.get("type") == "Sextupole" and e.get("pc")})


@pytest.fixture(scope="module")
def ctx():
    if not PREFIX:
        pytest.skip("DT4ACC_PREFIX not set: no running twin")
    c = p4p_client.Context("pva", nt=False)
    try:
        c.get(f"{PREFIX}:{CURRENT_PVS[0]}", timeout=5)
    except Exception as exc:
        c.close()
        pytest.skip(f"no twin with prefix {PREFIX}: {exc}")
    yield c
    c.close()


def get(ctx, pv: str):
    return ctx.get(f"{PREFIX}:{pv}", timeout=10)["value"]


def orbit_found(ctx) -> bool:
    """``beam:orbit:found`` (a boolIn: an enum over PV Access)"""
    return bool(get(ctx, "beam:orbit:found")["index"])


def put(ctx, pv: str, value):
    ctx.put(f"{PREFIX}:{pv}", value, timeout=30, wait=True)


def currents(ctx):
    return [get(ctx, pv) for pv in CURRENT_PVS]


def wait_for_current(ctx, value: float, timeout_s: float = TIMEOUT_S):
    end = time.time() + timeout_s
    while time.time() < end:
        got = currents(ctx)
        if all(abs(v - value) < 1e-6 for v in got):
            return got
        time.sleep(1.0)
    pytest.fail(f"beam current {currents(ctx)}, expected {value} within {timeout_s} s")


def reinit(ctx):
    put(ctx, "simulator_ring:reinit", "1")
    wait_for_current(ctx, STORED)


@pytest.fixture
def nominal(ctx):
    """stored beam at the start; afterwards back to nominal, whatever happened"""
    wait_for_current(ctx, STORED)
    yield
    try:
        wait_for_current(ctx, STORED, timeout_s=10)
    except pytest.fail.Exception:
        reinit(ctx)


def test_stored_at_nominal(ctx, nominal):
    assert currents(ctx) == [STORED, STORED]
    assert orbit_found(ctx)


def test_dynamic_aperture_too_small(ctx, nominal):
    supplies = sextupole_supplies()
    assert len(supplies) == 13
    start = {s: get(ctx, f"{s}:set") for s in supplies}
    try:
        for s, current in start.items():
            put(ctx, f"{s}:set", current * SEXTUPOLE_SCALE)
        wait_for_current(ctx, 0.0)
        # the closed orbit still exists: the particles around it are lost
        assert orbit_found(ctx)
    finally:
        for s, current in start.items():
            put(ctx, f"{s}:set", current)
    wait_for_current(ctx, STORED)


def test_no_closed_orbit(ctx, nominal):
    start = get(ctx, f"{STEERER_SUPPLY}:set")
    try:
        put(ctx, f"{STEERER_SUPPLY}:set", start + LETHAL_STEP)
        wait_for_current(ctx, 0.0)
        assert not orbit_found(ctx)
        # the twin is in error now: reinit brings back the nominal lattice and the beam
        reinit(ctx)
        assert orbit_found(ctx)
    finally:
        put(ctx, f"{STEERER_SUPPLY}:set", start)
    wait_for_current(ctx, STORED)
