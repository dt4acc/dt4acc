"""Turn by turn data of the storage ring alone: a beam started off the closed
orbit, tracked for some turns, read at the ring's BPMs

The same BPM PVs as the injection twin (``<bpm>:tbt:x``, ``<bpm>:tbt:y``),
where the beam comes from the transfer line instead
(``custom_facility/bessyii_injection``). Here it starts at the beginning of
the ring lattice, at the closed orbit plus an offset, e.g. a kicked beam:

* ``TBT:offset:{x,xp,y,yp,delta,ct}``: start offset from the closed orbit
  (without a closed orbit: the start itself)
* ``TBT:n_turns``: turns tracked
* ``TBT:start:{x,xp,y,yp,delta,ct}``: the start state tracked
* ``TBT:tbt:{x,y}``: position at the ring's BPMs, turn after turn (turn 1
  at all BPMs, then turn 2, ...), ``TBT:tbt:names``: the BPMs
* ``TBT:survived``: particles still there after each turn
* ``TBT:count``: number of computations
* ``<bpm>:tbt:x``, ``<bpm>:tbt:y``: one BPM, turn after turn

Recomputed when one of the settings changes and after each new closed orbit
(lattice change), as the injection twin's hand over.
"""
import asyncio
import logging
import math
from dataclasses import dataclass
from typing import List, Sequence

import at
import numpy as np
from softioc import builder as softioc_builder

from dt4acc.core.bl.shared_event_loop import get_shared_event_loop
from dt4acc_lib.model.output.track import ParticleState
from dt4acc_lib.model.output.track_as_np_wrapper import NPStatesForTurns
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

logger = logging.getLogger("dt4acc-bessyii")

MAX_TURNS = 1024
#: PV field, ParticleState field
PLANES = (("x", "x"), ("xp", "px"), ("y", "y"), ("yp", "py"), ("delta", "delta"), ("ct", "ct"))
UNITS = {"x": "m", "xp": "rad", "y": "m", "yp": "rad", "delta": "", "ct": "m"}
#: default start: 1 mm off the closed orbit in x and y (a kicked beam)
DEFAULT_OFFSET = (1e-3, 0.0, 1e-3, 0.0, 0.0, 0.0)
DEFAULT_TURNS = 128


def ring_bpms(backend: SimulatorBackend) -> List[str]:
    """the ring's BPMs (``BPMZ...``), in lattice order"""
    return [e.FamName for e in backend.acc.acc if isinstance(e, at.Monitor) and e.FamName.startswith("BPMZ")]


@dataclass
class TurnByTurnResult:
    """One computation: the state tracked, the turns at the BPMs"""

    start: ParticleState
    #: ring BPMs, in ring order
    monitors: List[str]
    #: dt4acc-lib's turn by turn data at the monitors
    turns: NPStatesForTurns

    def _per_monitor(self):
        by_uid = {e.uid: e for e in self.turns.per_element}
        return [by_uid[m] for m in self.monitors]

    def x(self) -> np.ndarray:
        """[turn, monitor] position [m]; NaN once the beam is lost"""
        return np.array([e.get_x().nanmean_per_turn() for e in self._per_monitor()]).T

    def y(self) -> np.ndarray:
        return np.array([e.get_y().nanmean_per_turn() for e in self._per_monitor()]).T

    def survived(self) -> np.ndarray:
        """particles still there at each turn (at the last BPM)"""
        last = self._per_monitor()[-1]
        return np.atleast_1d(last.get_survived().get_n_particles_survived_per_turn())


