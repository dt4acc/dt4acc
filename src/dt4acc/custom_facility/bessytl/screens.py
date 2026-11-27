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
  * a screen that observes is transparent; at the machine it scatters the
    beam a little (the beam size after it grows): not modelled
"""
import numpy as np

from dt4acc.core.bl.beam_spot import CameraGeometry as ScreenGeometry, beam_size, spot_image

#: placeholder: the screens' cameras are not known yet (20 mm x 20 mm)
SCREEN = ScreenGeometry()


def screen_image(x: float, y: float, sigma_x: float, sigma_y: float, geometry: ScreenGeometry = SCREEN) -> np.ndarray:
    """The image of the spot (:func:`dt4acc.core.bl.beam_spot.spot_image`), all [mm]"""
    return spot_image(x, y, sigma_x, sigma_y, geometry)


__all__ = ["SCREEN", "ScreenGeometry", "beam_size", "screen_image"]
