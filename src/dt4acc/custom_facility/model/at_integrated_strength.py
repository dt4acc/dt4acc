"""Integrated magnet strengths in AT's normalisation, as the twins publish them

**Not a general convention**: the one of AT (and Tracy) users, opt-in
(see :func:`enabled`). Kept out of ``dt4acc.core`` until it is checked
against the boundary conditions of the 2D (magneto quasi static) multipole
expansion and the usual conventions of single particle beam dynamics.

Convention, in Beth's representation (European indexing, R_ref = 1):

    B(z) = By + i Bx = sum_{n >= 1} (B_n + i A_n) z^(n - 1),  z = x + i y

* the lattice stores AT's coefficients, normalised by the beam rigidity
  p / q *with the sign of the charge*: PolynomB[n - 1] = B_n / (p / q),
  PolynomA[n - 1] = A_n / (p / q) (dt4acc_lib names them B<n> / A<n>: B1 =
  PolynomB[0], B2 = PolynomB[1], ...). AT integrates as for a positive
  particle: a positive PolynomB[1] focuses horizontally whatever the
  charge, for electrons the field B_n has the opposite sign. This module
  handles no field, it only scales these normalised coefficients.
* a thick element's coefficient is per metre, a thin one (``Length == 0``)
  stores it integrated already.
* published value = coefficient * L, L the element's length, 1 for a thin
  element. AT's coefficients include no n!: unlike MAD-X's ``knl`` this is
  K1 L for a quadrupole, but K2 L / 2 for a sextupole (PolynomB[2] = H =
  K2 / 2) and K3 L / 6 for an octupole.
* dipole terms (B1 = PolynomB[0], A1 = PolynomA[0]): the kick angle in rad,
  -PolynomB[0] * L horizontally (AT kicks px by -PolynomB[0] * L),
  +PolynomA[0] * L vertically.

Main dipoles (``at.Dipole``):

* ``main_strength``: published unchanged. dt4acc_lib reads it as the
  bending field (``MainStrengthForDipole``), no coefficient.
* B1 / A1: published as above, as a first order equivalent kick only: in a
  bend PolynomB[0] adds to the curvature, it also changes the weak
  focusing, the dispersion and the path length. The convention for main
  dipoles is still to be settled.

device value = :func:`strength_factor` * lattice value

The facilities put these factors in their translation service (slope of
the magnets' conversions), see :func:`strength_factors`: the twins convert
in one place, the command execution engine.
"""

import logging
import os

import at

logger = logging.getLogger("dt4acc")

#: sign of a horizontal kick angle relative to PolynomB[0]: AT's integrators
#: kick px by -PolynomB[0] * L and py by +PolynomA[0] * L, so a positive
#: PolynomB[0] deflects the beam towards -x.
HORIZONTAL_KICK_SIGN = -1.0

#: lattice property of the horizontal dipole term (dt4acc_lib's European
#: multipole naming: B1 is PolynomB[0])
_HORIZONTAL_KICK_PROPERTY = "B1"

#: lattice properties holding a multipole coefficient of the element: the
#: magnet's main strength or a European-named multipole (B1 = PolynomB[0],
#: A2 = PolynomA[1], ...)
_MULTIPOLE_PREFIXES = ("B", "A")


def is_strength_property(lattice_property: str) -> bool:
    """Is ``lattice_property`` a multipole coefficient (by its name only:
    see :func:`element_factor` for a main dipole's ``main_strength``)"""
    if lattice_property == "main_strength":
        return True
    return (
        len(lattice_property) >= 2
        and lattice_property[0] in _MULTIPOLE_PREFIXES
        and lattice_property[1:].isdigit()
    )


def lattice_element(acc, name: str):
    """The lattice element the simulator backend acts on for ``name``

    Same lookup as dt4acc_lib's PyATAcceleratorSimulator: the first element
    whose UUID is ``name``, else the first one whose FamName is.
    """
    for attribute in ("UUID", "FamName"):
        for elem in acc:
            if getattr(elem, attribute, None) == name:
                return elem
    raise ValueError(f"No lattice element with UUID or FamName {name!r}")


def effective_length(element) -> float:
    """Length turning the element's coefficient into the published value

    A thin element (zero length) already stores the integrated value: it
    counts as of unit length.
    """
    length = float(getattr(element, "Length", 0.0))
    return length if length > 0.0 else 1.0


def element_factor(element, lattice_property: str) -> float:
    """device value / lattice value for ``lattice_property`` of ``element``

    1 for anything that is no multipole coefficient (frequency, voltage, a
    main dipole's main_strength, ...)
    """
    if not is_strength_property(lattice_property):
        return 1.0
    if lattice_property == "main_strength" and isinstance(element, at.Dipole):
        # the bending field (dt4acc_lib's MainStrengthForDipole), no coefficient
        return 1.0
    factor = effective_length(element)
    if lattice_property == _HORIZONTAL_KICK_PROPERTY:
        factor *= HORIZONTAL_KICK_SIGN
    return factor


def strength_factor(acc, name: str, lattice_property: str) -> float:
    """device value / lattice value for ``lattice_property`` of the element ``name``"""
    if not is_strength_property(lattice_property):
        return 1.0
    return element_factor(lattice_element(acc, name), lattice_property)


#: environment variable a facility sets to "1" for its twin to publish
#: integrated strengths (inherited by the spawned processes); unset, the
#: magnets publish the lattice coefficients
ENABLE_ENV = "DT4ACC_INTEGRATED_STRENGTH"


def enabled() -> bool:
    """Does the twin publish integrated strengths (DT4ACC_INTEGRATED_STRENGTH=1)"""
    return os.environ.get(ENABLE_ENV) == "1"


def strength_factors(acc, lattice_property_ids) -> dict:
    """{(element name, lattice property): factor} of the strength properties

    ``lattice_property_ids``: LatticeElementPropertyIDs (e.g. all the ones of
    a liaison manager); the ones of no strength, or with a factor of 1, are
    left out, as the ones of no element of the lattice (logged): the
    backend can not act on these anyway.
    """
    # same lookup as lattice_element, indexed once: UUIDs first, then FamNames
    by_name = {}
    for attribute in ("FamName", "UUID"):
        for elem in reversed(acc):
            name = getattr(elem, attribute, None)
            if name is not None:
                by_name[name] = elem
    factors = {}
    for lat_p in lattice_property_ids:
        key = (lat_p.element_name, lat_p.property)
        if key in factors or not is_strength_property(lat_p.property):
            continue
        element = by_name.get(lat_p.element_name)
        if element is None:
            logger.warning(
                "integrated strength: no lattice element with UUID or FamName %r,"
                " left as lattice value", lat_p.element_name,
            )
            continue
        factor = element_factor(element, lat_p.property)
        if factor != 1.0:
            factors[key] = factor
    return factors
