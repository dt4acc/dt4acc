"""Walk through a running BESSY II injection twin: change one thing at a time,
say what to expect, show what came out

Run it next to ``live_plot.py`` to watch each step. Every value it changes is
put back at the end.

    DT4ACC_PREFIX=<P> python scripts/bessyii_injection/demo.py            # Enter between steps
    DT4ACC_PREFIX=<P> python scripts/bessyii_injection/demo.py --no-wait
"""
import argparse
import os
import time

import numpy as np
from p4p.client.thread import Context

STEPS = [
    ("start", [], "Line not steered, geometry 0: the beam enters the ring on its axis and stays close "
                  "to the closed orbit (a few 10 um at the BPMs)."),
    ("steer the transfer line", [("TL:H5PT:set", 0.4)],
     "H5PT (horizontal steerer H5MT) 0.4 A: the trajectory in the line bends from H5MT on; the beam "
     "leaves the line about -1.2 mm / +0.7 mrad off; in the ring it oscillates around the closed orbit, "
     "a few mm at the BPMs, a different pattern every turn (betatron oscillation, tune ~17.85)."),
    ("injection geometry", [("INJ:geometry:x", -2e-3), ("INJ:geometry:xp", 1e-4)],
     "The line's axis 2 mm inside / 0.1 mrad against the ring's axis: the injected beam is shifted by "
     "that, the oscillation in the ring grows; the line itself does not change."),
    ("more turns", [("INJ:n_turns", 5)], "Track 5 turns: the plot shows 5 ring circumferences."),
    ("change the ring", [("Q1PDR:set", None)],
     "Ring quadrupole supply Q1PDR +1 %: the horizontal tune moves from .85 to about .96, close to an "
     "integer: the oscillation of the injected beam (3 mm off) grows turn by turn and the beam is lost "
     "after 3 turns (NaN at the BPMs, INJ:survived drops to 0); the line does not change."),
    ("steer back", [("TL:H5PT:set", 0.0), ("INJ:geometry:x", 0.0), ("INJ:geometry:xp", 0.0)],
     "Back on axis: the oscillation is gone (the Q1PDR change stays until the end)."),
]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prefix", default=os.environ.get("DT4ACC_PREFIX", ""))
    p.add_argument("--no-wait", action="store_true", help="do not wait for Enter between steps")
    a = p.parse_args()
    ctx = Context("pva", nt=False)

    def pv(name):
        return f"{a.prefix}:{name}" if a.prefix else name

    def get(name):
        return ctx.get(pv(name), timeout=5).value

    def wait_for_hand_over(before):
        t0 = time.time()
        while int(get("INJ:count")) <= before and time.time() - t0 < 30:
            time.sleep(0.2)
        time.sleep(1.0)

    originals = {}
    for title, changes, expect in STEPS:
        print(f"\n== {title}\n   expect: {expect}")
        if not a.no_wait:
            input("   [Enter] ")
        count = int(get("INJ:count"))
        for name, value in changes:
            originals.setdefault(name, float(get(name)))
            value = originals[name] * 1.01 if value is None else value
            print(f"   {name} = {value:g}")
            ctx.put(pv(name), value)
        if changes:
            wait_for_hand_over(count)
        n_turns = int(get("INJ:n_turns"))
        x = np.asarray(get("INJ:tbt:x"))
        n_bpm = len(get("INJ:tbt:names"))
        x = x[: n_turns * n_bpm].reshape(n_turns, n_bpm)
        inj = [get(f"INJ:injected:{k}") for k in ("x", "xp")]
        print(f"   injected x {inj[0] * 1e3:+.3f} mm, x' {inj[1] * 1e3:+.3f} mrad; ring BPMs x rms per turn [mm]: "
              + " ".join(f"{np.sqrt(np.mean(t ** 2)) * 1e3:.3f}" for t in x))

    for name, value in originals.items():
        ctx.put(pv(name), value)
    print("\nput back:", ", ".join(f"{n} = {v:g}" for n, v in originals.items()))


if __name__ == "__main__":
    main()
