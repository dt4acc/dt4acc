"""The command line of the SOLEIL injection twin, and the environment of its two twins:
each runs as it does on its own, with its own physics engine, on one Tango database"""
import argparse
import os
from pathlib import Path
from typing import Dict

from dt4acc.custom_facility.soleil.utils import command_line_interface as ring_cli
from dt4acc.custom_facility.soleil_tl2.utils import command_line_interface as tl_cli

TL_SIM_DEV = "simulator/tlsimulator/tlsimulator"
DEFAULT_RING_SETUP_FILE = Path.home() / "Documents" / "dt4acc_config_data" / "accelerator_setup.json"
#: what one twin's environment must not pass on to the other
TWIN_VARIABLES = ("DT4ACC_SIM_DEVICE", "DT4ACC_TWISS_IN_FILE", "DT4ACC_LATTICE_FILE", "DT4ACC_VIEW",
                  "DT4ACC_ACCELERATOR_SETUP_FILE", "DT4ACC_LOAD_MANAGERS", "DT4ACC_MEXEC_PORT")


def build_args_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SOLEIL injection twin: storage ring and TL2 together")
    parser.add_argument("--tango-host", default=os.environ.get("DT4ACC_TANGO_HOST", "localhost:10000"))
    parser.add_argument("--ring-lattice", type=Path, default=ring_cli.DEFAULT_LATTICE_FILE)
    parser.add_argument("--ring-setup", type=Path, default=DEFAULT_RING_SETUP_FILE)
    parser.add_argument("--ring-port", type=int, default=50200, help="physics engine of the ring")
    parser.add_argument("--tl-lattice", type=Path, default=tl_cli.DEFAULT_LATTICE_FILE)
    parser.add_argument("--tl-setup", type=Path, default=tl_cli.DEFAULT_SETUP_FILE)
    parser.add_argument("--tl-twiss-in", type=Path, default=tl_cli.DEFAULT_TWISS_IN_FILE)
    parser.add_argument("--tl-port", type=int, default=50210, help="physics engine of TL2")
    return parser


def _base_env(args) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in TWIN_VARIABLES}
    env["TANGO_HOST"] = args.tango_host
    return env


def ring_env(args) -> Dict[str, str]:
    return {**_base_env(args), "DT4ACC_ACCELERATOR_SETUP_FILE": str(args.ring_setup)}


def tl_env(args) -> Dict[str, str]:
    return {**_base_env(args), "DT4ACC_ACCELERATOR_SETUP_FILE": str(args.tl_setup), "DT4ACC_SIM_DEVICE": TL_SIM_DEV}
