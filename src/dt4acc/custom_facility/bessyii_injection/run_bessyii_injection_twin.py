"""BESSY II injection twin: transfer line and storage ring in one IOC

Two models, as two MML submachines, each with its own devices and its own
simulation engine, and the hand over of the beam between them:

* storage ring: the BESSY II ring twin, PVs as there (``<P>:Q1PDR:set``,
  ``<P>:beam:orbit:x``, ...)
* transfer line: the transfer line twin cut at the injection septum exit.
  Its devices keep their machine names, as in the transfer line twin
  (``<P>:Q1PT:set``, ``<P>:Q1MT:Cm:rdbk``, ``<P>:FOMZ1T:x``; they do not
  clash with the ring's: line names end in T, ring names in R). Only its
  model PVs, which the ring has under the same names, are one level down:
  ``<P>:TL:beam:orbit:*``, ``<P>:TL:beam:twiss:*``, ``<P>:TL:survey:*``,
  ``<P>:TL:ORBITCC:*``
* hand over: ``<P>:INJ:...`` (see ``pvs.py``): the beam leaving the line,
  put into the ring at ``MSEPEXIT`` and tracked turn by turn; recomputed
  whenever line, ring or its settings change

``<P>`` is ``DT4ACC_PREFIX`` (default: the user name).
"""
import asyncio
import getpass
import logging
import os
from dataclasses import dataclass
from importlib import resources
from typing import List

import at
from softioc import builder, softioc

from dt4acc.config.data.querries import configure_data_file
from dt4acc.core.bl.controller import Controller, read_and_dispatch
from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc.custom_epics.ioc.controller import dispatcher
from dt4acc.custom_epics.ioc.orbit_pva import OrbitTwinServer
from dt4acc.custom_epics.ioc.view import View
from dt4acc.custom_facility.bessyii.liasion_translator_setup import load_managers
from dt4acc.custom_facility.bessyii.provide_lattice import provide_backend_encapsulating_lattice
from dt4acc.custom_facility.bessyii.run_bessyii_twin import initialise_pvs as ring_pvs
from dt4acc.custom_facility.bessyii_injection.handover import InjectionHandover
from dt4acc.custom_facility.bessyii_injection.pvs import InjectionPVs, hook_track_updates
from dt4acc.custom_epics.ioc.pv_setup import (
    initialize_orbit_pvs,
    initialize_power_converter_pvs,
    initialize_survey_info_pvs,
    initialize_twiss_pvs,
)
from dt4acc.custom_facility.bessytl.twin_setup import (
    ACCELERATOR_SETUP,
    bessytl_lattice,
    build_managers as line_managers,
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
logging.getLogger("transitions").setLevel(level=logging.WARNING)
logger = logging.getLogger("dt4acc-bessyii-injection")

#: the transfer line ends at the septum exit, where the ring takes over
SEPTUM = "SEK2D1R"
DELAYED = [ReadCommand("track", "pos"), ReadCommand("twiss", "parameters")]


def engine(backend, lm, ts):
    return TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=CommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )


@dataclass
class InjectionTwin:
    """Ring and transfer line, their controllers and views, and the hand over"""
    ring_backend: SimulatorBackend
    ring: Controller
    ring_view: View
    line: at.Lattice
    line_backend: SimulatorBackend
    line_monitors: List[str]
    tl: Controller
    line_view: TransferLineView
    handover: InjectionHandover


