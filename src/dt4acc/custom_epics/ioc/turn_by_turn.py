"""EPICS PVs of a storage ring twin's turn by turn data (BESSY II, MLS)

The computation is the control system independent
:mod:`dt4acc.core.bl.turn_by_turn`: a beam started at the beginning of the
ring lattice, at the closed orbit plus an offset (e.g. a kicked beam), read
at the ring's BPMs. The same BPM PVs as the BESSY II injection twin, where
the beam comes from the transfer line instead (``custom_facility/bessyii_injection``):

* ``TBT:offset:{x,px,y,py,delta,ct}``: start offset from the closed orbit
  (without a closed orbit: the start itself)
* ``TBT:n_turns``: turns tracked (up to ``MAX_TURNS``, as the BPM electronics)
* ``TBT:start:{x,px,y,py,delta,ct}``: the start state tracked
* ``TBT:tbt:{x,y}``: position at the ring's BPMs, turn after turn (turn 1
  at all BPMs, then turn 2, ...; the first ``MAX_TURNS_ALL_BPMS`` turns),
  ``TBT:tbt:names``: the BPMs
* ``TBT:survived``: particles still there after each turn
* ``TBT:count``: number of computations
* ``<bpm>:signal:tbt:X``, ``<bpm>:signal:tbt:Y``: one BPM, turn after turn [mm]
  (:mod:`dt4acc.custom_epics.ioc.bpm_pvs`)

The coordinates are named as dt4acc-lib's ``ParticleState``
(``COORDINATES``). Recomputed when one of the settings changes and after
each new closed orbit (lattice change), as the injection twin's hand over.

Todo: revisit the conversion of the turn by turn data (m -> mm by a fixed
      factor, ``bpm_pvs.M2MM``): use translation objects there too, as for
      the supplies and magnets?
"""
import asyncio
import logging
import math
from typing import Sequence

import numpy as np
from softioc import builder as softioc_builder

from dt4acc.core.bl.shared_event_loop import get_shared_event_loop
from dt4acc.core.bl.turn_by_turn import COORDINATES, MAX_TURNS, UNITS, RingTurnByTurn, TurnByTurnResult
from dt4acc.custom_epics.ioc.bpm_pvs import M2MM, TBT_FIELDS

logger = logging.getLogger("dt4acc")

#: turns the aggregates ``TBT:tbt:{x,y}`` (all BPMs in one waveform) hold at
#: most: their records are allocated for all BPMs; the BPMs' own PVs hold up
#: to ``MAX_TURNS``
MAX_TURNS_ALL_BPMS = 1024


class TurnByTurnPVs:
    """Records of the ring's turn by turn data; recomputes whenever the settings or the lattice change"""

    def __init__(self, tbt: RingTurnByTurn, builder=softioc_builder):
        self.tbt = tbt
        self._dirty = False
        self._running = False
        self.count = 0
        n_mon = len(tbt.monitors)
        self.rec = {}
        for name in COORDINATES:
            self.rec[f"offset:{name}"] = builder.aOut(
                f"TBT:offset:{name}", initial_value=getattr(tbt.offset, name), PREC=6, EGU=UNITS[name],
                on_update=lambda val, name=name: self._set_offset(name, val),
            )
            self.rec[f"start:{name}"] = builder.aIn(f"TBT:start:{name}", initial_value=0.0, PREC=9, EGU=UNITS[name])
        self.rec["n_turns"] = builder.longOut(
            "TBT:n_turns", initial_value=tbt.n_turns, DRVL=1, DRVH=MAX_TURNS, on_update=self._set_n_turns
        )
        for plane, field in TBT_FIELDS:
            self.rec[f"tbt:{plane}"] = builder.WaveformIn(
                f"TBT:tbt:{plane}", initial_value=np.zeros(1), length=MAX_TURNS_ALL_BPMS * n_mon, EGU="m"
            )
            for bpm in tbt.monitors:
                self.rec[f"{bpm}:{plane}"] = builder.WaveformIn(
                    f"{bpm}:{field}", initial_value=np.zeros(1), length=MAX_TURNS, EGU="mm"
                )
        self.rec["tbt:names"] = builder.WaveformIn("TBT:tbt:names", initial_value=list(tbt.monitors), length=n_mon)
        self.rec["survived"] = builder.WaveformIn("TBT:survived", initial_value=np.zeros(1), length=MAX_TURNS)
        self.rec["count"] = builder.longIn("TBT:count", initial_value=0)

    # --- settings
    def _set_offset(self, coordinate: str, value: float):
        self.tbt.set_offset(coordinate, value)
        self.trigger()

    def _set_n_turns(self, value: int):
        self.tbt.n_turns = value
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
                    self.publish(self.tbt.compute())
                except Exception as exc:
                    logger.error("turn by turn: tracking failed: %s", exc)
        finally:
            self._running = False

    def publish(self, r: TurnByTurnResult):
        for name, value in zip(COORDINATES, r.start):
            self.rec[f"start:{name}"].set(value)
        n_all = min(r.n_turns, MAX_TURNS_ALL_BPMS)
        self.rec["tbt:x"].set(r.x[:n_all].ravel())
        self.rec["tbt:y"].set(r.y[:n_all].ravel())
        for k, bpm in enumerate(r.monitors):
            self.rec[f"{bpm}:x"].set(r.x[:, k] * M2MM)
            self.rec[f"{bpm}:y"].set(r.y[:, k] * M2MM)
        self.rec["survived"].set(r.survived)
        self.count += 1
        self.rec["count"].set(self.count)
        survived = r.survived[-1] if len(r.survived) else math.nan
        logger.info("turn by turn: %d turns, survived %s", r.n_turns, survived)


def hook_track_updates(view, tbt: TurnByTurnPVs):
    """After the view publishes a new closed orbit, recompute the turn by turn data"""
    update_track = view.update_track

    def update_track_and_tbt(var, pkg):
        update_track(var, pkg)
        tbt.trigger()

    view.update_track = update_track_and_tbt
    return view


__all__: Sequence[str] = ["MAX_TURNS_ALL_BPMS", "TurnByTurnPVs", "hook_track_updates"]
