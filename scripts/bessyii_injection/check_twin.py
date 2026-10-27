"""Check a running BESSY II injection twin over EPICS (PVA)

Steers the transfer line, changes the injection geometry and the number of
turns, changes a ring supply, and compares the hand over (``INJ:...``) with
plain pyAT: the line up to the septum exit, then the ring from ``MSEPEXIT``.
Exit code 0 when everything agrees.

    DT4ACC_PREFIX=<prefix> python scripts/bessyii_injection/check_twin.py
"""
import os
import sys
import time

import at
import numpy as np
from p4p.client.thread import Context

from dt4acc.custom_facility.bessyii.provide_lattice import provide_lattice
from dt4acc.custom_facility.bessyii_injection.coupler import INJECTION_ELEMENT, InjectionGeometry
from dt4acc.custom_facility.bessytl.twin_setup import bessytl_lattice, load_accelerator_setup, load_twiss_in

P = os.environ.get("DT4ACC_PREFIX", "")
SEPTUM = "SEK2D2R"
ctx = Context("pva", nt=False)
failures = []
RING = provide_lattice()
BPMS = [e.FamName for e in RING if isinstance(e, at.Monitor) and e.FamName.startswith("BPMZ")]
SETUP = {m["name"]: m for m in load_accelerator_setup()}


def pv(name):
    return f"{P}:{name}" if P else name


def get(name):
    return ctx.get(pv(name), timeout=5).value


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


def wait_count(previous, timeout=30.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        n = int(get("INJ:count"))
        if n > previous:
            time.sleep(1.0)   # a request that arrived while computing: let it finish
            return int(get("INJ:count"))
        time.sleep(0.2)
    return int(get("INJ:count"))


def reference(steerer_currents, geometry, n_turns):
    line = bessytl_lattice(end_after=SEPTUM)
    by_name = {e.FamName: e for e in line}
    for magnet in SETUP.values():
        current = steerer_currents.get(magnet["pc"])
        if magnet["type"] == "Steerer" and current is not None:
            angles = [0.0, 0.0]
            angles[0 if magnet["name"].startswith("H") else 1] = current * magnet["magnetic_strength"]
            by_name[magnet["name"]].KickAngle = np.array(angles)
    x0 = np.array(load_twiss_in().closed_orbit, dtype=float).reshape(6, 1)
    out, *_ = line.track(x0.copy(), refpts=len(line), nturns=1)
    injected = geometry.to_ring(out[:, 0, 0, 0])
    (idx,) = [i for i, e in enumerate(RING) if e.FamName == INJECTION_ELEMENT]
    rotated = RING.rotate(idx)
    refpts = [i for i, e in enumerate(rotated) if e.FamName in BPMS]
    order = [rotated[i].FamName for i in refpts]
    out, *_ = rotated.track(injected.reshape(6, 1).copy(), refpts=refpts, nturns=n_turns)
    col = [order.index(b) for b in BPMS]
    return injected, out[0, 0, col, :].T, out[2, 0, col, :].T


def compare(label, steerers, geometry, n_turns):
    injected, x_ref, y_ref = reference(steerers, geometry, n_turns)
    got_inj = [get(f"INJ:injected:{k}") for k in ("x", "xp", "y", "yp")]
    check(np.allclose(got_inj, injected[:4], atol=1e-12), f"{label}: injected {np.round(np.array(got_inj) * 1e3, 4)} mm/mrad")
    n = len(BPMS)
    x = np.asarray(get("INJ:tbt:x"))[: n_turns * n].reshape(n_turns, n)
    y = np.asarray(get("INJ:tbt:y"))[: n_turns * n].reshape(n_turns, n)
    check(np.allclose(x, x_ref, atol=1e-12) and np.allclose(y, y_ref, atol=1e-12),
          f"{label}: {n_turns} turns x {n} BPMs, max |dx| {np.max(np.abs(x - x_ref)):.1e} m, "
          f"first turn x rms {np.sqrt(np.mean(x[0] ** 2)) * 1e3:.4f} mm")
    one = np.asarray(get(f"{BPMS[10]}:tbt:x"))[:n_turns]
    check(np.allclose(one, x_ref[:, 10], atol=1e-12), f"{label}: {BPMS[10]}:tbt:x matches")


def main():
    for name in ("Q1PT:set", "FOMZ1T:x", "TL:beam:orbit:x", "Q1PDR:set", "beam:orbit:x", "INJ:tbt:names"):
        try:
            get(name)
            check(True, f"{name} served")
        except Exception as exc:
            check(False, f"{name} served ({exc})")
    for name in ("TL:Q1PT:set", "TL:FOMZ1T:x"):
        try:
            ctx.get(pv(name), timeout=2)
            check(False, f"{name} not served (machine name without TL:)")
        except Exception:
            check(True, f"{name} not served (machine name without TL:)")
    check(list(get("INJ:tbt:names")) == BPMS, f"INJ:tbt:names: the {len(BPMS)} ring BPMs in ring order")

    count = wait_count(0)
    n_turns = int(get("INJ:n_turns"))
    compare("start", {}, InjectionGeometry(), n_turns)

    ctx.put(pv("H5PT:set"), 0.4)
    count = wait_count(count)
    compare("line steered (H5PT 0.4 A)", {"H5PT": 0.4}, InjectionGeometry(), n_turns)

    geometry = InjectionGeometry(x=-2e-3, xp=1e-4)
    ctx.put(pv("INJ:geometry:x"), geometry.x)
    ctx.put(pv("INJ:geometry:xp"), geometry.xp)
    ctx.put(pv("INJ:n_turns"), 5)
    count = wait_count(count)
    compare("geometry -2 mm / 0.1 mrad, 5 turns", {"H5PT": 0.4}, geometry, 5)

    before = np.asarray(get("INJ:tbt:x"))[: 5 * len(BPMS)].copy()
    ctx.put(pv("Q1PDR:set"), float(get("Q1PDR:set")) * 1.01)
    count2 = wait_count(count)
    after = np.asarray(get("INJ:tbt:x"))[: 5 * len(BPMS)]
    check(count2 > count and not np.allclose(before, after),
          f"ring change (Q1PDR +1 %) recomputes the hand over (count {count} -> {count2})")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
