"""SOLEIL TL2 transfer line twin (custom_facility/soleil_tl2), without Tango servers

SOLEIL's TL2 files are not in the repository: read from the folder the twin
uses (utils/command_line_interface), skipped without them.
"""
import asyncio
import collections
import json

import at
import numpy as np
import pytest
import yaml

from dt4acc.config.data.querries import configure_data_file, get_data_file
from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc.custom_facility.soleil_tl2 import liasion_translator_setup as tl2
from dt4acc.custom_facility.soleil_tl2.utils.command_line_interface import (
    DATA_DIR,
    DEFAULT_LATTICE_FILE,
    DEFAULT_TWISS_IN_FILE,
)
from dt4acc.custom_facility.soleil_tl2.yml2json_soleil_tl2 import INPUT_YAML, device_entries
from dt4acc.custom_tango.ioc.virtual_pass_through_command_rewriter import VirtualPassthroughCommandRewriter
from dt4acc_lib.model.input.twiss_in import TwissIn
from dt4acc_lib.model.utils.command import BehaviourOnError, Command
from dt4acc_lib.model.utils.identifiers import ConversionID, DevicePropertyID, LatticeElementPropertyID
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

if not all(f.exists() for f in (DEFAULT_LATTICE_FILE, DEFAULT_TWISS_IN_FILE, DATA_DIR / INPUT_YAML)):
    pytest.skip(f"SOLEIL TL2 files not found in {DATA_DIR}", allow_module_level=True)


def load_twiss_in() -> TwissIn:
    with open(DEFAULT_TWISS_IN_FILE) as fp:
        return TwissIn(**yaml.safe_load(fp))


@pytest.fixture(scope="module")
def line():
    return at.load_lattice(str(DEFAULT_LATTICE_FILE))


@pytest.fixture(scope="module")
def entries():
    with open(DATA_DIR / INPUT_YAML) as fp:
        return device_entries(yaml.safe_load(fp))


@pytest.fixture(scope="module")
def controlled(entries):
    return [e for e in entries if e["type"] in ("Quadrupole", "Steerer")]


@pytest.fixture(scope="module")
def managers(entries, tmp_path_factory):
    """from the device database, as the twin"""
    path = tmp_path_factory.mktemp("tl2") / "accelerator_setup.json"
    path.write_text(json.dumps(entries))
    previous = get_data_file()
    configure_data_file(path)
    try:
        yield tl2.build_managers()
    finally:
        configure_data_file(previous)


def prop_of(entry) -> str:
    if entry["type"] == "Quadrupole":
        return "main_strength"
    return "x_kick" if entry["FamName"].startswith("H") else "y_kick"


def test_device_database(entries):
    count = collections.Counter(e["type"] for e in entries)
    # as the ring: the bends are listed, not controlled
    assert set(count) == {"Quadrupole", "Steerer", "Bend", "BPM"}
    assert all(e["pc"] for e in entries if e["type"] != "BPM")


def test_yellow_pages_sort_all_correctors(entries, managers):
    yp, _, _ = managers
    steerers = {e["name"] for e in entries if e["type"] == "Steerer"}
    horizontal, vertical = set(yp.horizontal_steerer_names()), set(yp.vertical_steerer_names())
    assert horizontal and vertical and not horizontal & vertical
    assert horizontal | vertical == steerers


def test_liaison_as_the_ring(controlled, managers):
    """each magnet device's property is its element's property of the same name, slope 1"""
    _, lm, ts = managers
    for m in controlled:
        prop = prop_of(m)
        lat = LatticeElementPropertyID(element_name=m["uuid"], property=prop)
        dev = DevicePropertyID(device_name=m["name"], property=prop)
        assert tuple(lm.inverse(dev)) == (lat,)
        conversion = ts.get(ConversionID(lat, dev))
        assert (conversion.intercept, conversion.slope) == (0.0, 1.0)


def test_bends_not_controlled(entries, managers):
    _, lm, _ = managers
    for b in (e for e in entries if e["type"] == "Bend"):
        assert not lm.inverse_lut.get(DevicePropertyID(device_name=b["name"], property="main_strength"))
        assert not lm.inverse_lut.get(DevicePropertyID(device_name=b["uuid"], property="main_strength"))


def test_supplies_factor_one(controlled, managers):
    """a supply's set_current drives its magnet's property, slope 1"""
    _, lm, ts = managers
    for m in controlled:
        dev = DevicePropertyID(device_name=m["pc"], property=tl2.SUPPLY_PROPERTY)
        lat = LatticeElementPropertyID(element_name=m["uuid"], property=prop_of(m))
        assert lat in tuple(lm.inverse(dev))
        conversion = ts.get(ConversionID(lat, dev))
        assert (conversion.intercept, conversion.slope) == (0.0, 1.0)


