"""MLS storage ring twin: EPICS soft IOC (CA and PVA)

PVs (``<P>`` is ``DT4ACC_PREFIX``, default: the user name), named as on the
machine where MML knows them (``ao_mls.json``):

* supplies: ``<P>:<supply>:setCur`` (acts), ``<P>:<supply>:rdCur`` [A]
* BPMs: ``<P>:<bpm>:rdX``, ``<P>:<bpm>:rdY`` [mm]
* RF: ``<P>:MCLKHGP:setFrq`` (acts), ``<P>:MCLKHGP:rdFrq`` [kHz]
* beam current: ``<P>:CUM1ZK3RP:rdCur``
* twin only: magnets ``<P>:<magnet>:Cm:setCur``, ``Cm:rdCur``, ``im:I``,
  ``x:setCur``, ``y:setCur``; the model (``beam:orbit:*``, ``beam:twiss:*``,
  ``survey:*``, ``TUNEZR:*``, ``ORBITCCP:rdBpm`` / ``rdModel`` over PVA)
"""
import asyncio
import getpass
import logging
import os
from typing import Any, Dict, Sequence

from softioc import builder, softioc

from dt4acc.config.data.querries import configure_data_file
from dt4acc.core.bl.controller import Controller, read_and_dispatch
from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc.core.interfaces.controller_interface import ControllerInterface
from dt4acc.custom_epics.ioc.controller import dispatcher
from dt4acc.custom_epics.ioc.orbit_pva import OrbitTwinServer
from dt4acc.custom_epics.ioc.pv_setup import (
    PVFields,
    initialize_calculation_state_pvs,
    initialize_cavity_pvs,
    initialize_machine_info_pvs,
    initialize_master_clock_pvs,
    initialize_orbit_pvs,
    initialize_other_pvs,
    initialize_power_converter_pvs,
    initialize_survey_info_pvs,
    initialize_tune_pvs,
    initialize_twiss_pvs,
)
from dt4acc.custom_facility.mls.twin_setup import (
    ACCELERATOR_SETUP,
    HARMONIC_NUMBER,
    bpm_names,
    build_managers,
    mls_lattice,
    resource,
)
from dt4acc.custom_facility.mls.view import MLSView, initialize_bpm_pvs
from dt4acc_lib.bl.command_rewritter import CommandRewriter
from dt4acc_lib.model.utils.command import ReadCommand
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

logging.basicConfig(level=logging.WARNING)
logging.getLogger("lat2db").setLevel(level=logging.WARNING)
logging.getLogger("transitions").setLevel(level=logging.WARNING)
logger = logging.getLogger("dt4acc-mls")

#: MLS supply and magnet PV fields (MML: ``<supply>:setCur`` / ``rdCur``)
MLS_FIELDS = PVFields(
    supply_set="setCur", supply_rdbk="rdCur",
    magnet_set="Cm:setCur", magnet_rdbk="Cm:rdCur", magnet_current="im:I",
    magnet_x="x:setCur", magnet_y="y:setCur",
)
MASTER_CLOCK = "MCLKHGP"
CAVITIES = ("CAV",)
BEAM_CURRENT = "CUM1ZK3RP"
DELAYED = [ReadCommand("track", "pos"), ReadCommand("twiss", "parameters")]


def make_controller(backend, view, name="mls") -> Controller:
    lm, ts = build_managers()
    mexec = TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=CommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )
    return Controller(name=name, mexec=mexec, view=view, default_delayed_reads=DELAYED)


async def initialise_pvs(builder, controller: ControllerInterface, bpms: Sequence[str], *, n_elements: int
                         ) -> Dict[ReadCommand, Any]:
    """PVs of the MLS ring; the names are the twin's interface (``pv_list.md``,
    ``tests/mls/test_mls_twin.py``)"""
    # the supplies' and magnets' PVs are made from the device database
    configure_data_file(resource(ACCELERATOR_SETUP))
    return {
        **await initialize_master_clock_pvs(builder, controller=controller, master_clock_pv_name=MASTER_CLOCK,
                                            set_field="setFrq", rdbk_field="rdFrq"),
        **await initialize_cavity_pvs(builder, controller=controller, cavity_names=CAVITIES),
        **await initialize_power_converter_pvs(builder, controller=controller, fields=MLS_FIELDS),
        **initialize_bpm_pvs(bpms, builder=builder),
        **initialize_machine_info_pvs(builder, n_ref_buckets=HARMONIC_NUMBER),
        **initialize_survey_info_pvs(builder, n_elements=n_elements),
        **initialize_orbit_pvs(builder, n_elements=n_elements),
        **initialize_twiss_pvs(builder, n_elements=n_elements),
        **initialize_tune_pvs(builder),
        **initialize_other_pvs(builder, current_pv_name=BEAM_CURRENT, current_field="rdCur"),
        **initialize_calculation_state_pvs(builder, controller),
    }


async def main():
    ring = mls_lattice()
    backend = SimulatorBackend(name="MLS_on_PyAT", acc=PyATAcceleratorSimulator(at_lattice=ring))
    prefix = os.environ.get("DT4ACC_PREFIX", getpass.getuser())
    pva_prefix = prefix + ":" if prefix else ""
    orbit_server = OrbitTwinServer(pva_prefix + "ORBITCCP:rdBpm", pva_prefix + "ORBITCCP:rdModel")
    orbit_server.start()
    bpms = bpm_names(ring)
    view = MLSView(bpms=bpms, orbit_server=orbit_server)
    controller = make_controller(backend, view)
    controller.start()
    if prefix:
        builder.SetDeviceName(prefix)

    view.update_process_variables(await initialise_pvs(builder, controller, bpms, n_elements=len(ring) + 1))
    await read_and_dispatch(
        controller=controller, view=view, rcmds=[ReadCommand("survey", "s")] + list(controller.default_delayed_reads)
    )
    builder.LoadDatabase()
    softioc.iocInit(dispatcher)
    logger.warning("MLS twin: %d elements, %d BPMs, prefix %s", len(ring), len(bpms), prefix)
    softioc.interactive_ioc(globals())


def run():
    """console script: the twin runs until its IOC shell ends"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
