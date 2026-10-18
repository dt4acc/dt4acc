import json
import os
import pprint
from typing import Sequence

from dt4acc.custom_facility.soleil.utils.command_line_interface import (
    display_setup_from_args,
    build_args_parser,
)
from dt4acc.core.bl import handle_lattice
from dt4acc.custom_tango.ioc.devices.tango_device_setup import (
    register_all_devices,
    check_devices,
    family_trl_to_single_server_arguments,
)


def display_server_report(server_report):
    if len(server_report.errors):
        print("ERRORS :")
        pprint.pprint(server_report.errors, compact=True)

    if len(server_report.missing):
        print("missing:")
        pprint.pprint(server_report.errors, compact=True)

    txt = f"""Server summary report

    numbers: errors {len(server_report.errors)} missing {len(server_report.missing)} found {len(server_report.present)}
    """
    print(txt)


def export_present_devices(trls: Sequence[str], filename: str) -> None:
    data = [family_trl_to_single_server_arguments(t) for t in trls]
    with open(filename, "wt") as fp:
        json.dump(data, fp, indent=4)


def main():
    arg_parser = build_args_parser()
    arg_parser.add_argument("--register-devices", action="store_true")
    arg_parser.add_argument("--export-present-devices", default="")
    args = arg_parser.parse_args()
    display_setup_from_args(args)
    handle_lattice.lattice_loader.set_lattice_file(args.lattice)

    # build_device_plan()/register_all_devices() resolve each magnet's Tango
    # class and lattice property via lattice_properties_for_device(), which
    # needs the active facility's load_managers() -- normally set by
    # run_soleil_twin.py, but this script can run standalone (e.g. the
    # launcher's separate device-registration step), so set it here too.
    os.environ.setdefault(
        "DT4ACC_LOAD_MANAGERS",
        "dt4acc.custom_facility.soleil.liasion_translator_setup:load_managers",
    )

    if args.register_devices:
        servers = register_all_devices()
        print(f"Registered {len(servers)} servers")
        pprint.pprint(servers, compact=True)
    else:
        server_report = check_devices()
        display_server_report(server_report)
        if args.export_present_devices:
            export_present_devices(server_report.present, args.export_present_devices)


if __name__ == "__main__":
    main()
