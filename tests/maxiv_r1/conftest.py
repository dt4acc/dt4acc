"""
conftest.py
===========
Shared fixtures for the MAX IV R1 twin tests.

The offline tests need only the R1 lattice file; the integration tests
need a running twin (dt4acc_maxiv_r1) and are skipped otherwise.
"""

import os
import time
from pathlib import Path

import numpy as np
import pytest

from dt4acc.config.data.querries import get_data_file
from dt4acc.custom_facility.maxiv_r1.run_maxiv_r1_twin import DEFAULT_LATTICE_FILE

# the files the twin runs with (~/Documents/dt4acc_config_data/ unless overridden)
LATTICE_FILE = Path(os.environ.get("DT4ACC_LATTICE_FILE", DEFAULT_LATTICE_FILE))
SETUP_FILE = get_data_file()

RING_SIM_DEV = "simulator/ringsimulator/ringsimulator"

# known R1 devices: a horizontal corrector at 0 and a focusing quadrupole
TEST_STEERER_H = "R1-101/MAG/CRCOX-01"
TEST_QUAD = "R1-101/MAG/SQFO-01"

SETTLE_TIMEOUT_S = 15.0  # heartbeat is 1 s; leave room for the delayed reads


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (require running TANGO server)"
    )


def wait_until(predicate, timeout_s: float = SETTLE_TIMEOUT_S, period_s: float = 0.5) -> bool:
    """Poll predicate until it is true or timeout_s elapsed."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(period_s)
    return predicate()


QUIET_S = 2.5  # longer than heartbeat + delayed read (~2 s): no update pending


def wait_settled(read, timeout_s: float = SETTLE_TIMEOUT_S, quiet_s: float = QUIET_S,
                 period_s: float = 0.25) -> np.ndarray:
    """Value of read() once it has not changed for quiet_s."""
    deadline = time.monotonic() + timeout_s
    value, since = read(), time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(period_s)
        now = read()
        if not np.array_equal(now, value):
            value, since = now, time.monotonic()
        elif time.monotonic() - since >= quiet_s:
            return value
    raise AssertionError(f"value still changing after {timeout_s} s")


def read_array(dp, attr: str) -> np.ndarray:
    return np.atleast_1d(np.asarray(dp.read_attribute(attr).value, dtype=np.float64))


RECOVERY_TIMEOUT_S = 60.0  # Reset / Reinit take ~20 s: lattice reload + full recalculation


def beam_lost(dp_ring_sim) -> bool:
    """A failed optics calculation sets the ring simulator to ALARM."""
    import tango
    return dp_ring_sim.state() == tango.DevState.ALARM


def beam_ok(dp_ring_sim) -> bool:
    import tango
    return dp_ring_sim.state() == tango.DevState.ON and len(read_array(dp_ring_sim, "beta_x")) > 10


def reinit(dp_ring_sim) -> None:
    """Back to the nominal lattice (every magnet at its nominal value)."""
    dp_ring_sim.set_timeout_millis(int(RECOVERY_TIMEOUT_S * 1000))
    dp_ring_sim.command_inout("Reinit")
    assert wait_until(lambda: beam_ok(dp_ring_sim), timeout_s=RECOVERY_TIMEOUT_S), \
        "twin not back to ON after Reinit"


@pytest.fixture
def r1_setup():
    """Point dt4acc at the R1 setup file and lattice, restore afterwards."""
    if not LATTICE_FILE.exists():
        pytest.skip(f"R1 lattice not found: {LATTICE_FILE}")
    if not SETUP_FILE.exists():
        pytest.skip(f"device database not found: {SETUP_FILE}")
    from dt4acc.config.data import querries
    from dt4acc.core.bl.handle_lattice import lattice_loader

    previous_data_file, previous_lattice = querries.get_data_file(), lattice_loader.path
    querries.configure_data_file(SETUP_FILE)
    lattice_loader.set_lattice_file(LATTICE_FILE)
    yield
    querries.configure_data_file(previous_data_file)
    lattice_loader.set_lattice_file(previous_lattice)


def _connect(device_name: str):
    tango = pytest.importorskip("tango")
    try:
        dp = tango.DeviceProxy(device_name)
        dp.ping()
        return dp
    except Exception as exc:
        pytest.skip(f"{device_name} not reachable (is dt4acc_maxiv_r1 running?): {exc}")


@pytest.fixture(scope="session")
def tango_db():
    tango = pytest.importorskip("tango")
    _connect(RING_SIM_DEV)
    return tango.Database()


@pytest.fixture(scope="session")
def dp_ring_sim():
    dp = _connect(RING_SIM_DEV)
    if beam_lost(dp):  # left over from an earlier run
        reinit(dp)
    healthy = wait_until(lambda: len(read_array(dp, "beta_x")) > 10, timeout_s=30.0)
    if not healthy:
        pytest.skip("twin has not produced a calculation yet")
    return dp


@pytest.fixture(scope="session")
def dp_steerer_h():
    return _connect(TEST_STEERER_H)


@pytest.fixture(scope="session")
def dp_quad():
    return _connect(TEST_QUAD)
