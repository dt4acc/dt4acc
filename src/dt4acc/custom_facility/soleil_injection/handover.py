"""SOLEIL: hand the beam leaving TL2 over to the storage ring, as
``bessyii_injection/handover.py``

TL2 and the ring are two models, run as stages: the beam leaving the first is
the beam entering the second.

* TL2: its exit state is the centroid leaving the line (line frame)
* injection geometry: the line's reference against the ring's reference at the injection
  point, a difference state: ring state = line state + geometry
* ring: its lattice starts at the injection point (``INJECTION_ELEMENT``). The injected
  beam is tracked from there on the ring's physics engine as its turn by turn data
  (``Inject`` of the ring simulator), read at the ring's BPMs.

A shot (:meth:`InjectionHandover.shot`) hands over the beam as it is then: as at the
machine, the injection is fired on demand, changes of TL2, the ring or the geometry act
at the next shot.
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


def to_ring(line_state: Sequence[float], geometry: Sequence[float]) -> np.ndarray:
    """The line's state in the ring's frame"""
    return np.asarray(line_state, dtype=float) + np.asarray(geometry, dtype=float)


class InjectionHandover:
    """``line_exit()``: state leaving the line now (empty if there is none); ``ring``: its
    simulator device (command ``Inject``)"""

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

    def shot(self) -> Optional[np.ndarray]:
        """The beam leaving the line now, injected into the ring (tracked there): the
        injected state; None if no beam leaves the line (its optics failed): nothing is
        injected, the ring's turn by turn data stay as they are"""
        exit_state = np.asarray(self._line_exit(), dtype=float)
        if exit_state.shape != (len(COORDINATES),) or not np.all(np.isfinite(exit_state)):
            self.line_exit = self.injected = np.zeros(0)
            return None
        self.line_exit = exit_state
        self.injected = to_ring(exit_state, self.geometry)
        self.ring.Inject(self.injected)
        return self.injected