class RingTurnByTurn:
    """Tracks the ring from its first element: closed orbit + ``offset``, ``n_turns``"""

    def __init__(self, backend: SimulatorBackend, monitors: Sequence[str] = None,
                 offset: ParticleState = None, n_turns: int = DEFAULT_TURNS):
        assert backend.acc.is_ring
        self.backend = backend
        self.monitors = list(monitors) if monitors is not None else ring_bpms(backend)
        self.offset = offset or ParticleState.from_sequence(DEFAULT_OFFSET)
        self.n_turns = n_turns

    def closed_orbit(self) -> np.ndarray:
        """at the start of the lattice; zero without a closed orbit"""
        _, __, optics = self.backend.get_optics()
        if optics is None:
            return np.zeros(ParticleState.n_elements())
        _, __, elem_data = optics
        return np.asarray(elem_data.closed_orbit[0], dtype=float)

    async def compute(self) -> TurnByTurnResult:
        start = ParticleState.from_sequence(self.closed_orbit() + self.offset.as_array())
        for prop, value in (
            ("p0", [start]),
            ("n_turns", self.n_turns),
            ("data_needed_at", self.monitors),
            ("start_at", None),
        ):
            await self.backend.set("turn_by_turn_start", prop, value)
        turns = await self.backend.read("turn_by_turn", "pos")
        return TurnByTurnResult(start=start, monitors=self.monitors, turns=turns)


class TurnByTurnPVs:
    """Records of the ring's turn by turn data; recomputes whenever the settings or the lattice change"""

    def __init__(self, tbt: RingTurnByTurn, builder=softioc_builder):
        self.tbt = tbt
        self._dirty = False
        self._running = False
        self.count = 0
        n_mon = len(tbt.monitors)
        self.rec = {}
        for name, field in PLANES:
            self.rec[f"offset:{name}"] = builder.aOut(
                f"TBT:offset:{name}", initial_value=getattr(tbt.offset, field), PREC=6, EGU=UNITS[name],
                on_update=lambda val, field=field: self._set_offset(field, val),
            )
            self.rec[f"start:{name}"] = builder.aIn(f"TBT:start:{name}", initial_value=0.0, PREC=9, EGU=UNITS[name])
        self.rec["n_turns"] = builder.longOut(
            "TBT:n_turns", initial_value=tbt.n_turns, DRVL=1, DRVH=MAX_TURNS, on_update=self._set_n_turns
        )
        for plane in ("x", "y"):
            self.rec[f"tbt:{plane}"] = builder.WaveformIn(
                f"TBT:tbt:{plane}", initial_value=np.zeros(1), length=MAX_TURNS * n_mon, EGU="m"
            )
            for bpm in tbt.monitors:
                self.rec[f"{bpm}:{plane}"] = builder.WaveformIn(
                    f"{bpm}:tbt:{plane}", initial_value=np.zeros(1), length=MAX_TURNS, EGU="m"
                )
        self.rec["tbt:names"] = builder.WaveformIn("TBT:tbt:names", initial_value=list(tbt.monitors), length=n_mon)
        self.rec["survived"] = builder.WaveformIn("TBT:survived", initial_value=np.zeros(1), length=MAX_TURNS)
        self.rec["count"] = builder.longIn("TBT:count", initial_value=0)

    # --- settings
    def _set_offset(self, field: str, value: float):
        setattr(self.tbt.offset, field, float(value))
        self.trigger()

    def _set_n_turns(self, value: int):
        self.tbt.n_turns = int(value)
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
                    self.publish(await self.tbt.compute())
                except Exception as exc:
                    logger.error("turn by turn: tracking failed: %s", exc)
        finally:
            self._running = False

    def publish(self, r: TurnByTurnResult):
        for name, field in PLANES:
            self.rec[f"start:{name}"].set(getattr(r.start, field))
        x, y = r.x(), r.y()
        self.rec["tbt:x"].set(x.ravel())
        self.rec["tbt:y"].set(y.ravel())
        for k, bpm in enumerate(r.monitors):
            self.rec[f"{bpm}:x"].set(x[:, k])
            self.rec[f"{bpm}:y"].set(y[:, k])
        survived = r.survived()
        self.rec["survived"].set(np.asarray(survived, dtype=float))
        self.count += 1
        self.rec["count"].set(self.count)
        logger.info("turn by turn: %d turns, survived %s", len(survived), survived[-1] if len(survived) else math.nan)


def hook_track_updates(view, tbt: TurnByTurnPVs):
    """After the view publishes a new closed orbit, recompute the turn by turn data"""
    update_track = view.update_track

    def update_track_and_tbt(var, pkg):
        update_track(var, pkg)
        tbt.trigger()

    view.update_track = update_track_and_tbt
    return view


__all__: Sequence[str] = ["RingTurnByTurn", "TurnByTurnPVs", "TurnByTurnResult", "hook_track_updates", "ring_bpms"]
