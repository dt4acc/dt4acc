"""Check a running SOLEIL injection twin over Tango: injection on demand

Fires shots (``Inject`` of ``simulator/injection/injection``) and checks, as at the
machine, that the beam is seen only at a shot:

* a TL2 steerer change moves TL2's model (``orbit_x`` of its simulator) at once, but
  its BPMs (``XPosSA``) and the injected beam only at the next shot
* a ring steerer change moves the ring's closed orbit (``XPosSA`` of its BPMs) at once,
  but its turn by turn data (``XPosDD``) only at the next shot
* the ring tracks the injected beam from where it enters (``tbt_start`` = ``injected``)

Everything changed is put back. Exit code 0 when everything agrees.

    TANGO_HOST=H:P python scripts/soleil_injection/check_twin.py
"""
import sys
import time

import numpy as np
import tango

INJECTION = "simulator/injection/injection"
RING = "simulator/ringsimulator/ringsimulator"
TL = "simulator/tlsimulator/tlsimulator"
TL_BPMS = [f"LT2/DG-EPOS/BPM.0{k}" for k in range(1, 7)]
TL_STEERER = "LT2/EM-COR/COR.H.01"
RING_BPM = "AN01-AR/DG-EPOS/BPM.02"
RING_STEERER = "AN01-AR/EM-COR/SHF.01-CDLH.01"
#: settling: TL2 1 to 2 s, the ring about 20 s (its README)
TL_SETTLE_S, RING_SETTLE_S = 3.0, 25.0

failures = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


def proxy(name):
    p = tango.DeviceProxy(name)
    p.set_timeout_millis(30000)
    return p


inj, ring, tl = proxy(INJECTION), proxy(RING), proxy(TL)
tl_bpms = [proxy(b) for b in TL_BPMS]
ring_bpm = proxy(RING_BPM)


def tl_bpms_x():
    return np.array([b.XPosSA for b in tl_bpms])


def shot(timeout=120.0):
    """fire, wait until the ring tracked it: the new count"""
    before = inj.count
    inj.Inject()
    t0 = time.time()
    while time.time() - t0 < timeout:
        if inj.count > before:
            time.sleep(1.0)  # the BPM devices fetch the new result on read
            return inj.count
        time.sleep(0.5)
    check(False, f"shot after count {before} computed within {timeout} s")
    return inj.count


def main():
    t0 = time.time()
    while True:  # the injection device connects to both twins within a few seconds
        try:
            inj.count
            ring.tbt_count
            break
        except tango.DevFailed:
            if time.time() - t0 > 120:
                raise
            time.sleep(2)
    count = shot()
    check(count >= 1, f"Inject: a shot computed (count {count})")
    n_turns = int(inj.n_turns)
    check(len(ring_bpm.XPosDD) == n_turns, f"{RING_BPM} XPosDD: {n_turns} turns")
    check(np.allclose(ring.tbt_start, inj.injected, atol=1e-12), "the ring tracks the injected beam (tbt_start = injected)")

    # TL2 steered
    tl_before, model_before = tl_bpms_x(), np.array(tl.orbit_x)
    injected_before, dd_before = np.array(inj.injected), np.array(ring_bpm.XPosDD)
    steerer = proxy(TL_STEERER)
    original_tl = float(steerer.magnetic_strength)
    steerer.magnetic_strength = original_tl + 1e-4
    time.sleep(TL_SETTLE_S)
    check(not np.allclose(np.array(tl.orbit_x), model_before), f"{TL_STEERER} +1e-4, no shot: TL2's model (orbit_x) follows")
    check(np.allclose(tl_bpms_x(), tl_before) and inj.count == count,
          f"{TL_STEERER} +1e-4, no shot: TL2's {len(TL_BPMS)} BPMs keep the last shot, nothing injected")
    check(np.allclose(ring_bpm.XPosDD, dd_before, equal_nan=True), "no shot: the ring's turn by turn data stay")
    count = shot()
    moved = np.abs(tl_bpms_x() - tl_before)
    check(moved.max() > 1e-3, f"the shot: TL2's BPMs show the steered trajectory (max {moved.max():.3f} mm)")
    check(not np.allclose(inj.injected, injected_before), f"the shot: injected x {inj.injected[0] * 1e3:+.4f} mm")
    check(not np.allclose(ring_bpm.XPosDD, dd_before), f"the shot: {RING_BPM} XPosDD changed")
    check(np.allclose(ring.tbt_start, inj.injected, atol=1e-12), "tbt_start = injected")

    # ring steered
    sa_before, dd_before = float(ring_bpm.XPosSA), np.array(ring_bpm.XPosDD)
    rsteerer = proxy(RING_STEERER)
    original_ring = float(rsteerer.magnetic_strength)
    rsteerer.magnetic_strength = original_ring + 2e-5
    time.sleep(RING_SETTLE_S)
    check(abs(float(ring_bpm.XPosSA) - sa_before) > 1e-4,
          f"{RING_STEERER} +2e-5, no shot: the ring's closed orbit follows ({RING_BPM} XPosSA "
          f"{sa_before:+.4f} -> {float(ring_bpm.XPosSA):+.4f} mm)")
    check(np.allclose(ring_bpm.XPosDD, dd_before, equal_nan=True) and inj.count == count,
          "no shot: the ring's turn by turn data stay, nothing injected")
    count = shot()
    check(not np.allclose(ring_bpm.XPosDD, dd_before), f"the shot: {RING_BPM} XPosDD around the new closed orbit")
    check(np.allclose(ring.tbt_start, inj.injected, atol=1e-12),
          "tbt_start = injected: tracked against the closed orbit as it is at the shot")

    # back
    steerer.magnetic_strength = original_tl
    rsteerer.magnetic_strength = original_ring
    time.sleep(RING_SETTLE_S)
    shot()
    check(np.allclose(tl_bpms_x(), tl_before, atol=1e-6), "steerers back, shot: TL2's BPMs as at the first shot")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
