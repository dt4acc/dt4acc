"""Registers (or checks) the SOLEIL TL2 twin's Tango devices, as soleil/register_devices"""
import pprint

from dt4acc.core.bl import handle_lattice
from dt4acc.custom_facility.soleil.register_devices import display_server_report, export_present_devices
from dt4acc.custom_facility.soleil_tl2.utils.command_line_interface import (
    build_args_parser,
    display_setup_from_args,
    setup_environment,
)


def main():
    arg_parser = build_args_parser()
    arg_parser.add_argument("--register-devices", action="store_true")
    arg_parser.add_argument("--export-present-devices", default="")
    args = arg_parser.parse_args()
    setup_environment(args)
    display_setup_from_args(args)
    handle_lattice.lattice_loader.set_lattice_file(args.lattice)

    from dt4acc.custom_tango.ioc.devices.tango_device_setup import check_devices, register_all_devices

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