def test_optics_from_the_entering_beam(line):
    acc = PyATAcceleratorSimulator(at_lattice=line, twiss_in=load_twiss_in())
    _, _, data = acc.get_optics_parameters()
    # SOLEIL's values stay out of the repository: compared with its file
    np.testing.assert_allclose(data.beta[0], load_twiss_in().beta)
    assert np.all(np.isfinite(data.beta)) and np.all(data.beta > 0)


def test_corrector_steers_the_trajectory(line, managers, entries):
    _, lm, ts = managers
    backend = SimulatorBackend(
        name="tl2", acc=PyATAcceleratorSimulator(at_lattice=line, twiss_in=load_twiss_in())
    )
    mexec = TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=VirtualPassthroughCommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="design",
        num_readings=1,
    )

    last_bpm = [e for e in entries if e["type"] == "BPM"][-1]["uuid"]
    corrector = [e for e in entries if e["type"] == "Steerer" and prop_of(e) == "x_kick"][-1]["uuid"]

    async def x_at_last_bpm():
        track = await backend.read("track", "pos")
        return {p.uid: p for p in track.track}[last_bpm].x

    async def steer():
        before = await x_at_last_bpm()
        # as the magnet device (design view): addressed to its element (element_uuid)
        await mexec.set([Command(id=corrector, property="x_kick", value=1e-4,
                                 behaviour_on_error=BehaviourOnError.stop)])
        after = await x_at_last_bpm()
        assert await backend.read(corrector, "x_kick") == pytest.approx(1e-4)
        return before, after

    before, after = asyncio.run(steer())
    assert before == pytest.approx(0.0, abs=1e-12) and abs(after) > 1e-5


def test_supply_steers_the_trajectory(line, managers, entries):
    """supply view: the corrector's supply sets its kick, factor 1"""
    _, lm, ts = managers
    backend = SimulatorBackend(
        name="tl2", acc=PyATAcceleratorSimulator(at_lattice=line, twiss_in=load_twiss_in())
    )
    mexec = TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=VirtualPassthroughCommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )
    corrector = [e for e in entries if e["type"] == "Steerer" and prop_of(e) == "y_kick"][-1]
    asyncio.run(mexec.set([Command(id=corrector["pc"], property=tl2.SUPPLY_PROPERTY, value=2e-4,
                                   behaviour_on_error=BehaviourOnError.stop)]))
    assert asyncio.run(backend.read(corrector["uuid"], "y_kick")) == pytest.approx(2e-4)


@pytest.mark.parametrize("kind,value", [("Quadrupole", 0.8), ("Steerer", 1e-4)])
def test_magnet_device_writes_in_the_supply_view(line, managers, controlled, kind, value):
    """the magnet devices address themselves by their element's id, in the supply view too"""
    _, lm, ts = managers
    magnet = next(m for m in controlled if m["type"] == kind)
    uuid, prop = magnet["uuid"], prop_of(magnet)
    backend = SimulatorBackend(
        name="tl2", acc=PyATAcceleratorSimulator(at_lattice=line, twiss_in=load_twiss_in())
    )
    mexec = TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=VirtualPassthroughCommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )
    asyncio.run(mexec.set([Command(id=uuid, property=prop, value=value, behaviour_on_error=BehaviourOnError.stop)]))
    assert asyncio.run(backend.read(uuid, prop)) == pytest.approx(value)


def test_magnet_device_readback_conversion_is_known(controlled, managers):
    """single_server._lattice_to_device_value asks for this conversion on every poll"""
    _, _, ts = managers
    for m in controlled:
        prop = prop_of(m)
        conversion = ts.get(ConversionID(
            LatticeElementPropertyID(element_name=m["uuid"], property=prop),
            DevicePropertyID(device_name=m["uuid"], property=prop),
        ))
        assert (conversion.intercept, conversion.slope) == (0.0, 1.0)


def test_supply_follows_the_lattice_where_enabled(monkeypatch):
    """a supply device reads its value from the lattice, only if the twin enables it"""
    from tango.test_context import DeviceTestContext

    from dt4acc.custom_tango.ioc import single_server
    from dt4acc.custom_tango.ioc.devices.power_converter_device import PowerConverterDevice

    lattice = {"value": 1.5}
    monkeypatch.setattr(single_server, "read_device_value", lambda device, prop: lattice["value"])
    with DeviceTestContext(PowerConverterDevice, device_name="test/pc/1", process=False) as supply:
        assert supply.current_set == 1.5, "as at start, from the lattice"
        lattice["value"] = 2.0  # e.g. a write to its magnet
        assert supply.current_set == 1.5 and supply.current_readback == 1.5, "not enabled: the value last set"
        monkeypatch.setattr(single_server, "_supply_readback", True)
        assert supply.current_set == 2.0 and supply.current_readback == 2.0
