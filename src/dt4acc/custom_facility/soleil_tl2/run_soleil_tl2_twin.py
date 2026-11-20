#!/usr/bin/env python3
"""
run_soleil_tl2_twin.py
======================

Launch script for the SOLEIL TL2 digital twin TANGO server, as run_soleil_twin.py
for the ring. The steps, in the folder of SOLEIL's TL2 files:

    python -m dt4acc.custom_facility.soleil_tl2.yml2json_soleil_tl2
    python -m dt4acc.custom_facility.soleil_tl2.register_devices --register-devices
    python -m dt4acc.custom_facility.soleil_tl2.run_soleil_tl2_twin

Environment variables (all optional, CLI args take precedence)
--------------------------------------------------------------
    DT4ACC_LATTICE_FILE            Path to the TL2 lattice
    DT4ACC_TWISS_IN_FILE           Path to the beam entering the line
    DT4ACC_ACCELERATOR_SETUP_FILE  Path to the device database
    DT4ACC_TANGO_HOST              Tango database host:port  (default: localhost:10000)
    DT4ACC_VIEW                    Design or Device view (default: design, as the ring;
                                   device: the supplies too, ``--view device``)
"""

import os
import sys

from dt4acc.core.bl import handle_lattice
from dt4acc.custom_facility.soleil_tl2.utils.command_line_interface import (
    display_setup_from_args,
    parse_args,
    setup_environment,
)


def _soleil_tl2_load_managers():
    """Load the SOLEIL TL2 liaison manager and translator service."""
    from dt4acc.custom_facility.soleil_tl2.liasion_translator_setup import load_managers
    return load_managers()


def main():
    args = parse_args()
    setup_environment(args)

    for path in (args.lattice, args.twiss_in):
        if not path.exists():
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            sys.exit(1)

    from dt4acc.custom_tango.ioc import mexec_config, mexec_server_for_physics_engine, server_manager

    print("Starting SOLEIL TL2 Digital Twin (all servers)")
    display_setup_from_args(args)
    os.environ["DT4ACC_MEXEC_PORT"] = str(args.port)

    handle_lattice.lattice_loader.set_lattice_file(args.lattice)
    mexec_server_for_physics_engine.LOAD_MANAGERS_FN = _soleil_tl2_load_managers
    server_manager.HEARTBEAT_PERIOD = args.heartbeat_period
    mexec_config._MANAGER_PORT = args.port
    mexec_server_for_physics_engine.EXPECTED_VIEW = args.view

    if args.view == "device":
        # magnet devices and supplies read their value from the lattice: each follows the other's writes
        from dt4acc.custom_tango.ioc.single_server import enable_device_view_readback, enable_supply_readback

        enable_device_view_readback()
        enable_supply_readback()

    server_manager.main()


if __name__ == "__main__":
    main()
