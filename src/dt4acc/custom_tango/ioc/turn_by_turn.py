"""Tango side of a storage ring twin's turn by turn data (SOLEIL)

The computation is the control system independent
:mod:`dt4acc.core.bl.turn_by_turn`: a beam started at the beginning of the
ring lattice, at the closed orbit plus an offset (e.g. a kicked beam), read
at the ring's BPMs. Here it is spread over the twin's processes:

* physics engine (mexec service): :class:`TurnByTurnService` owns the
  computation, reached through ``SyncMexecProxy.sync_tbt_*``. It tracks
  again only after a lattice or settings change, so the ring simulator can
  ask for it on every heartbeat.
* ring simulator device (``simulator/ringsimulator/ringsimulator``): the
  settings and the summary, attributes ``tbt_offset`` (``x, px, y, py,
  delta, ct``, as ``COORDINATES``), ``tbt_n_turns``, ``tbt_start``,
  ``tbt_survived``, ``tbt_bpm_ids``, ``tbt_count``; command
  ``TurnByTurnAt(<bpm lattice id>)``
* BPM devices: one BPM, as the Libera Brilliance Plus electronics' Tango
  devices at SOLEIL (names as SOLEIL's MML reads them): ``XPosDD`` /
  ``ZPosDD`` turn by turn, ``XPosSA`` / ``ZPosSA`` slow acquisition (the
  closed orbit), all in mm; ``DDBufferSize``: the turns (shared by all BPMs
  of the twin: they see the same beam)

Todo: revisit the conversion of the BPM data (m -> mm by a fixed factor,
      ``M2MM``, as the EPICS twins' ``bpm_pvs.M2MM``): use translation
      objects there too, as for the supplies and magnets?
"""
import threading
from typing import Callable, Dict, List, Sequence

import numpy as np

from dt4acc.config.data.querries import get_bpms
from dt4acc.core.bl.turn_by_turn import (
    COORDINATES,
    DEFAULT_OFFSET,
    DEFAULT_TURNS,
    MAX_TURNS,
    RingTurnByTurn,
    TurnByTurnResult,
    ring_monitors,
)
from dt4acc.core.utils.logger import get_logger
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

logger = get_logger()

#: m -> mm: the model's positions [m] to the BPM devices' [mm]
M2MM = 1e3


def ring_bpm_ids(backend: SimulatorBackend) -> List[str]:
    """the device database's BPMs (lattice element ids) that are in the lattice,
    in ring order; without any (or without a device database): the lattice's monitors"""
    try:
        in_db = {bpm.get("uuid") for bpm in get_bpms()}
    except OSError as exc:
        logger.warning("turn by turn: no device database (%s): taking the lattice's monitors as BPMs", exc)
        in_db = set()
    ids = [uid for uid in backend.get_element_uids()[: len(backend.acc.acc)] if uid in in_db]
    return ids or ring_monitors(backend)


class TurnByTurnService:
    """Physics engine side: the computation and its latest result

    ``generation`` counts the results: it changes only when tracked again.
    """

    def __init__(self, backend: SimulatorBackend):
        self.tbt = RingTurnByTurn(backend, ring_bpm_ids(backend), offset=DEFAULT_OFFSET, n_turns=DEFAULT_TURNS)
        self.generation = 0
        self._result: TurnByTurnResult = None
        self._lock = threading.Lock()

    def configure(self, offset: Sequence[float], n_turns: int) -> None:
        if len(offset) != len(COORDINATES):
            raise ValueError(f"offset: expected {len(COORDINATES)} values ({COORDINATES}), got {len(offset)}")
        with self._lock:
            for name, value in zip(COORDINATES, offset):
                self.tbt.set_offset(name, value)
            self.tbt.n_turns = n_turns

    def update(self) -> Dict:
        """the latest result's summary, tracked again if needed"""
        with self._lock:
            result = self.tbt.latest()
            if result is not self._result:
                self._result = result
                self.generation += 1
                logger.info("turn by turn: %d turns tracked, generation %d", result.n_turns, self.generation)
            return self.summary()

    def summary(self) -> Dict:
        r = self._result
        return dict(
            generation=self.generation,
            offset=list(self.tbt.offset.as_array()),
            n_turns=self.tbt.n_turns,
            bpm_ids=list(self.tbt.monitors),
            start=list(r.start) if r else [],
            survived=list(r.survived) if r else [],
        )

    def at(self, bpm_id: str) -> List[float]:
        """the latest result at one BPM: x then y, turn after turn [m]; empty before the first result"""
        r = self._result
        if r is None:
            return []
        x, y = r.at(bpm_id)
        return list(np.concatenate([x, y]))


class TurnByTurnFollower:
    """Ring simulator side: the settings and the latest summary

    Asks the physics engine in a thread of its own when :meth:`request` ed
    (e.g. on each heartbeat) or the settings change, as tracking may take
    long; ``on_new(summary)`` is called when there is a new result.
    ``proxy`` returns the physics engine's ``SyncMexecProxy`` (None while
    not connected).
    """

    def __init__(self, proxy: Callable[[], object], on_new: Callable[[Dict], None]):
        self._proxy = proxy
        self._on_new = on_new
        self.offset = list(DEFAULT_OFFSET)
        self.n_turns = DEFAULT_TURNS
        self.summary: Dict = {}
        self.count = 0
        self._configure = True
        self._wake = threading.Event()
        threading.Thread(target=self._loop, daemon=True, name="turn-by-turn").start()

    def request(self) -> None:
        self._wake.set()

    def set_offset(self, values: Sequence[float]) -> None:
        values = [float(v) for v in values]
        if len(values) != len(COORDINATES):
            raise ValueError(f"tbt_offset: expected {len(COORDINATES)} values ({', '.join(COORDINATES)})")
        self.offset = values
        self._configure = True
        self.request()

    def set_n_turns(self, n_turns: int) -> None:
        n_turns = int(n_turns)
        if not 1 <= n_turns <= MAX_TURNS:
            raise ValueError(f"tbt_n_turns {n_turns}: expected 1 .. {MAX_TURNS}")
        self.n_turns = n_turns
        self._configure = True
        self.request()

    def at(self, bpm_id: str) -> List[float]:
        proxy = self._proxy()
        if proxy is None:
            return []
        return list(proxy.sync_tbt_at(bpm_id))

    def _loop(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            proxy = self._proxy()
            if proxy is None:
                continue
            try:
                if self._configure:
                    self._configure = False
                    proxy.sync_tbt_configure(self.offset, self.n_turns)
                summary = proxy.sync_tbt_update()
            except Exception as exc:
                logger.warning("turn by turn: %s", exc)
                continue
            if summary.get("generation") != self.summary.get("generation"):
                self.summary = summary
                self.count += 1
                try:
                    self._on_new(summary)
                except Exception as exc:
                    logger.warning("turn by turn: publishing failed: %s", exc)


__all__: Sequence[str] = ["M2MM", "MAX_TURNS", "TurnByTurnFollower", "TurnByTurnService", "ring_bpm_ids"]
