from __future__ import annotations

import getpass
import math
import os
import threading
import time
from typing import Any, Dict, List, Sequence

from ...core.utils.logger import get_logger
from p4p import Type, Value
from p4p.server import Server
from p4p.server.thread import SharedPV

logger = get_logger()

BEAM_PHYSICS_INFO_LABELS = [
    "BPM", "SPos", "BetaHor", "BetaVer", "PhaseAdvanceHor", "PhaseAdvanceVer",
]

beam_physics_info_type = Type(
    id="epics:nt/NTTable:1.0",
    spec=[
        ("labels", "as"),
        (
            "value",
            (
                "S",
                None,
                [
                    # fmt:off
                    ( "BPM"             , "as" ),
                    ( "SPos"            , "ad" ),
                    ( "BetaHor"         , "ad" ),
                    ( "BetaVer"         , "ad" ),
                    ( "PhaseAdvanceHor" , "ad" ),
                    ( "PhaseAdvanceVer" , "ad" ),
                    # fmt:on
                ],
            ),
        ),
        (
            "alarm",
            (
                "S",
                "alarm_t",
                [
                    ("severity", "i"),
                    ("status", "i"),
                    ("message", "s"),
                ],
            ),
        ),
        (
            "timeStamp",
            (
                "S",
                "time_t",
                [
                    ("secondsPastEpoch", "l"),
                    ("nanoseconds", "i"),
                    ("userTag", "i"),
                ],
            ),
        ),
    ],
)

ORBIT_LABELS = ["BPM", "X", "Y", "A", "B", "C", "D"]

orbit_type = Type(
    id="epics:nt/NTTable:1.0",
    spec=[
        ("labels", "as"),
        (
            "value",
            (
                "S",
                None,
                [
                    # fmt:off
                    ( "BPM", "as" ),
                    ( "X"  , "ad" ),
                    ( "Y"  , "ad" ),
                    ( "A"  , "ad" ),
                    ( "B"  , "ad" ),
                    ( "C"  , "ad" ),
                    ( "D"  , "ad" ),
                    # fmt:on
                ],
            ),
        ),
        (
            "alarm",
            (
                "S",
                "alarm_t",
                [
                    ("severity", "i"),
                    ("status", "i"),
                    ("message", "s"),
                ],
            ),
        ),
        (
            "timeStamp",
            (
                "S",
                "time_t",
                [
                    ("secondsPastEpoch", "l"),
                    ("nanoseconds", "i"),
                    ("userTag", "i"),
                ],
            ),
        ),
    ],
)

initial_data = {
    "labels": ORBIT_LABELS,
    "value": {
        # fmt:off
        "A"  : [] ,
        "B"  : [] ,
        "BPM": [] ,
        "C"  : [] ,
        "D"  : [] ,
        "X"  : [] ,
        "Y"  : [] ,
        # fmt:on
    },
}

initial_beam_physics_data = dict(
    labels=BEAM_PHYSICS_INFO_LABELS,
    value=dict(
        BPM=[],
        SPos=[],
        BetaHor=[],
        BetaVer=[],
        PhaseAdvanceHor=[],
        PhaseAdvanceVer=[],
    )
)


class OrbitTwinServer:
    def __init__(
        self, pv_name: str = "ORBITCC:rdBpm", bpm_physics_data="ORBITCC:rdModel"
    ):
        self.pv_name = pv_name
        self.pv = SharedPV(initial=Value(orbit_type, initial_data))
        self.beam_physics_info_pv_name = bpm_physics_data
        self.beam_physics_info = SharedPV(
            initial=Value(beam_physics_info_type, initial_beam_physics_data)
        )

        self._thread: threading.Thread | None = None

        @self.pv.put
        def _handle_put(pv, op):
            new_value = op.value()
            pv.post(new_value)
            op.done()

        @self.beam_physics_info.put
        def _handle_put_beam_physics_info(pv, op):
            new_value = op.value()
            pv.post(new_value)
            op.done()

    def start(self) -> None:
        """Start the PVA server in the background."""
        if self._thread and self._thread.is_alive():
            return

        def run_server():
            Server.forever(
                providers=[
                    {
                        self.pv_name: self.pv,
                        self.beam_physics_info_pv_name: self.beam_physics_info,
                    }
                ],
            )

        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()

    def push_model_data(
        self,
        *,
        bpm_names: Sequence[str],
        beta_hor: Sequence[float],
        beta_vert: Sequence[float],
        phase_advance_hor: Sequence[float],
        phase_advance_vert: Sequence[float],
        s_pos: Sequence[float] | None = None,
    ):
        now = time.time()
        if s_pos is None:
            s_pos = [0.0] * len(bpm_names)

        data = dict(
            labels=BEAM_PHYSICS_INFO_LABELS,
            value=dict(
                BPM=bpm_names,
                SPos=s_pos,
                BetaHor=beta_hor,
                BetaVer=beta_vert,
                PhaseAdvanceHor=phase_advance_hor,
                PhaseAdvanceVer=phase_advance_vert,
            ),
            timeStamp=dict(
                secondsPastEpoch=int(now),
                nanoseconds=int((now % 1) * 1e9),
                userTag=0,
            ),
            alarm=dict(severity=0, status=0, message=""),
        )
        self.beam_physics_info.post(Value(beam_physics_info_type, data))

    def push(self, *, x: List[float], y: List[float], names: List[str]) -> None:
        bpm_mask = [n.startswith("BPM") for n in names]
        x = [v for v, keep in zip(x, bpm_mask) if keep]
        y = [v for v, keep in zip(y, bpm_mask) if keep]
        names = [n for n, keep in zip(names, bpm_mask) if keep]

        now = time.time()
        data = {
            "labels": ORBIT_LABELS,
            "value": {
                "A": [v * 0.95 for v in x],
                "B": [v * 0.90 for v in x],
                "BPM": names,
                "C": [v * 0.85 for v in x],
                "D": [v * 0.80 for v in x],
                "X": x,
                "Y": y,
            },
            "timeStamp": {
                "secondsPastEpoch": int(now),
                "nanoseconds": int((now % 1) * 1e9),
                "userTag": 0,
            },
            "alarm": {
                "severity": 0,
                "status": 0,
                "message": "",
            },
        }
        self.pv.post(Value(orbit_type, data))

    def push_raw(self, data: Dict[str, Any]) -> None:
        """Publish a prebuilt dictionary from the server side."""
        self.pv.post(Value(orbit_type, data))


def main():
    prefix = os.environ.get("DT4ACC_PREFIX", getpass.getuser() + ":")
    logger.warning(f"PREFIX in orbit pva is: {prefix}")
    server = OrbitTwinServer(
        prefix + "ORBITCC:rdBpm",
        prefix + "ORBITCC:rdModel",
    )
    server.start()

    print(f"Orbit PV server is running on '{prefix}:ORBITCC:rdBpm'")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            threading.Event().wait(1.0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
