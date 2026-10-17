"""
test_maxiv_r1_rf.py
===================
MAX IV R1 twin: the RF chain, stepped up and down.

    simulator/rfpc/CavA.frequency       closed orbit through dispersion, linear
    simulator/rfpc/CavA.voltage         small change of beta_x (longitudinal)
    R1-D100101/RF/MO-01.current_set     sets the cavity voltage: same optics
    ringsimulator.reference_frequency   kHz, fanned out to the cavity frequency

Every test restores the nominal values; a lost beam is recovered by Reinit.
"""

import numpy as np
import pytest

from .conftest import beam_ok, read_array, reinit, wait_until

pytestmark = pytest.mark.integration

CAVITY = "simulator/rfpc/CavA"
RF_PC = "R1-D100101/RF/MO-01"

NOMINAL_FREQUENCY_HZ = 99_930_819.333  # cav575 in R1_lat_indexed.json
NOMINAL_VOLTAGE_V = 560_000.0
FREQUENCY_STEP_HZ = 100.0
VOLTAGE_STEP = 0.05  # relative
RF_WRITE_TIMEOUT_MS = 10_000  # a write waits for the cavity update; 3 s default is too short


@pytest.fixture(scope="module")
def dp_cavity():
    import tango
    dp = tango.DeviceProxy(CAVITY)
    dp.set_timeout_millis(RF_WRITE_TIMEOUT_MS)
    return dp


@pytest.fixture(scope="module")
def dp_rf_pc():
    import tango
    dp = tango.DeviceProxy(RF_PC)
    dp.set_timeout_millis(RF_WRITE_TIMEOUT_MS)
    return dp


@pytest.fixture
def rf_nominal(dp_ring_sim, dp_cavity, dp_rf_pc):
    """Nominal RF values (exact, as read) and optics; afterwards back to nominal."""
    dp_ring_sim.set_timeout_millis(RF_WRITE_TIMEOUT_MS)  # reference_frequency fans out to the cavities
    nominal = {"frequency": dp_cavity.frequency, "voltage": dp_cavity.voltage}
    assert nominal["frequency"] == pytest.approx(NOMINAL_FREQUENCY_HZ, rel=1e-9), \
        "cavity not at its nominal frequency before the test"
    assert nominal["voltage"] == pytest.approx(NOMINAL_VOLTAGE_V), \
        "cavity not at its nominal voltage before the test"
    baseline = {name: read_array(dp_ring_sim, name) for name in ("orbit_x", "beta_x")}
    yield nominal, baseline
    dp_cavity.frequency = nominal["frequency"]
    dp_cavity.voltage = nominal["voltage"]
    dp_rf_pc.current_set = nominal["voltage"]
    if not wait_until(lambda: beam_ok(dp_ring_sim) and _close(dp_ring_sim, baseline), timeout_s=10.0):
        reinit(dp_ring_sim)


def _close(dp_ring_sim, baseline, atol=1e-12) -> bool:
    return all(np.allclose(read_array(dp_ring_sim, name), value, rtol=1e-9, atol=atol)
               for name, value in baseline.items())


def _step(dp, attr, value, dp_ring_sim, observable, previous):
    """Write value, wait for its readback and the recalculation; the observable."""
    dp.write_attribute(attr, value)
    assert wait_until(lambda: dp.read_attribute(attr).value == pytest.approx(value, rel=1e-12)), \
        f"{attr} readback did not follow {value}"
    assert wait_until(lambda: not np.array_equal(read_array(dp_ring_sim, observable), previous)), \
        f"{observable} unchanged after writing {attr} = {value}"
    assert beam_ok(dp_ring_sim)
    return read_array(dp_ring_sim, observable)


