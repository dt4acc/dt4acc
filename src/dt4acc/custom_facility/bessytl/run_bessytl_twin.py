"""BESSY II transfer line twin (EPICS)

PVs (prefixed with ``DT4ACC_PREFIX``, default: the user name):

* supplies: ``<supply>:set``, ``<supply>:rdbk`` [A] (``Q1PT`` ... ``Q12PT``,
  ``H1PT`` ... ``V8PT``)
* magnets: ``<magnet>:Cm:set``, ``<magnet>:Cm:rdbk`` (K [1/m^2] or kick [rad])
* monitors: ``<monitor>:x``, ``<monitor>:y`` [m]: trajectory
* along the line: ``beam:orbit:{x,y,names,uids}``, ``beam:twiss:{x,y}:{beta,alpha,nu}``,
  ``survey:s``; PVA ``ORBITCC:rdBpm`` (BPMZ* only, nm)

``DT4ACC_BESSYTL_TWISS_IN``: yaml file with the beam entering the line
(default: the placeholder in resources/input/twiss_in.yaml).
"""
import asyncio
import getpass
import logging
import os
from importlib import resources
from typing import Any, Dict

from softioc import builder, softioc

from dt4acc.config.data.querries import configure_data_file
from dt4acc.core.bl.controller import Controller, read_and_dispatch
from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc.core.interfaces.controller_interface import ControllerInterface
from dt4acc.custom_epics.ioc.controller import dispatcher
from dt4acc.custom_epics.ioc.orbit_pva import OrbitTwinServer
from dt4acc.custom_epics.ioc.pv_setup import (
    initialize_orbit_pvs,
    initialize_power_converter_pvs,
    initialize_survey_info_pvs,
    initialize_twiss_pvs,
)
from dt4acc.custom_facility.bessytl.twin_setup import (
    ACCELERATOR_SETUP,
    bessytl_lattice,
    build_managers,
    load_twiss_in,
    monitor_names,
)
from dt4acc.custom_facility.bessytl.view import TransferLineView, initialize_monitor_pvs
from dt4acc_lib.bl.command_rewritter import CommandRewriter
from dt4acc_lib.model.utils.command import ReadCommand
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

logging.basicConfig(level=logging.WARNING)
logging.getLogger("lat2db").setLevel(level=logging.WARNING)
logger = logging.getLogger("dt4acc-bessytl")


async def main():
    # the supplies and magnets the PVs are made for
    configure_data_file(resources.files("dt4acc").joinpath(*ACCELERATOR_SETUP))

    line = bessytl_lattice()
    twiss_in = load_twiss_in(os.environ.get("DT4ACC_BESSYTL_TWISS_IN"))
    logger.warning("BESSY II transfer line: %d elements, entering beam %s", len(line), twiss_in)
    backend = SimulatorBackend(
        name="BESSYII_TL_on_PyAT",
        acc=PyATAcceleratorSimulator(at_lattice=line, twiss_in=twiss_in),
    )
    lm, ts = build_managers()
    mexec = TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=CommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )

    prefix = os.environ.get("DT4ACC_PREFIX", getpass.getuser())
    pva_prefix = prefix + ":" if prefix else ""
    orbit_server = OrbitTwinServer(pva_prefix + "ORBITCC:rdBpm", pva_prefix + "ORBITCC:rdModel")
    orbit_server.start()
    monitors = monitor_names(line)
    view = TransferLineView(monitors=monitors, orbit_server=orbit_server)

    controller = Controller(
        name="epics-bessytl-ctrller",
        mexec=mexec,
        view=view,
        default_delayed_reads=[ReadCommand("track", "pos"), ReadCommand("twiss", "parameters")],
    )
    controller.start()
    if prefix:
        builder.SetDeviceName(prefix)

    view.update_process_variables(await initialise_pvs(builder, controller, monitors, n_elements=len(line) + 1))
    await read_and_dispatch(
        controller=controller,
        view=view,
        rcmds=[ReadCommand("survey", "s")] + list(controller.default_delayed_reads),
    )
    builder.LoadDatabase()
    softioc.iocInit(dispatcher)
    softioc.interactive_ioc(globals())


async def initialise_pvs(builder, controller: ControllerInterface, monitors, *, n_elements) -> Dict[ReadCommand, Any]:
    return {
        **await initialize_power_converter_pvs(builder, controller=controller),
        **initialize_survey_info_pvs(builder, n_elements=n_elements),
        **initialize_orbit_pvs(builder, n_elements=n_elements),
        **initialize_twiss_pvs(builder, n_elements=n_elements),
        **initialize_monitor_pvs(monitors),
    }


def run():
    """console script: the twin runs until its IOC shell ends"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
