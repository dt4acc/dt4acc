"""Check a running BESSY II transfer line twin over EPICS (PVA)

Sets steerer supplies, reads the monitors and compares with plain pyAT on the
same lattice, currents and entering beam. Exit code 0 when everything agrees.

    DT4ACC_PREFIX=<prefix> python scripts/bessytl/check_twin.py
"""
import os
import sys
import time

import at
import numpy as np
from p4p.client.thread import Context

from dt4acc.custom_facility.bessytl.twin_setup import (
    bessytl_lattice,
    load_accelerator_setup,
    load_operating_currents,
    load_twiss_in,
    monitor_names,
)

PREFIX = os.environ.get("DT4ACC_PREFIX", "")
ctx = Context("pva", nt=False)
failures = []


def pv(name: str) -> str:
    return f"{PREFIX}:{name}" if PREFIX else name


def get(name: str):
    return ctx.get(pv(name), timeout=5).value


def check(ok: bool, what: str):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


def reference(currents, kicks):
    line = bessytl_lattice(currents=currents)
    by_name = {e.FamName: e for e in line}
    for name, angles in kicks.items():
        by_name[name].KickAngle = np.array(angles, dtype=float)
    _, _, ed = line.get_optics(at.All, twiss_in=load_twiss_in(os.environ.get("DT4ACC_BESSYTL_TWISS_IN")).as_at())
    idx = line.get_uint32_index(at.Monitor)
    return {line[i].FamName: ed.closed_orbit[i, [0, 2]] for i in idx}, ed


def wait_for(name: str, expected: float, tol: float, timeout: float = 15.0) -> float:
    t0 = time.time()
    while True:
        value = get(name)
        if abs(value - expected) <= tol or time.time() - t0 > timeout:
            return value
        time.sleep(0.2)


def main() -> int:
    setup = {m["name"]: m for m in load_accelerator_setup()}
    currents = load_operating_currents()
    monitors = monitor_names(bessytl_lattice())

    # 1. supplies start at the operating currents
    for pc, current in currents.items():
        check(abs(get(f"{pc}:set") - current) < 1e-6, f"{pc}:set starts at {current} A")

    # 2. without steerers: monitors read the trajectory of the entering beam
    ref, ed = reference(currents, {})
    for name in monitors:
        x, y = get(f"{name}:x"), get(f"{name}:y")
        check(np.allclose([x, y], ref[name], atol=1e-12), f"{name} at start: {x:.3e} {y:.3e}")

    # 3. steerers: set supplies over EPICS, compare with pyAT
    steer = {"H1PT": 0.2, "V2PT": -0.3, "H6PT": 0.5}
    for pc, current in steer.items():
        ctx.put(pv(f"{pc}:set"), current)
    kicks = {}
    for m in setup.values():
        if m["type"] == "Steerer" and m["pc"] in steer:
            plane = 0 if m["name"].startswith("H") else 1
            angles = [0.0, 0.0]
            angles[plane] = steer[m["pc"]] * m["magnetic_strength"]
            kicks[m["name"]] = angles
    ref, ed = reference(currents, kicks)
    last = monitors[-2]
    wait_for(f"{last}:x", ref[last][0], 1e-12)
    for name in monitors:
        x, y = get(f"{name}:x"), get(f"{name}:y")
        check(np.allclose([x, y], ref[name], atol=1e-12),
              f"{name} after steerers: {x * 1e3:+.4f} {y * 1e3:+.4f} mm (pyAT {ref[name][0] * 1e3:+.4f} {ref[name][1] * 1e3:+.4f})")
    for pc, current in steer.items():
        check(abs(get(f"{pc}:rdbk") - current) < 1e-9, f"{pc}:rdbk follows set ({current} A)")

    # 4. quadrupole supply: optics along the line
    currents2 = dict(currents, Q12PT=70.0)
    ctx.put(pv("Q12PT:set"), 70.0)
    ref, ed = reference(currents2, kicks)
    beta_x_end = ed.beta[-1, 0]
    got = wait_for_waveform_end("beam:twiss:x:beta", len(ed.beta), beta_x_end)
    check(np.isclose(got, beta_x_end, rtol=1e-9), f"beta_x at the end after Q12PT=70 A: {got:.4f} m (pyAT {beta_x_end:.4f})")
    # magnets read back in lattice units: K [1/m^2], kick [rad]
    brho = bessytl_lattice().energy / 299792458.0
    k_start = setup["Q1MT"]["magnetic_strength"] * currents["Q1PT"] / brho
    k = get("Q1MT:Cm:rdbk")
    check(np.isclose(k, k_start, rtol=1e-9), f"Q1MT:Cm:rdbk K = {k:.5f} 1/m^2 (expected {k_start:.5f})")
    k = get("Q12MT:Cm:rdbk")
    k_expected = setup["Q12MT"]["magnetic_strength"] * 70.0 / brho
    check(np.isclose(k, k_expected, rtol=1e-9), f"Q12MT:Cm:rdbk K after Q12PT=70 A = {k:.5f} 1/m^2 (expected {k_expected:.5f})")
    kick = get("H6MT:Cm:rdbk")
    check(np.isclose(kick, kicks["H6MT"][0], rtol=1e-9), f"H6MT:Cm:rdbk kick = {kick:.4e} rad (expected {kicks['H6MT'][0]:.4e})")

    names = get("beam:orbit:names")
    check(list(names)[-1] == "KIK4D1R:exit", f"beam:orbit ends at the exit of the line ({list(names)[-1]})")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


def wait_for_waveform_end(name: str, n: int, expected: float, timeout: float = 15.0) -> float:
    t0 = time.time()
    while True:
        value = np.asarray(get(name))[:n]
        if np.isclose(value[-1], expected, rtol=1e-9) or time.time() - t0 > timeout:
            return float(value[-1])
        time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
