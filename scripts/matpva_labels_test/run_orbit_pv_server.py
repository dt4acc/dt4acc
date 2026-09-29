"""
run_orbit_pv_server.py
=======================
Stand-alone PVA server for testing the ORBITCC:rdBpm / ORBITCC:rdModel
"labels" fix (see orbit_pva.py) against a real matpva installation.

Starts dt4acc's OrbitTwinServer with some fixed sample data and keeps it
running until Ctrl+C — no dt4acc twin/lattice/EPICS IOC needed, this only
exercises the PVAccess NTTable server side.

Usage:
    python3 scripts/matpva_labels_test/run_orbit_pv_server.py

Then, from MATLAB (with matpva installed and on the MATLAB path):
    scripts/matpva_labels_test/mpvaGet_labels_test.m

If this machine and the MATLAB machine are different hosts, PVAccess
discovery needs to find this process — either run them on the same host,
or set EPICS_PVA_ADDR_LIST / EPICS_PVA_BROADCAST_PORT appropriately on
both sides (see EPICS base docs). Sample values below match
mpvaGet_labels_test.m's expectations.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dt4acc.custom_epics.ioc.orbit_pva import OrbitTwinServer

PV_ORBIT = "ORBITCC:rdBpm"
PV_MODEL = "ORBITCC:rdModel"

BPM_NAMES = ["BPM01", "BPM02", "BPM03"]


def main():
    server = OrbitTwinServer(PV_ORBIT, PV_MODEL)

    server.push(x=[1.0, 2.0, 3.0], y=[4.0, 5.0, 6.0], names=BPM_NAMES)
    server.push_model_data(
        bpm_names=BPM_NAMES,
        beta_hor=[1.1, 2.1, 3.1],
        beta_vert=[1.2, 2.2, 3.2],
        phase_advance_hor=[0.1, 0.2, 0.3],
        phase_advance_vert=[0.4, 0.5, 0.6],
    )

    server.start()
    print(f"Serving {PV_ORBIT!r} and {PV_MODEL!r}. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
