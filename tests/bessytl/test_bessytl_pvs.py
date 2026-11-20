"""The BESSY II transfer line twin's PVs: exactly its PV list

The twin's own set up (``assemble``, ``initialise_pvs``) with a recording
builder: devices under their machine names, the model under ``TL:``, the same
names as in the injection twin (``tests/bessyii_injection/test_injection_pvs.py``).
"""
import asyncio
from importlib import resources
from pathlib import Path

import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

pytest.importorskip("lat2db.tools.pyat.bessy2_TL_reflat")

from dt4acc.config.data.querries import configure_data_file  # noqa: E402
from dt4acc.custom_facility.bessytl.run_bessytl_twin import assemble, initialise_pvs  # noqa: E402
from dt4acc.custom_facility.bessytl.twin_setup import ACCELERATOR_SETUP  # noqa: E402

from tests import pv_list_md  # noqa: E402
from tests.recording_builder import RecordingBuilder  # noqa: E402

PREFIX = "TEST"
PV_LIST = Path(resources.files("dt4acc").joinpath("custom_facility", "bessytl", "pv_list.md"))
PLACEHOLDERS = {"Power supplies": "supply", "Magnets (twin only)": "magnet"}


def expected():
    """soft IOC PVs of the list (the PVA only ones are the twin's own server's)"""
    fields, named, _ = pv_list_md.read(PV_LIST)
    out = set(named)
    for group, devices in pv_list_md.group_devices(PV_LIST).items():
        section, title = group.split(" / ")
        placeholder = PLACEHOLDERS.get(section)
        if section == "Monitors":
            placeholder = "screen" if title.startswith("FOM") else "bpm"
        assert placeholder, group
        out |= {f"{d}:{f}" for d in devices for f in fields[placeholder]}
    return out


@pytest.fixture(scope="module")
def pvs():
    configure_data_file(resources.files("dt4acc").joinpath(*ACCELERATOR_SETUP))
    twin = assemble(PREFIX, orbit_server=False)
    builder = RecordingBuilder()
    asyncio.run(initialise_pvs(builder, PREFIX, twin))
    return set(builder.names(PREFIX))


def test_pvs_are_exactly_the_list(pvs):
    want = expected()
    assert not pvs - want, f"not in pv_list.md: {sorted(pvs - want)[:10]}"
    assert not want - pvs, f"in pv_list.md, not served: {sorted(want - pvs)[:10]}"


def test_model_under_tl_devices_by_machine_name(pvs):
    """as in the injection twin, where the ring serves beam:*, ORBITCC:*"""
    assert {"TL:beam:orbit:x", "TL:beam:twiss:x:beta", "TL:survey:s", "TL:beam:emittance:x"} <= pvs
    assert not {pv for pv in pvs if pv.startswith(("beam:", "survey:"))}, "the model only under TL:"
    assert {"Q1PT:set", "BPMZ1T:signal:sa:X", "FOMZ1T:image", "FOMZ1T:sigma:x"} <= pvs
