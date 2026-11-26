"""The twin's random numbers: one generator, seeded once

Every calculation of the twin that needs random numbers (e.g. the noise on
the outputs, :mod:`dt4acc.core.bl.noise`) draws from the one generator of
:func:`generator`, so that a seed makes a run reproducible as a whole. It is
made at its first use and seeded once: with ``DT4ACC_SEED`` if set, else
from the operating system (not reproducible). :func:`seed` sets it
explicitly, before its first use; seeding it again is an error. A generator
of its own is the exception (e.g. a test).

Draws are serialised (:func:`sample`): the twin draws from several threads
(IOC callbacks, the calculation's loop, Tango events) and numpy's generators
are not thread safe.

Todo: the Tango twins run one process per device server; each has its own
generator. With ``DT4ACC_SEED`` they would all draw the same numbers: give
each process its own stream (``numpy.random.SeedSequence.spawn``) before
seeding the Tango twins.
"""
import os
import threading
from typing import Optional, Sequence

import numpy as np

#: environment variable: the seed of the twin's random numbers
SEED_ENV = "DT4ACC_SEED"

_lock = threading.Lock()
_generator: Optional[np.random.Generator] = None


def seed(value: Optional[int]) -> None:
    """Seed the twin's generator: once, before anything draws from it
    (``None``: from the operating system). RuntimeError if it exists already."""
    global _generator
    with _lock:
        if _generator is not None:
            raise RuntimeError("the twin's random numbers are seeded once, and they are already in use")
        _generator = np.random.default_rng(value)


def generator() -> np.random.Generator:
    """The twin's generator, made and seeded (``DT4ACC_SEED``) at its first use"""
    global _generator
    with _lock:
        if _generator is None:
            configured = os.environ.get(SEED_ENV)
            _generator = np.random.default_rng(int(configured) if configured else None)
        return _generator


def sample(random_variable, shape, rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """``shape`` samples of a frozen ``scipy.stats`` random variable, from the
    twin's generator (or ``rng``, the exception)"""
    if rng is not None:
        return random_variable.rvs(size=shape, random_state=rng)
    gen = generator()
    with _lock:
        return random_variable.rvs(size=shape, random_state=gen)


__all__: Sequence[str] = ["SEED_ENV", "generator", "sample", "seed"]
