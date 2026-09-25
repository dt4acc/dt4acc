"""Test bed for read commands on tango controller delegate

Without all the overhead of the tango control system

*NB* uses soleil setup
"""
import math
from pathlib import Path

import pytest

from dt4acc.core.bl.controller import Controller
from dt4acc.core.bl.translating_command_execution_engine import (
    TranslatingCommandExecutionEngine,
)
from dt4acc.core.interfaces.view_interface import ViewInterface
from dt4acc_lib.interfaces.backend.calculation_states import CalculationStates
from dt4acc_lib.interfaces.simulator.accelerator_simulator import OpticsCalculationProhibitedError
from dt4acc_lib.model.output.calculated_track import CalculatedTrack
from dt4acc.custom_facility.soleil.liasion_translator_setup import load_managers
from dt4acc.core.bl.handle_lattice import LatticeLoader
from dt4acc_lib.bl.command_rewritter import CommandRewriter
from dt4acc_lib.model.output.result import TranslatedReading
from dt4acc_lib.model.output.tune import Chromaticity
from dt4acc_lib.model.output.twiss import Twiss
from dt4acc_lib.model.utils.command import ReadCommand, Command, TransactionCommand
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend


@pytest.fixture(scope="function")
def backend():
    loader = LatticeLoader()
    # Todo: need here some test file
    #       * e.g. an outdated Soleil II file
    #       * a simple TME lattice file
    #       * a FODO File
    lattice_file = (
        Path.home()
        / "Documents"
        / "dt4acc_config_data"
        / "SOLEIL_II_V3635_STAB_SYM1_SB3_MULT7_4SX60_V001_Nomenclature.m"
    )
    loader.set_lattice_file(lattice_file)
    acc = loader.load()
    r = SimulatorBackend(
        name="Facility specific PYAT", acc=PyATAcceleratorSimulator(at_lattice=acc)
    )
    return r


@pytest.fixture(scope="module")
def managers():
    return load_managers()


@pytest.fixture(scope="function")
def mexec(managers, backend):
    _, lm, ts = managers

    cmd_rewriter = CommandRewriter(liaison_manager=lm, translation_service=ts)
    r = TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=cmd_rewriter,
        expected_view_for_output="design",
        num_readings=1,
    )
    return r

class ViewMockup(ViewInterface):

    async def dispatch(self, rcmd: ReadCommand, result: TranslatedReading) -> None:
        pass

    async def push_invalid(self) -> None:
        pass


@pytest.fixture(scope="function")
def controller(mexec):
    controller = Controller(
        name="tango-test-controller", mexec=mexec, default_delayed_reads=[], view=ViewMockup()
    )
    controller.start()
    return controller


@pytest.mark.asyncio
async def test_read_track(controller):
    rcmds = [ReadCommand(id="track", property="pos")]

    r = await controller.trigger_read(rcmds)
    (track_pkg,) = r.all_readings()
    track = track_pkg.payload
    assert isinstance(track, CalculatedTrack)
    assert len(track.track) > 1000
    track_pos, *_ = track.track
    # check that the element exists
    track_pos.fam_name
    track_pos.uid
    # typically undistoreted beam ... should be small
    assert abs(track_pos.x) < 1e-6
    assert abs(track_pos.y) < 1e-6


@pytest.mark.asyncio
async def test_read_chromaticity(controller):
    rcmds = [ReadCommand(id="chromaticity", property="transversal")]

    r = await controller.trigger_read(rcmds)
    (chroma_pkg,) = r.all_readings()
    chroma = chroma_pkg.payload
    assert isinstance(chroma, Chromaticity)
    assert not math.isnan(chroma.x)
    assert not math.isnan(chroma.y)
    assert chroma.x == pytest.approx(1.688, abs=1e-2)
    assert chroma.y == pytest.approx(1.39, abs=1e-2)


@pytest.mark.asyncio
async def test_read_twiss(controller):
    rcmds = [ReadCommand(id="twiss", property="parameters")]

    r = await controller.trigger_read(rcmds)
    (twiss_pkg,) = r.all_readings()
    twiss = twiss_pkg.payload
    assert isinstance(twiss, Twiss)
    assert len(twiss.twiss) > 1000
    twiss_for_element, *_ = twiss.twiss
    # check that these attributes exist
    twiss_for_element.x.beta
    twiss_for_element.y.beta
    twiss_for_element.x.nu
    twiss_for_element.y.nu


@pytest.mark.asyncio
async def test_reading_when_error_acknowledge(controller):
    rcmds = [ReadCommand(id="track", property="pos")]

    r = await controller.trigger_read(rcmds)
    (track_pkg,) = r.all_readings()
    track = track_pkg.payload
    assert isinstance(track, CalculatedTrack)
    for pos in track.track:
        assert math.isfinite(pos.x)
        assert math.isfinite(pos.y)

    # Now check normal run works ...
    # note ... only when data are read optics is calculated
    r = await controller.update(
        cmd=Command("SH3_VCOR_001", "x_kick", 0e-3, behaviour_on_error=None),
        reads=rcmds
    )
    assert controller.mexec.backend.get_state() == CalculationStates.finished

    # That should be still ok
    r = await controller.update(
        cmd=Command("SH3_VCOR_001", "y_kick", 1e-4, behaviour_on_error=None),
        reads=rcmds
    )
    assert controller.mexec.backend.get_state() == CalculationStates.finished

    # With that kick no orbit is found any more
    r = await controller.update(
        cmd=Command("SH3_VCOR_001", "y_kick", 2.5e-4, behaviour_on_error=None),
        reads=[]
    )
    assert controller.mexec.backend.get_state() == CalculationStates.pending

    r = await controller.trigger_read(reads=rcmds)
    (track_pkg,) = r.all_readings()
    track = track_pkg.payload
    assert track is None
    assert controller.mexec.backend.get_state() == CalculationStates.error

    with pytest.raises(OpticsCalculationProhibitedError):
        # controller needs to acknowledge the error only then it should go on
        # The ideas is to ensure that such calculation error does not go
        # unpassed
        await controller.update(
            cmd=Command("SH3_VCOR_001", "y_kick", 0.0e-4, behaviour_on_error=None),
            reads=[]
        )

    # Now set it to acknowledge ... now it should produce data, but track should
    # be None ... there is no data inside
    await controller.mexec.backend.acknowledge()
    assert controller.mexec.backend.get_state() == CalculationStates.acknowledged
    r = await controller.trigger_read(reads=rcmds)
    (track_pkg,) = r.all_readings()
    track = track_pkg.payload
    assert track is None

    # Need the steerer back otherwise it will not work ...
    await controller.update(
        cmd=Command("SH3_VCOR_001", "y_kick", 0.0e-4, behaviour_on_error=None),
        reads=[]
    )

    # Now reset it and check that the whole system works again
    await controller.mexec.backend.reset()
    r = await controller.trigger_read(rcmds)
    (track_pkg,) = r.all_readings()
    track = track_pkg.payload
    assert isinstance(track, CalculatedTrack)
    for pos in track.track:
        assert pos.x == pytest.approx(0.0, abs=1e-6)
        assert pos.y == pytest.approx(0.0, abs=1e-9)