"""Hand the beam leaving the transfer line over to the storage ring

Transfer line and ring are two models (as in MML: two submachines, each with
its own devices), run as stages (as LUME's StagedModel): the beam leaving the
first is the beam entering the second.

* transfer line: line mode, cut at the injection septum exit; its exit
  state is the centroid of the beam leaving the septum (line frame)
* injection geometry: the line's reference against the ring's reference at
  the septum exit, as a difference state (x, x', y, y', delta, ct): ring
  state = line state + geometry. delta is a momentum offset of the injected
  beam against the ring's reference, e.g. a booster energy that differs from
  the ring's
* ring: the beam is tracked from the septum exit (``MSEPEXIT``) for
  ``n_turns`` (dt4acc-lib turn by turn tracking starting at that element),
  read at the ring's beam position monitors
"""
import logging
from dataclasses import dataclass
from typing import List, Sequence

import numpy as np

from dt4acc_lib.model.output.track import ParticleState
from dt4acc_lib.model.output.track_as_np_wrapper import NPStatesForTurns
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

logger = logging.getLogger("dt4acc-bessyii-injection")

#: where the line's beam enters the ring lattice
INJECTION_ELEMENT = "MSEPEXIT"


def no_offset() -> ParticleState:
    return ParticleState.from_sequence([0.0] * ParticleState.n_elements())


def to_ring(line_state: ParticleState, geometry: ParticleState) -> ParticleState:
    """The line's state in the ring's frame"""
    return ParticleState.from_sequence(line_state.as_array() + geometry.as_array())


@dataclass
class InjectionResult:
    """One hand over: what left the line, what entered the ring, the turns"""

    #: centroid leaving the line (line frame)
    line_exit: ParticleState
    #: the same in the ring's frame, at the septum exit
    injected: ParticleState
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


class InjectionHandover:
    def __init__(
        self,
        *,
        line: SimulatorBackend,
        ring: SimulatorBackend,
        monitors: Sequence[str],
        geometry: ParticleState = None,
        n_turns: int = 2,
    ):
        assert not line.acc.is_ring, "the transfer line backend needs to work as a line (twiss_in)"
        assert ring.acc.is_ring
        self.line = line
        self.ring = ring
        self.monitors = list(monitors)
        self.geometry = geometry or no_offset()
        self.n_turns = n_turns

    def line_exit(self) -> ParticleState:
        """Centroid leaving the line: last point of its optics"""
        _, uids, optics = self.line.get_optics()
        if optics is None:
            raise RuntimeError("transfer line optics not available")
        _, _, elem_data = optics
        assert uids[-1].endswith(":exit"), uids[-1]
        return ParticleState.from_sequence(np.asarray(elem_data.closed_orbit[-1], dtype=float))

    async def compute(self) -> InjectionResult:
        exit_state = self.line_exit()
        injected = to_ring(exit_state, self.geometry)
        for prop, value in (
            ("p0", [injected]),
            ("n_turns", self.n_turns),
            ("data_needed_at", self.monitors),
            ("start_at", INJECTION_ELEMENT),
        ):
            await self.ring.set("turn_by_turn_start", prop, value)
        turns = await self.ring.read("turn_by_turn", "pos")
        return InjectionResult(line_exit=exit_state, injected=injected, monitors=self.monitors, turns=turns)
