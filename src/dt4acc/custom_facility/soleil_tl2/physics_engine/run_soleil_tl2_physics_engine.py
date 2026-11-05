"""Physics engine as tango device, as soleil/physics_engine/run_soleil_physics_engine

Starts the mexec service and the tango device
"""
from dt4acc.core.bl import handle_lattice
from dt4acc.custom_facility.soleil_tl2.run_soleil_tl2_twin import _soleil_tl2_load_managers
from dt4acc.custom_facility.soleil_tl2.utils.command_line_interface import (
    display_setup_from_args,
    parse_args,
    setup_environment,
)
from dt4acc.custom_tango.ioc import mexec_server_for_physics_engine
from dt4acc.custom_tango.ioc.mexec_server_for_physics_engine import _run_mexec_service


def main():
    args = parse_args()
    setup_environment(args)
    print("Starting SOLEIL TL2 twin physics mexec engine")
    display_setup_from_args(args)

    mexec_server_for_physics_engine.LOAD_MANAGERS_FN = _soleil_tl2_load_managers

    handle_lattice.lattice_loader.set_lattice_file(args.lattice)
    print(handle_lattice.lattice_loader)
    _run_mexec_service()


if __name__ == "__main__":
    main()
