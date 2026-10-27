"""Live plot of a running BESSY II injection twin

Redraws whenever the hand over is recomputed (``INJ:count`` changes), i.e.
after any change of a transfer line or ring supply or of the ``INJ:`` settings:

1. transfer line: trajectory along the line (x, y), its monitors marked
2. ring, horizontal: the injected beam at the ring BPMs, turn after turn
   (turn 1 from 0 to C, turn 2 from C to 2C, ...), the ring's closed orbit
3. ring, vertical: the same
4. what was injected (line exit and ring frame) and the settings

    DT4ACC_PREFIX=<P> python scripts/bessyii_injection/live_plot.py
    DT4ACC_PREFIX=<P> python scripts/bessyii_injection/live_plot.py --save inj.png   # no window: write a PNG per update

The EPICS environment (EPICS_PVA_ADDR_LIST, ...) must reach the twin. Nothing
is written to a PV.
"""
import argparse
import os
import threading

import numpy as np
from p4p.client.thread import Context


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prefix", default=os.environ.get("DT4ACC_PREFIX", ""))
    p.add_argument("--save", default=None, help="write the figure to this file on each update instead of a window")
    p.add_argument("--updates", type=int, default=0, help="stop after this many updates (0: never)")
    return p.parse_args()


class Twin:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.ctx = Context("pva", nt=False)
        self.changed = threading.Event()
        self.sub = self.ctx.monitor(self.pv("INJ:count"), lambda value: self.changed.set())

    def pv(self, name):
        return f"{self.prefix}:{name}" if self.prefix else name

    def get(self, *names):
        values = self.ctx.get([self.pv(n) for n in names], timeout=5)
        return [np.asarray(v.value) if hasattr(v, "value") else np.asarray(v) for v in values]

    def snapshot(self):
        """Everything one picture needs, read together"""
        tl_x, tl_y, tl_names, tl_s, tl_s_names = self.get(
            "TL:beam:orbit:x", "TL:beam:orbit:y", "TL:beam:orbit:names", "TL:survey:s", "TL:survey:names")
        ring_x, ring_y, ring_names, ring_s, ring_s_names = self.get(
            "beam:orbit:x", "beam:orbit:y", "beam:orbit:names", "survey:s", "survey:names")
        tbt_x, tbt_y, bpms, n_turns, count, survived = self.get(
            "INJ:tbt:x", "INJ:tbt:y", "INJ:tbt:names", "INJ:n_turns", "INJ:count", "INJ:survived")
        state = {}
        for what in ("line_exit", "injected", "geometry"):
            state[what] = [float(v) for v in self.get(*[f"INJ:{what}:{k}" for k in ("x", "xp", "y", "yp")])]
        return dict(
            tl=dict(x=tl_x, y=tl_y, s=along(tl_x, tl_s)),
            ring=dict(x=ring_x, y=ring_y, s=along(ring_x, ring_s)),
            bpm_s=positions(bpms, ring_s_names, ring_s), circumference=float(np.max(ring_s)),
            tbt_x=tbt_x, tbt_y=tbt_y, n_bpm=len(bpms), n_turns=int(n_turns), count=int(count),
            survived=survived, state=state,
        )


def along(values, survey_s):
    """s of each point of a waveform along the lattice (one point per element, in
    lattice order, as the survey; a last point more: the end of the lattice)"""
    s = np.asarray(survey_s, dtype=float)
    n = len(values)
    return s[:n] if len(s) >= n else np.concatenate([s, np.full(n - len(s), s[-1] if len(s) else 0.0)])


def positions(names, survey_names, survey_s):
    """s of each (unique) name: its first appearance in the survey; '<elem>:exit' at the end"""
    s_of = {}
    for name, s in zip(list(survey_names), np.asarray(survey_s, dtype=float)):
        s_of.setdefault(str(name), s)
    end = float(np.max(survey_s)) if len(survey_s) else 0.0
    return np.array([end if str(n).endswith(":exit") else s_of.get(str(n), np.nan) for n in names], dtype=float)


def draw(fig, axes, snap):
    for ax in axes:
        ax.clear()
    ax_tl, ax_x, ax_y, ax_txt = axes
    tl = snap["tl"]
    n = min(len(tl["s"]), len(tl["x"]))
    ax_tl.plot(tl["s"][:n], tl["x"][:n] * 1e3, label="x")
    ax_tl.plot(tl["s"][:n], tl["y"][:n] * 1e3, label="y")
    ax_tl.set(title="transfer line: trajectory", xlabel="s [m]", ylabel="[mm]")
    ax_tl.legend(loc="upper left")

    nt, nb, c = snap["n_turns"], snap["n_bpm"], snap["circumference"]
    s_turns = np.concatenate([snap["bpm_s"] + k * c for k in range(nt)])
    ring = snap["ring"]
    m = min(len(ring["s"]), len(ring["x"]))
    for ax, plane, label in ((ax_x, "tbt_x", "x"), (ax_y, "tbt_y", "y")):
        values = snap[plane][: nt * nb] * 1e3
        ax.plot(s_turns, values, ".-", ms=3, lw=0.8, label=f"injected beam, {nt} turn(s)")
        for k in range(nt):
            ax.plot(ring["s"][:m] + k * c, ring[label][:m] * 1e3, "k--", lw=0.6,
                    label="closed orbit" if k == 0 else None)
        for k in range(1, nt):
            ax.axvline(k * c, color="grey", lw=0.5)
        ax.set(title=f"ring: {label} at the BPMs, turn after turn", xlabel="s from the start of turn 1 [m]",
               ylabel="[mm]")
        ax.legend(loc="upper right")

    st = snap["state"]
    rows = [("line exit (line frame)", st["line_exit"]), ("geometry", st["geometry"]),
            ("injected (ring frame)", st["injected"])]
    text = "\n".join(f"{name:24s} x {v[0] * 1e3:+8.3f} mm  x' {v[1] * 1e3:+8.3f} mrad   "
                     f"y {v[2] * 1e3:+8.3f} mm  y' {v[3] * 1e3:+8.3f} mrad" for name, v in rows)
    survived = snap["survived"][: nt]
    text += f"\n\nhand over #{snap['count']}, {nt} turn(s), particles left after each turn: {list(survived.astype(int))}"
    ax_txt.axis("off")
    ax_txt.text(0.0, 1.0, text, va="top", family="monospace", fontsize=9)
    fig.tight_layout()


def main():
    a = parse_args()
    import matplotlib
    if a.save:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    twin = Twin(a.prefix)
    fig, axes = plt.subplots(4, 1, figsize=(12, 13), gridspec_kw=dict(height_ratios=[1, 1, 1, 0.5]))
    n = 0
    while True:
        twin.changed.wait(timeout=None if a.save else 0.2)
        if twin.changed.is_set():
            twin.changed.clear()
            draw(fig, axes, twin.snapshot())
            n += 1
            if a.save:
                fig.savefig(a.save, dpi=90)
                print(f"update {n}: {a.save}")
            if a.updates and n >= a.updates:
                break
        if not a.save:
            if not plt.fignum_exists(fig.number) and n:
                break
            plt.pause(0.05)
    twin.sub.close()


if __name__ == "__main__":
    main()
