"""Magnetic rigidity from the beam energy (dt4acc.core.utils.energy)"""
import at
import pytest
from scipy.constants import c

from dt4acc.core.utils.energy import ELECTRON_REST_ENERGY, DomainError, brho_to_energy, energy_to_brho
from dt4acc_lib.bl.unit_conversion import calculate_brho


@pytest.mark.parametrize("energy", [10e6, 629e6, 1.7185e9, 3e9])
def test_as_pyat(energy):
    lattice = at.Lattice([at.Drift("D", 1.0)], energy=energy, periodicity=1, particle="electron")
    assert energy_to_brho(energy) == pytest.approx(lattice.BRho, rel=1e-9)


def test_total_not_kinetic_energy():
    """dt4acc_lib's calculate_brho takes the kinetic energy"""
    energy = 1.7185e9
    assert energy_to_brho(energy) == pytest.approx(5.732299, abs=1e-6)
    assert calculate_brho(energy - ELECTRON_REST_ENERGY, ELECTRON_REST_ENERGY) == pytest.approx(
        energy_to_brho(energy), rel=1e-12
    )
    assert calculate_brho(energy) / energy_to_brho(energy) - 1 == pytest.approx(3e-4, rel=0.02)


def test_at_rest_and_below():
    assert energy_to_brho(ELECTRON_REST_ENERGY) == 0.0
    with pytest.raises(DomainError, match="rest energy"):
        energy_to_brho(0.5 * ELECTRON_REST_ENERGY)
    # still a ValueError for callers that catch that
    with pytest.raises(ValueError):
        energy_to_brho(0.5 * ELECTRON_REST_ENERGY)


def test_other_particle():
    proton = 938.272e6
    assert energy_to_brho(2e9, proton) == pytest.approx((2e9 ** 2 - proton ** 2) ** 0.5 / c, rel=1e-12)


@pytest.mark.parametrize("energy", [ELECTRON_REST_ENERGY, 10e6, 629e6, 1.7185e9, 3e9])
def test_brho_to_energy_inverts(energy):
    assert brho_to_energy(energy_to_brho(energy)) == pytest.approx(energy, rel=1e-12)


def test_brho_to_energy_other_particle_and_domain():
    proton = 938.272e6
    assert brho_to_energy(energy_to_brho(2e9, proton), proton) == pytest.approx(2e9, rel=1e-12)
    assert brho_to_energy(0.0) == ELECTRON_REST_ENERGY
    with pytest.raises(DomainError, match="below 0"):
        brho_to_energy(-1.0)
