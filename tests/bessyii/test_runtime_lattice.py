"""A lattice with small differences loaded at run time (#81): the ring twin's
``simulator_ring:lattice``, first case the wavelength shifters inserted"""
import asyncio

import at
import numpy as np
import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.custom_epics.ioc.lattice_pvs import (
    LatticeSwitch, after_load_refresh, refresh_settings, replacement_check, required_elements,
    set_unprocessed, takes_process,
)
from dt4acc.custom_facility.bessyii.liasion_translator_setup import load_managers
from dt4acc.custom_facility.bessyii.provide_lattice import bessyii_pyat_lattice, provide_backend, provide_lattice
from dt4acc.custom_facility.bessyii.run_bessyii_twin import BPM_PREFIX, initialise_pvs
from dt4acc.core.bl.turn_by_turn import ring_monitors
from dt4acc_lib.model.utils.command import ReadCommand
from dt4acc_lib.pyat_simulator.accelerator_simulator import LatticeMismatch

from tests.bessyii.test_ring_pvs import PREFIX, ring_controller
from tests.recording_builder import RecordingBuilder

#: a quadrupole whose strength the "re-matched" lattice changes, and its supply
QUAD, SUPPLY = "Q3M1D1R", "Q3PD1R"


def with_insertion(lattice: at.Lattice, dk: float = 0.0) -> at.Lattice:
    """``lattice`` with a drift of the T1R wavelength shifter's straight split
    around thin pieces (as an insertion device adds elements), ``QUAD``'s K + ``dk``"""
    new = lattice.deepcopy()
    start = int(new.get_uint32_index("W7IT1R_START")[0])
    i = next(k for k in range(start + 1, len(new)) if isinstance(new[k], at.Drift) and new[k].Length > 0.1)
    half = new[i].Length / 2
    new[i:i + 1] = [
        at.Drift("WLS_TEST_D1", half),
        at.Marker("WLS_TEST_M"),
        at.Corrector("WLS_TEST_K", 0.0, [0.0, 0.0]),
        at.Drift("WLS_TEST_D2", half),
    ]
    for elem in new:
        if elem.FamName == QUAD:
            elem.PolynomB[1] += dk
            elem.K = elem.PolynomB[1]
    return new


@pytest.fixture
def twin(tmp_path):
    lattice = provide_lattice()
    backend = provide_backend(lattice)
    controller = ring_controller(backend)
    builder = RecordingBuilder()
    builder.SetDeviceName(PREFIX)
    bpms = ring_monitors(backend, BPM_PREFIX)
    controller.view.update_process_variables(
        asyncio.run(initialise_pvs(builder=builder, controller=controller, bpms=bpms))
    )
    switch = LatticeSwitch(
        backend=backend,
        lattice_dir=tmp_path,
        load_file=bessyii_pyat_lattice,
        start_lattice=lattice,
        check=replacement_check(lattice, required_elements(load_managers()[1], lattice, bpms)),
        after_load=after_load_refresh(controller, controller.view, []),
    )
    return switch, backend, builder, lattice, tmp_path


def pv(builder, name):
    return builder.records[f"{PREFIX}:{name}"].value


def test_a_lattice_with_an_insertion_is_loaded(twin):
    switch, backend, builder, lattice, lattice_dir = twin
    new = with_insertion(lattice, dk=0.01)
    new.save(lattice_dir / "with_insertion.json")
    k_before, current_before = pv(builder, f"{QUAD}:Cm:set"), pv(builder, f"{SUPPLY}:set")

    message = asyncio.run(switch.load("with_insertion.json"))

    assert message == f"loaded with_insertion.json: {len(lattice) + 3} elements"
    names = backend.get_element_names()
    assert len(names) == len(lattice) + 3 + 1 and "WLS_TEST_K" in names
    # the settings' PVs show the new lattice's values
    assert pv(builder, f"{QUAD}:Cm:set") == pytest.approx(k_before + 0.01)
    assert pv(builder, f"{QUAD}:Cm:rdbk") == pytest.approx(k_before + 0.01)
    assert pv(builder, f"{SUPPLY}:set") != pytest.approx(current_before)
    assert pv(builder, f"{SUPPLY}:rdbk") == pytest.approx(pv(builder, f"{SUPPLY}:set"))
    # the model follows: the tunes are the new lattice's
    tune = asyncio.run(backend.read("tune", "transversal"))
    np.testing.assert_allclose([tune.x, tune.y], new.get_tune()[:2], atol=1e-6)

    # an empty name: back to the start lattice
    assert asyncio.run(switch.load("")) == f"loaded the start lattice: {len(lattice)} elements"
    assert len(backend.get_element_names()) == len(lattice) + 1
    assert pv(builder, f"{QUAD}:Cm:set") == pytest.approx(k_before)


