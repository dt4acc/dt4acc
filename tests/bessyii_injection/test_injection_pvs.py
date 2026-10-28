"""The BESSY II injection twin's PVs: ring, transfer line and hand over

The twin's own set up (``assemble``, ``initialise_pvs``) with a recording
builder: the storage ring serves exactly its PVs as the ring twin
(``bessyii/pv_list.md``), the transfer line its supplies, magnets and monitors
up to the septum exit under machine names (``bessytl/pv_list.md``) and its
model PVs under ``TL:``, the hand over its PVs (``bessyii_injection/pv_list.md``).
Every magnet of ring and line has ``Cm:set``, ``Cm:rdbk``, ``im:I``,
``x:set`` and ``y:set``.
"""
import asyncio
import json
from importlib import resources
from pathlib import Path

import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.custom_facility.bessyii.run_bessyii_twin import ACCELERATOR_SETUP as RING_SETUP
from dt4acc.custom_facility.bessyii_injection.run_bessyii_injection_twin import assemble, initialise_pvs
from dt4acc.custom_facility.bessytl.twin_setup import ACCELERATOR_SETUP as LINE_SETUP

from tests import pv_list_md
from tests.bessyii.test_ring_pvs import MAGNET_FIELDS, SUPPLY_FIELDS, expected_from_pv_list
from tests.recording_builder import RecordingBuilder

PREFIX = "TEST"


def pv_list(facility: str) -> Path:
    return Path(resources.files("dt4acc").joinpath("custom_facility", facility, "pv_list.md"))


def database(path):
    with open(resources.files("dt4acc").joinpath(*path)) as fp:
        return json.load(fp)


@pytest.fixture(scope="module")
def twin_and_pvs():
    twin = assemble(PREFIX, orbit_servers=False)
    builder = RecordingBuilder()
    asyncio.run(initialise_pvs(builder, PREFIX, twin))
    return twin, set(builder.names(PREFIX))


def line_device_pvs(monitors):
    """the transfer line twin's device PVs, monitors limited to those of the injection twin's line"""
    path = pv_list("bessytl")
    fields, _, _ = pv_list_md.read(path)
    out = set()
    for group, devices in pv_list_md.group_devices(path).items():
        section = group.split(" / ")[0]
        placeholder = {"Power supplies": "supply", "Monitors": "monitor"}.get(section)
        if section.startswith("Magnets"):
            placeholder = "magnet"
        if placeholder == "monitor":
            devices = [d for d in devices if d in monitors]
        if placeholder:
            out |= {f"{d}:{f}" for d in devices for f in fields[placeholder]}
    return out


def line_model_pvs():
    """the transfer line twin's soft IOC model PVs, under TL:"""
    _, named, _ = pv_list_md.read(pv_list("bessytl"))
    return {f"TL:{pv}" for pv in named}


def handover_pvs():
    path = pv_list("bessyii_injection")
    fields, named, _ = pv_list_md.read(path)
    (bpms,) = [d for g, d in pv_list_md.group_devices(path).items() if g.startswith("Hand over / Ring BPMs")]
    return named | {f"{b}:{f}" for b in bpms for f in fields["bpm"]}


def test_ring_pvs_as_the_ring_twin(twin_and_pvs):
    _, pvs = twin_and_pvs
    expected = expected_from_pv_list(pv_list("bessyii"))
    assert not expected - pvs, f"ring PVs not served: {sorted(expected - pvs)[:10]}"


def test_every_magnet_has_its_pvs(twin_and_pvs):
    _, pvs = twin_and_pvs
    missing = []
    for path in (RING_SETUP, LINE_SETUP):
        db = database(path)
        missing += [f"{e['name']}:{f}" for e in db if e.get("pc") for f in sorted(MAGNET_FIELDS)
                    if f"{e['name']}:{f}" not in pvs]
        missing += [f"{pc}:{f}" for pc in sorted({e["pc"] for e in db if e.get("pc")}) for f in sorted(SUPPLY_FIELDS)
                    if f"{pc}:{f}" not in pvs]
    assert not missing, f"{len(missing)} missing, e.g. {missing[:5]}"


def test_line_devices_and_model(twin_and_pvs):
    twin, pvs = twin_and_pvs
    for part, expected in (("devices", line_device_pvs(twin.line_monitors)), ("model", line_model_pvs())):
        assert not expected - pvs, f"transfer line {part} not served: {sorted(expected - pvs)[:10]}"


def test_pvs_are_exactly_the_parts(twin_and_pvs):
    twin, pvs = twin_and_pvs
    ring = expected_from_pv_list(pv_list("bessyii"))
    line_dev = line_device_pvs(twin.line_monitors)
    line_model = line_model_pvs()
    handover = handover_pvs()
    assert not ring & line_dev, f"transfer line PVs with a ring name: {sorted(ring & line_dev)[:5]}"
    expected = ring | line_dev | line_model | handover
    assert not pvs - expected, f"not in the PV lists: {sorted(pvs - expected)[:10]}"
    assert not expected - pvs, f"in the PV lists, not served: {sorted(expected - pvs)[:10]}"
