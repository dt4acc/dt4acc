"""Turn by turn data of the BESSY II ring alone: a beam off the closed orbit
oscillates around it with the ring's tunes"""
import asyncio

import numpy as np
import pytest

from dt4acc.custom_facility.bessyii.provide_lattice import provide_backend_encapsulating_lattice
from dt4acc.custom_facility.bessyii.turn_by_turn import RingTurnByTurn
from dt4acc_lib.model.output.track import ParticleState

#: design tunes of the BESSY II twin (TUNEZR:flq:rdH / rdV)
Q = (17.8481, 6.7268)


@pytest.fixture(scope="module")
def backend():
    return provide_backend_encapsulating_lattice()


def run(backend, offset, n_turns=128):
    tbt = RingTurnByTurn(backend, offset=ParticleState.from_sequence(offset), n_turns=n_turns)
    return asyncio.run(tbt.compute())


def peak_tune(signal) -> float:
    """fractional tune of the strongest line, folded into [0, 0.5]"""
    s = np.asarray(signal) - np.mean(signal)
    n = 16 * len(s)
    spectrum = np.abs(np.fft.rfft(s * np.hanning(len(s)), n))
    return np.fft.rfftfreq(n)[np.argmax(spectrum)]


def test_shapes_and_survival(backend):
    r = run(backend, [1e-3, 0, 1e-3, 0, 0, 0], n_turns=64)
    assert len(r.monitors) == 123
    assert r.x().shape == (64, 123) and r.y().shape == (64, 123)
    assert np.all(r.survived() == 1)
    assert np.all(np.isfinite(r.x()))


def test_no_offset_stays_on_the_closed_orbit(backend):
    # the closed orbit is not zero (6D: off momentum orbit), but the same every turn
    r = run(backend, [0.0] * 6, n_turns=16)
    assert np.max(np.abs(r.x() - r.x()[0])) < 1e-9 and np.max(np.abs(r.y() - r.y()[0])) < 1e-9


@pytest.mark.parametrize("plane", [0, 1])
def test_oscillates_with_the_tune(backend, plane):
    offset = [1e-4, 0, 0, 0, 0, 0] if plane == 0 else [0, 0, 1e-4, 0, 0, 0]
    r = run(backend, offset)
    signal = (r.x() if plane == 0 else r.y())[:, 0]
    frac = Q[plane] % 1
    assert peak_tune(signal) == pytest.approx(min(frac, 1 - frac), abs=2e-3)


def test_start_is_closed_orbit_plus_offset(backend):
    offset = np.array([2e-4, 0, -1e-4, 0, 0, 0])
    r = run(backend, offset, n_turns=2)
    co = RingTurnByTurn(backend).closed_orbit()
    np.testing.assert_allclose(r.start.as_array(), co + offset, rtol=0, atol=1e-15)
