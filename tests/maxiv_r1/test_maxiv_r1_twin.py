"""
test_maxiv_r1_twin.py
=====================
MAX IV R1 twin: BPM devices and the write → recalculation → readback chain.

    pytest tests/maxiv_r1                       # all; integration skipped without a twin
    pytest tests/maxiv_r1 -m "not integration"  # offline only

The integration tests need a running twin (dt4acc_maxiv_r1) whose devices
were registered with dt4acc_maxiv_r1_register; every value written is
restored afterwards.
"""

import numpy as np
import pytest

from .conftest import read_array, wait_until


# ---------------------------------------------------------------------------
# Offline: BPM registration against the lattice
# ---------------------------------------------------------------------------

class TestBpmLatticePositions:
    """R1 BPMs are at.Monitor elements whose UUID is their setup uuid ("BPM10",
    see dt4acc_agent scripts/maxiv_r1_lattice.py): each gets its orbit index
    and s position."""

    @pytest.fixture
    def resolved(self, r1_setup):
        from dt4acc.config.data.querries import get_bpms
        from dt4acc.custom_tango.ioc.devices import tango_device_setup

        positions = tango_device_setup._bpm_lattice_positions()
        return [
            (bpm, *tango_device_setup._bpm_orbit_index_and_s_pos(bpm, positions))
            for bpm in get_bpms()
        ]

    def test_every_bpm_has_an_orbit_index(self, resolved):
        missing = [bpm["name"] for bpm, orbit_index, _ in resolved if orbit_index < 0]
        assert len(resolved) == 37
        assert missing == []

    def test_orbit_index_points_at_the_bpm_element(self, r1_setup, resolved):
        from dt4acc.core.bl.handle_lattice import lattice_loader

        lattice = lattice_loader.load()
        for bpm, orbit_index, _ in resolved:
            assert lattice[orbit_index].FamName == bpm["uuid"], bpm["name"]

    def test_s_pos_taken_from_lattice(self, resolved):
        s_pos = [s for _, _, s in resolved]
        assert all(s > 0 for s in s_pos)
        assert max(s_pos) < 96.0  # R1 circumference 96 m


# ---------------------------------------------------------------------------
# Integration: running twin
# ---------------------------------------------------------------------------

def _bpm_devices(tango_db) -> dict[str, int]:
    """Exported BPM device name → orbit index from its device property."""
    names = tango_db.get_device_exported_for_class("BPMDevice").value_string
    return {
        name: int(tango_db.get_device_property(name, "orbit_index")["orbit_index"][0])
        for name in names
    }


def _tunes(dp_ring_sim) -> np.ndarray:
    """Fractional + integer tunes: total phase advance / 2 pi."""
    return np.array([
        read_array(dp_ring_sim, "nu_x")[-1],
        read_array(dp_ring_sim, "nu_y")[-1],
    ]) / (2 * np.pi)


def _bpm_matches_orbit(bpm_dp, orbit_index: int, dp_ring_sim) -> bool:
    return np.isclose(bpm_dp.x, read_array(dp_ring_sim, "orbit_x")[orbit_index],
                      rtol=1e-9, atol=1e-15)


@pytest.mark.integration
class TestBpmDevices:

    def test_all_bpm_devices_registered_with_orbit_index(self, tango_db):
        bpms = _bpm_devices(tango_db)
        assert len(bpms) == 37
        assert [name for name, index in bpms.items() if index < 0] == []

    def test_bpm_devices_read_the_orbit(self, tango_db, dp_ring_sim):
        import tango

        bpms = _bpm_devices(tango_db)
        orbit_x = read_array(dp_ring_sim, "orbit_x")
        readings = {name: tango.DeviceProxy(name).x for name in bpms}
        assert any(x != 0.0 for x in readings.values()), "all BPM devices read 0"
        for name, index in bpms.items():
            assert readings[name] == pytest.approx(orbit_x[index], rel=1e-9, abs=1e-15), name


@pytest.mark.integration
class TestSteererMovesOrbit:
    """A 10 urad horizontal kick moves the closed orbit and the BPM devices."""

    KICK = 1e-5
    BPM = "R1-101/DIA/BPM-03"

    def test_kick_moves_orbit_and_bpm_device(self, tango_db, dp_ring_sim, dp_steerer_h):
        import tango

        bpm = tango.DeviceProxy(self.BPM)
        bpm_index = _bpm_devices(tango_db)[self.BPM]
        k0 = dp_steerer_h.magnetic_strength
        orbit_before = read_array(dp_ring_sim, "orbit_x")
        bpm_before = bpm.x
        try:
            dp_steerer_h.magnetic_strength = k0 + self.KICK
            assert wait_until(lambda: not np.allclose(
                read_array(dp_ring_sim, "orbit_x"), orbit_before, rtol=0, atol=1e-7
            )), "orbit_x unchanged after steerer kick"
            assert wait_until(lambda: abs(bpm.x - bpm_before) > 1e-7), \
                f"{self.BPM} unchanged after steerer kick"
            assert wait_until(lambda: _bpm_matches_orbit(bpm, bpm_index, dp_ring_sim))
        finally:
            dp_steerer_h.magnetic_strength = k0
        assert wait_until(lambda: np.allclose(
            read_array(dp_ring_sim, "orbit_x"), orbit_before, rtol=0, atol=1e-12
        )), "orbit_x not restored"


@pytest.mark.integration
class TestQuadrupoleChangesTunes:
    """+1 % on SQFO-01 shifts the tunes by ~1e-3 and back when restored."""

    def test_quad_change_shifts_tunes(self, dp_ring_sim, dp_quad):
        k0 = dp_quad.magnetic_strength
        tunes_before = _tunes(dp_ring_sim)
        assert tunes_before == pytest.approx([11.22, 3.15], abs=0.01)
        try:
            dp_quad.magnetic_strength = k0 * 1.01
            assert wait_until(lambda: np.abs(_tunes(dp_ring_sim) - tunes_before).max() > 1e-4), \
                "tunes unchanged after quadrupole change"
        finally:
            dp_quad.magnetic_strength = k0
        assert wait_until(lambda: np.allclose(_tunes(dp_ring_sim), tunes_before, rtol=0, atol=1e-9)), \
            "tunes not restored"
