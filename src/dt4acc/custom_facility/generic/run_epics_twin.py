"""Generic EPICS digital twin launcher.

Starts an EPICS soft-IOC digital twin for any lattice + accelerator_setup.json
catalog pair conforming to the generic schema (Quadrupole/Sextupole/Steerer,
one power converter per magnet — see
``custom_facility.generic.liasion_translator_setup``). No facility-specific
code is required: this is the EPICS-side equivalent of
``custom_facility.soleil.run_soleil_twin`` for Tango.

If neither ``--lattice``/``DT4ACC_LATTICE_FILE`` nor
``--accelerator-setup-file``/``DT4ACC_ACCELERATOR_SETUP_FILE`` are supplied,
falls back to the bundled FODO test lattice/catalog under ``resources/``.
"""

import argparse
import asyncio
import getpass
import logging
import os
from pathlib import Path
from typing import Dict, Any

from importlib import resources

from softioc import builder, softioc

from dt4acc.core.bl.controller import read_and_dispatch
from dt4acc.core.bl.handle_lattice import lattice_loader
from dt4acc.core.interfaces.controller_interface import ControllerInterface
from dt4acc.config.data.querries import configure_data_file
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
from dt4acc.custom_facility.generic.liasion_translator_setup import load_managers

logging.basicConfig(level=logging.WARNING)
logging.getLogger("dt4acc_lib").setLevel(level=logging.WARNING)
logging.getLogger("transitions").setLevel(level=logging.WARNING)
logging.getLogger("transitions.core").setLevel(level=logging.WARNING)
logger = logging.getLogger("dt4acc-epics")

_DEFAULT_LATTICE_FILE = resources.files("dt4acc").joinpath(
    "custom_facility/generic/resources/fodo_lattice.json"
)
_DEFAULT_ACCELERATOR_SETUP_FILE = resources.files("dt4acc").joinpath(
    "custom_facility/generic/resources/accelerator_setup.json"
)

# A generous margin over the loaded lattice's element count, so orbit/twiss/
# survey waveform PVs never truncate a lattice larger than the bundled FODO
# test lattice (whose element count is below the BESSY-derived default).
_N_ELEMENTS_MARGIN = 100


def _build_args_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the generic EPICS digital twin for a given lattice + accelerator_setup.json.",
    )
    parser.add_argument(
        "--lattice",
        help="PyAT lattice file (.m or .json). "
        "Default: DT4ACC_LATTICE_FILE, else the bundled FODO test lattice.",
    )
    parser.add_argument(
        "--accelerator-setup-file",
        help="accelerator_setup.json catalog file. "
        "Default: DT4ACC_ACCELERATOR_SETUP_FILE, else the bundled FODO test catalog.",
    )
    parser.add_argument(
        "--prefix",
        help="EPICS PV prefix. Default: DT4ACC_PREFIX, else the current user name.",
    )
    return parser


def _resolve_path(cli_value, env_name: str, default) -> Path:
    resolved = cli_value or os.environ.get(env_name) or default
    return Path(resolved)


async def main(argv=None):
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
    args = _build_args_parser().parse_args(argv)

    lattice_file = _resolve_path(args.lattice, "DT4ACC_LATTICE_FILE", _DEFAULT_LATTICE_FILE)
    if not lattice_file.exists():
        raise SystemExit(f"Error: lattice file not found: {lattice_file}")

    accelerator_setup_file = _resolve_path(
        args.accelerator_setup_file, "DT4ACC_ACCELERATOR_SETUP_FILE", _DEFAULT_ACCELERATOR_SETUP_FILE
    )
    if not accelerator_setup_file.exists():
        raise SystemExit(f"Error: accelerator setup file not found: {accelerator_setup_file}")

    # dt4acc.config.data.querries resolves its data file from
    # DT4ACC_ACCELERATOR_SETUP_FILE only once, at import time - by the time
    # we get here it has typically already been imported (transitively, via
    # pv_setup/liasion_translator_setup above). Point it explicitly at the
    # resolved path before anything reads the catalog.
    configure_data_file(accelerator_setup_file)

    lattice_loader.set_lattice_file(lattice_file)
    acc = lattice_loader.load()
    backend = SimulatorBackend(
        name="EPICS_twin",
        acc=PyATAcceleratorSimulator(at_lattice=acc),
    )

    yp, lm, ts = load_managers(acc)

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

    prefix = args.prefix or os.environ.get("DT4ACC_PREFIX", getpass.getuser())
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

    n_elements = len(acc) + _N_ELEMENTS_MARGIN

    view.update_process_variables(
        await initialise_pvs(
            builder=builder,
            controller=controller,
            cavity_names=yp.cavity_names(),
            n_elements=n_elements,
        )
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
    builder,
    controller: ControllerInterface,
    cavity_names=None,
    n_elements=None,
) -> Dict[ReadCommand, Any]:
    cavity_kwargs = {} if cavity_names is None else {"cavity_names": cavity_names}
    n_elements_kwargs = {} if n_elements is None else {"n_elements": n_elements}

    return {
        **await initialize_master_clock_pvs(builder, controller=controller),
        **await initialize_cavity_pvs(builder, controller=controller, **cavity_kwargs),
        **await initialize_power_converter_pvs(builder, controller=controller),
        **initialize_machine_info_pvs(builder, n_ref_buckets=400),
        **initialize_survey_info_pvs(builder, **n_elements_kwargs),
        **initialize_orbit_object_pvs(builder),
        **initialize_orbit_pvs(builder, **n_elements_kwargs),
        **initialize_twiss_pvs(builder, **n_elements_kwargs),
        **initialize_tune_pvs(builder),
        **initialize_other_pvs(builder),
    }


if __name__ == "__main__":
    asyncio.run(main())
