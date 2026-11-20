"""EPICS side of the injection: PVs of the hand over and what fires it

An injection is a shot, fired on demand (``INJ:trigger``), as at the
machine: the beam passes the transfer line only during a shot, so its
monitors and the ring's turn by turn buffers (triggered by the injection
timing) show the beam leaving the line and its first turns in the ring only
then, and keep them until the next shot. Changes of the line, the ring or the
settings below act at the next shot. The models (transfer line trajectory and
optics, the ring's closed orbit) still follow every change: the ring's stored
beam is measured continuously.

* ``INJ:trigger``: write 1 to fire a shot (back at 0 once accepted)
* ``INJ:geometry:{x,xp,y,yp,delta,ct}``: the line's reference against the
  ring's at the septum exit, a difference state (ring = line + geometry)
* ``INJ:n_turns``: turns tracked in the ring
* ``INJ:line_exit:{x,xp,y,yp,delta,ct}``: centroid leaving the line (line frame)
* ``INJ:injected:{x,xp,y,yp,delta,ct}``: the same in the ring frame
* ``INJ:tbt:{x,y}``: position at the ring's BPMs, turn after turn
  (turn 1 at all BPMs, then turn 2, ...), ``INJ:tbt:names``: the BPMs
* ``INJ:survived``: particles still there after each turn
* ``INJ:count``: number of shots computed
* ``<bpm>:signal:tbt:X``, ``<bpm>:signal:tbt:Y``: one BPM, turn after turn [mm]
  (:mod:`dt4acc.custom_epics.ioc.bpm_pvs`)
"""
import asyncio
import logging
import math
from typing import Awaitable, Callable, Optional, Sequence

import numpy as np
from softioc import builder as softioc_builder

from dt4acc.core.bl.shared_event_loop import get_shared_event_loop
from dt4acc.custom_epics.ioc.bpm_pvs import M2MM, TBT_FIELDS
from .handover import InjectionHandover, InjectionResult

logger = logging.getLogger("dt4acc-bessyii-injection")

MAX_TURNS = 256
#: PV field, ParticleState field
PLANES = (("x", "x"), ("xp", "px"), ("y", "y"), ("yp", "py"), ("delta", "delta"), ("ct", "ct"))
UNITS = {"x": "m", "xp": "rad", "y": "m", "yp": "rad", "delta": "", "ct": "m"}


class InjectionPVs:
    """Records of the hand over; a shot is computed when ``INJ:trigger`` fires

    ``before_shot``: what else a shot does before the hand over is computed,
    e.g. the transfer line's monitors showing the beam passing.
    """

    def __init__(
        self,
        handover: InjectionHandover,
        builder=softioc_builder,
        before_shot: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        self.handover = handover
        self.before_shot = before_shot
        self._pending = False
        self._running = False
        self.count = 0
        n_mon = len(handover.monitors)
        self.rec = {}
        self.rec["trigger"] = builder.boolOut(
            "INJ:trigger", initial_value=False, ZNAM="Idle", ONAM="Fire", always_update=True,
            on_update=self._on_trigger,
        )
        for name, field in PLANES:
            self.rec[f"geometry:{name}"] = builder.aOut(
                f"INJ:geometry:{name}", initial_value=getattr(handover.geometry, field), PREC=6, EGU=UNITS[name],
                on_update=lambda val, field=field: self._set_geometry(field, val),
            )
            for what in ("line_exit", "injected"):
                self.rec[f"{what}:{name}"] = builder.aIn(f"INJ:{what}:{name}", initial_value=0.0, PREC=9, EGU=UNITS[name])
        self.rec["n_turns"] = builder.longOut(
            "INJ:n_turns", initial_value=handover.n_turns, DRVL=1, DRVH=MAX_TURNS, on_update=self._set_n_turns
        )
        for plane, field in TBT_FIELDS:
            self.rec[f"tbt:{plane}"] = builder.WaveformIn(
                f"INJ:tbt:{plane}", initial_value=np.zeros(1), length=MAX_TURNS * n_mon, EGU="m"
            )
            for bpm in handover.monitors:
                self.rec[f"{bpm}:{plane}"] = builder.WaveformIn(
                    f"{bpm}:{field}", initial_value=np.zeros(1), length=MAX_TURNS, EGU="mm"
                )
        self.rec["tbt:names"] = builder.WaveformIn("INJ:tbt:names", initial_value=list(handover.monitors), length=n_mon)
        self.rec["survived"] = builder.WaveformIn("INJ:survived", initial_value=np.zeros(1), length=MAX_TURNS)
        self.rec["count"] = builder.longIn("INJ:count", initial_value=0)

    # --- settings: they act at the next shot
    def _set_geometry(self, field: str, value: float):
        setattr(self.handover.geometry, field, float(value))

    def _set_n_turns(self, value: int):
        self.handover.n_turns = int(value)

    def _on_trigger(self, value):
        if not value:
            return
        self.fire()
        # a trigger, not a state: ready for the next one
        self.rec["trigger"].set(False, process=False)

    # --- shots: one that arrives while one is computed is fired after it
    def fire(self):
        """Fire a shot (from any thread)"""
        self._pending = True
        if not self._running:
            self._running = True
            asyncio.run_coroutine_threadsafe(self._run(), get_shared_event_loop())

    async def _run(self):
        try:
            while self._pending:
                self._pending = False
                await self.shot()
        finally:
            self._running = False

    async def shot(self):
        """One shot: the line's part (``before_shot``), then the hand over"""
        if self.before_shot is not None:
            try:
                await self.before_shot()
            except Exception as exc:
                logger.error("injection: transfer line part of the shot failed: %s", exc)
        try:
            self.publish(await self.handover.compute())
        except Exception as exc:
            logger.error("injection: hand over failed: %s", exc)

    def publish(self, r: InjectionResult):
        for name, field in PLANES:
            self.rec[f"line_exit:{name}"].set(getattr(r.line_exit, field))
            self.rec[f"injected:{name}"].set(getattr(r.injected, field))
        x, y = r.x(), r.y()
        self.rec["tbt:x"].set(x.ravel())
        self.rec["tbt:y"].set(y.ravel())
        for k, bpm in enumerate(r.monitors):
            self.rec[f"{bpm}:x"].set(x[:, k] * M2MM)
            self.rec[f"{bpm}:y"].set(y[:, k] * M2MM)
        survived = r.survived()
        self.rec["survived"].set(np.asarray(survived, dtype=float))
        self.count += 1
        self.rec["count"].set(self.count)
        logger.info("injection: %d turns, survived %s", len(survived), survived[-1] if len(survived) else math.nan)


__all__: Sequence[str] = ["InjectionPVs"]
