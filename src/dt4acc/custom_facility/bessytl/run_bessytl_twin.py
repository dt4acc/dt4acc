"""BESSY II transfer line twin (EPICS)

PVs (prefixed with ``DT4ACC_PREFIX``, default: the user name):

* supplies: ``<supply>:set``, ``<supply>:rdbk`` [A] (``Q1PT`` ... ``Q12PT``,
  ``H1PT`` ... ``V8PT``)
* magnets: ``<magnet>:Cm:set``, ``<magnet>:Cm:rdbk`` (K [1/m^2] or kick [rad])
* BPMs and striplines: ``<bpm>:signal:sa:X`` / ``Y`` [mm]
* screens: ``<screen>:image``, beam centre ``<screen>:x`` / ``y`` and size
  ``<screen>:sigma:x`` / ``y`` [mm] (see ``screens.py``)
* the model, under ``TL:`` (as in the injection twin, see ``view.py``):
  ``TL:beam:orbit:{x,y,names,uids}``, ``TL:beam:twiss:{x,y}:{beta,alpha,nu}``,
  ``TL:beam:emittance:{x,y}`` (writable), ``TL:survey:s``; PVA
  ``TL:ORBITCC:rdBpm`` (BPMZ* and striplines SLZ*, in lattice order, nm),
  ``TL:ORBITCC:rdModel``

``DT4ACC_BESSYTL_TWISS_IN``: yaml file with the beam entering the line
(default: the placeholder in resources/input/twiss_in.yaml).
"""
import asyncio
import getpass
import logging
import os
from dataclasses import dataclass, field
from importlib import resources
from typing import List

import at

from softioc import builder, softioc

from dt4acc.config.data.querries import configure_data_file
from dt4acc.core.bl.controller import Controller, read_and_dispatch
from dt4acc.core.bl import random_numbers
from dt4acc.core.bl.noise import BpmNoise
from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc.custom_epics.ioc.controller import dispatcher
from dt4acc.custom_epics.ioc.noise_pvs import initialize_bpm_noise_pvs
from dt4acc.custom_epics.ioc.orbit_pva import OrbitTwinServer
from dt4acc.custom_epics.ioc.pv_setup import initialize_power_converter_pvs
from dt4acc.custom_facility.bessytl.twin_setup import (
    ACCELERATOR_SETUP,
    ORBIT_MONITOR_PREFIXES,
    bessytl_lattice,
    build_managers,
    load_twiss_in,
    monitor_names,
)
from dt4acc.custom_facility.bessytl.view import (
    TransferLineView,
    initialize_model_pvs,
    initialize_monitor_pvs,
    initialize_screen_mode_pvs,
    model_device,
)
from dt4acc_lib.bl.command_rewritter import CommandRewriter
from dt4acc_lib.model.utils.command import ReadCommand
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

logging.basicConfig(level=logging.WARNING)
logging.getLogger("lat2db").setLevel(level=logging.WARNING)
logger = logging.getLogger("dt4acc-bessytl")


@dataclass
class TransferLineTwin:
    line: at.Lattice
    controller: Controller
    view: TransferLineView
    monitors: List[str]
    #: on the BPMs' readings (noise:bpm:sa:...), off at start
    noise: BpmNoise = field(default_factory=BpmNoise)


def assemble(prefix: str, *, orbit_server: bool = True) -> TransferLineTwin:
    """Model, controller and view; ``orbit_server``: the PVA server of the BPM
    structures (``TL:ORBITCC``), left out in tests"""
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
    model = model_device(prefix)
    server = OrbitTwinServer(f"{model}:ORBITCC:rdBpm", f"{model}:ORBITCC:rdModel",
                             monitor_prefixes=ORBIT_MONITOR_PREFIXES) if orbit_server else None
    monitors = monitor_names(line)
    noise = BpmNoise()
    view = TransferLineView(monitors=monitors, orbit_server=server, bpm_noise=noise.sa,
                            elements=[e.FamName for e in line])
    controller = Controller(
        name="epics-bessytl-ctrller",
        mexec=mexec,
        view=view,
        default_delayed_reads=[ReadCommand("track", "pos"), ReadCommand("twiss", "parameters")],
    )
    return TransferLineTwin(line=line, controller=controller, view=view, monitors=monitors, noise=noise)


async def main():
    # the supplies and magnets the PVs are made for
    configure_data_file(resources.files("dt4acc").joinpath(*ACCELERATOR_SETUP))
    prefix = os.environ.get("DT4ACC_PREFIX", getpass.getuser())
    # the twin's random numbers, made now: a bad DT4ACC_SEED stops the twin here
    random_numbers.generator()
    twin = assemble(prefix)
    twin.view.orbit_server.start()
    twin.controller.start()
    await initialise_pvs(builder, prefix, twin)
    await read_and_dispatch(
        controller=twin.controller,
        view=twin.view,
        rcmds=[ReadCommand("survey", "s")] + list(twin.controller.default_delayed_reads),
    )
    builder.LoadDatabase()
    softioc.iocInit(dispatcher)
    softioc.interactive_ioc(globals())


async def initialise_pvs(builder, prefix: str, twin: TransferLineTwin) -> None:
    """The line's records, handed to its view: devices under their machine
    names (``<prefix>:Q1PT:set``), the model under ``<prefix>:TL``

    The PV names are the twin's interface (``pv_list.md``,
    ``tests/bessytl/test_bessytl_pvs.py``).
    """
    if prefix:
        builder.SetDeviceName(prefix)
    twin.view.update_process_variables({
        **await initialize_power_converter_pvs(builder, controller=twin.controller),
        **initialize_monitor_pvs(twin.monitors, builder=builder),
        **initialize_screen_mode_pvs(twin.view, builder=builder),
    })
    # a line: no turn by turn, the trajectory is the BPMs' slow acquisition
    # (under the prefix, not under TL: as the ring's and the MLS's noise PVs)
    initialize_bpm_noise_pvs(twin.noise, builder=builder, kinds=("sa",),
                             on_change={"sa": twin.view.republish_monitors})
    builder.SetDeviceName(model_device(prefix))
    twin.view.update_process_variables(initialize_model_pvs(builder, twin.view, n_elements=len(twin.line) + 1))


def run():
    """console script: the twin runs until its IOC shell ends"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
