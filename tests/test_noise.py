"""Noise on the BPMs' readings (#82): off by default; when on, the BPM PVs
show the model plus a sample of the noise, the model PVs stay the model's"""
import math
from types import SimpleNamespace

import numpy as np
import pytest

# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.core.bl import random_numbers
from dt4acc.core.bl.noise import BpmNoise, GaussianAdditiveNoise
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

SIGMA = 5e-5  # m (0.05 mm)


@pytest.fixture(autouse=True)
def fresh_generator(monkeypatch):
    """each test: the twin's generator not made yet, no DT4ACC_SEED"""
    monkeypatch.setattr(random_numbers, "_generator", None)
    monkeypatch.delenv(random_numbers.SEED_ENV, raising=False)


def on(sigma=SIGMA):
    return GaussianAdditiveNoise(sigma=sigma, enabled=True)


# --- the noise itself
def test_off_by_default_and_unchanged():
    values = np.array([1.0, -2.0, math.nan])
    for noise in (GaussianAdditiveNoise(sigma=1.0), GaussianAdditiveNoise(sigma=0.0, enabled=True), BpmNoise().sa, BpmNoise().tbt):
        assert not noise.active
        np.testing.assert_array_equal(noise.apply(values), values)
    assert GaussianAdditiveNoise().apply(1.5) == 1.5


def test_zero_mean_and_sigma():
    sample = on().apply(np.zeros(200_000))
    assert abs(sample.mean()) < 5 * SIGMA / math.sqrt(len(sample))
    assert sample.std() == pytest.approx(SIGMA, rel=0.01)


def test_no_beam_stays_no_beam_and_float_stays_float():
    noise = on()
    assert math.isnan(noise.apply(math.nan))
    assert isinstance(noise.apply(1.0), float) and noise.apply(1.0) != 1.0


def draws(seed):
    """slow acquisition and turn by turn, one after the other, from a freshly seeded twin"""
    random_numbers._generator = None
    random_numbers.seed(seed)
    noise = BpmNoise(sa=on(), tbt=on())
    return np.concatenate([noise.sa.apply(np.zeros(3)), noise.tbt.apply(np.zeros(3)), noise.sa.apply(np.zeros(2))])


def test_one_generator_seeded_once_reproduces_the_whole_run():
    first = draws(3)
    np.testing.assert_array_equal(draws(3), first)
    assert not np.array_equal(draws(4), first)
    # all noise sources draw from the one generator: one stream, not one per source
    random_numbers._generator = None
    random_numbers.seed(3)
    np.testing.assert_array_equal(on().apply(np.zeros(8)), first)


def test_seeded_again_with_a_warning(caplog):
    on().apply(np.zeros(1))
    with caplog.at_level("WARNING", logger="dt4acc"):
        random_numbers.seed(1)
    assert "seeded again" in caplog.text
    first = on().apply(np.zeros(4))
    random_numbers.seed(1)
    np.testing.assert_array_equal(on().apply(np.zeros(4)), first)


@pytest.mark.parametrize("configured", ["abc", "0x10", "1.5", "-3"])
def test_bad_seed_is_a_clear_error(monkeypatch, configured):
    monkeypatch.setenv(random_numbers.SEED_ENV, configured)
    with pytest.raises(ValueError, match=random_numbers.SEED_ENV):
        random_numbers.generator()


def test_sigma_not_specified():
    noise = GaussianAdditiveNoise(enabled=True)
    assert noise.sigma is None and not noise.active
    assert noise.apply(1.5) == 1.5
    noise.set_sigma(SIGMA)
    assert noise.active
    noise.set_sigma(None)
    assert not noise.active


def test_seed_from_the_environment(monkeypatch):
    monkeypatch.setenv(random_numbers.SEED_ENV, "3")
    first = on().apply(np.zeros(8))
    random_numbers._generator = None
    np.testing.assert_array_equal(on().apply(np.zeros(8)), first)


def test_a_generator_of_its_own_is_the_exception():
    own = GaussianAdditiveNoise(sigma=SIGMA, enabled=True, rng=np.random.default_rng(5))
    expected = GaussianAdditiveNoise(sigma=SIGMA, enabled=True, rng=np.random.default_rng(5)).apply(np.zeros(4))
    np.testing.assert_array_equal(own.apply(np.zeros(4)), expected)
    assert random_numbers._generator is None, "the twin's generator untouched"


