"""SOLEIL injection twin: the hand over (custom_facility/soleil_injection/handover) fired on
demand, a shot at a time, and what the launcher sets for it; without a running Tango system"""
from types import SimpleNamespace

import numpy as np
import pytest

from dt4acc.custom_facility.soleil_injection.handover import InjectionHandover, to_ring


class Ring:
    """stand in for the ring simulator device: what was injected"""

    def __init__(self):
        self.shots = []

    def Inject(self, state):
        self.shots.append(np.array(state, dtype=float))


def handover(exit_state):
    ring = Ring()
    return InjectionHandover(line_exit=lambda: exit_state, ring=ring), ring


def test_ring_state_is_line_state_plus_geometry():
    np.testing.assert_allclose(to_ring([1, 2, 3, 4, 5, 6], [1, 0, 0, 0, 0, 1]), [2, 2, 3, 4, 5, 7])


def test_a_shot_injects_the_beam_leaving_the_line():
    h, ring = handover([1e-4, 2e-4, 0, 0, 0, 0])
    h.set_geometry([-1e-3, 0, 0, 0, 0, 0])
    assert not ring.shots, "no shot yet: nothing injected"
    np.testing.assert_allclose(h.shot(), [-9e-4, 2e-4, 0, 0, 0, 0])
    (state,) = ring.shots
    np.testing.assert_allclose(state, [-9e-4, 2e-4, 0, 0, 0, 0])
    np.testing.assert_allclose(h.injected, state)
    np.testing.assert_allclose(h.line_exit, [1e-4, 2e-4, 0, 0, 0, 0])


def test_every_shot_injects_also_unchanged():
    """a shot is a shot: the ring tracks it again, as the BPMs are triggered again"""
    h, ring = handover([0.0] * 6)
    h.shot()
    h.shot()
    assert len(ring.shots) == 2


def test_geometry_acts_at_the_next_shot():
    h, ring = handover([0.0] * 6)
    h.set_geometry([1e-3, 0, 0, 0, 0, 0])
    assert not ring.shots
    h.shot()
    np.testing.assert_allclose(ring.shots[-1], [1e-3, 0, 0, 0, 0, 0])


@pytest.mark.parametrize("exit_state", [[], [float("nan")] * 6])
def test_no_beam_leaving_the_line_injects_nothing(exit_state):
    h, ring = handover(exit_state)
    assert h.shot() is None
    assert not ring.shots
    assert len(h.injected) == 0 and len(h.line_exit) == 0


def test_geometry_needs_all_coordinates():
    h, _ = handover([0.0] * 6)
    with pytest.raises(ValueError):
        h.set_geometry([0.0] * 5)


def test_injection_device_shot_fires_the_line_then_injects():
    """the order of a shot: TL2's BPMs see the beam pass, then it enters the ring"""
    tango = pytest.importorskip("tango")  # noqa: F841
    from dt4acc.custom_facility.soleil_injection.injection_device import InjectionDevice

    calls = []
    h, ring = handover([1e-4, 0, 0, 0, 0, 0])
    ring.Inject = lambda state: calls.append("ring")
    device = SimpleNamespace(_line=SimpleNamespace(Fire=lambda: calls.append("line")), _handover=h)
    InjectionDevice.shot(device)
    assert calls == ["line", "ring"]


def test_only_the_injection_twin_injects_on_demand(monkeypatch):
    """its ring tracks only for a shot, its TL2's BPMs are single pass; the twins on
    their own are not (they do not get these variables), nor do they leak in"""
    from dt4acc.custom_facility.soleil_injection.utils.command_line_interface import (
        build_args_parser, ring_env, tl_env)

    monkeypatch.setenv("DT4ACC_SINGLE_PASS", "1")
    args = build_args_parser().parse_args([])
    ring, tl = ring_env(args), tl_env(args)
    assert ring["DT4ACC_TBT_ON_DEMAND"] == "1" and "DT4ACC_SINGLE_PASS" not in ring
    assert tl["DT4ACC_SINGLE_PASS"] == "1" and "DT4ACC_TBT_ON_DEMAND" not in tl


@pytest.mark.parametrize("single_pass, attributes", [("", ("orbit_x", "orbit_y")), ("1", ("shot_x", "shot_y"))])
def test_bpm_devices_follow_the_shot_in_single_pass(monkeypatch, single_pass, attributes):
    pytest.importorskip("tango")
    import importlib

    from dt4acc.custom_tango.ioc import mexec_config
    from dt4acc.custom_tango.ioc.devices import bpm_device

    monkeypatch.setenv("DT4ACC_SINGLE_PASS", single_pass)
    try:
        importlib.reload(mexec_config)
        assert importlib.reload(bpm_device).POSITION_ATTRIBUTES == attributes
    finally:
        monkeypatch.delenv("DT4ACC_SINGLE_PASS")
        importlib.reload(mexec_config)
        importlib.reload(bpm_device)


def test_simulator_device_unchanged_by_default(monkeypatch):
    """the other twins: the same device name as before"""
    import importlib

    from dt4acc.custom_tango.ioc import mexec_config

    monkeypatch.delenv("DT4ACC_SIM_DEVICE", raising=False)
    assert importlib.reload(mexec_config).SIMULATOR_DEVICE == "simulator/ringsimulator/ringsimulator"
