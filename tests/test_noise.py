"""Noise on the BPMs' readings (#82): off by default; when on, the BPM PVs
show the model plus a sample of the noise, the model PVs stay the model's"""
import math
from types import SimpleNamespace

import numpy as np
import pytest

# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.core.bl.noise import BpmNoise, Noise
from dt4acc.core.bl.turn_by_turn import COORDINATES
from dt4acc.custom_epics.ioc.bpm_pvs import M2MM
from dt4acc.custom_epics.ioc.noise_pvs import initialize_bpm_noise_pvs
from dt4acc.custom_epics.ioc.turn_by_turn import TurnByTurnPVs
from dt4acc.custom_epics.ioc.view import View
from dt4acc.custom_facility.bessyii_injection.pvs import InjectionPVs
from dt4acc_lib.model.output.result import SingleReading, TranslatedReading
from dt4acc_lib.model.output.track import ParticleState
from dt4acc_lib.model.utils.command import ReadCommand

from tests.recording_builder import RecordingBuilder

SIGMA = 0.05  # mm


def on(sigma=SIGMA, seed=1):
    return Noise(sigma=sigma, enabled=True, seed=seed)


# --- the noise itself
def test_off_by_default_and_unchanged():
    values = np.array([1.0, -2.0, math.nan])
    for noise in (Noise(sigma=1.0), Noise(sigma=0.0, enabled=True), BpmNoise().sa, BpmNoise().tbt):
        assert not noise.active
        np.testing.assert_array_equal(noise.apply(values), values)
    assert Noise().apply(1.5) == 1.5


def test_zero_mean_and_sigma():
    sample = on(seed=7).apply(np.zeros(200_000))
    assert abs(sample.mean()) < 5 * SIGMA / math.sqrt(len(sample))
    assert sample.std() == pytest.approx(SIGMA, rel=0.01)


def test_no_beam_stays_no_beam_and_float_stays_float():
    noise = on()
    assert math.isnan(noise.apply(math.nan))
    assert isinstance(noise.apply(1.0), float) and noise.apply(1.0) != 1.0


def test_seed_reproduces():
    np.testing.assert_array_equal(on(seed=3).apply(np.zeros(5)), on(seed=3).apply(np.zeros(5)))
    assert not np.array_equal(on(seed=3).apply(np.zeros(5)), on(seed=4).apply(np.zeros(5)))


@pytest.mark.parametrize("sigma", [-1e-3, math.nan, math.inf])
def test_sigma_finite_and_not_negative(sigma):
    with pytest.raises(ValueError):
        Noise(sigma=sigma)
    noise = Noise(sigma=0.1)
    with pytest.raises(ValueError):
        noise.set_sigma(sigma)
    assert noise.sigma == 0.1


def test_random_variable():
    rv = on().random_variable()
    assert rv.mean() == 0.0 and rv.std() == pytest.approx(SIGMA)


# --- the PVs that set it
class KwargsBuilder(RecordingBuilder):
    """also keeps the records' callbacks"""

    def __init__(self):
        super().__init__()
        self.kwargs = {}

    def __getattr__(self, kind):
        make = super().__getattr__(kind)

        def make_and_keep(name, *args, **kwargs):
            self.kwargs[name] = kwargs
            return make(name, *args, **kwargs)

        return make_and_keep


def test_pvs_set_the_noise():
    noise, builder = BpmNoise(), KwargsBuilder()
    initialize_bpm_noise_pvs(noise, builder=builder)
    assert set(builder.records) == {
        f"noise:bpm:{k}:{p}" for k in ("sa", "tbt") for p in ("enable", "sigma")
    }
    sa = {p: builder.kwargs[f"noise:bpm:sa:{p}"] for p in ("enable", "sigma")}
    sa["enable"]["on_update"](1)
    assert noise.sa.enabled and not noise.tbt.enabled
    assert not sa["sigma"]["validate"](None, -1.0) and noise.sa.sigma == BpmNoise().sa.sigma
    assert sa["sigma"]["validate"](None, 0.2)
    sa["sigma"]["on_update"](0.2)
    assert noise.sa.sigma == 0.2


def test_a_line_only_slow_acquisition():
    builder = RecordingBuilder()
    initialize_bpm_noise_pvs(BpmNoise(), builder=builder, kinds=("sa",))
    assert set(builder.records) == {"noise:bpm:sa:enable", "noise:bpm:sa:sigma"}


# --- where it acts
class Record:
    def __init__(self):
        self.value = None

    def set(self, value, *args, **kwargs):
        self.value = value


