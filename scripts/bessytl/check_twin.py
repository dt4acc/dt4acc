"""Check a running BESSY II transfer line twin over EPICS (PVA)

Sets steerer supplies, reads the monitors and compares with plain pyAT on the
same lattice, currents and entering beam; the screens' beam size with
sqrt(emittance beta) of pyAT's optics and the centre of their image with the
trajectory. Exit code 0 when everything agrees.

    DT4ACC_PREFIX=<prefix> python scripts/bessytl/check_twin.py
"""
import os
import sys
import time

import at
import numpy as np
from p4p.client.thread import Context

from dt4acc.custom_epics.ioc.bpm_pvs import M2MM
from dt4acc.custom_facility.bessytl.screens import beam_size
from dt4acc.custom_facility.bessytl.view import is_screen
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



def monitor_pv(name: str, plane: str) -> str:
    """beam centre: screens ``<screen>:x``, BPMs and striplines ``<bpm>:signal:sa:X`` [mm]"""
    return f"{name}:{plane}" if name.startswith("FOMZ") else f"{name}:signal:sa:{plane.upper()}"

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
        # monitor PVs in mm
        x, y = get(monitor_pv(name, "x")) / M2MM, get(monitor_pv(name, "y")) / M2MM
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
    wait_for(monitor_pv(last, "x"), ref[last][0] * M2MM, 1e-9)
    for name in monitors:
        x, y = get(monitor_pv(name, "x")) / M2MM, get(monitor_pv(name, "y")) / M2MM
        check(np.allclose([x, y], ref[name], atol=1e-12),
              f"{name} after steerers: {x * 1e3:+.4f} {y * 1e3:+.4f} mm (pyAT {ref[name][0] * 1e3:+.4f} {ref[name][1] * 1e3:+.4f})")
    for pc, current in steer.items():
        check(abs(get(f"{pc}:rdbk") - current) < 1e-9, f"{pc}:rdbk follows set ({current} A)")

    # 4. quadrupole supply: optics along the line
    currents2 = dict(currents, Q12PT=70.0)
    ctx.put(pv("Q12PT:set"), 70.0)
    ref, ed = reference(currents2, kicks)
    beta_x_end = ed.beta[-1, 0]
    got = wait_for_waveform_end("TL:beam:twiss:x:beta", len(ed.beta), beta_x_end)
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

    # 5. screens: the image of the beam spot, centre from the trajectory, size
    # from the emittance and beta at the screen
    check_screens(currents2, kicks)

    names = get("TL:beam:orbit:names")
    check(list(names)[-1] == "KIK4D1R:exit", f"beam:orbit ends at the exit of the line ({list(names)[-1]})")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


def check_screens(currents, kicks):
    line = bessytl_lattice(currents=currents)
    ref, ed = reference(currents, kicks)
    index = {line[i].FamName: i for i in line.get_uint32_index(at.Monitor)}
    screens = [n for n in index if is_screen(n)]
    emittance = [get(f"TL:beam:emittance:{p}") for p in ("x", "y")]
    for name in screens:
        beta = ed.beta[index[name]]
        expected = [beam_size(e, b) * M2MM for e, b in zip(emittance, beta)]
        sigma = [get(f"{name}:sigma:{p}") for p in ("x", "y")]
        check(np.allclose(sigma, expected, rtol=1e-9),
              f"{name}: sigma {sigma[0]:.4f} {sigma[1]:.4f} mm = sqrt(emittance beta) (pyAT beta {beta[0]:.3f} {beta[1]:.3f} m)")
        image = np.asarray(get(f"{name}:image"))
        width, height, pixel = int(get(f"{name}:image:width")), int(get(f"{name}:image:height")), get(f"{name}:image:pixel")
        image = image[: width * height].reshape(height, width)
        centre = ref[name] * M2MM
        if image.sum() > 0.99:
            cx = (np.arange(width) - width / 2 + 0.5) * pixel
            cy = (np.arange(height) - height / 2 + 0.5)[::-1] * pixel
            got = [(image.sum(axis=0) * cx).sum() / image.sum(), (image.sum(axis=1) * cy).sum() / image.sum()]
            check(np.allclose(got, centre, atol=pixel / 2),
                  f"{name}: image centred at {got[0]:+.3f} {got[1]:+.3f} mm (trajectory {centre[0]:+.3f} {centre[1]:+.3f})")
        else:
            print(f"     {name}: {image.sum():.2f} of the beam on the screen (centre {centre[0]:+.2f} {centre[1]:+.2f} mm)")

    # the emittance acts on the size at once (the line on its own)
    name = screens[0]
    before = get(f"{name}:sigma:x")
    ctx.put(pv("TL:beam:emittance:x"), emittance[0] * 4)
    after = wait_for(f"{name}:sigma:x", 2 * before, 1e-9)
    check(np.isclose(after, 2 * before, rtol=1e-9), f"{name}: emittance x 4 -> sigma:x x 2 ({before:.4f} -> {after:.4f} mm)")
    ctx.put(pv("TL:beam:emittance:x"), emittance[0])


def wait_for_waveform_end(name: str, n: int, expected: float, timeout: float = 15.0) -> float:
    t0 = time.time()
    while True:
        value = np.asarray(get(name))[:n]
        if np.isclose(value[-1], expected, rtol=1e-9) or time.time() - t0 > timeout:
            return float(value[-1])
        time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
