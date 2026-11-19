"""SOLEIL Tango twin: the magnets' commands translated by the engine

The design-view devices address the engine by their names (engine in the
device view); SOLEIL's liaison manager and translation service convert their
values to their lattice elements', integrated strengths included. Built from
a small SOLEIL-named catalog and lattice, no Tango server needed.
"""

import asyncio
import json
import os
import threading

import at
import pytest

from dt4acc_lib.model.utils.command import BehaviourOnError, Command, ReadCommand
from dt4acc_lib.model.utils.identifiers import (
    ConversionID,
    DevicePropertyID,
    LatticeElementPropertyID,
)

from dt4acc.config.data import querries
from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc.custom_facility.model import at_integrated_strength
from dt4acc.custom_facility.soleil import liasion_translator_setup as soleil

QUAD = "AN01-AR/EM-QP/QF.01"         # QF_001, 0.4 m
H_STEERER = "AN01-AR/EM-COR/CH.01"   # COR_001 B1, thick corrector
V_STEERER = "AN01-AR/EM-COR/CV.01"   # COR_001 A1
CAVITY = "AN01-SD/RF-CAV/CAV"        # RF_001
DIPOLE = "AN01-AR/EM-DIP/B.01"       # B_001, main dipole

_CATALOG = [
    {"uuid": "QF_001", "type": "Quadrupole", "FamName": "QF_001", "name": QUAD},
    {"uuid": "COR_001", "type": "Multipole", "FamName": "COR_001", "name": H_STEERER},
    {"uuid": "COR_001", "type": "Steerer", "FamName": "COR_001", "name": V_STEERER},
    {"uuid": "B_001", "type": "Bend", "FamName": "B_001", "name": DIPOLE},
    {"uuid": "RF_001", "type": "RFCavity", "FamName": "RF_001", "name": CAVITY, "pc": "simulator/rfpc/rfpc"},
]


def _lattice():
    quad = at.Quadrupole("QF_001", 0.4, 1.2)
    cor = at.Multipole("COR_001", 0.1, [0.0, 0.0], [0.0, 0.0])
    bend = at.Dipole("B_001", 1.5, 0.1)
    cavity = at.RFCavity("RF_001", 0.0, 1e5, 352e6, 400, 1e9)
    for elem in (quad, cor, bend, cavity):
        elem.UUID = elem.FamName
    return at.Lattice([at.Drift("D", 1.0), quad, cor, bend, cavity], energy=1e9)


def _managers(tmp_path_factory, integrated_strength: bool):
    catalog = tmp_path_factory.mktemp("soleil") / "accelerator_setup.json"
    entries = [{"magnetic_strength": 1.0, "k": 1.0, "pc": e["name"] + "-pc", **e} for e in _CATALOG]
    catalog.write_text(json.dumps(entries))
    acc = _lattice()
    previous_file = querries.get_data_file()
    previous_load = soleil.lattice_loader.load
    previous_env = os.environ.pop(at_integrated_strength.ENABLE_ENV, None)
    if integrated_strength:
        os.environ[at_integrated_strength.ENABLE_ENV] = "1"
    querries.configure_data_file(catalog)
    soleil.lattice_loader.load = lambda: acc
    try:
        return soleil.build_managers(soleil.strength_factors_from_lattice()), acc
    finally:
        querries.configure_data_file(previous_file)
        soleil.lattice_loader.load = previous_load
        os.environ.pop(at_integrated_strength.ENABLE_ENV, None)
        if previous_env is not None:
            os.environ[at_integrated_strength.ENABLE_ENV] = previous_env


@pytest.fixture(scope="module")
def enabled(tmp_path_factory):
    return _managers(tmp_path_factory, integrated_strength=True)


@pytest.fixture(scope="module")
def disabled(tmp_path_factory):
    return _managers(tmp_path_factory, integrated_strength=False)


def _length(acc, uuid):
    return at_integrated_strength.lattice_element(acc, uuid).Length


def _slope(ts, element, lat_prop, device, dev_prop=None):
    conversion = ts.lut.get(ConversionID(
        LatticeElementPropertyID(element_name=element, property=lat_prop),
        DevicePropertyID(device_name=device, property=dev_prop or lat_prop),
    ))
    assert not conversion.energy_dependent
    return list(conversion.coeffs)


def test_magnet_slopes_integrated(enabled):
    (_, lm, ts), acc = enabled
    assert list(lm.inverse(DevicePropertyID(device_name=QUAD, property="main_strength"))) == [
        LatticeElementPropertyID(element_name="QF_001", property="main_strength")
    ]
    assert _slope(ts, "QF_001", "main_strength", QUAD) == pytest.approx([0.0, _length(acc, "QF_001")])
    length = _length(acc, "COR_001")
    assert length > 0.0
    assert _slope(ts, "COR_001", "B1", H_STEERER) == pytest.approx([0.0, -length])
    assert _slope(ts, "COR_001", "A1", V_STEERER) == pytest.approx([0.0, length])


