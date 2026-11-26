"""Noise on the twin's outputs, to be closer to real devices (#82)

Facility and control system independent. A :class:`Noise` adds a sample of a
random variable to a measured value: zero mean, standard deviation ``sigma``
(Gaussian by default, :meth:`Noise.random_variable`), in the units of the
values it is applied to. Off by default: the outputs are then the model's.

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
class Noise:
    """``sigma``: standard deviation, in the units of the values; ``enabled``:
    applied or not. The samples come from the twin's one generator
    (:mod:`dt4acc.core.bl.random_numbers`); ``rng``: a generator of its own,
    the exception (e.g. a test)"""
    sigma: float = 0.0
    enabled: bool = False
    rng: Optional[np.random.Generator] = field(default=None, repr=False)

    def __post_init__(self):
        self.set_sigma(self.sigma)

    def set_sigma(self, value: float) -> None:
        """ValueError unless finite and >= 0"""
        value = float(value)
        if not (math.isfinite(value) and value >= 0.0):
            raise ValueError(f"noise: sigma expected finite and >= 0, got {value}")
        self.sigma = value

    @property
    def active(self) -> bool:
        return self.enabled and self.sigma > 0.0

    def random_variable(self):
        """the noise's distribution (a frozen ``scipy.stats`` random variable)"""
        return stats.norm(loc=0.0, scale=self.sigma)

    def apply(self, values):
        """``values`` with a sample of the noise added to each; a float for a
        float, an array otherwise. Unchanged (as an array) when not active."""
        arr = np.asarray(values, dtype=float)
        if not self.active:
            return float(arr) if arr.ndim == 0 else arr
        noisy = arr + random_numbers.sample(self.random_variable(), arr.shape, rng=self.rng)
        return float(noisy) if arr.ndim == 0 else noisy


@dataclass
class BpmNoise:
    """Noise of the beam position monitors' readings [mm]: slow acquisition
    (closed orbit, a line's trajectory) and turn by turn

    The default levels are placeholders, not a BPM system's resolution.
    """
    sa: Noise = field(default_factory=lambda: Noise(sigma=1e-3))
    tbt: Noise = field(default_factory=lambda: Noise(sigma=1e-2))


__all__ = ["BpmNoise", "Noise"]
