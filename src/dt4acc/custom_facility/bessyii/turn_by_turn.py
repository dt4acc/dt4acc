"""Turn by turn data of the BESSY II ring alone, at its BPMs (``BPMZ...``):
:mod:`dt4acc.custom_epics.ioc.turn_by_turn`"""
from typing import List, Sequence

import at

from dt4acc.custom_epics.ioc.turn_by_turn import RingTurnByTurn
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend


def ring_bpms(backend: SimulatorBackend) -> List[str]:
    """the ring's BPMs (``BPMZ...``), in lattice order"""
    return [e.FamName for e in backend.acc.acc if isinstance(e, at.Monitor) and e.FamName.startswith("BPMZ")]


def ring_turn_by_turn(backend: SimulatorBackend, **kwargs) -> RingTurnByTurn:
    """``RingTurnByTurn`` at the ring's BPMs; kwargs: ``offset``, ``n_turns``"""
    return RingTurnByTurn(backend, ring_bpms(backend), **kwargs)


__all__: Sequence[str] = ["ring_bpms", "ring_turn_by_turn"]
