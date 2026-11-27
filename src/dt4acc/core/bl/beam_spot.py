"""Image of a Gaussian beam spot, as a camera shows it

Facility and control system independent; used by fluorescent screens
(``custom_facility/bessytl/screens.py``) and pinhole cameras
(:mod:`dt4acc.core.bl.pinhole`).

The beam is one bunch with a Gaussian distribution, the planes are not
coupled: the spot is an ellipse with its axes along x and y.

Image: ``height`` rows of ``width`` pixels of ``pixel`` mm, centred on the
camera's axis. Row 0 is the top (+y), column 0 the left (-x). A pixel holds
the fraction of the beam that hits it: an image sums to 1 when the whole beam
is in view, less when part of it misses.
"""
import math
from dataclasses import dataclass

import numpy as np
from scipy.special import erf


@dataclass(frozen=True)
class CameraGeometry:
    """The camera's view: pixels and their size"""
    width: int = 100
    height: int = 100
    #: [mm]
    pixel: float = 0.2

    def edges(self, n: int) -> np.ndarray:
        """pixel edges [mm] along an axis of ``n`` pixels, centred on 0"""
        return (np.arange(n + 1) - n / 2.0) * self.pixel


def beam_size(emittance: float, beta: float) -> float:
    """sigma [m] of a beam of ``emittance`` [m rad] where the optics give ``beta`` [m]"""
    return math.sqrt(emittance * beta)


def _fractions(edges: np.ndarray, centre: float, sigma: float) -> np.ndarray:
    """fraction of a Gaussian (``centre``, ``sigma`` [mm]) in each interval between ``edges``"""
    if sigma > 0.0:
        cdf = 0.5 * (1.0 + erf((edges - centre) / (math.sqrt(2.0) * sigma)))
    else:
        # all of it at the centre
        cdf = (edges > centre).astype(float)
    return np.diff(cdf)


def spot_image(x: float, y: float, sigma_x: float, sigma_y: float, geometry: CameraGeometry) -> np.ndarray:
    """The image of the spot, ``geometry.height`` x ``geometry.width``

    ``x``, ``y``: beam centre, ``sigma_x``, ``sigma_y``: beam size, all [mm].
    No beam (a value is NaN, e.g. the calculation failed): a dark image.
    """
    shape = (geometry.height, geometry.width)
    if not all(math.isfinite(v) for v in (x, y, sigma_x, sigma_y)):
        return np.zeros(shape)
    along_x = _fractions(geometry.edges(geometry.width), x, sigma_x)
    # row 0 at the top: y decreasing along the rows
    along_y = _fractions(geometry.edges(geometry.height), y, sigma_y)[::-1]
    return np.outer(along_y, along_x)


__all__ = ["CameraGeometry", "beam_size", "spot_image"]
