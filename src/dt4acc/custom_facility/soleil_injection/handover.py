"""SOLEIL: hand the beam leaving TL2 over to the storage ring, as
``bessyii_injection/handover.py``

TL2 and the ring are two models, run as stages: the beam leaving the first is
the beam entering the second.

* TL2: its exit state is the centroid leaving the line (line frame)
* injection geometry: the line's reference against the ring's at the injection
  point, a difference state: ring state = line state + geometry
* ring: its lattice starts at the injection point (``INJECTION_ELEMENT``). Its
  turn by turn data start at the lattice's start, at closed orbit + offset. So
  with offset = injected - closed orbit they are the injected beam's, read at
  the ring's BPMs, tracked on the ring's physics engine.

Recomputed when TL2 or the ring change or the settings change.
"""
from typing import Callable, Optional, Sequence

import numpy as np

from dt4acc.core.bl.turn_by_turn import COORDINATES

#: where TL2's beam enters the ring: the first element of its lattice, centre of the
#: injection straight. TL2 ends at the middle of the injection straight too. To be
#: confirmed by SOLEIL, as the geometry there (a placeholder: no offset)
INJECTION_ELEMENT = "SD01ICENTER"
#: turns tracked by default, as the BESSY II injection twin
DEFAULT_TURNS = 2
#: offsets differing less are the same [m, rad, 1, m]
TOLERANCE = 1e-12


def to_ring(line_state: Sequence[float], geometry: Sequence[float]) -> np.ndarray:
    """The line's state in the ring's frame"""
    return np.asarray(line_state, dtype=float) + np.asarray(geometry, dtype=float)


class InjectionHandover:
    """``line_exit()``: state leaving the line (empty if there is none); ``ring``: its
    simulator device (``tbt_closed_orbit``, ``tbt_offset``, ``tbt_count``)"""

    def __init__(self, *, line_exit: Callable[[], Sequence[float]], ring):
        self._line_exit = line_exit
        self.ring = ring
        self.geometry = np.zeros(len(COORDINATES))
        self.line_exit = np.zeros(0)
        self.injected = np.zeros(0)

    def set_geometry(self, values: Sequence[float]) -> None:
        values = np.asarray(values, dtype=float)
        if values.shape != (len(COORDINATES),):
            raise ValueError(f"geometry: expected {len(COORDINATES)} values ({', '.join(COORDINATES)})")
        self.geometry = values

    def update(self) -> Optional[np.ndarray]:
        """Hands over the present beam: returns the offset written to the ring, None if
        it is up to date (or there is no beam or closed orbit yet)"""
        exit_state = np.asarray(self._line_exit(), dtype=float)
        if exit_state.shape != (len(COORDINATES),) or not np.all(np.isfinite(exit_state)):
            return None
        self.line_exit = exit_state
        self.injected = to_ring(exit_state, self.geometry)
        closed_orbit = np.asarray(self.ring.tbt_closed_orbit, dtype=float)
        if closed_orbit.shape != self.injected.shape:
            return None
        offset = self.injected - closed_orbit
        if np.all(np.abs(np.asarray(self.ring.tbt_offset, dtype=float) - offset) <= TOLERANCE):
            return None
        self.ring.tbt_offset = offset
        return offset
