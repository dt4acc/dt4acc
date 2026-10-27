"""Hand the beam leaving the transfer line to the storage ring

Transfer line and ring are two models (as in MML: two submachines, each with
its own devices), run as stages (as LUME's StagedModel): the beam leaving the
first is the beam entering the second.

* transfer line: line mode, cut at the injection septum exit; its exit
  state is the centroid of the beam leaving the septum (line frame)
* injection geometry: the line's axis against the ring's axis at the septum
  exit (offset and angle); ring = line + geometry
* ring: the beam is tracked from the septum exit (``MSEPEXIT``) for
  ``n_turns``, read at the ring's beam position monitors

The elements between the start of the ring lattice and ``MSEPEXIT`` are
drifts and markers: the beam is moved back through them to the ring's start,
where tracking begins, so that its first pass through ``MSEPEXIT`` is the
injected state.
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

import at
import numpy as np

from dt4acc_lib.model.output.track import ParticleState
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

logger = logging.getLogger("dt4acc-bessyii-injection")

INJECTION_ELEMENT = "MSEPEXIT"


@dataclass
class InjectionGeometry:
    """Line axis against ring axis at the septum exit (ring = line + this)"""

    #: [m]
    x: float = 0.0
    #: [rad]
    xp: float = 0.0
    #: [m]
    y: float = 0.0
    #: [rad]
    yp: float = 0.0

    def to_ring(self, state: Sequence[float]) -> np.ndarray:
        r = np.array(state, dtype=float)
        r[:4] += (self.x, self.xp, self.y, self.yp)
        return r


@dataclass
class InjectionResult:
    #: centroid leaving the line, line frame (x, x', y, y', delta, ct)
    line_exit: List[float]
    #: same, ring frame, at the septum exit
    injected: List[float]
    #: monitors in ring order
    monitors: List[str]
    #: [turn][monitor] position (m); NaN once the beam is lost
    x: List[List[float]] = field(default_factory=list)
    y: List[List[float]] = field(default_factory=list)
    #: particles still there at each turn
    survived: List[int] = field(default_factory=list)


def drift_back(state: np.ndarray, length: float) -> np.ndarray:
    """Undo a drift of ``length`` (pyAT's DriftPass, 6D)"""
    x, px, y, py, delta, ct = state
    norm = 1.0 / (1.0 + delta)
    nx, ny = px * norm, py * norm
    r = state.copy()
    r[0] = x - length * nx
    r[2] = y - length * ny
    r[5] = ct - length * (nx * nx + ny * ny) / 2
    return r


def back_to_start(ring: at.Lattice, state: np.ndarray, element: str = INJECTION_ELEMENT) -> np.ndarray:
    """The state at the start of the ring lattice that reaches ``element`` as ``state``"""
    (idx,) = [i for i, elem in enumerate(ring) if elem.FamName == element]
    r = np.array(state, dtype=float)
    for elem in reversed(ring[:idx]):
        if isinstance(elem, at.Drift):
            r = drift_back(r, elem.Length)
        elif elem.Length != 0 or not isinstance(elem, at.Marker):
            raise ValueError(f"only drifts and markers before {element}, found {elem.FamName} ({type(elem).__name__})")
    return r


class InjectionCoupler:
    def __init__(
        self,
        *,
        line: SimulatorBackend,
        ring: SimulatorBackend,
        monitors: Sequence[str],
        geometry: InjectionGeometry = None,
        n_turns: int = 2,
    ):
        assert not line.acc.is_ring, "the transfer line backend needs to work as a line (twiss_in)"
        assert ring.acc.is_ring
        self.line = line
        self.ring = ring
        self.monitors = list(monitors)
        self.geometry = geometry or InjectionGeometry()
        self.n_turns = n_turns

    def line_exit(self) -> np.ndarray:
        """Centroid leaving the line: last point of its optics"""
        _, uids, optics = self.line.get_optics()
        if optics is None:
            raise RuntimeError("transfer line optics not available")
        _, _, elem_data = optics
        assert uids[-1].endswith(":exit"), uids[-1]
        return np.array(elem_data.closed_orbit[-1], dtype=float)

    async def compute(self) -> InjectionResult:
        exit_state = self.line_exit()
        injected = self.geometry.to_ring(exit_state)
        start = back_to_start(self.ring.acc.acc, injected)
        await self.ring.set("turn_by_turn_start", "p0", [ParticleState.from_sequence(start)])
        await self.ring.set("turn_by_turn_start", "n_turns", self.n_turns)
        await self.ring.set("turn_by_turn_start", "data_needed_at", self.monitors)
        data = await self.ring.read("turn_by_turn", "pos")
        by_uid: Dict[str, object] = {e.uid: e for e in data.per_element}
        per_monitor = [by_uid[m] for m in self.monitors]
        x = np.array([e.get_x().nanmean_per_turn() for e in per_monitor]).T
        y = np.array([e.get_y().nanmean_per_turn() for e in per_monitor]).T
        survived = per_monitor[-1].get_survived().get_n_particles_survived_per_turn()
        return InjectionResult(
            line_exit=exit_state.tolist(),
            injected=injected.tolist(),
            monitors=self.monitors,
            x=x.tolist(),
            y=y.tolist(),
            survived=[int(v) for v in np.atleast_1d(survived)],
        )
