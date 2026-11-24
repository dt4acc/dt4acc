"""Beam energy and magnetic rigidity"""
import math

from scipy.constants import c, electron_mass, electron_volt

#: [eV]
ELECTRON_REST_ENERGY = electron_mass * c ** 2 / electron_volt


def energy_to_brho(energy: float, rest_energy: float = ELECTRON_REST_ENERGY) -> float:
    """Magnetic rigidity [T m] of a particle of charge e

    ``brho = sqrt(energy**2 - rest_energy**2) / c``, as pyAT's ``Lattice.BRho``.

    Args:
        energy: total energy [eV], the rest energy included, as pyAT's
            ``Lattice.energy``. dt4acc_lib's ``calculate_brho`` takes the
            kinetic energy instead.
        rest_energy: [eV], the electron's by default
    """
    if energy < rest_energy:
        raise ValueError(f"total energy {energy} eV below the rest energy {rest_energy} eV")
    return math.sqrt(energy ** 2 - rest_energy ** 2) / c


__all__ = ["ELECTRON_REST_ENERGY", "energy_to_brho"]