def test_a_lattice_without_a_magnet_is_refused(twin):
    switch, backend, builder, lattice, lattice_dir = twin
    new = with_insertion(lattice)
    del new[[e.FamName for e in new].index(QUAD)]
    new.save(lattice_dir / "missing.json")
    message = asyncio.run(switch.load("missing.json"))
    assert message.startswith("refused: missing.json:") and QUAD in message
    assert len(backend.get_element_names()) == len(lattice) + 1


@pytest.mark.parametrize("name, reason", [
    ("../bessy2_storage_ring.json", "not a file name"),
    ("/etc/passwd", "not a file name"),
    ("absent.json", "not in"),
])
def test_only_files_of_the_lattice_directory(twin, name, reason):
    switch, backend, *_ = twin
    message = asyncio.run(switch.load(name))
    assert message.startswith("refused") and reason in message


def test_an_unreadable_file_is_refused(twin):
    switch, backend, builder, lattice, lattice_dir = twin
    (lattice_dir / "broken.json").write_text("{not json")
    assert asyncio.run(switch.load("broken.json")).startswith("refused: broken.json could not be read")
    assert len(backend.get_element_names()) == len(lattice) + 1


def test_the_check_can_be_turned_off_or_replaced(twin):
    switch, backend, builder, lattice, lattice_dir = twin
    new = with_insertion(lattice)
    del new[[e.FamName for e in new].index("BPMZ1D1R")]
    new.save(lattice_dir / "no_bpm.json")
    assert asyncio.run(switch.load("no_bpm.json")).startswith("refused")

    def refuse(_):
        raise LatticeMismatch("not today")

    switch.check = refuse
    assert asyncio.run(switch.load("no_bpm.json")) == "refused: no_bpm.json: not today"
    assert len(backend.get_element_names()) == len(lattice) + 1

    switch.check = None
    assert asyncio.run(switch.load("no_bpm.json")).startswith("loaded no_bpm.json")
    assert "BPMZ1D1R" not in backend.get_element_names()


def test_required_elements_are_the_devices(twin):
    _, backend, _, lattice, _ = twin
    required = set(required_elements(load_managers()[1], lattice, ring_monitors(backend, BPM_PREFIX)))
    assert {QUAD, "BPMZ1D1R", "CAVH1T8R"} <= required
    assert "WLS_TEST_K" not in required and "DU_MSEPEXIT" not in required


def test_the_bundled_lattice_with_the_wavelength_shifters(twin):
    """bessy2_storage_ring_wls.json (scripts/bessyii/export_lattice.py
    --wavelength-shifters) from the twin's default lattice directory"""
    from dt4acc.custom_facility.bessyii.run_bessyii_twin import lattice_directory

    switch, backend, builder, lattice, _ = twin
    switch.lattice_dir = lattice_directory()
    k_before = pv(builder, f"{QUAD}:Cm:set")

    message = asyncio.run(switch.load("bessy2_storage_ring_wls.json"))

    assert message == "loaded bessy2_storage_ring_wls.json: 1255 elements", message
    assert len(lattice) == 1137
    names = backend.get_element_names()
    assert "W7IT1R_0_0" in names and "W7IT7R_2_19" in names
    # bessy2reflat re-matches the tunes with the Q3 quadrupoles
    assert pv(builder, f"{QUAD}:Cm:set") != pytest.approx(k_before, rel=1e-9)
    tune = asyncio.run(backend.read("tune", "transversal"))
    np.testing.assert_allclose([tune.x, tune.y], [0.848074, 0.726783], atol=1e-5)


def test_only_output_records_take_process():
    """softioc's own records"""
    _softioc_builder.SetDeviceName("TEST_RUNTIME_LATTICE")
    assert takes_process(_softioc_builder.aOut("out", initial_value=0.0))
    assert not takes_process(_softioc_builder.aIn("in", initial_value=0.0))


def test_a_type_error_of_the_record_is_not_hidden():
    class Failing:
        def set(self, value, process=True):
            raise TypeError("bad value")

    with pytest.raises(TypeError, match="bad value"):
        set_unprocessed(Failing(), "x")


class _Settings:
    """controller and records that note the order of reads and sets"""

    class Reading:
        payload = 1.0

    def __init__(self, n, failing=()):
        self.log = []
        outer = self

        class Rec:
            def __init__(self, name):
                self.name = name

            def set(self, value, process=True):
                if self.name in failing:
                    raise ValueError(self.name)
                outer.log.append("set" if not process else "processed")

        self.records = {ReadCommand(f"M{i}", "main_strength"): Rec(f"M{i}") for i in range(n)}

    async def trigger_read(self, rcmds):
        self.log.append("read")
        return self

    def all_readings(self):
        return [self.Reading()]


def test_all_settings_are_read_before_the_first_is_set():
    settings = _Settings(3)
    assert asyncio.run(refresh_settings(settings, settings.records)) == 3
    assert settings.log == ["read"] * 3 + ["set"] * 3


def test_one_failing_record_does_not_stop_the_others(caplog):
    settings = _Settings(3, failing=("M0",))
    assert asyncio.run(refresh_settings(settings, settings.records)) == 2
    assert "not set" in caplog.text
