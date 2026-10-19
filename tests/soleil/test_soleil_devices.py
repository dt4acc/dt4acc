"""
test_soleil_devices.py
======================
SOLEIL II twin: every changeable magnet device, stepped up and down.

Each device is written nominal + step, nominal - step and back to nominal;
its readback must follow and the optics observable of its kind must move:

    steerer H / V (B1 / A1)          closed orbit x / y   linear
    quadrupole, CQLN (B2)            tunes                linear
    bend                             tunes                linear  -- xfail: the twin
                                     raises "Main strength for dipole not handled"
    sextupole                        chromaticity         linear
    skew quadrupole CQLT (A2)        beta_y               quadratic (coupling)
    octupole (B4)                    nothing linear at zero orbit: readback only

Back at nominal everything must return exactly to the starting optics. The
kind of a steerer (its plane) comes from the liaison manager.

    pytest tests/soleil/test_soleil_devices.py                       # one device per family
    DT4ACC_SOLEIL_ALL_DEVICES=1 pytest tests/soleil/test_soleil_devices.py   # all magnets
"""

import os
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pytest

from .conftest import LOAD_MANAGERS, SETUP_FILE, proxy, read_array, setup_entries, wait_settled, wait_until

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Kind:
    observables: tuple
    zero_step: float           # step when the nominal value is 0
    min_change: float          # max |observable change| a step must exceed
    linear: Optional[bool]     # up / down opposite (True), same (False) way; None: no observable


KINDS = {
    "steerer_x": Kind(("orbit_x",), 1e-5, 1e-7, True),
    "steerer_y": Kind(("orbit_y",), 1e-5, 1e-7, True),
    "quadrupole": Kind(("nu_x", "nu_y"), 1e-2, 1e-6, True),
    "bend": Kind(("nu_x", "nu_y"), 1e-2, 1e-9, True),
    "sextupole": Kind(("xi_x", "xi_y"), 1.0, 1e-6, True),
    "skew_quadrupole": Kind(("beta_y",), 1e-3, 1e-9, False),
    "octupole": Kind((), 1.0, 0.0, None),
}
RELATIVE_STEP = 0.01
ALL_OBSERVABLES = ("orbit_x", "orbit_y", "beta_x", "beta_y", "nu_x", "nu_y", "xi_x", "xi_y")
# chromaticity is a finite difference in momentum: write-back equal to the last bit only
RESTORE_RTOL = {"xi_x": 1e-5, "xi_y": 1e-5}


def _kind(entry) -> Optional[str]:
    t = entry["type"]
    if t == "Steerer":
        from dt4acc.custom_tango.ioc.mexec_server_for_physics_engine import lattice_properties_for_device
        (prop,) = lattice_properties_for_device(entry["name"])
        return {"B1": "steerer_x", "A1": "steerer_y"}[prop]
    return {"Quadrupole": "quadrupole", "QuadrupoleCorrector": "quadrupole", "Bend": "bend",
            "Sextupole": "sextupole", "SkewQuadrupoleCorrector": "skew_quadrupole",
            "Octupole": "octupole"}.get(t)


# known twin gaps: strict, so that a fix shows up as XPASS -> failure
KNOWN_GAPS = {
    "bend": "twin: writing a dipole's main_strength raises 'Main strength for dipole not handled'",
}


def _family(name: str) -> str:
    return re.sub(r"[.\-]\d+.*$", "", name.split("/")[-1])


def _magnet_devices():
    """(device name, kind) of the SOLEIL magnet devices; one per (family, kind)
    unless DT4ACC_SOLEIL_ALL_DEVICES is set."""
    if not SETUP_FILE.exists():
        return []
    os.environ.setdefault("DT4ACC_LOAD_MANAGERS", LOAD_MANAGERS)
    try:
        entries = setup_entries()
        devices, seen = [], set()
        for e in entries:
            kind = _kind(e)
            if kind is None or "/EM-" not in e["name"]:
                continue
            key = (_family(e["name"]), kind)
            if not os.environ.get("DT4ACC_SOLEIL_ALL_DEVICES") and key in seen:
                continue
            seen.add(key)
            marks = [pytest.mark.xfail(strict=True, reason=KNOWN_GAPS[kind])] if kind in KNOWN_GAPS else []
            devices.append(pytest.param(e["name"], kind, id=e["name"], marks=marks))
        return devices
    except Exception:   # not the SOLEIL database: nothing to parametrize
        return []


def _observe(dp_ring_sim, names) -> np.ndarray:
    parts = []
    for name in names:
        value = read_array(dp_ring_sim, name)
        parts.append(value[-1:] / (2 * np.pi) if name.startswith("nu_") else value)
    return np.concatenate(parts) if parts else np.zeros(0)


def _snapshot(dp_ring_sim):
    return {name: _observe(dp_ring_sim, (name,)) for name in ALL_OBSERVABLES}


def _restored(dp_ring_sim, baseline) -> bool:
    now = _snapshot(dp_ring_sim)
    return all(np.allclose(now[k], baseline[k], rtol=RESTORE_RTOL.get(k, 1e-9), atol=1e-12) for k in baseline)


@pytest.mark.parametrize("device_name, kind_key", _magnet_devices())
def test_magnet_up_and_down(device_name, kind_key, dp_ring_sim):
    kind = KINDS[kind_key]
    dp = proxy(device_name)
    nominal = dp.magnetic_strength
    step = abs(nominal) * RELATIVE_STEP if abs(nominal) > 1e-9 else kind.zero_step
    everything = lambda: _observe(dp_ring_sim, ALL_OBSERVABLES)  # noqa: E731
    observe = (lambda: _observe(dp_ring_sim, kind.observables)) if kind.observables else everything  # noqa: E731
    start = wait_settled(observe)
    baseline = _snapshot(dp_ring_sim)

    def step_to(value, previous):
        dp.magnetic_strength = value
        assert wait_until(lambda: dp.magnetic_strength == pytest.approx(value, rel=1e-9, abs=1e-15)), \
            f"readback did not follow the write of {value}"
        if kind.linear is None:
            return wait_settled(observe)
        assert wait_until(lambda: not np.array_equal(observe(), previous)), \
            f"{kind.observables} unchanged after writing {value}"
        observed = wait_settled(observe)
        assert np.abs(observed - start).max() > kind.min_change, \
            f"{kind.observables} moved only {np.abs(observed - start).max():.2e} for a step of {step:.3g}"
        return observed

    try:
        at_up = step_to(nominal + step, start)
        at_down = step_to(nominal - step, at_up)
        if kind.linear is not None:
            up, down = at_up - start, at_down - start
            if kind.linear:
                assert np.dot(up, down) < 0, "up and down steps moved the optics the same way"
            else:
                assert np.dot(up, down) > 0, "expected a quadratic response, got opposite signs"
    finally:
        dp.magnetic_strength = nominal
    assert wait_until(lambda: _restored(dp_ring_sim, baseline)), "optics not restored at nominal"
