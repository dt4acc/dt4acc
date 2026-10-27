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
from importlib import resources

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


async def main():
    prefix = os.environ.get("DT4ACC_PREFIX", getpass.getuser())

    # storage ring
    ring_backend = provide_backend_encapsulating_lattice()
    _, ring_lm, ring_ts, ring_pv_col = load_managers()
    ring_view = View(orbit_server=OrbitTwinServer(f"{prefix}:ORBITCC:rdBpm", f"{prefix}:ORBITCC:rdModel"))
    ring_view.orbit_server.start()
    ring = Controller(name="ring", mexec=engine(ring_backend, ring_lm, ring_ts), view=ring_view,
                      default_delayed_reads=DELAYED)

    # transfer line, up to the septum exit
    configure_data_file(resources.files("dt4acc").joinpath(*ACCELERATOR_SETUP))
    line = bessytl_lattice(end_after=SEPTUM)
    line_backend = SimulatorBackend(
        name="BESSYII_TL_on_PyAT", acc=PyATAcceleratorSimulator(at_lattice=line, twiss_in=load_twiss_in())
    )
    line_lm, line_ts = line_managers()
    line_monitors = monitor_names(line)
    line_view = TransferLineView(
        monitors=line_monitors,
        orbit_server=OrbitTwinServer(f"{prefix}:TL:ORBITCC:rdBpm", f"{prefix}:TL:ORBITCC:rdModel"),
    )
    line_view.orbit_server.start()
    tl = Controller(name="transfer-line", mexec=engine(line_backend, line_lm, line_ts), view=line_view,
                    default_delayed_reads=DELAYED)

    # hand over
    ring_bpms = [e.FamName for e in ring_backend.acc.acc if isinstance(e, at.Monitor) and e.FamName.startswith("BPMZ")]
    handover = InjectionHandover(line=line_backend, ring=ring_backend, monitors=ring_bpms)

    # machine names: ring, hand over, transfer line devices
    builder.SetDeviceName(prefix)
    ring_view.update_process_variables(await ring_pvs(builder=builder, models=ring_pv_col.vars, controller=ring))
    injection = InjectionPVs(handover)
    line_view.update_process_variables({
        **await initialize_power_converter_pvs(builder, controller=tl),
        **initialize_monitor_pvs(line_monitors),
    })
    # model PVs of the transfer line: the ring has the same names
    builder.SetDeviceName(f"{prefix}:TL")
    n_elements = len(line) + 1
    line_view.update_process_variables({
        **initialize_survey_info_pvs(builder, n_elements=n_elements),
        **initialize_orbit_pvs(builder, n_elements=n_elements),
        **initialize_twiss_pvs(builder, n_elements=n_elements),
    })
    hook_track_updates(ring_view, injection)
    hook_track_updates(line_view, injection)

    ring.start()
    tl.start()
    for controller, view in ((ring, ring_view), (tl, line_view)):
        await read_and_dispatch(
            controller=controller, view=view, rcmds=[ReadCommand("survey", "s")] + list(DELAYED)
        )
    builder.LoadDatabase()
    softioc.iocInit(dispatcher)
    logger.warning(
        "BESSY II injection twin: ring %d elements, transfer line %d elements up to %s, %d ring BPMs",
        len(ring_backend.acc.acc), len(line), SEPTUM, len(ring_bpms),
    )
    softioc.interactive_ioc(globals())


if __name__ == "__main__":
    asyncio.run(main())
