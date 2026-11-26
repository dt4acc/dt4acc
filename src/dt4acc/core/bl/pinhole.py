"""Pinhole cameras of a storage ring twin, independent of the control system

A pinhole camera images the synchrotron light of the beam at a source point,
usually inside a dipole. The twin shows there

* the beam centre: the closed orbit,
* the beam size: ``sigma = sqrt(emittance * beta)`` in each plane, from the
  optics and a set emittance (planes not coupled),
* an idealised image: a Gaussian spot (:mod:`dt4acc.core.bl.beam_spot`), in
  the coordinates of the beam at the source point: the camera's magnification
  and resolution are not modelled.

The values are the controller's orbit and optics at the camera's lattice
element, handed over by the view (a camera is a view of its element). The
source points are not in the lattice yet: a camera uses an element near its
source point (BESSY II: the dipole's entrance), and moves to the source
point's marker once the lattice has it.

Todo:
  * the energy spread: ``(dispersion * energy spread)^2`` adds to sigma_x^2;
    the optics handed over have no dispersion yet (dt4acc-lib's twiss)
  * the image's blur (pinhole diffraction, camera resolution), noise (#82)
  * coupling: a tilted spot, the vertical emittance from it
"""
import math
from dataclasses import dataclass
from typing import Mapping

from .beam_spot import CameraGeometry

PLANES = ("x", "y")


@dataclass(frozen=True)
class PinholeCamera:
    """``name``: the device, ``element``: the lattice element whose orbit and
    optics it shows (its source point, or the nearest element until the
    lattice has one)"""
    name: str
    element: str
    geometry: CameraGeometry = CameraGeometry()


@dataclass(frozen=True)
class BeamSpot:
    """beam centre and size at the camera's element [m]; NaN without a closed orbit"""
    x: float
    y: float
    sigma_x: float
    sigma_y: float


NO_BEAM = BeamSpot(math.nan, math.nan, math.nan, math.nan)


def beam_spot(x: float, y: float, beta: Mapping[str, float], emittance: Mapping[str, float]) -> BeamSpot:
    """centre (``x``, ``y`` [m]) and size ``sqrt(emittance * beta)`` per plane;
    NaN in, NaN out (no closed orbit, failed optics)"""

    def size(plane: str) -> float:
        b, e = beta[plane], emittance[plane]
        return math.sqrt(e * b) if b >= 0.0 and e >= 0.0 else math.nan

    return BeamSpot(x=float(x), y=float(y), sigma_x=size("x"), sigma_y=size("y"))


__all__ = ["BeamSpot", "NO_BEAM", "PLANES", "PinholeCamera", "beam_spot"]
