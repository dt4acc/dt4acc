"""The transfer line's BPM structure (ORBITCC:rdBpm): its BPMs and striplines, in
the machine's order, without the screens; the rings' as before (BPMs only)"""
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("p4p")
pytest.importorskip("lat2db.tools.pyat.bessy2_TL_reflat")

from dt4acc.custom_epics.ioc.orbit_pva import OrbitTwinServer  # noqa: E402
from dt4acc.custom_facility.bessytl.twin_setup import (  # noqa: E402
    ORBIT_MONITOR_PREFIXES,
    bessytl_lattice,
    monitor_names,
)

#: as at the machine, along the line
LINE_ORDER = ["BPMZ1T", "SLZ1T", "SLZ2T", "BPMZ2T", "BPMZ3T", "BPMZ4T", "BPMZ5T", "SLZ3T"]


def served(server):
    v = server.pv.current().value
    return list(v.BPM), np.asarray(v.X), np.asarray(v.Y)


def track(names):
    return [SimpleNamespace(fam_name=n, x=k * 1e-6, y=-k * 1e-6) for k, n in enumerate(names)]


def test_line_serves_its_bpms_and_striplines_in_order():
    names = monitor_names(bessytl_lattice())
    server = OrbitTwinServer("T:rdBpm", "T:rdModel", monitor_prefixes=ORBIT_MONITOR_PREFIXES)
    t = track(names)
    server.push(x=[p.x * 1e9 for p in t], y=[p.y * 1e9 for p in t], names=names)
    bpm, x, _ = served(server)
    assert bpm == LINE_ORDER, "BPMs and striplines, no screens"
    assert x == pytest.approx([p.x * 1e9 for p in t if p.fam_name in LINE_ORDER])


def test_ring_default_unchanged():
    server = OrbitTwinServer("R:rdBpm", "R:rdModel")
    server.push(x=[1.0, 2.0, 3.0], y=[0.0, 0.0, 0.0], names=["BPMZ1D1R", "SLZ1T", "FOMZ1T"])
    assert served(server)[0] == ["BPMZ1D1R"]


def test_injection_twin_shot_serves_them():
    """single pass: what a shot showed, the striplines too"""
    from dt4acc.custom_facility.bessytl.view import TransferLineView

    names = monitor_names(bessytl_lattice())
    server = OrbitTwinServer("T:rdBpm", "T:rdModel", monitor_prefixes=ORBIT_MONITOR_PREFIXES)
    view = TransferLineView(monitors=names, single_pass=True, orbit_server=server)
    view.update_monitors(track(names))
    assert served(server)[0] == [], "no shot yet"
    view.fire()
    assert served(server)[0] == LINE_ORDER
