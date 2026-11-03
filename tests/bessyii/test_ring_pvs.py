"""The BESSY II storage ring twin's PVs: its interface to users and scripts

Every supply has ``set`` and ``rdbk``, every magnet it drives ``Cm:set``,
``Cm:rdbk``, ``im:I``, ``x:set`` and ``y:set``; and the twin serves exactly
the PVs of its static list (``custom_facility/bessyii/pv_list.md``), so a
change of the interface has to show up there.
"""
import asyncio
import json
from importlib import resources
from pathlib import Path

import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.core.bl.controller import Controller
from dt4acc.custom_epics.ioc.view import View
from dt4acc.custom_facility.bessyii.liasion_translator_setup import load_managers
from dt4acc.custom_facility.bessyii.provide_lattice import provide_backend_encapsulating_lattice
from dt4acc.custom_facility.bessyii.run_bessyii_twin import (
    ACCELERATOR_SETUP,
    initialise_pvs,
    BPM_PREFIX,
    initialise_turn_by_turn_pvs,
)
from dt4acc.core.bl.turn_by_turn import ring_monitors
from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc_lib.bl.command_rewritter import CommandRewriter

from tests import pv_list_md
from tests.recording_builder import RecordingBuilder

PREFIX = "TEST"
PV_LIST = Path(resources.files("dt4acc").joinpath("custom_facility", "bessyii", "pv_list.md"))
MAGNET_FIELDS = {"Cm:set", "Cm:rdbk", "im:I", "x:set", "y:set"}
SUPPLY_FIELDS = {"set", "rdbk"}
#: every BPM, named as the BPM system (custom_epics/ioc/bpm_pvs)
BPM_FIELDS = {"signal:sa:X", "signal:sa:Y"}
TBT_FIELDS = {"signal:tbt:X", "signal:tbt:Y"}
#: served by the ring twin alone, not by the injection twin
TURN_BY_TURN_SECTION = "Turn by turn (ring twin alone)"


def ring_controller(backend=None) -> Controller:
    _, lm, ts, _ = load_managers()
    mexec = TranslatingCommandExecutionEngine(
        backend=backend or provide_backend_encapsulating_lattice(),
        cmd_rewriter=CommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )
    return Controller(name="ring", mexec=mexec, view=View(), default_delayed_reads=[])


@pytest.fixture(scope="module")
def ring_pvs():
    backend = provide_backend_encapsulating_lattice()
    builder = RecordingBuilder()
    builder.SetDeviceName(PREFIX)
    bpms = ring_monitors(backend, BPM_PREFIX)
    asyncio.run(initialise_pvs(builder=builder, controller=ring_controller(backend), bpms=bpms))
    initialise_turn_by_turn_pvs(builder, backend, bpms)
    return builder.names(PREFIX)


def turn_by_turn_pvs(path: Path):
    """The PVs of the list's turn by turn section (ring twin alone)"""
    rows, section = [], ""
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif section == TURN_BY_TURN_SECTION:
            m = pv_list_md.ROW.match(line)
            if m and not m.group(1).startswith("<"):
                rows.append(m.group(1))
    (bpms,) = [d for g, d in pv_list_md.group_devices(path).items() if g.startswith(TURN_BY_TURN_SECTION)]
    return set(rows) | {f"{b}:{f}" for b in bpms for f in TBT_FIELDS}


def expected_from_pv_list(path: Path, turn_by_turn: bool = True):
    """The soft IOC PVs the static list describes; ``turn_by_turn``: with
    those of the ring twin alone"""
    fields, named, _ = pv_list_md.read(path)
    expected = set(named)
    for group, devices in pv_list_md.group_devices(path).items():
        section = group.split(" / ")[0]
        placeholder = {"Power supplies": "supply", "Magnets (twin only)": "magnet"}.get(section)
        if placeholder:
            expected |= {f"{d}:{f}" for d in devices for f in fields[placeholder]}
        elif section == "BPMs":
            expected |= {f"{d}:{f}" for d in devices for f in BPM_FIELDS}
    tbt = turn_by_turn_pvs(path)
    return expected | tbt if turn_by_turn else expected - tbt


def test_every_magnet_has_its_pvs(ring_pvs):
    with open(resources.files("dt4acc").joinpath(*ACCELERATOR_SETUP)) as fp:
        db = json.load(fp)
    pvs = set(ring_pvs)
    magnets = [e["name"] for e in db if e.get("pc")]
    supplies = {e["pc"] for e in db if e.get("pc")}
    assert len(magnets) == 385 and len(supplies) == 195      # with the 16 skew quadrupoles (CQS)
    missing = [f"{m}:{f}" for m in magnets for f in sorted(MAGNET_FIELDS) if f"{m}:{f}" not in pvs]
    missing += [f"{s}:{f}" for s in sorted(supplies) for f in sorted(SUPPLY_FIELDS) if f"{s}:{f}" not in pvs]
    assert not missing, f"{len(missing)} missing, e.g. {missing[:5]}"


def test_rf_pvs(ring_pvs):
    pvs = set(ring_pvs)
    for pv in ["MCLKHX251C:freq", "lattice_info:ref_freq", "lattice_info:ref_freq:khz:up",
               "lattice_info:ref_freq:khz:frac", "CAVH1T8R:freq", "CAVH4T8R:freq"]:
        assert pv in pvs, pv


def test_pvs_are_those_of_the_pv_list(ring_pvs):
    expected = expected_from_pv_list(PV_LIST)
    created = set(ring_pvs)
    assert not created - expected, f"not in pv_list.md: {sorted(created - expected)[:10]}"
    assert not expected - created, f"in pv_list.md, not served: {sorted(expected - created)[:10]}"


def test_turn_by_turn_pvs(ring_pvs):
    pvs = set(ring_pvs)
    for pv in ["TBT:n_turns", "TBT:offset:x", "TBT:start:x", "TBT:tbt:x", "TBT:tbt:names", "TBT:survived",
               "BPMZ1D1R:signal:tbt:X", "BPMZ7T8R:signal:tbt:Y"]:
        assert pv in pvs, pv
    assert len([pv for pv in pvs if pv.endswith(":signal:tbt:X")]) == 123


def test_bpm_pvs(ring_pvs):
    pvs = set(ring_pvs)
    assert len([pv for pv in pvs if pv.endswith(":signal:sa:X")]) == 123
    assert len([pv for pv in pvs if pv.endswith(":signal:sa:Y")]) == 123
    assert "BPMZ1D1R:signal:sa:X" in pvs