def assemble(prefix: str, *, orbit_servers: bool = True) -> InjectionTwin:
    """Models, controllers and views; ``orbit_servers``: the PVA servers of the
    BPM structures (``ORBITCC``), left out in tests"""

    def orbit_server(p):
        return OrbitTwinServer(f"{p}:ORBITCC:rdBpm", f"{p}:ORBITCC:rdModel") if orbit_servers else None

    # storage ring
    ring_backend = provide_backend_encapsulating_lattice()
    _, ring_lm, ring_ts, _ = load_managers()
    ring_view = View(orbit_server=orbit_server(prefix))
    ring = Controller(name="ring", mexec=engine(ring_backend, ring_lm, ring_ts), view=ring_view,
                      default_delayed_reads=DELAYED)

    # transfer line, up to the septum exit
    line = bessytl_lattice(end_after=SEPTUM)
    line_backend = SimulatorBackend(
        name="BESSYII_TL_on_PyAT", acc=PyATAcceleratorSimulator(at_lattice=line, twiss_in=load_twiss_in())
    )
    line_lm, line_ts = line_managers()
    line_monitors = monitor_names(line)
    line_view = TransferLineView(monitors=line_monitors, orbit_server=orbit_server(f"{prefix}:TL"))
    tl = Controller(name="transfer-line", mexec=engine(line_backend, line_lm, line_ts), view=line_view,
                    default_delayed_reads=DELAYED)

    # hand over
    ring_bpms = [e.FamName for e in ring_backend.acc.acc if isinstance(e, at.Monitor) and e.FamName.startswith("BPMZ")]
    handover = InjectionHandover(line=line_backend, ring=ring_backend, monitors=ring_bpms)
    return InjectionTwin(ring_backend=ring_backend, ring=ring, ring_view=ring_view, line=line,
                         line_backend=line_backend, line_monitors=line_monitors, tl=tl, line_view=line_view,
                         handover=handover)


async def initialise_pvs(builder, prefix: str, twin: InjectionTwin) -> InjectionPVs:
    """Records of ring, hand over and transfer line, handed to their views

    The PV names are the twin's interface (``pv_list.md``,
    ``tests/bessyii_injection/test_injection_pvs.py``).
    """
    # machine names: ring, hand over, transfer line devices
    builder.SetDeviceName(prefix)
    twin.ring_view.update_process_variables(await ring_pvs(builder=builder, controller=twin.ring))
    injection = InjectionPVs(twin.handover, builder=builder)
    # the line's supplies and magnets come from its own device database
    configure_data_file(resources.files("dt4acc").joinpath(*ACCELERATOR_SETUP))
    twin.line_view.update_process_variables({
        **await initialize_power_converter_pvs(builder, controller=twin.tl),
        **initialize_monitor_pvs(twin.line_monitors, builder=builder),
    })
    # model PVs of the transfer line: the ring has the same names
    builder.SetDeviceName(f"{prefix}:TL")
    n_elements = len(twin.line) + 1
    twin.line_view.update_process_variables({
        **initialize_survey_info_pvs(builder, n_elements=n_elements),
        **initialize_orbit_pvs(builder, n_elements=n_elements),
        **initialize_twiss_pvs(builder, n_elements=n_elements),
    })
    return injection


async def main():
    prefix = os.environ.get("DT4ACC_PREFIX", getpass.getuser())
    twin = assemble(prefix)
    for view in (twin.ring_view, twin.line_view):
        view.orbit_server.start()
    injection = await initialise_pvs(builder, prefix, twin)
    hook_track_updates(twin.ring_view, injection)
    hook_track_updates(twin.line_view, injection)

    twin.ring.start()
    twin.tl.start()
    for controller, view in ((twin.ring, twin.ring_view), (twin.tl, twin.line_view)):
        await read_and_dispatch(
            controller=controller, view=view, rcmds=[ReadCommand("survey", "s")] + list(DELAYED)
        )
    builder.LoadDatabase()
    softioc.iocInit(dispatcher)
    logger.warning(
        "BESSY II injection twin: ring %d elements, transfer line %d elements up to %s, %d ring BPMs",
        len(twin.ring_backend.acc.acc), len(twin.line), SEPTUM, len(twin.handover.monitors),
    )
    softioc.interactive_ioc(globals())


def run():
    """console script: the twin runs until its IOC shell ends"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
