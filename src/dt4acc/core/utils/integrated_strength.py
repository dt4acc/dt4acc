"""Integrated magnet strengths, as the twins publish them

The lattice stores multipole coefficients the AT way: a thick element's
``PolynomA``/``PolynomB`` hold K (per metre), a thin one (``Length == 0``)
holds the integrated strength itself. The twins publish integrated
strengths instead, the convention of pyaml (accelerator middle layer):

* quadrupole, sextupole, ...: K * L
* steerer: its kick angle in rad, -PolynomB[0] * L horizontally,
  +PolynomA[0] * L vertically

so a client reads the same value from the twin as from its own model of
the lattice.

device value = :func:`strength_factor` * lattice value

The EPICS twin (custom_facility.generic) puts these factors in its
translation service. The Tango twin's design view bypasses it: its devices
convert with the table :func:`strength_factors` builds, when the facility
enables it (DT4ACC_INTEGRATED_STRENGTH=1, see :func:`enabled`).
"""

import logging
import os

logger = logging.getLogger("dt4acc")

#: sign of a horizontal kick angle relative to PolynomB[0]: AT's integrators
#: kick px by -PolynomB[0] * L and py by +PolynomA[0] * L, so a positive
#: PolynomB[0] deflects the beam towards -x. pyaml's HORIZONTAL_KICK_SIGN.
HORIZONTAL_KICK_SIGN = -1.0

#: lattice properties of the horizontal kick (dt4acc_lib's European
#: multipole naming: B1 is PolynomB[0])
_HORIZONTAL_KICK_PROPERTIES = frozenset({"B1"})

#: lattice properties holding a multipole coefficient of the element: the
#: magnet's main strength or a European-named multipole (B1 = PolynomB[0],
#: A2 = PolynomA[1], ...)
_MULTIPOLE_PREFIXES = ("A", "B")


def is_strength_property(lattice_property: str) -> bool:
    """Is ``lattice_property`` a multipole coefficient (published integrated)"""
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
    """Length turning the element's coefficient into an integrated strength

    A thin element (zero length) already stores the integrated strength:
    it counts as of unit length (as pyaml does).
    """
    length = float(getattr(element, "Length", 0.0))
    return length if length > 0.0 else 1.0


def strength_factor(acc, name: str, lattice_property: str) -> float:
    """device value / lattice value for ``lattice_property`` of ``name``

    1 for anything that is no multipole coefficient (frequency, voltage, ...)
    """
    if not is_strength_property(lattice_property):
        return 1.0
    factor = effective_length(lattice_element(acc, name))
    if lattice_property in _HORIZONTAL_KICK_PROPERTIES:
        factor *= HORIZONTAL_KICK_SIGN
    return factor


#: environment variable a facility sets to "1" for its Tango devices to
#: publish integrated strengths (inherited by the spawned server processes)
ENABLE_ENV = "DT4ACC_INTEGRATED_STRENGTH"


def enabled() -> bool:
    """Do the Tango devices publish integrated strengths (DT4ACC_INTEGRATED_STRENGTH=1)"""
    return os.environ.get(ENABLE_ENV) == "1"


def strength_factors(acc, lattice_property_ids) -> dict:
    """{(element name, lattice property): factor} of the strength properties

    ``lattice_property_ids``: LatticeElementPropertyIDs (e.g. all the ones of
    a liaison manager); the ones of no strength, or with a factor of 1, are
    left out, as the ones of no element of the lattice (logged): the
    backend can not act on these anyway.
    """
    factors = {}
    for lat_p in lattice_property_ids:
        key = (lat_p.element_name, lat_p.property)
        if key in factors or not is_strength_property(lat_p.property):
            continue
        try:
            factor = strength_factor(acc, *key)
        except ValueError as exc:
            logger.warning("integrated strength: %s, left as lattice value", exc)
            continue
        if factor != 1.0:
            factors[key] = factor
    return factors
