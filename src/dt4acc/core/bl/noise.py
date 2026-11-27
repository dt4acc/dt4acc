"""Noise on the twin's outputs, to be closer to real devices (#82)

Facility and control system independent. A :class:`GaussianAdditiveNoise`
adds a sample of a Gaussian random variable to a measured value: zero mean,
standard deviation ``sigma``, in the units of the values it is applied to (SI
units in the twin: m for positions; other units only for display, e.g. the
PVs in mm). Off by default: the outputs are then the model's. Other kinds of
noise can be added later as classes of their own.

Applied to what a device measures (e.g. a beam position monitor's reading),
never to the model itself (the closed orbit, the optics). NaN (no beam) stays
NaN.

Todo:
  * the pinhole camera and the beam current (#82)
  * noise that depends on the beam current (a BPM's resolution gets worse
    with less current, #33, #78)
  * a reading refreshed with new noise while the model does not change, as a
    real device at its acquisition rate
"""
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy import stats

from . import random_numbers


@dataclass
class GaussianAdditiveNoise:
    """``sigma``: standard deviation, in the units of the values (``None``: not
    specified, the noise is then never active); ``enabled``: applied or not.

    The samples come from the twin's one generator
    (:mod:`dt4acc.core.bl.random_numbers`), handed to ``scipy.stats`` as its
    ``random_state``; ``rng``: a generator of its own, the exception (e.g. a
    test)"""
    sigma: Optional[float] = None
    enabled: bool = False
    rng: Optional[np.random.Generator] = field(default=None, repr=False)

    def __post_init__(self):
        self.set_sigma(self.sigma)

    def set_sigma(self, value: Optional[float]) -> None:
        """``None`` (not specified), else ValueError unless finite and >= 0"""
        if value is None:
            self.sigma = None
            return
        value = float(value)
        if not (math.isfinite(value) and value >= 0.0):
            raise ValueError(f"noise: sigma expected finite and >= 0, got {value}")
        self.sigma = value

    @property
    def active(self) -> bool:
        return self.enabled and self.sigma is not None and self.sigma > 0.0

    def random_variable(self):
        """the noise's distribution (a frozen ``scipy.stats`` random variable);
        its samples are drawn by :func:`random_numbers.sample`"""
        return stats.norm(loc=0.0, scale=self.sigma)

    def apply(self, values):
        """``values`` with a sample of the noise added to each; a float for a
        float, an array otherwise. Unchanged (as an array) when not active.

        One call draws all samples at once: pass all values of a reading as one
        array rather than one value after the other."""
        arr = np.asarray(values, dtype=float)
        if not self.active:
            return float(arr) if arr.ndim == 0 else arr
        noisy = arr + random_numbers.sample(self.random_variable(), arr.shape, rng=self.rng)
        return float(noisy) if arr.ndim == 0 else noisy


@dataclass
class BpmNoise:
    """Noise of the beam position monitors' readings [m]: slow acquisition
    (closed orbit, a line's trajectory) and turn by turn

    The default levels (1 um, 10 um) are placeholders, not a BPM system's
    resolution.
    """
    sa: GaussianAdditiveNoise = field(default_factory=lambda: GaussianAdditiveNoise(sigma=1e-6))
    tbt: GaussianAdditiveNoise = field(default_factory=lambda: GaussianAdditiveNoise(sigma=1e-5))


__all__ = ["BpmNoise", "GaussianAdditiveNoise"]
