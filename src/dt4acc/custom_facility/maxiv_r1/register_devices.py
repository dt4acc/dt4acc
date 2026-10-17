#!/usr/bin/env python3
"""
register_devices.py
===================
Register the MAX IV R1 twin devices in the Tango database, with the same
device database, lattice and liaison / translator setup as
run_maxiv_r1_twin.py. The twin only starts the devices it finds in the
database, so run this once on a fresh database before starting it, with
the twin stopped (registering unexports the devices of a running twin).

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
import sys
from pathlib import Path

from dt4acc.config.data.querries import get_data_file
from dt4acc.custom_facility.maxiv_r1.run_maxiv_r1_twin import (
    DEFAULT_LATTICE_FILE,
    _maxiv_r1_load_managers,
)
from dt4acc.core.bl import handle_lattice
from dt4acc.custom_tango.ioc import mexec_server_for_physics_engine


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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Register even if the twin looks running (stale export after a crash)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    os.environ["TANGO_HOST"] = args.tango_host

    from dt4acc.custom_tango.ioc.devices.tango_device_setup import (
        check_devices,
        register_all_devices,
    )

    print(f"  Lattice : {args.lattice}")
    print(f"  Devices : {get_data_file()}")
    print(f"  TANGO   : {args.tango_host}")

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

    # re-adding a device marks it not exported: a running twin's devices
    # would become unreachable until it is restarted
    import tango
    from dt4acc.custom_tango.ioc.devices.virtual_devices import RING_SIM_DEV

    exported = tango.Database().get_device_exported(RING_SIM_DEV).value_string
    if not args.force and RING_SIM_DEV.lower() in (d.lower() for d in exported):
        print(
            f"ERROR: {RING_SIM_DEV} is exported, the twin seems to be running.\n"
            "       Stop it before registering (or use --check; --force if it crashed).",
            file=sys.stderr,
        )
        sys.exit(1)

    servers = register_all_devices()
    print(f"Registered {len(servers)} servers")
    pprint.pprint(servers, compact=True)


if __name__ == "__main__":
    main()
