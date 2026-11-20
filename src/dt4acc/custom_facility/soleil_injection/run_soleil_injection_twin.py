#!/usr/bin/env python3
"""SOLEIL injection twin: storage ring and TL2 together, the beam handed from the line to the
ring, as ``bessyii_injection``. See its README.

    python -m dt4acc.custom_facility.soleil_injection.register_devices --tango-host HOST:PORT
    python -m dt4acc.custom_facility.soleil_injection.run_soleil_injection_twin --tango-host HOST:PORT

Three processes on one Tango database: the ring twin and the TL2 twin, each with its own
physics engine, liaison and device database, and the hand over's device. If one ends, all end.
"""
import signal
import subprocess
import sys
import time

from dt4acc.custom_facility.soleil_injection.utils.command_line_interface import build_args_parser, ring_env, tl_env


def _die_with_parent():
    """Linux: the child gets SIGTERM when this launcher ends, also when it is killed (SIGKILL,
    the IDE's stop button) and its own stop() cannot run; else the twins keep their ports."""
    if sys.platform.startswith("linux"):
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def main():
    args = build_args_parser().parse_args()
    start = dict(preexec_fn=_die_with_parent)
    processes = [
        subprocess.Popen([sys.executable, "-m", "dt4acc.custom_facility.soleil.run_soleil_twin",
                          "--lattice", str(args.ring_lattice), "--tango-host", args.tango_host,
                          "--port", str(args.ring_port)], env=ring_env(args), **start),
        subprocess.Popen([sys.executable, "-m", "dt4acc.custom_facility.soleil_tl2.run_soleil_tl2_twin",
                          "--lattice", str(args.tl_lattice), "--twiss-in", str(args.tl_twiss_in),
                          "--tango-host", args.tango_host, "--port", str(args.tl_port)], env=tl_env(args),
                         **start),
        subprocess.Popen([sys.executable, "-m", "dt4acc.custom_facility.soleil_injection.injection_device"],
                         env={**ring_env(args), "DT4ACC_TL_MEXEC_PORT": str(args.tl_port)}, **start),
    ]

    def stop(*_):
        for process in processes:
            process.terminate()
        time.sleep(2.0)
        for process in processes:
            if process.poll() is None:
                process.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while all(process.poll() is None for process in processes):
        time.sleep(2.0)
    print("One of the twin's processes ended: stopping", file=sys.stderr)
    stop()


if __name__ == "__main__":
    main()
