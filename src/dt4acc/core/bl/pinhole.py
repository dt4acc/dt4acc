"""Pinhole cameras of a storage ring twin, independent of the control system

A pinhole camera images the synchrotron light of the beam at a source point,
usually inside a dipole. The twin computes there

* the beam centre: the closed orbit,
* the beam size: ``sigma^2 = emittance * beta + (dispersion * energy spread)^2``
  in each plane, from the optics and a set emittance and energy spread
  (planes not coupled),
* an idealised image: a Gaussian spot (:mod:`dt4acc.core.bl.beam_spot`), in
  the coordinates of the beam at the source point: the camera's magnification
  and resolution are not modelled.

The twin has optics at the elements' entrances. They are propagated to the
source point through the element's first part; the lattice is not split.

Todo:
  * the image's blur (pinhole diffraction, camera resolution), noise (#82)
  * coupling: a tilted spot, the vertical emittance from it
"""
import math
from dataclasses import dataclass
from typing import Dict, List, Sequence

import at
import numpy as np

from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

from .beam_spot import CameraGeometry

PLANES = ("x", "y")
#: steps of the central differences of the transfer map: x, px, y, py, delta
_STEPS = (1e-6, 1e-6, 1e-6, 1e-6, 1e-6)


@dataclass(frozen=True)
class PinholeCamera:
    """``name``: the device, ``element``: lattice element its light comes from,
    ``offset``: of the source point from the element's entrance [m]"""
    name: str
    element: str
    offset: float
    geometry: CameraGeometry = CameraGeometry()


@dataclass(frozen=True)
class BeamSpot:
    """beam centre and size at the source point [m]; NaN without a closed orbit"""
    x: float
    y: float
    sigma_x: float
    sigma_y: float


NO_BEAM = BeamSpot(math.nan, math.nan, math.nan, math.nan)


def _first_part(element, length: float):
    """the element up to ``length`` from its entrance (entrance edge included)"""
    if not 0.0 <= length <= element.Length:
        raise ValueError(f"{element.FamName}: source point at {length} m, length {element.Length} m")
    if length == element.Length:
        return element.deepcopy()
    part = element.divide([length / element.Length, 1.0 - length / element.Length])[0]
    return part


def _map_to(element, length: float, orbit: np.ndarray, energy: float):
    """(orbit, d(x, px, y, py) / d(x, px, y, py, delta)) at ``length`` into the element"""
    if length == 0.0:
        return orbit.copy(), np.eye(4, 5)
    r_in = np.repeat(orbit[:, np.newaxis], 1 + 2 * len(_STEPS), axis=1)
    for k, step in enumerate(_STEPS):
        r_in[k, 1 + 2 * k] += step
        r_in[k, 2 + 2 * k] -= step
    line = at.Lattice([_first_part(element, length)], energy=energy, periodicity=1)
    out = line.track(np.asfortranarray(r_in), nturns=1, refpts=[1], use_mp=False)[0][:, :, 0, 0]
    jac = np.array([(out[:4, 1 + 2 * k] - out[:4, 2 + 2 * k]) / (2 * step) for k, step in enumerate(_STEPS)]).T
    return out[:, 0], jac


class RingPinholes:
    """The ``cameras``' beam spots for a set ``emittance`` (per plane [m rad]) and ``energy_spread``"""

    def __init__(self, backend: SimulatorBackend, cameras: Sequence[PinholeCamera],
                 emittance: Dict[str, float], energy_spread: float):
        assert backend.acc.is_ring
        self.backend = backend
        self.cameras: List[PinholeCamera] = list(cameras)
        for plane in PLANES:
            self._check(emittance[plane])
        self._check(energy_spread)
        self.emittance = {plane: float(emittance[plane]) for plane in PLANES}
        self._energy_spread = float(energy_spread)
        for camera in self.cameras:
            element = self._element(camera.element)[1]
            if not 0.0 <= camera.offset <= element.Length:
                raise ValueError(f"{camera.name}: source point outside {camera.element}")

    @staticmethod
    def _check(value: float) -> None:
        if not (math.isfinite(value) and value >= 0.0):
            raise ValueError(f"expected a finite value >= 0, got {value}")

    def set_emittance(self, plane: str, value: float) -> None:
        self._check(value)
        self.emittance[plane] = float(value)

    @property
    def energy_spread(self) -> float:
        return self._energy_spread

    @energy_spread.setter
    def energy_spread(self, value: float) -> None:
        self._check(value)
        self._energy_spread = float(value)

    def _element(self, name: str):
        """(index, element): by lattice element id (UUID, else its name)"""
        found = [(i, e) for i, e in enumerate(self.backend.acc.acc) if getattr(e, "UUID", e.FamName) == name]
        if len(found) != 1:
            raise ValueError(f"pinhole camera: {len(found)} lattice elements {name!r}, expected one")
        return found[0]

    def compute(self) -> Dict[str, BeamSpot]:
        """{camera name: spot} of the current closed orbit and optics"""
        _, __, optics = self.backend.get_optics()
        if optics is None:
            return {camera.name: NO_BEAM for camera in self.cameras}
        _, __, elem_data = optics
        return {camera.name: self._spot(camera, elem_data) for camera in self.cameras}

    def _spot(self, camera: PinholeCamera, elem_data) -> BeamSpot:
        index, element = self._element(camera.element)
        entrance = elem_data[index]
        orbit, m = _map_to(
            element, camera.offset, np.array(entrance["closed_orbit"], dtype=float), self.backend.acc.acc.energy
        )
        # the dispersion (x, px, y, py per delta) moves with the map
        dispersion = m[:, :4] @ np.asarray(entrance["dispersion"], dtype=float) + m[:, 4]
        sigma = {}
        for k, plane in enumerate(PLANES):
            i = 2 * k
            beta, alpha = entrance["beta"][k], entrance["alpha"][k]
            gamma = (1.0 + alpha ** 2) / beta
            m11, m12 = m[i, i], m[i, i + 1]
            beta_source = m11 ** 2 * beta - 2 * m11 * m12 * alpha + m12 ** 2 * gamma
            sigma[plane] = math.sqrt(
                self.emittance[plane] * beta_source + (dispersion[i] * self.energy_spread) ** 2
            )
        return BeamSpot(x=float(orbit[0]), y=float(orbit[2]), sigma_x=sigma["x"], sigma_y=sigma["y"])


__all__ = ["BeamSpot", "NO_BEAM", "PLANES", "PinholeCamera", "RingPinholes"]
