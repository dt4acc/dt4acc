"""Beam energy and magnetic rigidity"""
import math

from scipy.constants import c, electron_mass, electron_volt

#: [eV]
ELECTRON_REST_ENERGY = electron_mass * c ** 2 / electron_volt


class DomainError(ValueError):
    """A value outside the domain of the physics, e.g. a total energy below the rest energy"""


def energy_to_brho(energy: float, rest_energy: float = ELECTRON_REST_ENERGY) -> float:
    """Magnetic rigidity [T m] of a particle of charge e

    ``brho = sqrt(energy**2 - rest_energy**2) / c``, as pyAT's ``Lattice.BRho``.

    Args:
        energy: total energy [eV], the rest energy included, as pyAT's
            ``Lattice.energy``. dt4acc_lib's ``calculate_brho`` takes the
            kinetic energy instead.
        rest_energy: [eV], the electron's by default

    Raises:
        DomainError: ``energy`` below ``rest_energy``
    """
    if energy < rest_energy:
        raise DomainError(f"total energy {energy} eV below the rest energy {rest_energy} eV")
    return math.sqrt(energy ** 2 - rest_energy ** 2) / c


def brho_to_energy(brho: float, rest_energy: float = ELECTRON_REST_ENERGY) -> float:
    """Total energy [eV] of a particle of charge e with magnetic rigidity ``brho`` [T m]

    The inverse of :func:`energy_to_brho`: ``energy = sqrt((brho * c)**2 + rest_energy**2)``.

    Raises:
        DomainError: ``brho`` negative
    """
    if brho < 0.0:
        raise DomainError(f"magnetic rigidity {brho} T m below 0")
    return math.hypot(brho * c, rest_energy)


__all__ = ["DomainError", "ELECTRON_REST_ENERGY", "brho_to_energy", "energy_to_brho"]
