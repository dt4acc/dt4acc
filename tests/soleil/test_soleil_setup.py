"""
test_soleil_setup.py
====================
SOLEIL II twin, offline: the device database, the liaison manager and the
lattice agree (no twin needed).

    pytest tests/soleil -m "not integration"
"""

import collections

import pytest

from .conftest import HARMONIC_CAVITY, MAIN_CAVITY, setup_entries

# what each device type drives, per the liaison manager
EXPECTED_PROPERTIES = {
    "Quadrupole": ["main_strength"],
    "Sextupole": ["main_strength"],
    "Bend": ["main_strength"],
    "Octupole": ["B4"],
    "QuadrupoleCorrector": ["B2"],       # CQLN: normal quadrupole on an octupole
    "SkewQuadrupoleCorrector": ["A2"],   # CQLT: skew quadrupole on an octupole
    "RFCavity": ["frequency", "voltage"],
}


@pytest.fixture(scope="module")
def entries(soleil_files):
    return setup_entries()


@pytest.fixture(scope="module")
def lattice_properties(soleil_files):
    from dt4acc.custom_tango.ioc.mexec_server_for_physics_engine import lattice_properties_for_device

    return lattice_properties_for_device


def test_device_database_counts(entries):
    counts = collections.Counter(e["type"] for e in entries)
    assert counts == {
        "BPM": 199, "Sextupole": 412, "Steerer": 398, "Octupole": 160, "QuadrupoleCorrector": 160,
        "SkewQuadrupoleCorrector": 134, "Quadrupole": 374, "Bend": 311, "RFCavity": 2,
    }


def test_device_names_unique(entries):
    names = [e["name"] for e in entries]
    assert len(names) == len(set(names))


def test_every_device_type_drives_its_property(entries, lattice_properties):
    wrong = {}
    for e in entries:
        expected = EXPECTED_PROPERTIES.get(e["type"])
        if expected is not None and sorted(lattice_properties(e["name"])) != sorted(expected):
            wrong[e["name"]] = lattice_properties(e["name"])
    assert wrong == {}


def test_steerer_plane_from_liaison_matches_its_name(entries, lattice_properties):
    """A horizontal steerer drives B1, a vertical one A1 -- per the liaison
    manager, and the same as SOLEIL's name convention says."""
    from dt4acc.custom_facility.soleil.corrector_direction import corrector_direction

    plane = {"B1": "horizontal", "A1": "vertical"}
    mismatch, counts = {}, collections.Counter()
    for e in (x for x in entries if x["type"] == "Steerer"):
        props = lattice_properties(e["name"])
        assert len(props) == 1 and props[0] in plane, (e["name"], props)
        counts[plane[props[0]]] += 1
        by_name = corrector_direction(e["name"], e.get("FamName", ""))
        if by_name != plane[props[0]]:
            mismatch[e["name"]] = (props[0], by_name)
    assert mismatch == {}
    assert counts == {"horizontal": 199, "vertical": 199}


def test_every_device_element_is_in_the_lattice(entries, soleil_ring):
    uuids = {getattr(e, "UUID", None) for e in soleil_ring}
    missing = [e["name"] for e in entries if e.get("uuid") not in uuids]
    assert missing == []


def test_bpms_are_monitor_elements(entries, soleil_ring):
    by_uuid = {getattr(e, "UUID", None): e for e in soleil_ring}
    bpms = [e for e in entries if e["type"] == "BPM"]
    assert len(bpms) == 199
    assert {type(by_uuid[b["uuid"]]).__name__ for b in bpms} == {"Monitor"}


def test_lattice_is_6d_with_both_cavities(entries, soleil_ring):
    by_uuid = {getattr(e, "UUID", None): e for e in soleil_ring}
    cavities = {e["name"]: by_uuid[e["uuid"]] for e in entries if e["type"] == "RFCavity"}
    assert set(cavities) == {MAIN_CAVITY, HARMONIC_CAVITY}
    assert soleil_ring.is_6d
    assert soleil_ring.harmonic_number == 416
    main = cavities[MAIN_CAVITY]
    assert main.Frequency == pytest.approx(352_314_167.2312, rel=1e-9)
    assert main.Voltage > 0
