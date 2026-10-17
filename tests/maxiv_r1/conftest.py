"""
conftest.py
===========
Shared fixtures for the MAX IV R1 twin tests.

The offline tests need only the R1 lattice file; the integration tests
need a running twin (dt4acc_maxiv_r1) and are skipped otherwise.
"""

import os
import time
from importlib.resources import files
from pathlib import Path

import numpy as np
import pytest

LATTICE_FILE = Path(os.environ.get(
    "DT4ACC_LATTICE_FILE",
    Path.home() / "Documents" / "dt4acc_config_data" / "R1_lat_indexed.json",
))
SETUP_FILE = Path(str(files("dt4acc").joinpath(
    "custom_facility", "maxiv_r1", "resources", "accelerator_setup_maxiv_r1.json"
)))

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


def read_array(dp, attr: str) -> np.ndarray:
    return np.asarray(dp.read_attribute(attr).value, dtype=np.float64)


@pytest.fixture
def r1_setup():
    """Point dt4acc at the R1 setup file and lattice, restore afterwards."""
    if not LATTICE_FILE.exists():
        pytest.skip(f"R1 lattice not found: {LATTICE_FILE}")
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
