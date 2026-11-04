"""SOLEIL injection twin: registers its devices in one Tango database, once per database

    python -m dt4acc.custom_facility.soleil_injection.register_devices --tango-host HOST:PORT

The ring's and TL2's devices by their own register_devices (TL2's device
database: yml2json_soleil_tl2 first), then the hand over's device.
"""
import os
import subprocess
import sys

from dt4acc.custom_facility.soleil_injection.utils.command_line_interface import build_args_parser, ring_env, tl_env


def main():
    args = build_args_parser().parse_args()
    ring = [sys.executable, "-m", "dt4acc.custom_facility.soleil.register_devices", "--register-devices",
            "--lattice", str(args.ring_lattice), "--tango-host", args.tango_host]
    tl = [sys.executable, "-m", "dt4acc.custom_facility.soleil_tl2.register_devices", "--register-devices",
          "--lattice", str(args.tl_lattice), "--twiss-in", str(args.tl_twiss_in), "--tango-host", args.tango_host]
    subprocess.run(ring, env=ring_env(args), check=True, stdout=subprocess.DEVNULL)
    subprocess.run(tl, env=tl_env(args), check=True, stdout=subprocess.DEVNULL)

    os.environ["TANGO_HOST"] = args.tango_host
    from tango import Database, DbDevInfo

    from dt4acc.custom_facility.soleil_injection.injection_device import INJECTION_DEV, SERVER

    db = Database()
    info = DbDevInfo()
    info.name, info._class, info.server = INJECTION_DEV, "InjectionDevice", "/".join(SERVER)
    db.add_device(info)
    print(f"Registered the ring, TL2 and {INJECTION_DEV}")


if __name__ == "__main__":
    main()
