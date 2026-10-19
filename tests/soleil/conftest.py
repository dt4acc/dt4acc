"""
conftest.py
===========
Shared fixtures for the SOLEIL II twin tests.

The offline tests need the SOLEIL lattice and device database; the
integration tests need a running twin (run_soleil_twin.py, devices
registered with register_devices.py --register-devices) and are skipped
otherwise. Files: DT4ACC_LATTICE_FILE / DT4ACC_ACCELERATOR_SETUP_FILE, else
~/Documents/dt4acc_config_data/.
"""

import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

from dt4acc.config.data.querries import get_data_file
from dt4acc.custom_facility.soleil.utils.command_line_interface import DEFAULT_LATTICE_FILE

LATTICE_FILE = Path(os.environ.get("DT4ACC_LATTICE_FILE", DEFAULT_LATTICE_FILE))
SETUP_FILE = get_data_file()
LOAD_MANAGERS = "dt4acc.custom_facility.soleil.liasion_translator_setup:load_managers"

RING_SIM_DEV = "simulator/ringsimulator/ringsimulator"

# known SOLEIL II devices (all in the device database)
TEST_STEERER_H = "AN01-AR/EM-COR/SHF.01-CDLH.01"   # on sextupole SH1_COR_001, B1, nominal 0
TEST_QUAD = "AN01-AR/EM-QP/QF01.01"                # K = 9.07 /m^2
MAIN_CAVITY = "AN02-SD/RF-CAV/CAV"                 # RF_002
HARMONIC_CAVITY = "AN06-SD/RF-HARM/CAV"            # RFHARMON_002

CLIENT_TIMEOUT_MS = 30_000   # a write waits while the twin recalculates (4087 elements, 6D)
SETTLE_TIMEOUT_S = 30.0
QUIET_S = 4.0                # longer than heartbeat + delayed read: no update pending
RECOVERY_TIMEOUT_S = 120.0   # Reset / Reinit: lattice reload + full recalculation


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (require running TANGO server)"
    )


def setup_entries() -> list:
    return json.loads(SETUP_FILE.read_text())


def wait_until(predicate, timeout_s: float = SETTLE_TIMEOUT_S, period_s: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(period_s)
    return predicate()


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


def tunes(dp_ring_sim) -> np.ndarray:
    """Total phase advance / 2 pi."""
    return np.array([read_array(dp_ring_sim, "nu_x")[-1], read_array(dp_ring_sim, "nu_y")[-1]]) / (2 * np.pi)


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


def proxy(device_name: str):
    """DeviceProxy with a client timeout long enough for a twin write."""
    tango = pytest.importorskip("tango")
    try:
        dp = tango.DeviceProxy(device_name)
        dp.set_timeout_millis(CLIENT_TIMEOUT_MS)
        dp.ping()
        return dp
    except Exception as exc:
        pytest.skip(f"{device_name} not reachable (is the SOLEIL twin running?): {exc}")


@pytest.fixture(scope="session")
def soleil_files():
    if not LATTICE_FILE.exists():
        pytest.skip(f"SOLEIL lattice not found: {LATTICE_FILE}")
    if not SETUP_FILE.exists():
        pytest.skip(f"device database not found: {SETUP_FILE}")
    if not any(e.get("name") == TEST_QUAD for e in setup_entries()):
        pytest.skip(f"{SETUP_FILE} is not the SOLEIL II device database")
    os.environ.setdefault("DT4ACC_LOAD_MANAGERS", LOAD_MANAGERS)
    return LATTICE_FILE, SETUP_FILE


@pytest.fixture(scope="session")
def soleil_ring(soleil_files):
    from dt4acc.core.bl.handle_lattice import LatticeLoader

    loader = LatticeLoader()
    loader.set_lattice_file(soleil_files[0])
    return loader.load()


@pytest.fixture(scope="session")
def tango_db():
    tango = pytest.importorskip("tango")
    proxy(RING_SIM_DEV)
    return tango.Database()


@pytest.fixture(scope="session")
def dp_ring_sim():
    dp = proxy(RING_SIM_DEV)
    if beam_lost(dp):  # left over from an earlier run
        reinit(dp)
    if not wait_until(lambda: len(read_array(dp, "beta_x")) > 10, timeout_s=60.0):
        pytest.skip("twin has not produced a calculation yet")
    return dp


@pytest.fixture(scope="session")
def dp_steerer_h():
    return proxy(TEST_STEERER_H)


@pytest.fixture(scope="session")
def dp_quad():
    return proxy(TEST_QUAD)
