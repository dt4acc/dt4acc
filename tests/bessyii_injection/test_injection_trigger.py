"""Injection on demand: a shot is fired by ``INJ:trigger``

As at the machine: the transfer line carries beam only during a shot. Its
model (trajectory, optics) follows every change; its monitors and the ring's
turn by turn data show the beam only when a shot is fired, and keep it until
the next one. The injection settings act at the next shot.
"""
import asyncio
import math
import time
from types import SimpleNamespace

import numpy as np
import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.custom_facility.bessyii_injection.handover import no_offset
from dt4acc.custom_facility.bessyii_injection.pvs import InjectionPVs
from dt4acc.custom_facility.bessytl.view import TransferLineView, initialize_monitor_pvs
from dt4acc.custom_epics.ioc.pv_setup import initialize_orbit_pvs
from dt4acc_lib.model.utils.command import ReadCommand

from tests.recording_builder import RecordingBuilder

TRACK = ReadCommand("track", "pos")
MONITORS = ["BPM1T", "FOMZ1T"]


# --- transfer line view, single pass
def track_package(x_at):
    """a trajectory over a drift and the monitors, x [m] per element name"""
    names = ["D1", *MONITORS]
    track = [SimpleNamespace(x=x_at.get(n, 0.0), y=0.0, fam_name=n, uid=f"{n}:0") for n in names]
    return SimpleNamespace(readings=[SimpleNamespace(payload=SimpleNamespace(track=track))])


def line_view(single_pass):
    builder = RecordingBuilder()
    view = TransferLineView(monitors=MONITORS, single_pass=single_pass)
    view.update_process_variables({
        **initialize_monitor_pvs(MONITORS, builder=builder),
        **initialize_orbit_pvs(builder, n_elements=3),
    })
    return view


def monitor_x(view):
    return [view.process_variables[ReadCommand(m, "x")].get() for m in MONITORS]


def model_x(view):
    return list(view.process_variables[ReadCommand("beam", "x")].get())


def test_single_pass_monitors_show_the_trajectory_only_when_fired():
    view = line_view(single_pass=True)
    assert not view.fire(), "no trajectory yet: nothing to show"

    view.update_track(TRACK, track_package({"BPM1T": 1e-3, "FOMZ1T": 2e-3}))
    assert model_x(view) == [0.0, 1e-3, 2e-3], "the model follows the change"
    assert monitor_x(view) == [0.0, 0.0], "no shot yet: the monitors saw no beam"

    assert view.fire()
    assert monitor_x(view) == pytest.approx([1.0, 2.0]), "the shot: the trajectory [mm]"

    view.update_track(TRACK, track_package({"BPM1T": -1e-3}))
    assert monitor_x(view) == pytest.approx([1.0, 2.0]), "they keep the last shot's reading"
    view.fire()
    assert monitor_x(view) == pytest.approx([-1.0, 0.0])


def test_single_pass_shot_after_a_failed_calculation_shows_nan():
    view = line_view(single_pass=True)
    view.update_track(TRACK, track_package({"BPM1T": 1e-3}))
    asyncio.run(view.push_invalid())
    view.fire()
    assert all(math.isnan(v) for v in monitor_x(view))


def test_without_single_pass_monitors_follow_every_change():
    """the transfer line twin on its own: as before"""
    view = line_view(single_pass=False)
    view.update_track(TRACK, track_package({"BPM1T": 1e-3}))
    assert monitor_x(view) == pytest.approx([1.0, 0.0])


# --- the trigger
class FakeHandover:
    monitors = ["BPMZ1D1R", "BPMZ2D1R"]

    def __init__(self, calls):
        self.calls = calls
        self.geometry = no_offset()
        self.n_turns = 2

    async def compute(self):
        self.calls.append(("handover", self.n_turns, self.geometry.x))
        state = no_offset()
        x = np.full((self.n_turns, 2), 1e-3)
        return SimpleNamespace(line_exit=state, injected=state, monitors=self.monitors,
                               x=lambda: x, y=lambda: 0 * x, survived=lambda: np.ones(self.n_turns))