def test_rf_nominal_values(dp_ring_sim, dp_cavity, dp_rf_pc):
    assert dp_cavity.frequency == pytest.approx(NOMINAL_FREQUENCY_HZ, rel=1e-9)
    assert dp_cavity.voltage == pytest.approx(NOMINAL_VOLTAGE_V)
    assert dp_rf_pc.current_set == pytest.approx(NOMINAL_VOLTAGE_V)
    assert dp_rf_pc.voltage == pytest.approx(NOMINAL_VOLTAGE_V)
    assert dp_ring_sim.reference_frequency == pytest.approx(NOMINAL_FREQUENCY_HZ * 1e-3, rel=1e-9)


def test_cavity_frequency_moves_orbit(dp_ring_sim, dp_cavity, rf_nominal):
    """Higher RF frequency → shorter path → orbit moves inwards (mean x < 0), and back."""
    nominal, baseline = rf_nominal
    start = baseline["orbit_x"]
    up = _step(dp_cavity, "frequency", nominal["frequency"] + FREQUENCY_STEP_HZ,
               dp_ring_sim, "orbit_x", start)
    down = _step(dp_cavity, "frequency", nominal["frequency"] - FREQUENCY_STEP_HZ,
                 dp_ring_sim, "orbit_x", up)
    mean_up, mean_down = np.mean(up - start), np.mean(down - start)
    assert mean_up < -1e-6
    assert mean_down > 1e-6
    assert mean_up == pytest.approx(-mean_down, rel=0.05)
    dp_cavity.frequency = nominal["frequency"]
    assert wait_until(lambda: _close(dp_ring_sim, baseline)), "orbit not restored"


def test_cavity_voltage_changes_optics(dp_ring_sim, dp_cavity, rf_nominal):
    nominal, baseline = rf_nominal
    previous = baseline["beta_x"]
    for factor in (1 + VOLTAGE_STEP, 1 - VOLTAGE_STEP):
        beta_x = _step(dp_cavity, "voltage", nominal["voltage"] * factor, dp_ring_sim, "beta_x", previous)
        assert np.abs(beta_x - baseline["beta_x"]).max() > 1e-9
        previous = beta_x
    dp_cavity.voltage = nominal["voltage"]
    assert wait_until(lambda: _close(dp_ring_sim, baseline)), "optics not restored"


def test_rf_power_converter_drives_cavity_voltage(dp_ring_sim, dp_cavity, dp_rf_pc, rf_nominal):
    """MO-01 sets the cavity voltage: the same optics as writing CavA.voltage."""
    nominal, baseline = rf_nominal
    value = nominal["voltage"] * (1 + VOLTAGE_STEP)
    via_pc = _step(dp_rf_pc, "current_set", value, dp_ring_sim, "beta_x", baseline["beta_x"])
    assert dp_rf_pc.current_readback == pytest.approx(value)
    assert dp_rf_pc.voltage == pytest.approx(value)

    dp_rf_pc.current_set = nominal["voltage"]
    assert wait_until(lambda: _close(dp_ring_sim, baseline)), "optics not restored"
    via_cavity = _step(dp_cavity, "voltage", value, dp_ring_sim, "beta_x", baseline["beta_x"])
    np.testing.assert_allclose(via_pc, via_cavity, rtol=1e-9, atol=1e-12)


def test_reference_frequency_drives_cavity_frequency(dp_ring_sim, dp_cavity, rf_nominal):
    """reference_frequency [kHz] → every main cavity: the same orbit as writing CavA."""
    nominal, baseline = rf_nominal
    value_hz = nominal["frequency"] + FREQUENCY_STEP_HZ
    via_reference = _step(dp_ring_sim, "reference_frequency", value_hz * 1e-3,
                          dp_ring_sim, "orbit_x", baseline["orbit_x"])

    dp_ring_sim.reference_frequency = nominal["frequency"] * 1e-3
    assert wait_until(lambda: _close(dp_ring_sim, baseline, atol=1e-9)), "orbit not restored"
    via_cavity = _step(dp_cavity, "frequency", value_hz, dp_ring_sim, "orbit_x", baseline["orbit_x"])
    np.testing.assert_allclose(via_reference, via_cavity, rtol=1e-6, atol=1e-12)
