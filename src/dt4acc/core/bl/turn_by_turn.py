"""Turn by turn data of a storage ring twin, independent of the control system

A beam started at the beginning of the ring lattice, at the closed orbit
plus an offset (e.g. a kicked beam), tracked for some turns and read at the
ring's BPMs. The control systems only publish it:

* EPICS: :mod:`dt4acc.custom_epics.ioc.turn_by_turn` (PVs ``TBT:...``,
  ``<bpm>:signal:tbt:X`` / ``Y``), used by the BESSY II and MLS ring twins
* Tango: :mod:`dt4acc.custom_tango.ioc.turn_by_turn` (the ring simulator's
  ``tbt_*`` attributes, the BPM devices' ``XPosDD`` / ``ZPosDD``), used by
  the SOLEIL twin

The BESSY II injection twin has its own turn by turn data: there the beam
comes from the transfer line (``custom_facility/bessyii_injection``).

The phase space coordinates are named as dt4acc-lib's
:class:`~dt4acc_lib.model.output.track.ParticleState`:
``x, px, y, py, delta, ct``.
"""
from typing import List, Optional, Sequence

import at
import numpy as np
from pydantic import BaseModel, ConfigDict

from dt4acc_lib.model.output.track import ParticleState
from dt4acc_lib.model.output.track_as_np_wrapper import NPStatesForTurns
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

#: as many turns as the BPM electronics (Libera) record
MAX_TURNS = 64 * 1024
DEFAULT_TURNS = 128
#: the ParticleState fields, in its order
COORDINATES = ("x", "px", "y", "py", "delta", "ct")
UNITS = {"x": "m", "px": "rad", "y": "m", "py": "rad", "delta": "", "ct": "m"}
#: default start: 1 mm off the closed orbit in x and y (a kicked beam)
DEFAULT_OFFSET = (1e-3, 0.0, 1e-3, 0.0, 0.0, 0.0)


class TurnByTurnResult(BaseModel):
    """One computation: the state tracked, the positions at the BPMs, turn after turn"""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    #: start state tracked (closed orbit + offset), ``COORDINATES``
    start: List[float]
    #: number of turns tracked
    n_turns: int
    #: the BPMs (lattice element ids), in ring order
    monitors: List[str]
    #: [turn, monitor] horizontal position [m]; NaN once the beam is lost
    x: np.ndarray
    #: [turn, monitor] vertical position [m]; NaN once the beam is lost
    y: np.ndarray
    #: particles still there after each turn (at the last BPM)
    survived: np.ndarray

    def at(self, monitor: str) -> (np.ndarray, np.ndarray):
        """x, y [m] at one BPM, turn after turn"""
        k = self.monitors.index(monitor)
        return self.x[:, k], self.y[:, k]

    @classmethod
    def from_turns(cls, start: ParticleState, n_turns: int, monitors: Sequence[str],
                   turns: NPStatesForTurns) -> "TurnByTurnResult":
        by_uid = {e.uid: e for e in turns.per_element}
        per_monitor = [by_uid[m] for m in monitors]
        survived = per_monitor[-1].get_survived().get_n_particles_survived_per_turn()
        return cls(
            start=list(start.as_array()),
            n_turns=n_turns,
            monitors=list(monitors),
            x=np.array([e.get_x().nanmean_per_turn() for e in per_monitor]).T,
            y=np.array([e.get_y().nanmean_per_turn() for e in per_monitor]).T,
            survived=np.atleast_1d(np.asarray(survived, dtype=float)),
        )


def ring_monitors(backend: SimulatorBackend, name_prefix: Optional[str] = None) -> List[str]:
    """the ring's BPMs: its ``at.Monitor`` elements (lattice element ids), in lattice
    order; ``name_prefix``: only those whose name starts with it (e.g. ``BPMZ``)"""
    return [
        getattr(e, "UUID", e.FamName)
        for e in backend.acc.acc
        if isinstance(e, at.Monitor) and (name_prefix is None or e.FamName.startswith(name_prefix))
    ]


class RingTurnByTurn:
    """Tracks the ring from its first element: closed orbit + ``offset``, ``n_turns``,
    read at ``monitors`` (lattice element ids, e.g. from :func:`ring_monitors`)"""

    def __init__(self, backend: SimulatorBackend, monitors: Sequence[str],
                 offset: Sequence[float] = DEFAULT_OFFSET, n_turns: int = DEFAULT_TURNS):
        assert backend.acc.is_ring
        assert len(monitors) > 0, "turn by turn data needs at least one BPM"
        self.backend = backend
        self.monitors = list(monitors)
        self.offset = ParticleState.from_sequence(offset)
        self.n_turns = n_turns
        self._latest: Optional[TurnByTurnResult] = None
        self._computed_for = None

    @property
    def n_turns(self) -> int:
        return self._n_turns

    @n_turns.setter
    def n_turns(self, value: int):
        value = int(value)
        if not 1 <= value <= MAX_TURNS:
            raise ValueError(f"n_turns {value}: expected 1 .. {MAX_TURNS}")
        self._n_turns = value

    def set_offset(self, coordinate: str, value: float):
        """one coordinate of the start offset (``COORDINATES``)"""
        if coordinate not in COORDINATES:
            raise ValueError(f"coordinate {coordinate!r}: expected one of {COORDINATES}")
        setattr(self.offset, coordinate, float(value))

    def _optics(self):
        _, __, optics = self.backend.get_optics()
        return optics

    def closed_orbit(self, optics=None) -> np.ndarray:
        """at the start of the lattice; zero without a closed orbit"""
        optics = optics if optics is not None else self._optics()
        if optics is None:
            return np.zeros(ParticleState.n_elements())
        _, __, elem_data = optics
        return np.asarray(elem_data.closed_orbit[0], dtype=float)

    def compute(self) -> TurnByTurnResult:
        """tracks now"""
        optics = self._optics()
        result = self._compute(optics)
        self._remember(optics, result)
        return result

    def latest(self) -> TurnByTurnResult:
        """the last result, tracked again only if the lattice (its optics) or the
        settings changed since: cheap to call periodically (e.g. by a heartbeat)"""
        optics = self._optics()
        if self._latest is None or not self._is_for(optics):
            self._remember(optics, self._compute(optics))
        return self._latest

    def _settings(self):
        return tuple(self.offset.as_array()), self.n_turns, tuple(self.monitors)

    def _is_for(self, optics) -> bool:
        # the backend computes new optics after each lattice change: compare the object
        last_optics, settings = self._computed_for
        return last_optics is optics and settings == self._settings()

    def _remember(self, optics, result: TurnByTurnResult):
        self._latest = result
        self._computed_for = (optics, self._settings())

    def _compute(self, optics) -> TurnByTurnResult:
        start = ParticleState.from_sequence(self.closed_orbit(optics) + self.offset.as_array())
        turns = self.backend.compute_track([start], self.n_turns, self.monitors)
        return TurnByTurnResult.from_turns(start, self.n_turns, self.monitors, turns)


__all__: Sequence[str] = [
    "COORDINATES", "DEFAULT_OFFSET", "DEFAULT_TURNS", "MAX_TURNS", "UNITS",
    "RingTurnByTurn", "TurnByTurnResult", "ring_monitors",
]
