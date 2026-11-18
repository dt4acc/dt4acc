#!/usr/bin/env python3
"""
run_maxiv_twin.py
==================

Launch script for the SOLEIL digital twin TANGO server.

Usage
-----
    python scripts/soleil/run_maxiv_twin.py [--lattice PATH] [--port PORT]

All SOLEIL-specific configuration is set here before handing off to the
generic server_manager. The server_manager itself has no hardcoded paths.

Directory layout
----------------
    scripts/
        soleil/
            run_maxiv_twin.py      ← this file
    src/
        dt4acc/
            custom_tango/
                ioc/
                    server_manager.py

Environment variables (all optional, CLI args take precedence)
--------------------------------------------------------------
    DT4ACC_LATTICE_FILE   Path to the SOLEIL AT lattice .m file
    DT4ACC_TANGO_HOST     Tango database host:port  (default: localhost:10000)
    DT4ACC_VIEW           Design or Device view (default: design)
"""

import os
import sys
from pathlib import Path



from dt4acc.custom_facility.soleil.utils.command_line_interface import display_setup_from_args, parse_args
from dt4acc.core.bl import handle_lattice
from dt4acc.custom_facility.model import integrated_strength
from dt4acc.custom_tango.ioc import mexec_config, mexec_server_for_physics_engine
from dt4acc.custom_tango.ioc import server_manager

# ---------------------------------------------------------------------------
# Resolve paths — script lives at scripts/soleil/, src is two levels up
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR    = SCRIPTS_DIR.parent.parent
SRC_DIR     = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ---------------------------------------------------------------------------
# SOLEIL-specific load_managers
# ---------------------------------------------------------------------------

def _soleil_load_managers():
    """Load the SOLEIL liaison manager and translator service."""
    from dt4acc.custom_facility.soleil.liasion_translator_setup import load_managers
    return load_managers()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    if not args.lattice.exists():
        print(f"ERROR: Lattice file not found: {args.lattice}", file=sys.stderr)
        sys.exit(1)

    print("Starting SOLEIL Digital Twin (all servers)")
    display_setup_from_args(args)
    os.environ["TANGO_HOST"] = args.tango_host
    os.environ["DT4ACC_LATTICE_FILE"] = str(args.lattice)
    os.environ["DT4ACC_LOAD_MANAGERS"] = (
        "dt4acc.custom_facility.soleil.liasion_translator_setup:load_managers"
    )
    os.environ["DT4ACC_MEXEC_PORT"] = str(args.port)
    os.environ["DT4ACC_VIEW"] = args.view
    # magnets publish integrated strengths (coefficient * L, kick angles in
    # rad): see dt4acc.custom_facility.model.integrated_strength
    os.environ.setdefault(integrated_strength.ENABLE_ENV, "1")


    handle_lattice.lattice_loader.set_lattice_file(args.lattice)
    mexec_server_for_physics_engine.LOAD_MANAGERS_FN = _soleil_load_managers
    server_manager.HEARTBEAT_PERIOD  = args.heartbeat_period
    mexec_config._MANAGER_PORT = args.port
    mexec_server_for_physics_engine.EXPECTED_VIEW = args.view

    server_manager.main()


if __name__ == "__main__":
    main()
