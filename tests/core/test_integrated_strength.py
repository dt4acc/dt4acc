"""Conversion factors between lattice coefficients and integrated strengths"""

import at
import pytest

from dt4acc.core.utils.integrated_strength import (
    effective_length,
    is_strength_property,
    lattice_element,
    strength_factor,
)


@pytest.fixture
def acc():
    quad = at.Quadrupole("Q", 0.4, 1.0)
    quad.UUID = "Q_uuid"
    return at.Lattice(
        [
            at.Drift("D", 1.0),
            quad,
            at.Sextupole("S", 0.1, 2.0),
            at.ThinMultipole("COR", [0.0], [0.0]),
            at.Quadrupole("Q", 0.2, 1.0),  # same FamName, not the one acted on
        ],
        energy=1e9,
    )


def test_lookup_uuid_then_famname(acc):
    assert lattice_element(acc, "Q_uuid") is acc[1]
    assert lattice_element(acc, "Q") is acc[1]
    assert lattice_element(acc, "S") is acc[2]
    with pytest.raises(ValueError):
        lattice_element(acc, "nowhere")


def test_effective_length_thick_and_thin(acc):
    assert effective_length(acc[1]) == pytest.approx(0.4)
    assert effective_length(acc[3]) == 1.0


@pytest.mark.parametrize(
    "name, prop, factor",
    [
        ("Q_uuid", "main_strength", 0.4),
        ("S", "main_strength", 0.1),
        ("Q", "B2", 0.4),
        ("COR", "B1", -1.0),  # horizontal kick angle = -PolynomB[0] * L
        ("COR", "A1", 1.0),
        ("S", "frequency", 1.0),  # no strength: untouched
    ],
)
def test_strength_factor(acc, name, prop, factor):
    assert strength_factor(acc, name, prop) == pytest.approx(factor)


@pytest.mark.parametrize(
    "prop, expected",
    [("main_strength", True), ("B1", True), ("A2", True), ("B4", True),
     ("frequency", False), ("voltage", False), ("x", False), ("BPM", False)],
)
def test_is_strength_property(prop, expected):
    assert is_strength_property(prop) is expected
