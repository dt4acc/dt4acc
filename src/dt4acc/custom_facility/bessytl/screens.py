"""What a fluorescent screen (``FOMZ...``) shows: an image of the beam spot

A screen is no beam position monitor: the beam hits a fluorescent plate and a
camera records the light, an image of the beam's transverse distribution. The
twin computes it from

* the beam centre: the trajectory at the screen,
* the beam size: the emittance of the beam and the optics at the screen.

The beam is one bunch with a Gaussian distribution. In each plane its phase
space ellipse is ``gamma x^2 + 2 alpha x x' + beta x'^2 = emittance`` (the
Twiss parameters at the screen). The screen sees its projection on x (and on
y): ``sigma = sqrt(emittance * beta)``. alpha tilts the ellipse in (x, x'),
which a screen does not see. The planes are not coupled, so the spot is an
ellipse with its axes along x and y.

Image: ``height`` rows of ``width`` pixels of ``pixel`` mm, centred on the
screen's axis (the line's reference). Row 0 is the top (+y), column 0 the left
(-x), as a camera image. A pixel holds the fraction of the beam that hits it:
an image sums to 1 when the whole beam is on the screen, less when part of it
misses.

Todo:
  * dispersion: the energy spread adds ``(D * sigma_delta)^2`` to sigma^2;
    the line's optics give no dispersion yet
  * a screen in the beam stops it: the twin's screens are transparent, the
    beam carries on to the next monitors and the ring
"""
import math
from dataclasses import dataclass

import numpy as np
from scipy.special import erf


@dataclass(frozen=True)
class ScreenGeometry:
    """The camera's view of the screen: pixels and their size"""
    width: int = 100
    height: int = 100
    #: [mm]
    pixel: float = 0.2

    def edges(self, n: int) -> np.ndarray:
        """pixel edges [mm] along an axis of ``n`` pixels, centred on 0"""
        return (np.arange(n + 1) - n / 2.0) * self.pixel


#: placeholder: the screens' cameras are not known yet (20 mm x 20 mm)
SCREEN = ScreenGeometry()


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


def screen_image(x: float, y: float, sigma_x: float, sigma_y: float, geometry: ScreenGeometry = SCREEN) -> np.ndarray:
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