@pytest.mark.parametrize("sigma", [-1e-3, math.nan, math.inf])
def test_sigma_finite_and_not_negative(sigma):
    with pytest.raises(ValueError):
        GaussianAdditiveNoise(sigma=sigma)
    noise = GaussianAdditiveNoise(sigma=0.1)
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
    # the PV in mm, the noise in m
    assert builder.kwargs["noise:bpm:sa:sigma"]["initial_value"] == pytest.approx(BpmNoise().sa.sigma * M2MM)
    assert sa["sigma"]["validate"](None, 0.2)
    sa["sigma"]["on_update"](0.2)
    assert noise.sa.sigma == pytest.approx(0.2 / M2MM)


def test_pvs_republish_on_a_change():
    calls = []
    builder = KwargsBuilder()
    initialize_bpm_noise_pvs(BpmNoise(), builder=builder, on_change={"sa": lambda: calls.append("sa")})
    builder.kwargs["noise:bpm:sa:enable"]["on_update"](1)
    builder.kwargs["noise:bpm:sa:sigma"]["on_update"](0.2)
    builder.kwargs["noise:bpm:tbt:enable"]["on_update"](1)
    assert calls == ["sa", "sa"]


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


@pytest.mark.parametrize("noise", [None, GaussianAdditiveNoise(sigma=SIGMA)])
def test_view_without_noise_shows_the_model(noise):
    view = view_with(noise)
    view.update_track(*orbit(1e-3))
    assert value(view, "BPM1", "x") == 1e-3 * M2MM and value(view, "BPM1", "y") == -1e-3 * M2MM


def test_view_bpms_noisy_model_not():
    view = view_with(on())
    view.update_track(*orbit(1e-3))
    assert value(view, "beam", "x") == [1e-3, 2e-3], "the model stays the model"
    assert value(view, "BPM1", "x") != pytest.approx(1e-3 * M2MM, abs=1e-12)
    assert value(view, "BPM1", "x") == pytest.approx(1e-3 * M2MM, abs=6 * SIGMA * M2MM)


def test_view_draws_once_per_plane(monkeypatch):
    shapes = []
    sample = random_numbers.sample

    def counting(rv, shape, rng=None):
        shapes.append(shape)
        return sample(rv, shape, rng=rng)

    monkeypatch.setattr(random_numbers, "sample", counting)
    view_with(on()).update_track(*orbit(1e-3))
    assert shapes == [(2,), (2,)]


def test_view_no_beam_stays_nan_and_the_cache_the_last_good_data():
    view = view_with(on())
    view.update_track(*orbit(1e-3))
    rcmd, _ = orbit(0.0)
    view.update_track(rcmd, TranslatedReading(rcmd, [SingleReading(cmd=rcmd, name="test", payload=None)]))
    assert math.isnan(value(view, "BPM1", "x"))
    cached = view.last_data_cache[ReadCommand("track", "pos")]
    assert [pos.x for pos in cached.track] == [1e-3, 2e-3]


def test_view_republishes_with_and_without_noise():
    noise = GaussianAdditiveNoise(sigma=SIGMA)
    view = view_with(noise)
    view.republish_monitors()  # no track yet: nothing
    assert value(view, "BPM1", "x") is None
    view.update_track(*orbit(1e-3))
    noise.enabled = True
    view.republish_monitors()
    assert value(view, "BPM1", "x") != pytest.approx(1e-3 * M2MM, abs=1e-12)
    noise.enabled = False
    view.republish_monitors()
    assert value(view, "BPM1", "x") == 1e-3 * M2MM


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
    np.testing.assert_allclose(got[:2], x[:2, 0] * M2MM, atol=6 * SIGMA * M2MM)


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
    records = injection_pvs(GaussianAdditiveNoise(sigma=SIGMA))
    np.testing.assert_array_equal(records["INJ:tbt:x"].value, Shot._x.ravel())
    np.testing.assert_array_equal(records["BPM1:signal:tbt:X"].value, Shot._x[:, 0] * M2MM)


def test_injection_one_sample_for_both_pvs():
    records = injection_pvs(on())
    inj = records["INJ:tbt:x"].value.reshape(Shot._x.shape)
    assert not np.allclose(inj[0], Shot._x[0], rtol=0, atol=1e-12)
    for k, bpm in enumerate(Shot.monitors):
        np.testing.assert_allclose(records[f"{bpm}:signal:tbt:X"].value, inj[:, k] * M2MM, rtol=1e-12)
    assert math.isnan(inj[1, 1])
