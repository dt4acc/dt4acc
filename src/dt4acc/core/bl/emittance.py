"""The stored beam's emittance, calculated from the ring's lattice

For a steady state beam in a storage ring the emittance is a result of the
lattice (radiation damping and quantum excitation), not a setting: pyAT's
beam envelope (Ohmi) of the twin's lattice, 6D. The vertical emittance comes
from coupling (e.g. skew quadrupoles): an uncoupled lattice gives (almost) 0.

For a transfer line, or the start bunch of tracking, the emittance is a
parameter the user gives (e.g. ``TL:beam:emittance:*``), not calculated here.

Todo:
  * as a read of the controller (dt4acc-lib's backend), as the orbit and the
    optics, instead of from the backend's lattice here
  * coupling the lattice does not model (errors): the vertical emittance of
    the machine is larger than the twin's
"""
import math
from typing import Dict, Sequence

PLANES = ("x", "y")


def ring_emittance(lattice) -> Dict[str, float]:
    """{"x": ..., "y": ...} [m rad] of ``lattice`` (a pyAT ring); NaN if the
    envelope cannot be calculated (e.g. no closed orbit)"""
    try:
        ring = lattice if lattice.is_6d else lattice.enable_6d(copy=True)
        emittances = ring.envelope_parameters().emittances
        return {plane: max(float(emittances[k]), 0.0) for k, plane in enumerate(PLANES)}
    except Exception:
        return {plane: math.nan for plane in PLANES}


__all__: Sequence[str] = ["PLANES", "ring_emittance"]
