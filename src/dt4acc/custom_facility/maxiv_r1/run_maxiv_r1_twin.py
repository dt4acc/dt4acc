#!/usr/bin/env python3
"""
run_maxiv_r1_twin.py
====================
Launch the MAX IV R1 digital twin TANGO server with the generated
liaison / translator setup in this directory (see README.md): validated
against MAX IV's own Matlab Middle Layer, it needs the dt4acc-lib curve
conversion fix (dt4acc-lib PR #29).

Usage
-----
    dt4acc_maxiv_r1                                  # installed entry point
    python run_maxiv_r1_twin.py                      # direct
    python run_maxiv_r1_twin.py --lattice PATH       # custom lattice
    python run_maxiv_r1_twin.py --heartbeat-period 0 # disable heartbeat

Files
-----
    lattice      ~/Documents/dt4acc_config_data/R1_lat_indexed.json (default,
                 --lattice / DT4ACC_LATTICE_FILE to override); the generated
                 tables name its slices ("sqfi73", ...)
    devices      ~/Documents/dt4acc_config_data/accelerator_setup.json
                 (default, DT4ACC_ACCELERATOR_SETUP_FILE to override): the
                 device database the TANGO devices are registered from; copy
                 resources/accelerator_setup_maxiv_r1.json there, it is
                 generated together with the tables so that both agree

Environment variables (all optional, CLI args take precedence)
--------------------------------------------------------------
    DT4ACC_LATTICE_FILE             Path to the MAX IV R1 AT lattice JSON file
    DT4ACC_ACCELERATOR_SETUP_FILE   Path to the device database JSON
    DT4ACC_TANGO_HOST               Tango database host:port  (default: localhost:10000)
    DT4ACC_VIEW                     view mode (default: device)
"""

import argparse
import os
import sys
from importlib.resources import files
from pathlib import Path

from dt4acc.config.data.querries import get_data_file
from dt4acc.core.bl import handle_lattice
from dt4acc.custom_tango.ioc import mexec_config, mexec_server_for_physics_engine

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DATA_DIR = Path.home() / "Documents" / "dt4acc_config_data"

DEFAULT_LATTICE_FILE = DATA_DIR / "R1_lat_indexed.json"

# generated together with the liaison / translator tables of this package
GENERATED_SETUP_FILE = files("dt4acc").joinpath(
    "custom_facility", "maxiv_r1", "resources", "accelerator_setup_maxiv_r1.json"
)

DEFAULT_HEARTBEAT_PERIOD_S = 1.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Launch the MAX IV R1 digital twin TANGO server (generated setup)"
    )
    parser.add_argument(
        "--lattice",
        type=Path,
        default=Path(os.environ.get("DT4ACC_LATTICE_FILE", DEFAULT_LATTICE_FILE)),
        help=f"Path to the MAX IV R1 AT lattice JSON file (default: {DEFAULT_LATTICE_FILE})",
    )
    parser.add_argument(
        "--tango-host",
        default=os.environ.get("DT4ACC_TANGO_HOST", "localhost:10000"),
        help="Tango database host:port (default: localhost:10000)",
    )
    parser.add_argument(
        "--heartbeat-period",
        type=float,
        default=DEFAULT_HEARTBEAT_PERIOD_S,
        help=f"Recalculation period in seconds, 0 to disable (default: {DEFAULT_HEARTBEAT_PERIOD_S})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=50200,
        help="TCP port for the MexecService manager (default: 50200)",
    )
    parser.add_argument(
        "--no-settle-supplies",
        action="store_true",
        help="start from the lattice file as is, instead of writing every power"
             " supply's nominal current (translated from that lattice) once",
    )
    parser.add_argument(
        "--view",
        type=str,
        default=os.environ.get("DT4ACC_VIEW", "device"),
        help="View mode: 'device' (MAX IV default) or 'design' (default: device)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# MAX IV R1 load_managers (generated)
# ---------------------------------------------------------------------------

def _maxiv_r1_load_managers():
    """Load the generated MAX IV R1 liaison manager and translator service."""
    from dt4acc.custom_facility.maxiv_r1.liasion_translator_setup import load_managers
    return load_managers()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    if not args.lattice.exists():
        print(f"ERROR: Lattice file not found: {args.lattice}", file=sys.stderr)
        print(
            f"       Copy R1_lat_indexed.json to {DATA_DIR}/ or pass --lattice PATH",
            file=sys.stderr,
        )
        sys.exit(1)

    setup_file = get_data_file()
    if not setup_file.exists():
        print(f"ERROR: Device database not found: {setup_file}", file=sys.stderr)
        print(
            f"       Copy {GENERATED_SETUP_FILE} there"
            " or set DT4ACC_ACCELERATOR_SETUP_FILE",
            file=sys.stderr,
        )
        sys.exit(1)

    print("MAX IV R1 twin server starting (generated setup)")
    print(f"  Lattice          : {args.lattice}")
    print(f"  Devices          : {setup_file}")
    print(f"  TANGO            : {args.tango_host}")
    print(f"  Recalc period    : {args.heartbeat_period}s (no lattice changes)")
    print(f"  MexecPort        : {args.port}")
    print(f"  View             : {args.view}")
    print(f"  Settle supplies  : {not args.no_settle_supplies}")

    os.environ["TANGO_HOST"] = args.tango_host

    from dt4acc.custom_tango.ioc import server_manager
    from dt4acc.custom_tango.ioc.single_server import enable_device_view_readback

    enable_device_view_readback()

    handle_lattice.lattice_loader.set_lattice_file(args.lattice)
    mexec_server_for_physics_engine.LOAD_MANAGERS_FN = _maxiv_r1_load_managers
    server_manager.HEARTBEAT_PERIOD = args.heartbeat_period
    mexec_config._MANAGER_PORT = args.port
    # device view: the Tango devices are MAX IV's power converters and magnets,
    # translated into the lattice by the liaison manager / translation service
    # (all slices and components with their shares). Set before the servers
    # start; DT4ACC_VIEW is inherited by their processes.
    mexec_server_for_physics_engine.set_expected_view(args.view)
    # the lattice file is not in the liaison's image (no dipole share on the
    # combined-function quadrupole slices, ...): start at the supplies'
    # nominal currents, so that writing back what a device reads is a no-op
    os.environ["DT4ACC_SETTLE_SUPPLIES"] = "0" if args.no_settle_supplies else "1"

    server_manager.main()


if __name__ == "__main__":
    main()
