"""
test_maxiv_r1_beam_loss.py
==========================
MAX IV R1 twin: beam loss and the two ways back.

A 10 mrad horizontal kick makes the optics calculation fail: the ring
simulator goes to ALARM ("Beam loss"). Then

    Reset    clears the error and recalculates on the CURRENT lattice:
             recovers only once the cause is undone
    Reinit   reloads the NOMINAL lattice and refreshes every magnet device:
             recovers with the cause still written, and undoes it

Each recovery takes ~20 s. Every test leaves the twin at nominal.
"""

import numpy as np
import pytest

from .conftest import (
    RECOVERY_TIMEOUT_S,
    beam_lost,
    beam_ok,
    read_array,
    reinit,
    wait_until,
)

pytestmark = pytest.mark.integration

LETHAL_KICK = 1e-2  # rad; 3 mrad still circulates
SAFE_KICK = 1e-3


def _tunes(dp_ring_sim) -> np.ndarray:
    return np.array([read_array(dp_ring_sim, "nu_x")[-1],
                     read_array(dp_ring_sim, "nu_y")[-1]]) / (2 * np.pi)


@pytest.fixture
def nominal(dp_ring_sim, dp_steerer_h):
    """Nominal tunes and steerer value; afterwards back to nominal, whatever happened."""
    dp_ring_sim.set_timeout_millis(int(RECOVERY_TIMEOUT_S * 1000))
    state = {"tunes": _tunes(dp_ring_sim), "steerer": dp_steerer_h.magnetic_strength}
    yield state
    dp_steerer_h.magnetic_strength = state["steerer"]
    if not wait_until(lambda: beam_ok(dp_ring_sim), timeout_s=5.0):
        reinit(dp_ring_sim)


def _lose_beam(dp_ring_sim, dp_steerer_h):
    dp_steerer_h.magnetic_strength = LETHAL_KICK
    assert wait_until(lambda: beam_lost(dp_ring_sim)), "10 mrad kick did not lose the beam"


def _back_at_nominal(dp_ring_sim, nominal) -> bool:
    return beam_ok(dp_ring_sim) and np.allclose(_tunes(dp_ring_sim), nominal["tunes"],
                                                rtol=0, atol=1e-9)


def test_moderate_kick_keeps_beam(dp_ring_sim, dp_steerer_h, nominal):
    dp_steerer_h.magnetic_strength = SAFE_KICK
    assert wait_until(lambda: not np.allclose(_tunes(dp_ring_sim), nominal["tunes"],
                                              rtol=0, atol=1e-9))
    assert beam_ok(dp_ring_sim)


def test_large_kick_loses_beam(dp_ring_sim, dp_steerer_h, nominal):
    _lose_beam(dp_ring_sim, dp_steerer_h)
    assert "Beam loss" in dp_ring_sim.status()


def test_reset_keeps_alarm_while_cause_is_written(dp_ring_sim, dp_steerer_h, nominal):
    _lose_beam(dp_ring_sim, dp_steerer_h)
    dp_ring_sim.command_inout("Reset")
    assert wait_until(lambda: beam_lost(dp_ring_sim)), \
        "Reset recovered although the lethal kick is still in the lattice"
    assert not beam_ok(dp_ring_sim)


def test_reset_recovers_after_cause_is_undone(dp_ring_sim, dp_steerer_h, nominal):
    _lose_beam(dp_ring_sim, dp_steerer_h)
    dp_steerer_h.magnetic_strength = nominal["steerer"]
    dp_ring_sim.command_inout("Reset")
    assert wait_until(lambda: _back_at_nominal(dp_ring_sim, nominal),
                      timeout_s=RECOVERY_TIMEOUT_S), "Reset did not bring the beam back"


def test_reinit_recovers_and_restores_nominal_lattice(dp_ring_sim, dp_steerer_h, nominal):
    _lose_beam(dp_ring_sim, dp_steerer_h)
    reinit(dp_ring_sim)  # lethal kick still written
    assert wait_until(lambda: _back_at_nominal(dp_ring_sim, nominal),
                      timeout_s=RECOVERY_TIMEOUT_S), "Reinit did not restore the nominal optics"
    assert wait_until(lambda: dp_steerer_h.magnetic_strength == nominal["steerer"]), \
        "steerer device not refreshed to its nominal value after Reinit"