def test_main_dipole_bending_field_unchanged(enabled):
    """A main dipole's device reads and writes its main_strength (the
    bending field) by its name, unchanged"""
    (_, lm, ts), _ = enabled
    assert list(lm.inverse(DevicePropertyID(device_name=DIPOLE, property="main_strength"))) == [
        LatticeElementPropertyID(element_name="B_001", property="main_strength")
    ]
    assert _slope(ts, "B_001", "main_strength", DIPOLE) == [0.0, 1.0]


def test_magnet_slopes_default(disabled):
    (_, _, ts), _ = disabled
    assert _slope(ts, "QF_001", "main_strength", QUAD) == [0.0, 1.0]
    assert _slope(ts, "COR_001", "B1", H_STEERER) == [0.0, 1.0]


def test_cavity_addressed_by_uuid_and_name(enabled):
    (_, lm, ts), _ = enabled
    for device in ("RF_001", CAVITY):
        for prop in ("frequency", "voltage"):
            assert list(lm.inverse(DevicePropertyID(device_name=device, property=prop))) == [
                LatticeElementPropertyID(element_name="RF_001", property=prop)
            ]
            assert _slope(ts, "RF_001", prop, device) == [0.0, 1.0]
    assert _slope(ts, "RF_001", "frequency", "master_clock", "reference_frequency") == [0.0, 1e-3]


class _Backend:
    """Lattice values, as the simulator backend (design view) holds them"""

    def __init__(self, values):
        self.values = dict(values)

    def get_natural_view_name(self):
        return "design"

    async def set(self, dev_id, prop_id, value):
        self.values[(dev_id, prop_id)] = value

    async def read(self, dev_id, prop_id):
        return self.values[(dev_id, prop_id)]


@pytest.fixture
def engine(enabled):
    from dt4acc.custom_tango.ioc.virtual_pass_through_command_rewriter import (
        VirtualPassthroughCommandRewriter,
    )

    (_, lm, ts), acc = enabled
    backend = _Backend({
        ("QF_001", "main_strength"): 2.0,
        ("COR_001", "B1"): 0.0,
        ("RF_001", "frequency"): 352e6,
    })
    return TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=VirtualPassthroughCommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    ), backend, acc


def _set(engine, name, prop, value):
    asyncio.run(engine.set([Command(id=name, property=prop, value=value,
                                    behaviour_on_error=BehaviourOnError.stop)]))


def test_engine_writes_lattice_coefficient(engine):
    mexec, backend, acc = engine
    length = _length(acc, "QF_001")
    _set(mexec, QUAD, "main_strength", 3.0 * length)
    assert backend.values[("QF_001", "main_strength")] == pytest.approx(3.0)

    # a kick angle of 1e-4 rad: PolynomB[0] = -1e-4 / L
    _set(mexec, H_STEERER, "B1", 1e-4)
    assert backend.values[("COR_001", "B1")] == pytest.approx(-1e-4 / _length(acc, "COR_001"))

    # cavities: their lattice element, unchanged
    _set(mexec, "RF_001", "frequency", 352.1e6)
    assert backend.values[("RF_001", "frequency")] == pytest.approx(352.1e6)


def test_engine_reads_device_value(engine):
    mexec, backend, acc = engine
    result = asyncio.run(mexec.trigger_read([ReadCommand(id=QUAD, property="main_strength")]))
    (translated,) = result.data
    (reading,) = translated.readings
    assert reading.cmd.id == QUAD
    assert reading.payload == pytest.approx(2.0 * _length(acc, "QF_001"))


def test_magnet_uuid_not_a_device(engine):
    """No identity for the magnets' lattice elements: no way around the conversion"""
    mexec, _, _ = engine
    with pytest.raises(KeyError):
        _set(mexec, "QF_001", "main_strength", 1.0)


def test_sync_trigger_read_reports_requested_ids(engine):
    pytest.importorskip("tango")
    from dt4acc.custom_tango.ioc.sync_mexec_proxy import SyncMexecProxy

    mexec, _, acc = engine
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        proxy = SyncMexecProxy(mexec=mexec, service_loop=loop)
        out = proxy.sync_trigger_read([QUAD, "RF_001"], ["main_strength", "frequency"])
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
    assert {(i, p) for i, p, _ in out} == {(QUAD, "main_strength"), ("RF_001", "frequency")}
    values = {i: v for i, _, v in out}
    assert values[QUAD] == pytest.approx(2.0 * _length(acc, "QF_001"))
    assert values["RF_001"] == pytest.approx(352e6)
