"""
test_soleil_bpm.py
==================
SOLEIL II twin: the BPM devices -- registered with the orbit index of their
own lattice monitor, reading the ring simulator's closed orbit there, and
following a steerer kick.
"""

import numpy as np
import pytest

from .conftest import read_array, setup_entries, wait_until

pytestmark = pytest.mark.integration

KICK = 1e-4   # B1 [1/m] on the steerer's host sextupole


@pytest.fixture(scope="module")
def bpm_index(tango_db):
    names = tango_db.get_device_exported_for_class("BPMDevice").value_string
    return {n: int(tango_db.get_device_property(n, "orbit_index")["orbit_index"][0]) for n in names}


def test_all_bpm_devices_exported(bpm_index):
    expected = {e["name"].lower() for e in setup_entries() if e["type"] == "BPM"}
    assert {n.lower() for n in bpm_index} == expected
    assert len(bpm_index) == 199


def test_orbit_index_points_at_the_bpm_monitor(bpm_index, soleil_ring):
    uuid = {e["name"].lower(): e["uuid"] for e in setup_entries() if e["type"] == "BPM"}
    wrong = {n: i for n, i in bpm_index.items()
             if not (0 <= i < len(soleil_ring) and getattr(soleil_ring[i], "UUID", None) == uuid[n.lower()])}
    assert wrong == {}


def test_bpm_devices_read_the_orbit(bpm_index, dp_ring_sim):
    import tango

    orbit_x, orbit_y = read_array(dp_ring_sim, "orbit_x"), read_array(dp_ring_sim, "orbit_y")
    for name, i in list(bpm_index.items())[::20]:
        dp = tango.DeviceProxy(name)
        assert dp.x == pytest.approx(orbit_x[i], rel=1e-9, abs=1e-15), name
        assert dp.y == pytest.approx(orbit_y[i], rel=1e-9, abs=1e-15), name


def test_steerer_kick_moves_the_bpm_readings(bpm_index, dp_ring_sim, dp_steerer_h):
    import tango

    name, i = next(iter(bpm_index.items()))
    bpm = tango.DeviceProxy(name)
    b0, x0 = dp_steerer_h.magnetic_strength, bpm.x
    try:
        dp_steerer_h.magnetic_strength = b0 + KICK
        assert wait_until(lambda: abs(bpm.x - x0) > 1e-9), f"{name} unchanged after a kick"
        assert wait_until(lambda: bpm.x == pytest.approx(read_array(dp_ring_sim, "orbit_x")[i], rel=1e-9, abs=1e-15))
    finally:
        dp_steerer_h.magnetic_strength = b0
    assert wait_until(lambda: abs(bpm.x - x0) < 1e-12), f"{name} not back after the kick was undone"
