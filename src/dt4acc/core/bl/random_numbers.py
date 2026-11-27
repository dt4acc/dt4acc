"""The twin's random numbers: one generator, seeded once

Every calculation of the twin that needs random numbers (e.g. the noise on
the outputs, :mod:`dt4acc.core.bl.noise`) draws from the one generator of
:func:`generator`. It is made at its first use (the twins make it at startup:
a bad ``DT4ACC_SEED`` stops them there) and seeded once: with ``DT4ACC_SEED``
if set, else from the operating system. :func:`seed` sets it explicitly,
normally before its first use; seeding it again (e.g. asked for by a user)
is allowed, with a warning. A generator of its own is the exception (e.g. a
test).

What a seed reproduces: the sequence of numbers the generator gives. The
twin draws from several tasks (the closed orbit's view, the turn by turn
data, the injection's shots), in an order that depends on timing; when they
interleave differently, a reading gets other numbers of the same sequence.

Draws are serialised (:func:`sample`): the twin draws from several threads
(IOC callbacks, the calculation's loop, Tango events) and numpy's generators
are not thread safe.

Todo: the Tango twins run one process per device server; each has its own
generator. With ``DT4ACC_SEED`` they would all draw the same numbers: give
each process its own stream (``numpy.random.SeedSequence.spawn``) before
seeding the Tango twins.
"""
import logging
import os
import threading
from typing import Optional, Sequence

import numpy as np

logger = logging.getLogger("dt4acc")

#: environment variable: the seed of the twin's random numbers
SEED_ENV = "DT4ACC_SEED"

_lock = threading.Lock()
_generator: Optional[np.random.Generator] = None


def configured_seed() -> Optional[int]:
    """``DT4ACC_SEED`` as an integer, ``None`` if not set; ValueError if it is
    not a non negative integer"""
    configured = os.environ.get(SEED_ENV, "").strip()
    if not configured:
        return None
    try:
        value = int(configured)
    except ValueError:
        raise ValueError(f"{SEED_ENV} expected a non negative integer, got {configured!r}") from None
    if value < 0:
        raise ValueError(f"{SEED_ENV} expected a non negative integer, got {value}")
    return value


def seed(value: Optional[int]) -> None:
    """Seed the twin's generator (``None``: from the operating system).
    Normally once, before anything draws from it; seeding it again starts a
    new sequence and logs a warning."""
    global _generator
    with _lock:
        if _generator is not None:
            logger.warning("the twin's random numbers were seeded already and are in use: seeded again (%s)", value)
        _generator = np.random.default_rng(value)


def generator() -> np.random.Generator:
    """The twin's generator, made and seeded (``DT4ACC_SEED``) at its first use"""
    global _generator
    with _lock:
        if _generator is None:
            _generator = np.random.default_rng(configured_seed())
        return _generator


def sample(random_variable, shape, rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """``shape`` samples of a frozen ``scipy.stats`` random variable, from the
    twin's generator (or ``rng``, the exception)"""
    if rng is not None:
        return random_variable.rvs(size=shape, random_state=rng)
    gen = generator()
    with _lock:
        return random_variable.rvs(size=shape, random_state=gen)


__all__: Sequence[str] = ["SEED_ENV", "configured_seed", "generator", "sample", "seed"]
