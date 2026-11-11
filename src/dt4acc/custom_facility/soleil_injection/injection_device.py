"""SOLEIL injection twin: the hand over as a Tango device, ``simulator/injection/injection``,
the role of the BESSY II injection twin's ``INJ:`` PVs

    Inject     command: fire a shot (the BESSY II twin's INJ:trigger)
    geometry   (x, px, y, py, delta, ct)  line against ring at the injection point, writable
    n_turns    turns tracked in the ring (the ring simulator's ``tbt_n_turns``), writable
    line_exit  centroid leaving TL2 at the last shot (line frame)
    injected   the same in the ring's frame
    survived   particles still there after each turn
    count      shots computed so far

As at the machine, the injection is fired on demand: a shot passes TL2 (its BPMs show
the trajectory: TL2 simulator's ``Fire``, single pass), leaves it and is tracked in
the ring (ring simulator's ``Inject``: its BPMs' ``XPosDD`` / ``ZPosDD``). Changes of
TL2, the ring, ``geometry`` or ``n_turns`` act at the next shot; TL2's model
(``orbit_*``, optics) and the ring's closed orbit (``XPosSA``) follow every change.
"""
import logging
import os
import threading

import numpy as np
from tango import AttrWriteType, DeviceProxy, DevState, DevDouble
from tango.server import AttrDataFormat, Device, attribute, command, run

from dt4acc.core.bl.turn_by_turn import COORDINATES, MAX_TURNS
from dt4acc.custom_facility.soleil_injection.handover import DEFAULT_TURNS, InjectionHandover
from dt4acc.custom_facility.soleil_injection.utils.command_line_interface import TL_SIM_DEV
from dt4acc.custom_tango.ioc import mexec_config
from dt4acc.custom_tango.ioc.mexec_server_for_physics_engine import MexecManagerService

logger = logging.getLogger("dt4acc-soleil-injection")

INJECTION_DEV = "simulator/injection/injection"
SERVER = ("simulator", "injection")
RING_SIM_DEV = "simulator/ringsimulator/ringsimulator"
PERIOD_S = 1.0


def _line_engine():
    """the transfer line's physics engine (its port: DT4ACC_TL_MEXEC_PORT)"""
    MexecManagerService.register("get_mexec_proxy")
    client = MexecManagerService(
        address=(mexec_config._MANAGER_HOST, int(os.environ["DT4ACC_TL_MEXEC_PORT"])),
        authkey=mexec_config._MANAGER_AUTHKEY,
    )
    client.connect()
    return client.get_mexec_proxy()


class InjectionDevice(Device):
    def init_device(self):
        super().init_device()
        self._ring = None
        self._line = None
        self._engine = None
        self._handover = None
        self._count = 0
        self._ring_count = None
        self._geometry = np.zeros(len(COORDINATES))
        self._n_turns_set = False
        self._stop = threading.Event()
        self._shots = threading.Event()
        #: both threads connect
        self._connecting = threading.Lock()
        self.set_state(DevState.ON)
        threading.Thread(target=self._loop, daemon=True, name="injection").start()
        threading.Thread(target=self._shot_loop, daemon=True, name="injection-shots").start()

    def delete_device(self):
        self._stop.set()
        self._shots.set()

    def _connect(self):
        with self._connecting:
            self._connect_once()

    def _connect_once(self):
        if self._handover is None:
            self._engine = _line_engine()
            self._ring = DeviceProxy(RING_SIM_DEV)
            self._ring.set_timeout_millis(10000)
            self._line = DeviceProxy(TL_SIM_DEV)
            self._line.set_timeout_millis(10000)
            self._handover = InjectionHandover(line_exit=self._engine.sync_line_exit, ring=self._ring)
            self._handover.set_geometry(self._geometry)
        if not self._n_turns_set:
            self._ring.tbt_n_turns = DEFAULT_TURNS
            self._n_turns_set = True

    def _loop(self):
        """count: follows the ring's results, one per shot"""
        while not self._stop.wait(PERIOD_S):
            try:
                self._connect()
                ring_count = self._ring.tbt_count
                if ring_count != self._ring_count:
                    self._ring_count = ring_count
                    self._count = ring_count  # the ring's results since the twin started
            except Exception as exc:  # the twins may still be starting, or restarting
                self._handover = None
                logger.info("injection: %s", exc)

    def _shot_loop(self):
        """one shot per Inject; those arriving while one is fired are merged into the next"""
        while True:
            self._shots.wait()
            self._shots.clear()
            if self._stop.is_set():
                return
            try:
                self._connect()
                self.shot()
            except Exception as exc:
                self._handover = None
                logger.warning("injection: shot failed: %s", exc)

    def shot(self):
        """TL2's BPMs see the beam pass, then it leaves TL2 into the ring"""
        self._line.Fire()
        if self._handover.shot() is None:
            logger.warning("injection: no beam leaves TL2 (its optics failed): nothing injected")

    @command
    def Inject(self):
        """Fire a shot: TL2's BPMs show the beam passing, the ring tracks it (count + 1 when done)"""
        self._shots.set()

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, access=AttrWriteType.READ_WRITE,
               max_dim_x=len(COORDINATES), label="Injection geometry",
               description="line against ring at the injection point: " + ", ".join(COORDINATES))
    def geometry(self):
        return self._geometry

    @geometry.write
    def geometry(self, values):
        values = np.asarray(values, dtype=float)
        if values.shape != (len(COORDINATES),):
            raise ValueError(f"geometry: expected {len(COORDINATES)} values ({', '.join(COORDINATES)})")
        self._geometry = values
        if self._handover is not None:
            self._handover.set_geometry(values)

    @attribute(dtype=int, access=AttrWriteType.READ_WRITE, min_value=1, max_value=MAX_TURNS, label="Turns")
    def n_turns(self):
        return int(DeviceProxy(RING_SIM_DEV).tbt_n_turns)

    @n_turns.write
    def n_turns(self, value):
        DeviceProxy(RING_SIM_DEV).tbt_n_turns = int(value)

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=len(COORDINATES),
               label="Leaving the line", description="centroid leaving TL2 at the last shot, line frame")
    def line_exit(self):
        return self._handover.line_exit if self._handover else np.zeros(0)

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=len(COORDINATES),
               label="Injected", description="the beam entering the ring, ring frame")
    def injected(self):
        return self._handover.injected if self._handover else np.zeros(0)

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_TURNS,
               label="Survived", description="particles still there after each turn")
    def survived(self):
        return np.asarray(DeviceProxy(RING_SIM_DEV).tbt_survived, dtype=float)

    @attribute(dtype=int, label="Shots", description="shots computed so far")
    def count(self):
        return self._count


def main():
    run((InjectionDevice,), args=list(SERVER))


if __name__ == "__main__":
    main()