@pytest.fixture
def injection():
    calls = []

    async def before_shot():
        calls.append("line")

    pvs = InjectionPVs(FakeHandover(calls), builder=RecordingBuilder(), before_shot=before_shot)
    fired = []
    pvs.fire = lambda: fired.append(True)
    return pvs, calls, fired


def test_settings_act_at_the_next_shot_only(injection):
    pvs, calls, fired = injection
    pvs._set_geometry("x", -2e-3)
    pvs._set_n_turns(5)
    assert not fired and not calls, "a setting does not inject"
    assert (pvs.handover.geometry.x, pvs.handover.n_turns) == (-2e-3, 5)


def test_trigger_fires_and_is_ready_again(injection):
    pvs, _, fired = injection
    pvs.rec["trigger"].set(True)
    pvs._on_trigger(1)
    assert fired == [True]
    assert pvs.rec["trigger"].get() is False, "back at 0, ready for the next trigger"
    pvs._on_trigger(0)
    assert fired == [True], "writing 0 does not fire"


def test_a_shot_passes_the_line_then_enters_the_ring(injection):
    pvs, calls, _ = injection
    pvs._set_n_turns(3)
    asyncio.run(pvs.shot())
    assert calls == ["line", ("handover", 3, 0.0)]
    assert pvs.rec["count"].get() == 1
    assert list(pvs.rec["BPMZ1D1R:x"].get()) == pytest.approx([1.0] * 3), "turn by turn [mm]"


def test_fire_runs_the_shot_on_the_shared_loop():
    pvs = InjectionPVs(FakeHandover([]), builder=RecordingBuilder())
    pvs.fire()
    t0 = time.time()
    while pvs.rec["count"].get() != 1 and time.time() - t0 < 5:
        time.sleep(0.02)
    assert pvs.rec["count"].get() == 1


# --- the twin: transfer line and ring
@pytest.fixture(scope="module")
def twin_and_injection():
    pytest.importorskip("lat2db.tools.pyat.bessy2_TL_reflat")
    from dt4acc.custom_facility.bessyii_injection.run_bessyii_injection_twin import assemble, initialise_pvs

    twin = assemble("TEST", orbit_servers=False)
    injection = asyncio.run(initialise_pvs(RecordingBuilder(), "TEST", twin))
    return twin, injection


def test_twin_line_change_reaches_the_monitors_only_with_a_shot(twin_and_injection):
    from dt4acc.core.bl.controller import read_and_dispatch
    from dt4acc_lib.model.utils.command import Command

    twin, injection = twin_and_injection
    view = twin.line_view
    bpms = sorted(m for m in twin.line_monitors if not m.startswith("FOMZ"))

    def at_monitors():
        return np.array([view.process_variables[ReadCommand(m, "x")].get() for m in bpms])

    async def steer_and_read():
        # as a write of H5PT:set: the supply, then the delayed reads of the model
        await twin.tl.mexec.set([Command(id="H5PT", property="set_current", value=0.4, behaviour_on_error=None)])
        await read_and_dispatch(controller=twin.tl, view=view, rcmds=[TRACK])

    asyncio.run(steer_and_read())
    model = dict(zip(view.process_variables[ReadCommand("beam", "names")].get(),
                     view.process_variables[ReadCommand("beam", "x")].get()))
    expected = np.array([model[m] * 1e3 for m in bpms])
    assert np.abs(expected).max() > 0.1, "the steerer moves the trajectory at the BPMs [mm]"
    assert not at_monitors().any(), "no shot: the line's BPMs saw no beam"
    assert injection.rec["count"].get() == 0, "a change does not inject"

    asyncio.run(injection.shot())
    assert at_monitors() == pytest.approx(expected), "the shot: the BPMs show the trajectory"
    assert injection.rec["count"].get() == 1
    assert injection.rec["injected:x"].get() != 0.0, "the steered beam entered the ring"
    assert np.abs(injection.rec["tbt:x"].get()).max() > 1e-4, "and oscillates in it"
