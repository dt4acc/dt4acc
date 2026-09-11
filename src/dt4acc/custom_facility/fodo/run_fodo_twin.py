import asyncio
import getpass
import logging
import os
from typing import Dict, Any

from importlib import resources

from softioc import builder, softioc

from dt4acc.core.bl.controller import read_and_dispatch
from dt4acc.core.bl.handle_lattice import lattice_loader
from dt4acc.core.interfaces.controller_interface import ControllerInterface
from dt4acc.custom_epics.ioc.pv_setup import (
    initialize_master_clock_pvs,
    initialize_cavity_pvs,
    initialize_power_converter_pvs,
    initialize_machine_info_pvs,
    initialize_survey_info_pvs,
    initialize_orbit_object_pvs,
    initialize_orbit_pvs,
    initialize_twiss_pvs,
    initialize_tune_pvs,
    initialize_other_pvs,
)
from dt4acc.core.bl.controller import Controller
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend
from dt4acc_lib.bl.command_rewritter import CommandRewriter
from dt4acc_lib.model.utils.command import ReadCommand
from dt4acc.core.bl.translating_command_execution_engine import (
    TranslatingCommandExecutionEngine,
)
from dt4acc.custom_epics.ioc.orbit_pva import OrbitTwinServer
from dt4acc.custom_epics.ioc.controller import dispatcher
from dt4acc.custom_epics.ioc.view import View
from dt4acc.custom_facility.fodo.liasion_translator_setup import load_managers

logging.basicConfig(level=logging.WARNING)
logging.getLogger("dt4acc_lib").setLevel(level=logging.WARNING)
logging.getLogger("transitions").setLevel(level=logging.WARNING)
logging.getLogger("transitions.core").setLevel(level=logging.WARNING)
logger = logging.getLogger("dt4acc-fodo")


async def main():
    """Handle all startups

    * load liasion manager and translation service
      and build command rewriter from them
    * use a basic measurement execution engine should be
      (should be rather called "command execution engine).
      This currently uses an pyat based backend.

    * view is a key-value storage to access the proces variables
    * controller takes care to
        * build up all variables of the view (needed due to EPICS builder)
        * pass them to the view
        * handle delayed execution

    """
    filename = resources.files("dt4acc").joinpath(
        "custom_facility/fodo/resources/fodo_lattice.json"
    )
    lattice_loader.set_lattice_file(filename)
    acc = lattice_loader.load()
    backend = SimulatorBackend(
        name="FODO_on_PyAT",
        acc=PyATAcceleratorSimulator(at_lattice=acc),
    )

    _, lm, ts = load_managers()

    command_rewriter = CommandRewriter(liaison_manager=lm, translation_service=ts)

    # Todo: review if a dedicated execution engine
    #       View gets an engine to execute
    #       each trigger calls to the engine. When something happens
    mexec = TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=command_rewriter,
        expected_view_for_output="device",
        num_readings=1,
    )

    prefix = os.environ.get("DT4ACC_PREFIX", getpass.getuser())
    if prefix:
        pva_prefix = prefix + ":"
    else:
        pva_prefix = ""
    orbit_server = OrbitTwinServer(
        pva_prefix + "ORBITCC:rdBpm",
        pva_prefix + "ORBITCC:rdModel",
    )

    orbit_server.start()
    view = View(orbit_server=orbit_server)

    controller = Controller(
        name="epics-delegate-ctrller",
        mexec=mexec,
        view=view,
        default_delayed_reads=[
            ReadCommand("track", "pos"),
            ReadCommand("twiss", "parameters"),
        ],
    )
    controller.start()
    if prefix:
        builder.SetDeviceName(prefix)

    view.update_process_variables(
        await initialise_pvs(builder=builder, controller=controller)
    )
    # Extra reads at startup
    await read_and_dispatch(
        controller=controller,
        view=view,
        rcmds=[ReadCommand("survey", "s")] + list(controller.default_delayed_reads),
    )
    builder.LoadDatabase()
    softioc.iocInit(dispatcher)
    logger.warning("EPICS IOC ready: prefix=%s", prefix or "<none>")

    headless = os.environ.get("DT4ACC_HEADLESS", "").lower() in ("1", "true", "yes")
    if headless:
        softioc.non_interactive_ioc()
    else:
        softioc.interactive_ioc(globals())


async def initialise_pvs(
    builder, controller: ControllerInterface
) -> Dict[ReadCommand, Any]:

    return {
        **await initialize_master_clock_pvs(builder, controller=controller),
        **await initialize_cavity_pvs(builder, controller=controller),
        **await initialize_power_converter_pvs(builder, controller=controller),
        **initialize_machine_info_pvs(builder, n_ref_buckets=400),
        **initialize_survey_info_pvs(builder),
        **initialize_orbit_object_pvs(builder),
        **initialize_orbit_pvs(builder),
        **initialize_twiss_pvs(builder),
        **initialize_tune_pvs(builder),
        **initialize_other_pvs(builder),
    }


if __name__ == "__main__":
    asyncio.run(main())
