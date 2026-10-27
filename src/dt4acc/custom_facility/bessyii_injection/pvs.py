"""EPICS side of the injection: PVs of the hand over and what triggers it

* ``INJ:geometry:{x,xp,y,yp}``: line axis against ring axis at the septum exit
* ``INJ:n_turns``: turns tracked in the ring
* ``INJ:line_exit:{x,xp,y,yp}``: centroid leaving the line (line frame)
* ``INJ:injected:{x,xp,y,yp}``: the same in the ring frame
* ``INJ:tbt:{x,y}``: position at the ring's BPMs, turn after turn
  (turn 1 at all BPMs, then turn 2, ...), ``INJ:tbt:names``: the BPMs
* ``INJ:survived``: particles still there after each turn
* ``INJ:count``: number of hand overs computed
* ``<bpm>:tbt:x``, ``<bpm>:tbt:y``: one BPM, turn after turn
"""
import asyncio
import logging
import math
from typing import Sequence

import numpy as np
from softioc import builder

from dt4acc.core.bl.shared_event_loop import get_shared_event_loop
from .coupler import InjectionCoupler, InjectionResult

logger = logging.getLogger("dt4acc-bessyii-injection")

MAX_TURNS = 256
PLANES = (("x", "x"), ("xp", "xp"), ("y", "y"), ("yp", "yp"))
UNITS = {"x": "m", "xp": "rad", "y": "m", "yp": "rad"}


class InjectionPVs:
    """Records of the hand over; recomputes it whenever line, ring or settings change"""

    def __init__(self, coupler: InjectionCoupler):
        self.coupler = coupler
        self._dirty = False
        self._running = False
        self.count = 0
        n_mon = len(coupler.monitors)
        self.rec = {}
        for name, _ in PLANES:
            self.rec[f"geometry:{name}"] = builder.aOut(
                f"INJ:geometry:{name}", initial_value=getattr(coupler.geometry, name), PREC=6, EGU=UNITS[name],
                on_update=lambda val, name=name: self._set_geometry(name, val),
            )
            for what in ("line_exit", "injected"):
                self.rec[f"{what}:{name}"] = builder.aIn(f"INJ:{what}:{name}", initial_value=0.0, PREC=9, EGU=UNITS[name])
        self.rec["n_turns"] = builder.longOut(
            "INJ:n_turns", initial_value=coupler.n_turns, DRVL=1, DRVH=MAX_TURNS, on_update=self._set_n_turns
        )
        for plane in ("x", "y"):
            self.rec[f"tbt:{plane}"] = builder.WaveformIn(
                f"INJ:tbt:{plane}", initial_value=np.zeros(1), length=MAX_TURNS * n_mon, EGU="m"
            )
            for bpm in coupler.monitors:
                self.rec[f"{bpm}:{plane}"] = builder.WaveformIn(
                    f"{bpm}:tbt:{plane}", initial_value=np.zeros(1), length=MAX_TURNS, EGU="m"
                )
        self.rec["tbt:names"] = builder.WaveformIn("INJ:tbt:names", initial_value=list(coupler.monitors), length=n_mon)
        self.rec["survived"] = builder.WaveformIn("INJ:survived", initial_value=np.zeros(1), length=MAX_TURNS)
        self.rec["count"] = builder.longIn("INJ:count", initial_value=0)

    # --- settings
    def _set_geometry(self, name: str, value: float):
        setattr(self.coupler.geometry, name, float(value))
        self.trigger()

    def _set_n_turns(self, value: int):
        self.coupler.n_turns = int(value)
        self.trigger()

    # --- recompute, coalescing requests that arrive while it runs
    def trigger(self):
        self._dirty = True
        if not self._running:
            self._running = True
            asyncio.run_coroutine_threadsafe(self._run(), get_shared_event_loop())

    async def _run(self):
        try:
            while self._dirty:
                self._dirty = False
                try:
                    self.publish(await self.coupler.compute())
                except Exception as exc:
                    logger.error("injection: hand over failed: %s", exc)
        finally:
            self._running = False

    def publish(self, r: InjectionResult):
        for k, (name, _) in enumerate(PLANES):
            self.rec[f"line_exit:{name}"].set(r.line_exit[k])
            self.rec[f"injected:{name}"].set(r.injected[k])
        x, y = np.array(r.x), np.array(r.y)
        self.rec["tbt:x"].set(x.ravel())
        self.rec["tbt:y"].set(y.ravel())
        for k, bpm in enumerate(r.monitors):
            self.rec[f"{bpm}:x"].set(x[:, k])
            self.rec[f"{bpm}:y"].set(y[:, k])
        self.rec["survived"].set(np.array(r.survived, dtype=float))
        self.count += 1
        self.rec["count"].set(self.count)
        logger.info("injection: %d turns, survived %s", len(r.survived), r.survived[-1] if r.survived else math.nan)


def hook_track_updates(view, injection: InjectionPVs):
    """After the view publishes a new trajectory / orbit, recompute the hand over"""
    update_track = view.update_track

    def update_track_and_inject(var, pkg):
        update_track(var, pkg)
        injection.trigger()

    view.update_track = update_track_and_inject
    return view


__all__: Sequence[str] = ["InjectionPVs", "hook_track_updates"]
