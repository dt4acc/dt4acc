"""BESSY II injection twin: transfer line and storage ring in one IOC

"Injection" here is the injection into the storage ring: the beam extracted
from the booster passes the transfer line (booster -> storage ring) and is
injected at the septa. It is not the injection line (LINAC -> booster), which
this twin does not model.

Two models, as two MML submachines, each with its own devices and its own
simulation engine, and the hand over of the beam between them:

* storage ring: the BESSY II ring twin, PVs as there (``<P>:Q1PDR:set``,
  ``<P>:beam:orbit:x``, ...)
* transfer line: the transfer line twin cut at the injection septum exit,
  with the same PV names as the transfer line twin on its own. Its devices
  keep their machine names (``<P>:Q1PT:set``, ``<P>:Q1MT:Cm:rdbk``,
  ``<P>:FOMZ1T:image``; they do not clash with the ring's: line names end in
  T, ring names in R), its model is under ``TL``: ``<P>:TL:beam:orbit:*``,
  ``<P>:TL:beam:twiss:*``, ``<P>:TL:beam:emittance:*``, ``<P>:TL:survey:*``,
  ``<P>:TL:ORBITCC:*``
* hand over: ``<P>:INJ:...`` (see ``pvs.py``): the beam leaving the line,
  put into the ring at ``MSEPEXIT`` and tracked turn by turn, when a shot is
  fired (``<P>:INJ:trigger``; to fire shots from a client, e.g. at a
  repetition rate: :mod:`.mockup`). The line's monitors (BPMs, screens,
  ``TL:ORBITCC:rdBpm``) show the beam passing only then; its model
  (``TL:beam:orbit:*``, ``TL:beam:twiss:*``) and the ring's closed orbit follow
  every change

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
from dt4acc.custom_facility.bessyii.run_bessyii_twin import initialise_pvs as ring_pvs, initialise_pinhole_pvs
from dt4acc.custom_epics.ioc.pinhole_pvs import hook_pinholes
from dt4acc.custom_facility.bessyii_injection.handover import InjectionHandover
from dt4acc.custom_facility.bessyii_injection.pvs import InjectionPVs
from dt4acc.custom_epics.ioc.pv_setup import initialize_power_converter_pvs
from dt4acc.custom_facility.bessytl.twin_setup import (
    ACCELERATOR_SETUP,
    ORBIT_MONITOR_PREFIXES,
    bessytl_lattice,
    build_managers as line_managers,
    load_twiss_in,
    monitor_names,
)
from dt4acc.custom_facility.bessytl.view import (
    TRACK,
    TWISS,
    TransferLineView,
    initialize_model_pvs,
    initialize_monitor_pvs,
    model_device,
)
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
DELAYED = [TRACK, TWISS]


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

    def orbit_server(p, **kwargs):
        return OrbitTwinServer(f"{p}:ORBITCC:rdBpm", f"{p}:ORBITCC:rdModel", **kwargs) if orbit_servers else None

    # storage ring
    ring_backend = provide_backend_encapsulating_lattice()
    _, ring_lm, ring_ts, _ = load_managers()
    ring_bpms = [e.FamName for e in ring_backend.acc.acc if isinstance(e, at.Monitor) and e.FamName.startswith("BPMZ")]
    ring_view = View(orbit_server=orbit_server(prefix), bpms=ring_bpms)
    ring = Controller(name="ring", mexec=engine(ring_backend, ring_lm, ring_ts), view=ring_view,
                      default_delayed_reads=DELAYED)

    # transfer line, up to the septum exit
    line = bessytl_lattice(end_after=SEPTUM)
    line_backend = SimulatorBackend(
        name="BESSYII_TL_on_PyAT", acc=PyATAcceleratorSimulator(at_lattice=line, twiss_in=load_twiss_in())
    )
    line_lm, line_ts = line_managers()
    line_monitors = monitor_names(line)
    # the line carries beam only during a shot (InjectionPVs, INJ:trigger)
    line_view = TransferLineView(
        monitors=line_monitors, single_pass=True,
        orbit_server=orbit_server(model_device(prefix), monitor_prefixes=ORBIT_MONITOR_PREFIXES),
    )
    tl = Controller(name="transfer-line", mexec=engine(line_backend, line_lm, line_ts), view=line_view,
                    default_delayed_reads=DELAYED)

    # hand over
    handover = InjectionHandover(line=line_backend, ring=ring_backend, monitors=ring_bpms)
    return InjectionTwin(ring_backend=ring_backend, ring=ring, ring_view=ring_view, line=line,
                         line_backend=line_backend, line_monitors=line_monitors, tl=tl, line_view=line_view,
                         handover=handover)


def line_shot(twin: InjectionTwin):
    """The transfer line's part of a shot: its monitors show the beam

    Trajectory and optics (the screens' beam size) are read when the shot is
    fired, not taken from the last delayed read: a shot right after a change
    sees the line as it is now. No trajectory (the line's optics failed): the
    BPMs show NaN, the screens a dark image.
    """
    async def shot():
        try:
            for rcmd in DELAYED:
                (translated,) = (await twin.tl.trigger_read([rcmd])).data
                await twin.line_view.dispatch(rcmd, translated)
        except Exception as exc:
            logger.error("injection: no transfer line trajectory for the shot: %s", exc)
            await twin.line_view.push_invalid()
        twin.line_view.fire()

    return shot


async def initialise_pvs(builder, prefix: str, twin: InjectionTwin) -> InjectionPVs:
    """Records of ring, hand over and transfer line, handed to their views

    The PV names are the twin's interface (``pv_list.md``,
    ``tests/bessyii_injection/test_injection_pvs.py``).
    """
    # machine names: ring, hand over, transfer line devices
    builder.SetDeviceName(prefix)
    twin.ring_view.update_process_variables(await ring_pvs(builder=builder, controller=twin.ring, bpms=twin.handover.monitors))
    hook_pinholes(twin.ring_view, initialise_pinhole_pvs(builder, twin.ring_backend))
    injection = InjectionPVs(twin.handover, builder=builder, before_shot=line_shot(twin))
    # the line's supplies and magnets come from its own device database
    configure_data_file(resources.files("dt4acc").joinpath(*ACCELERATOR_SETUP))
    twin.line_view.update_process_variables({
        **await initialize_power_converter_pvs(builder, controller=twin.tl),
        **initialize_monitor_pvs(twin.line_monitors, builder=builder),
    })
    # model PVs of the transfer line, under TL as in the transfer line twin
    # (the ring serves beam:*, ORBITCC:*)
    builder.SetDeviceName(model_device(prefix))
    twin.line_view.update_process_variables(
        initialize_model_pvs(builder, twin.line_view, n_elements=len(twin.line) + 1)
    )
    return injection


async def main():
    prefix = os.environ.get("DT4ACC_PREFIX", getpass.getuser())
    twin = assemble(prefix)
    for view in (twin.ring_view, twin.line_view):
        view.orbit_server.start()
    await initialise_pvs(builder, prefix, twin)

    twin.ring.start()
    twin.tl.start()
    for controller, view in ((twin.ring, twin.ring_view), (twin.tl, twin.line_view)):
        await read_and_dispatch(
            controller=controller, view=view, rcmds=[ReadCommand("survey", "s")] + list(DELAYED)
        )
    builder.LoadDatabase()
    softioc.iocInit(dispatcher)
    logger.warning(
        "BESSY II injection twin: ring %d elements, transfer line %d elements up to %s, %d ring BPMs;"
        " caput %s:INJ:trigger 1 to inject",
        len(twin.ring_backend.acc.acc), len(twin.line), SEPTUM, len(twin.handover.monitors), prefix,
    )
    softioc.interactive_ioc(globals())


def run():
    """console script: the twin runs until its IOC shell ends"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
