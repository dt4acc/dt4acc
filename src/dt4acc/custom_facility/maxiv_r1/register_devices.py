#!/usr/bin/env python3
"""
register_devices.py
===================
Register the MAX IV R1 twin devices in the Tango database, with the same
device database, lattice and liaison / translator setup as
run_maxiv_r1_twin.py. The twin only starts the devices it finds in the
database, so run this once on a fresh database before starting it.

Usage
-----
    dt4acc_maxiv_r1_register                          # installed entry point
    python register_devices.py                        # direct
    python register_devices.py --check                # only report, register nothing
    python register_devices.py --lattice PATH         # custom lattice

Environment variables as for run_maxiv_r1_twin.py (DT4ACC_LATTICE_FILE,
DT4ACC_ACCELERATOR_SETUP_FILE, DT4ACC_TANGO_HOST).
"""

import argparse
import os
import pprint
from pathlib import Path

# imported first: chooses the device database before dt4acc.config.data.querries
from dt4acc.custom_facility.maxiv_r1.run_maxiv_r1_twin import (
    DEFAULT_LATTICE_FILE,
    _maxiv_r1_load_managers,
)
from dt4acc.core.bl import handle_lattice  # noqa: E402
from dt4acc.custom_tango.ioc import mexec_server_for_physics_engine  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Register the MAX IV R1 twin devices in the Tango database"
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
        "--check",
        action="store_true",
        help="Only report present / missing devices, register nothing",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    os.environ["TANGO_HOST"] = args.tango_host

    from dt4acc.config.data.querries import configure_data_file
    from dt4acc.custom_tango.ioc.devices.tango_device_setup import (
        check_devices,
        register_all_devices,
    )

    print(f"  Lattice : {args.lattice}")
    print(f"  Devices : {os.environ['DT4ACC_ACCELERATOR_SETUP_FILE']}")
    print(f"  TANGO   : {args.tango_host}")

    configure_data_file(os.environ["DT4ACC_ACCELERATOR_SETUP_FILE"])
    handle_lattice.lattice_loader.set_lattice_file(args.lattice)
    mexec_server_for_physics_engine.LOAD_MANAGERS_FN = _maxiv_r1_load_managers

    if args.check:
        report = check_devices()
        if report.errors:
            print("ERRORS:")
            pprint.pprint(report.errors, compact=True)
        if report.missing:
            print("missing:")
            pprint.pprint(report.missing, compact=True)
        print(
            f"errors {len(report.errors)} missing {len(report.missing)} "
            f"found {len(report.present)}"
        )
        return

    servers = register_all_devices()
    print(f"Registered {len(servers)} servers")
    pprint.pprint(servers, compact=True)


if __name__ == "__main__":
    main()
