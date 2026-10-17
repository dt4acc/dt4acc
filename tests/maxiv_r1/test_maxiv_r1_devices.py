"""
test_maxiv_r1_devices.py
========================
MAX IV R1 twin: every changeable magnet device, stepped up and down.

Each device is written nominal + step, nominal - step and back to nominal;
its readback must follow and the optics observable of its kind must move:

    steerer H / V     closed orbit x / y   linear: up and down move opposite ways
    quadrupole, bend  tunes                linear
    sextupole         chromaticity         linear
    skew quadrupole   beta_y               quadratic: coupling, same way for +/-

Back at nominal everything must return exactly to the starting optics.

    pytest tests/maxiv_r1/test_maxiv_r1_devices.py                   # one device per family
    DT4ACC_R1_ALL_DEVICES=1 pytest tests/maxiv_r1/test_maxiv_r1_devices.py   # all 324 (~30 min)

Read-only devices (BPMs) are covered in test_maxiv_r1_twin.py; beam loss and
Reset / Reinit in test_maxiv_r1_beam_loss.py.
"""

import json
import os
import re
from dataclasses import dataclass

import numpy as np
import pytest

from .conftest import SETUP_FILE, read_array, wait_settled, wait_until

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Kind:
    observables: tuple[str, ...]
    zero_step: float     # step when the nominal value is 0
    min_change: float    # max |observable change| a step must exceed
    linear: bool         # up / down change opposite (True) or same (False) way


KINDS = {
    ("Steerer", "H"): Kind(("orbit_x",), 1e-5, 1e-6, True),
    ("Steerer", "V"): Kind(("orbit_y",), 1e-5, 1e-6, True),
    ("Quadrupole", ""): Kind(("nu_x", "nu_y"), 1e-2, 1e-5, True),
    ("Bend", ""): Kind(("nu_x", "nu_y"), 1e-2, 1e-9, True),
    ("Sextupole", ""): Kind(("xi_x", "xi_y"), 1.0, 1e-6, True),
    ("SkewQuadrupoleCorrector", ""): Kind(("beta_y",), 1e-3, 1e-9, False),
}
RELATIVE_STEP = 0.01
ALL_OBSERVABLES = ("orbit_x", "orbit_y", "beta_x", "beta_y", "nu_x", "nu_y", "xi_x", "xi_y")


def _family(device_name: str) -> str:
    return re.sub(r"-\d+.*$", "", device_name.split("/")[-1])


def _magnet_devices() -> list[tuple[str, tuple[str, str]]]:
    """(device name, kind key) of the magnet devices in the R1 setup; one per
    family unless DT4ACC_R1_ALL_DEVICES is set."""
    if not SETUP_FILE.exists():
        return []  # nothing to parametrize: the test is reported as skipped
    entries = json.loads(SETUP_FILE.read_text())
    devices, families = [], set()
    for entry in entries:
        key = (entry.get("type"), entry.get("subtype") or "")
        if key not in KINDS or "/MAG/" not in entry["name"]:
            continue
        family = _family(entry["name"])
        if not os.environ.get("DT4ACC_R1_ALL_DEVICES") and family in families:
            continue
        families.add(family)
        devices.append((entry["name"], key))
    return devices


def _observe(dp_ring_sim, names) -> np.ndarray:
    """Observables in one vector; tunes as total phase advance / 2 pi."""
    parts = []
    for name in names:
        value = read_array(dp_ring_sim, name)
        parts.append(value[-1:] / (2 * np.pi) if name.startswith("nu_") else value)
    return np.concatenate(parts)


def _snapshot(dp_ring_sim) -> dict[str, np.ndarray]:
    return {name: _observe(dp_ring_sim, (name,)) for name in ALL_OBSERVABLES}


def _restored(dp_ring_sim, baseline) -> bool:
    now = _snapshot(dp_ring_sim)
    return all(np.allclose(now[k], baseline[k], rtol=1e-9, atol=1e-12) for k in baseline)


@pytest.mark.parametrize("device_name, kind_key", _magnet_devices(),
                         ids=[name for name, _ in _magnet_devices()])
def test_magnet_up_and_down(device_name, kind_key, dp_ring_sim):
    import tango

    kind = KINDS[kind_key]
    dp = tango.DeviceProxy(device_name)
    nominal = dp.magnetic_strength
    step = abs(nominal) * RELATIVE_STEP if abs(nominal) > 1e-9 else kind.zero_step
    observe = lambda: _observe(dp_ring_sim, kind.observables)  # noqa: E731
    start = wait_settled(observe)  # no update of an earlier test still pending
    baseline = _snapshot(dp_ring_sim)

    def step_to(value, previous):
        """Write value, wait for readback and recalculation; settled observed state."""
        dp.magnetic_strength = value
        assert wait_until(lambda: dp.magnetic_strength == pytest.approx(value, rel=1e-9, abs=1e-15)), \
            f"readback did not follow the write of {value}"
        assert wait_until(lambda: not np.array_equal(observe(), previous)), \
            f"{kind.observables} unchanged after writing {value}"
        observed = wait_settled(observe)
        change = observed - start
        assert np.abs(change).max() > kind.min_change, \
            f"{kind.observables} moved only {np.abs(change).max():.2e} for a step of {step:.3g}"
        return observed

    try:
        at_up = step_to(nominal + step, start)
        at_down = step_to(nominal - step, at_up)
        up, down = at_up - start, at_down - start
        if kind.linear:
            assert np.dot(up, down) < 0, "up and down steps moved the optics the same way"
        else:
            assert np.dot(up, down) > 0, "expected a quadratic response, got opposite signs"
    finally:
        dp.magnetic_strength = nominal
    assert wait_until(lambda: _restored(dp_ring_sim, baseline)), "optics not restored at nominal"
