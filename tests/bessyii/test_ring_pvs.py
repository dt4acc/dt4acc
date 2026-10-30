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
from dt4acc.custom_facility.bessyii.run_bessyii_twin import ACCELERATOR_SETUP, initialise_pvs
from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc_lib.bl.command_rewritter import CommandRewriter

from tests import pv_list_md
from tests.recording_builder import RecordingBuilder

PREFIX = "TEST"
PV_LIST = Path(resources.files("dt4acc").joinpath("custom_facility", "bessyii", "pv_list.md"))
MAGNET_FIELDS = {"Cm:set", "Cm:rdbk", "im:I", "x:set", "y:set"}
SUPPLY_FIELDS = {"set", "rdbk"}


def ring_controller() -> Controller:
    _, lm, ts, _ = load_managers()
    mexec = TranslatingCommandExecutionEngine(
        backend=provide_backend_encapsulating_lattice(),
        cmd_rewriter=CommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )
    return Controller(name="ring", mexec=mexec, view=View(), default_delayed_reads=[])


@pytest.fixture(scope="module")
def ring_pvs():
    builder = RecordingBuilder()
    builder.SetDeviceName(PREFIX)
    asyncio.run(initialise_pvs(builder=builder, controller=ring_controller()))
    return builder.names(PREFIX)


def expected_from_pv_list(path: Path):
    """The soft IOC PVs the static list describes"""
    fields, named, _ = pv_list_md.read(path)
    expected = set(named)
    for group, devices in pv_list_md.group_devices(path).items():
        placeholder = {"Power supplies": "supply", "Magnets (twin only)": "magnet"}.get(group.split(" / ")[0])
        if placeholder:
            expected |= {f"{d}:{f}" for d in devices for f in fields[placeholder]}
    return expected


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
