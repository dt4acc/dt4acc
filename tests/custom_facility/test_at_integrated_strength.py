"""Conversion factors between lattice coefficients and integrated strengths"""

import at
import pytest

import numpy as np
from dt4acc_lib.pyat_simulator.proxies.proxy_factory import create_at_properties_lut_per_element_cls

from dt4acc.custom_facility.model.at_integrated_strength import (
    HORIZONTAL_KICK_SIGN,
    element_factor,
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


_X, _Y = 1e-3, 0.5e-3


def _kick(elem):
    """(dpx, dpy) of a particle at (_X, _Y) through ``elem``, tracked by AT"""
    r_in = np.zeros((6, 1))
    r_in[0, 0], r_in[2, 0] = _X, _Y
    r_out = at.lattice_track(at.Lattice([elem], energy=1e9), r_in.copy(), 1)[0]
    return float(r_out[1].flat[0]), float(r_out[3].flat[0])


@pytest.mark.parametrize("thick", [False, True], ids=["thin", "thick"])
@pytest.mark.parametrize("skew", [False, True], ids=["normal", "skew"])
@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_published_value_is_beth_coefficient_times_length(n, skew, thick):
    """Cross-check against AT's tracking, order by order (Beth's
    representation, European indexing): with C_n L = B_n L + i A_n L the
    integrated coefficient the published values stand for,

        dpx - i dpy = -C_n L (x + i y)^(n - 1)

    (B1: the published value is the kick angle, -PolynomB[0] * L)"""
    coefficient = 0.37
    poly = [0.0] * n
    poly[n - 1] = coefficient
    zeros = [0.0] * n
    poly_a, poly_b = (poly, zeros) if skew else (zeros, poly)
    length = 1e-4
    elem = (at.Multipole("M", length, poly_a, poly_b) if thick
            else at.ThinMultipole("M", poly_a, poly_b))
    prop = f"{'A' if skew else 'B'}{n}"

    published = coefficient * element_factor(elem, prop)
    assert published == pytest.approx(
        coefficient * (length if thick else 1.0) * (HORIZONTAL_KICK_SIGN if prop == "B1" else 1.0)
    )
    integrated = published * (HORIZONTAL_KICK_SIGN if prop == "B1" else 1.0)
    c_n = 1j * integrated if skew else integrated
    expected = -c_n * complex(_X, _Y) ** (n - 1)

    dpx, dpy = _kick(elem)
    rel = 1e-3 if thick else 1e-9
    assert dpx == pytest.approx(expected.real, rel=rel, abs=1e-18)
    assert -dpy == pytest.approx(expected.imag, rel=rel, abs=1e-18)
    if prop == "B1":
        assert dpx == pytest.approx(published, rel=rel)  # the kick angle
    if prop == "A1":
        assert dpy == pytest.approx(published, rel=rel)


@pytest.mark.parametrize(
    "elem, beth",
    [
        (at.Quadrupole("Q", 0.4, 1.2), "B2"),
        (at.Sextupole("S", 0.1, 2.5), "B3"),
        (at.Octupole("O", 0.1, [0.0] * 4, [0.0, 0.0, 0.0, 30.0]), "B4"),
    ],
    ids=["quadrupole", "sextupole", "octupole"],
)
def test_main_strength_is_beth_coefficient(elem, beth):
    """dt4acc_lib's main_strength of a quadrupole / sextupole / octupole is
    its B2 / B3 / B4 (PolynomB[1] / [2] / [3]): same factor L"""
    props = create_at_properties_lut_per_element_cls()[type(elem).__name__]
    n = int(beth[1:])
    assert props["main_strength"].peek(elem) == props[beth].peek(elem) == elem.PolynomB[n - 1]
    assert element_factor(elem, "main_strength") == element_factor(elem, beth) == pytest.approx(elem.Length)
