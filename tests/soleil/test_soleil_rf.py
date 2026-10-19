"""
test_soleil_rf.py
=================
SOLEIL II twin: the RF.

    AN02-SD/RF-CAV/CAV.frequency       closed orbit through dispersion, linear
    AN02-SD/RF-CAV/CAV.voltage         small change of beta_x (longitudinal)
    ringsimulator.reference_frequency  kHz, fanned out to the main cavity only
                                       (not the harmonic cavity AN06-SD/RF-HARM/CAV)

Every test restores the nominal values; a lost beam is recovered by Reinit.
"""

import numpy as np
import pytest

from .conftest import HARMONIC_CAVITY, MAIN_CAVITY, beam_ok, proxy, read_array, reinit, wait_until

pytestmark = pytest.mark.integration

NOMINAL_FREQUENCY_HZ = 352_314_167.2312   # RF_002 in the SOLEIL II lattice
FREQUENCY_STEP_HZ = 100.0
VOLTAGE_STEP = 0.05                       # relative


@pytest.fixture(scope="module")
def dp_cavity():
    return proxy(MAIN_CAVITY)


@pytest.fixture(scope="module")
def dp_harmonic():
    return proxy(HARMONIC_CAVITY)


@pytest.fixture
def rf_nominal(dp_ring_sim, dp_cavity, dp_harmonic):
    nominal = {"frequency": dp_cavity.frequency, "voltage": dp_cavity.voltage,
               "harmonic_frequency": dp_harmonic.frequency}
    assert nominal["frequency"] == pytest.approx(NOMINAL_FREQUENCY_HZ, rel=1e-9), \
        "main cavity not at its nominal frequency before the test"
    baseline = {name: read_array(dp_ring_sim, name) for name in ("orbit_x", "beta_x")}
    yield nominal, baseline
    dp_cavity.frequency = nominal["frequency"]
    dp_cavity.voltage = nominal["voltage"]
    dp_harmonic.frequency = nominal["harmonic_frequency"]
    if not wait_until(lambda: beam_ok(dp_ring_sim) and _close(dp_ring_sim, baseline), timeout_s=30.0):
        reinit(dp_ring_sim)


def _close(dp_ring_sim, baseline, atol=1e-12) -> bool:
    return all(np.allclose(read_array(dp_ring_sim, name), value, rtol=1e-9, atol=atol)
               for name, value in baseline.items())


def _step(dp, attr, value, dp_ring_sim, observable, previous):
    dp.write_attribute(attr, value)
    assert wait_until(lambda: dp.read_attribute(attr).value == pytest.approx(value, rel=1e-12)), \
        f"{attr} readback did not follow {value}"
    assert wait_until(lambda: not np.array_equal(read_array(dp_ring_sim, observable), previous)), \
        f"{observable} unchanged after writing {attr} = {value}"
    assert beam_ok(dp_ring_sim)
    return read_array(dp_ring_sim, observable)


def test_rf_nominal_values(dp_ring_sim, dp_cavity):
    assert dp_cavity.frequency == pytest.approx(NOMINAL_FREQUENCY_HZ, rel=1e-9)
    assert dp_cavity.voltage > 0
    assert dp_ring_sim.reference_frequency == pytest.approx(NOMINAL_FREQUENCY_HZ * 1e-3, rel=1e-9)


def test_cavity_frequency_moves_orbit(dp_ring_sim, dp_cavity, rf_nominal):
    """Higher RF frequency -> shorter path -> orbit moves inwards (mean x < 0), and back."""
    nominal, baseline = rf_nominal
    start = baseline["orbit_x"]
    up = _step(dp_cavity, "frequency", nominal["frequency"] + FREQUENCY_STEP_HZ, dp_ring_sim, "orbit_x", start)
    down = _step(dp_cavity, "frequency", nominal["frequency"] - FREQUENCY_STEP_HZ, dp_ring_sim, "orbit_x", up)
    mean_up, mean_down = np.mean(up - start), np.mean(down - start)
    assert mean_up < -1e-7
    assert mean_down > 1e-7
    assert mean_up == pytest.approx(-mean_down, rel=0.05)
    dp_cavity.frequency = nominal["frequency"]
    assert wait_until(lambda: _close(dp_ring_sim, baseline)), "orbit not restored"


def test_cavity_voltage_changes_optics(dp_ring_sim, dp_cavity, rf_nominal):
    nominal, baseline = rf_nominal
    previous = baseline["beta_x"]
    for factor in (1 + VOLTAGE_STEP, 1 - VOLTAGE_STEP):
        beta_x = _step(dp_cavity, "voltage", nominal["voltage"] * factor, dp_ring_sim, "beta_x", previous)
        assert np.abs(beta_x - baseline["beta_x"]).max() > 1e-11   # SOLEIL: ~6e-10 for 5 %
        previous = beta_x
    dp_cavity.voltage = nominal["voltage"]
    assert wait_until(lambda: _close(dp_ring_sim, baseline)), "optics not restored"


def test_reference_frequency_drives_main_cavity_only(dp_ring_sim, dp_cavity, rf_nominal):
    """reference_frequency [kHz] -> the main cavity: the same orbit as writing
    the main cavity directly (the harmonic cavity unchanged, else the orbits
    would differ)."""
    nominal, baseline = rf_nominal
    value_hz = nominal["frequency"] + FREQUENCY_STEP_HZ
    via_reference = _step(dp_ring_sim, "reference_frequency", value_hz * 1e-3,
                          dp_ring_sim, "orbit_x", baseline["orbit_x"])
    dp_ring_sim.reference_frequency = nominal["frequency"] * 1e-3
    assert wait_until(lambda: _close(dp_ring_sim, baseline, atol=1e-9)), "orbit not restored"
    via_cavity = _step(dp_cavity, "frequency", value_hz, dp_ring_sim, "orbit_x", baseline["orbit_x"])
    np.testing.assert_allclose(via_reference, via_cavity, rtol=1e-6, atol=1e-12)


@pytest.mark.xfail(strict=True, reason="twin: the cavity device's frequency readback is not refreshed "
                                       "after a reference_frequency fan-out (the lattice is)")
def test_cavity_readback_follows_reference_frequency(dp_ring_sim, dp_cavity, rf_nominal):
    nominal, baseline = rf_nominal
    value_hz = nominal["frequency"] + FREQUENCY_STEP_HZ
    _step(dp_ring_sim, "reference_frequency", value_hz * 1e-3, dp_ring_sim, "orbit_x", baseline["orbit_x"])
    assert wait_until(lambda: dp_cavity.frequency == pytest.approx(value_hz, rel=1e-12), timeout_s=10.0)
