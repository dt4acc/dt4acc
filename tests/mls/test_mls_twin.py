"""MLS storage ring twin: calibration as MML, PVs named as on the machine

Calibration: the conversion reproduces MML's ``amp2k.m`` (``K =
polyval(amp2k, I) / Brho``), exactly; the design lattice needs
supply currents inside MML's setpoint ranges. PVs: supplies
``setCur`` / ``rdCur``, BPMs ``signal:sa:X`` / ``Y``, RF ``MCLKHGP:setFrq`` /
``rdFrq``, beam current ``CUM1ZK3RP:rdCur`` (``ao_mls.json``); magnets
twin only.
"""
import asyncio

import numpy as np
import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc_lib.bl.translator_service import create_translation_object_for_data_model
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend
from dt4acc.core.bl.turn_by_turn import RingTurnByTurn
from dt4acc.custom_facility.mls.run_mls_twin import initialise_pvs, initialise_turn_by_turn_pvs, make_controller
from dt4acc.custom_facility.mls.twin_setup import (
    BRHO, bpm_names, calibration, lattice_element, load_accelerator_setup, mls_lattice,
)
from dt4acc.custom_facility.mls.view import MLSView

from tests.recording_builder import RecordingBuilder

PREFIX = "TEST"
SUPPLY_FIELDS = {"setCur", "rdCur"}
MAGNET_FIELDS = {"Cm:setCur", "Cm:rdCur", "im:I", "x:setCur", "y:setCur"}


@pytest.fixture(scope="module")
def setup():
    return load_accelerator_setup()


@pytest.fixture(scope="module")
def twin():
    ring = mls_lattice()
    backend = SimulatorBackend(name="MLS_on_PyAT", acc=PyATAcceleratorSimulator(at_lattice=ring))
    bpms = bpm_names(ring)
    controller = make_controller(backend, MLSView(bpms=bpms))
    builder = RecordingBuilder()
    builder.SetDeviceName(PREFIX)
    asyncio.run(initialise_pvs(builder, controller, bpms, n_elements=len(ring) + 1))
    initialise_turn_by_turn_pvs(builder, backend, bpms)
    return ring, bpms, builder


def test_device_database(setup):
    assert len(setup) == 76 and len({m["pc"] for m in setup}) == 59
    ring = mls_lattice()
    names = {e.FamName for e in ring}
    assert not [m["name"] for m in setup if lattice_element(m) not in names]


def test_calibration_as_mml_amp2k(setup):
    for m in setup:
        conv = create_translation_object_for_data_model(calibration(m), brho=BRHO)
        currents = np.linspace(*m["range"], 13)
        mml = np.polyval(m["amp2k"], currents / m["amp2k_scale"]) / BRHO
        twin = np.array([conv.inverse(i) for i in currents])
        np.testing.assert_allclose(twin, mml, rtol=1e-12, atol=1e-15, err_msg=m["name"])
        # round trip
        for i in currents:
            assert conv.forward(conv.inverse(i)) == pytest.approx(i, abs=1e-9)


def test_design_currents_within_the_setpoint_ranges(setup, twin):
    _, _, builder = twin
    out = []
    for m in setup:
        i = builder.records[f"{PREFIX}:{m['pc']}:setCur"].value
        lo, hi = m["range"]
        if not lo - 1e-6 <= i <= hi + 1e-6:
            out.append((m["pc"], i, m["range"]))
    # the design lattice has the sextupoles off: their supplies sit at amp2k's offset, just below 0 A
    assert all(pc.startswith("S") and -1.0 < i < 0 for pc, i, _ in out), out


def test_pv_names(setup, twin):
    _, bpms, builder = twin
    pvs = set(builder.names(PREFIX))
    expected = {f"{m['pc']}:{f}" for m in setup for f in SUPPLY_FIELDS}
    expected |= {f"{m['name']}:{f}" for m in setup for f in MAGNET_FIELDS}
    expected |= {f"{b}:{f}" for b in bpms for f in ("signal:sa:X", "signal:sa:Y")}
    expected |= {"MCLKHGP:setFrq", "MCLKHGP:rdFrq", "CAV:freq", "CUM1ZK3RP:rdCur"}
    # turn by turn, as the BESSY II ring twin
    expected |= {f"{b}:{f}" for b in bpms for f in ("signal:tbt:X", "signal:tbt:Y")}
    expected |= {"TBT:n_turns", "TBT:tbt:x", "TBT:tbt:y", "TBT:tbt:names", "TBT:survived", "TBT:count"}
    expected |= {f"TBT:{w}:{p}" for w in ("offset", "start") for p in ("x", "px", "y", "py", "delta", "ct")}
    assert len(bpms) == 28
    missing = sorted(expected - pvs)
    assert not missing, f"{len(missing)} missing, e.g. {missing[:5]}"
    # nothing under BESSY II's names
    bessy = sorted(p for p in pvs if p.endswith((":set", ":rdbk", "Cm:set", "Cm:rdbk")) or p.startswith("MCLKHX251C"))
    assert not bessy, bessy


def test_design_tunes():
    ring = mls_lattice()
    _, ring_data, _ = ring.get_optics()
    np.testing.assert_allclose(ring_data.tune[:2], [0.1785, 0.2320], atol=5e-4)


def test_turn_by_turn_oscillates_with_the_tunes():
    """a beam 0.1 mm off the closed orbit in x and y: the signal at a BPM peaks at the tunes"""
    ring = mls_lattice()
    backend = SimulatorBackend(name="MLS_on_PyAT", acc=PyATAcceleratorSimulator(at_lattice=ring))
    bpms = bpm_names(ring)
    tbt = RingTurnByTurn(backend, bpms, offset=[1e-4, 0, 1e-4, 0, 0, 0], n_turns=128)
    r = tbt.compute()
    assert r.x.shape == (128, 28) and np.all(r.survived == 1)
    for signal, q in ((r.x[:, 0], 0.1785), (r.y[:, 0], 0.2320)):
        s = signal - signal.mean()
        n = 16 * len(s)
        f = np.fft.rfftfreq(n)[np.argmax(np.abs(np.fft.rfft(s * np.hanning(len(s)), n)))]
        assert f == pytest.approx(min(q, 1 - q), abs=2e-3)