def orbit(x):
    rcmd = ReadCommand("track", "pos")
    track = [SimpleNamespace(fam_name=n, uid=n, x=v, y=-v) for n, v in (("BPM1", x), ("Q1", 2 * x))]
    return rcmd, TranslatedReading(rcmd, [SingleReading(cmd=rcmd, name="test", payload=SimpleNamespace(track=track))])


def view_with(noise):
    view = View(bpms=["BPM1"], bpm_noise=noise)
    view.update_process_variables({ReadCommand("beam", p): Record() for p in ("x", "y", "found")})
    view.update_process_variables({ReadCommand("BPM1", p): Record() for p in ("x", "y")})
    return view


def value(view, device, prop):
    return view.process_variables[ReadCommand(device, prop)].value


@pytest.mark.parametrize("noise", [None, Noise(sigma=SIGMA)])
def test_view_without_noise_shows_the_model(noise):
    view = view_with(noise)
    view.update_track(*orbit(1e-3))
    assert value(view, "BPM1", "x") == 1e-3 * M2MM and value(view, "BPM1", "y") == -1e-3 * M2MM


def test_view_bpms_noisy_model_not():
    view = view_with(on())
    view.update_track(*orbit(1e-3))
    assert value(view, "beam", "x") == [1e-3, 2e-3], "the model stays the model"
    assert value(view, "BPM1", "x") != pytest.approx(1e-3 * M2MM, abs=1e-12)
    assert value(view, "BPM1", "x") == pytest.approx(1e-3 * M2MM, abs=6 * SIGMA)


def test_view_no_beam_stays_nan():
    view = view_with(on())
    view.update_track(*orbit(1e-3))
    rcmd, _ = orbit(0.0)
    view.update_track(rcmd, TranslatedReading(rcmd, [SingleReading(cmd=rcmd, name="test", payload=None)]))
    assert math.isnan(value(view, "BPM1", "x"))


def test_ring_turn_by_turn_noisy():
    tbt = SimpleNamespace(
        offset=ParticleState.from_sequence([0.0] * 6), n_turns=4, backend=None, monitors=["BPM1"]
    )
    builder = RecordingBuilder()
    pvs = TurnByTurnPVs(tbt, builder=builder, noise=on())
    x = np.array([[1e-3], [2e-3], [math.nan], [math.nan]])
    pvs.publish(SimpleNamespace(start=[0.0] * len(COORDINATES), monitors=["BPM1"], x=x, y=-x,
                                survived=np.array([[1], [1], [0], [0]]), n_turns=4))
    got = builder.records["BPM1:signal:tbt:X"].value
    assert np.isnan(got[2:]).all()
    assert not np.allclose(got[:2], x[:2, 0] * M2MM, rtol=0, atol=1e-12)
    np.testing.assert_allclose(got[:2], x[:2, 0] * M2MM, atol=6 * SIGMA)


class Shot:
    monitors = ["BPM1", "BPM2"]
    line_exit = injected = ParticleState.from_sequence([0.0] * 6)
    _x = np.array([[1e-3, 2e-3], [3e-3, math.nan]])

    def x(self):
        return self._x

    def y(self):
        return -self._x

    def survived(self):
        return np.array([1, 0])


def injection_pvs(noise):
    handover = SimpleNamespace(monitors=Shot.monitors, geometry=ParticleState.from_sequence([0.0] * 6), n_turns=2,
                               ring=None)
    builder = RecordingBuilder()
    pvs = InjectionPVs(handover, builder=builder, noise=noise)
    pvs.publish(Shot())
    return builder.records


def test_injection_without_noise_exactly_the_model():
    records = injection_pvs(Noise(sigma=SIGMA))
    np.testing.assert_array_equal(records["INJ:tbt:x"].value, Shot._x.ravel())
    np.testing.assert_array_equal(records["BPM1:signal:tbt:X"].value, Shot._x[:, 0] * M2MM)


def test_injection_one_sample_for_both_pvs():
    records = injection_pvs(on())
    inj = records["INJ:tbt:x"].value.reshape(Shot._x.shape)
    assert not np.allclose(inj[0], Shot._x[0], rtol=0, atol=1e-12)
    for k, bpm in enumerate(Shot.monitors):
        np.testing.assert_allclose(records[f"{bpm}:signal:tbt:X"].value, inj[:, k] * M2MM, rtol=1e-12)
    assert math.isnan(inj[1, 1])
