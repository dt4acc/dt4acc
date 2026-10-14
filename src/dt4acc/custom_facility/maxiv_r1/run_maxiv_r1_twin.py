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
    devices      resources/accelerator_setup_maxiv_r1.json (default,
                 DT4ACC_ACCELERATOR_SETUP_FILE to override): the device
                 database the TANGO devices are registered from, generated
                 together with the tables so that both agree

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

# The device database must be chosen before dt4acc.config.data.querries is
# imported anywhere (it reads the variable at import time), and is inherited
# by the processes the server starts.
_DEFAULT_SETUP_FILE = files("dt4acc").joinpath(
    "custom_facility", "maxiv_r1", "resources", "accelerator_setup_maxiv_r1.json"
)
os.environ.setdefault("DT4ACC_ACCELERATOR_SETUP_FILE", str(_DEFAULT_SETUP_FILE))

from dt4acc.core.bl import handle_lattice  # noqa: E402
from dt4acc.custom_tango.ioc import mexec_config, mexec_server_for_physics_engine  # noqa: E402

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DATA_DIR = Path.home() / "Documents" / "dt4acc_config_data"

DEFAULT_LATTICE_FILE = DATA_DIR / "R1_lat_indexed.json"

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

    print("MAX IV R1 twin server starting (generated setup)")
    print(f"  Lattice          : {args.lattice}")
    print(f"  Devices          : {os.environ['DT4ACC_ACCELERATOR_SETUP_FILE']}")
    print(f"  TANGO            : {args.tango_host}")
    print(f"  Recalc period    : {args.heartbeat_period}s (no lattice changes)")
    print(f"  MexecPort        : {args.port}")
    print(f"  View             : {args.view}")

    os.environ["TANGO_HOST"] = args.tango_host

    from dt4acc.config.data.querries import configure_data_file
    from dt4acc.custom_tango.ioc import server_manager
    from dt4acc.custom_tango.ioc.single_server import enable_device_view_readback

    configure_data_file(os.environ["DT4ACC_ACCELERATOR_SETUP_FILE"])
    enable_device_view_readback()

    handle_lattice.lattice_loader.set_lattice_file(args.lattice)
    mexec_server_for_physics_engine.LOAD_MANAGERS_FN = _maxiv_r1_load_managers
    server_manager.HEARTBEAT_PERIOD = args.heartbeat_period
    mexec_config._MANAGER_PORT = args.port
    server_manager.EXPECTED_VIEW    = args.view

    server_manager.main()


if __name__ == "__main__":
    main()
