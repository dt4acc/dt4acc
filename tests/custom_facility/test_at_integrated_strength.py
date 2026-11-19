"""Conversion factors between lattice coefficients and integrated strengths"""

import at
import pytest

from dt4acc.custom_facility.model.at_integrated_strength import (
    effective_length,
    is_strength_property,
    lattice_element,
    strength_factor,
    strength_factors,
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
            at.Dipole("BEND", 1.5, 0.1, 0.2),  # combined function main dipole
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
        ("BEND", "main_strength", 1.0),  # bending field, no coefficient
        ("BEND", "B1", -1.5),  # first order equivalent kick
        ("BEND", "A1", 1.5),
        ("BEND", "B2", 1.5),  # its gradient: coefficient * L
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


def test_strength_factors_table(acc):
    """Same lookup as strength_factor (UUID, then the first FamName); the
    factors of 1 and the elements not in the lattice left out"""
    from dt4acc_lib.model.utils.identifiers import LatticeElementPropertyID

    ids = [
        LatticeElementPropertyID(element_name=name, property=prop)
        for name, prop in (
            ("Q_uuid", "main_strength"),
            ("Q", "main_strength"),  # FamName: the first Q, 0.4 m
            ("COR", "B1"),
            ("COR", "A1"),  # factor 1
            ("BEND", "main_strength"),  # factor 1
            ("S", "frequency"),  # no strength
            ("missing", "B2"),  # not in the lattice
        )
    ]
    assert strength_factors(acc, ids) == {
        ("Q_uuid", "main_strength"): pytest.approx(0.4),
        ("Q", "main_strength"): pytest.approx(0.4),
        ("COR", "B1"): -1.0,
    }


def test_beth_order_of_prefixes():
    """C_n = B_n + i A_n"""
    from dt4acc.custom_facility.model import at_integrated_strength

    assert at_integrated_strength._MULTIPOLE_PREFIXES == ("B", "A")
