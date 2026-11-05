"""SOLEIL injection twin's hand over (custom_facility/soleil_injection/handover), without Tango"""
from types import SimpleNamespace

import numpy as np
import pytest

from dt4acc.custom_facility.soleil_injection.handover import InjectionHandover, to_ring


def handover(exit_state, closed_orbit=(1e-6, 0, 0, 0, 0, 0), offset=(1e-3, 0, 1e-3, 0, 0, 0)):
    ring = SimpleNamespace(tbt_closed_orbit=np.array(closed_orbit, dtype=float), tbt_offset=np.array(offset, dtype=float))
    return InjectionHandover(line_exit=lambda: exit_state, ring=ring), ring


def test_ring_state_is_line_state_plus_geometry():
    np.testing.assert_allclose(to_ring([1, 2, 3, 4, 5, 6], [1, 0, 0, 0, 0, 1]), [2, 2, 3, 4, 5, 7])


def test_ring_starts_at_the_injected_beam():
    """the ring starts at closed orbit + offset: so offset = injected - closed orbit"""
    h, ring = handover([1e-4, 2e-4, 0, 0, 0, 0])
    h.set_geometry([-1e-3, 0, 0, 0, 0, 0])
    h.update()
    np.testing.assert_allclose(ring.tbt_closed_orbit + ring.tbt_offset, [-9e-4, 2e-4, 0, 0, 0, 0])
    np.testing.assert_allclose(h.injected, [-9e-4, 2e-4, 0, 0, 0, 0])
    np.testing.assert_allclose(h.line_exit, [1e-4, 2e-4, 0, 0, 0, 0])


def test_written_only_when_it_changes():
    h, _ = handover([0.0] * 6)
    assert h.update() is not None
    assert h.update() is None, "up to date: the ring is not tracked again"


@pytest.mark.parametrize("exit_state", [[], [float("nan")] * 6])
def test_no_beam_leaves_the_ring_as_it_is(exit_state):
    h, ring = handover(exit_state)
    offset = ring.tbt_offset.copy()
    assert h.update() is None
    np.testing.assert_array_equal(ring.tbt_offset, offset)


def test_no_closed_orbit_yet():
    h, _ = handover([0.0] * 6, closed_orbit=())
    assert h.update() is None


def test_geometry_needs_all_coordinates():
    h, _ = handover([0.0] * 6)
    with pytest.raises(ValueError):
        h.set_geometry([0.0] * 5)


def test_simulator_device_unchanged_by_default(monkeypatch):
    """the other twins: the same device name as before"""
    import importlib

    from dt4acc.custom_tango.ioc import mexec_config

    monkeypatch.delenv("DT4ACC_SIM_DEVICE", raising=False)
    assert importlib.reload(mexec_config).SIMULATOR_DEVICE == "simulator/ringsimulator/ringsimulator"
