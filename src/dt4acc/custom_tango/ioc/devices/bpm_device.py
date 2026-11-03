"""
bpm_device.py
=============

Read-only Tango device for a single Beam Position Monitor.

Subscribes to change events on RingSimulatorDevice.orbit_x / orbit_y
and caches its own x/y by index. No polling of the backend — one event
subscription per BPM, values updated on every heartbeat calculation.

Attributes (read-only, polled every 1s from local cache):
    x   — horizontal closed-orbit position at this BPM [m]
    y   — vertical closed-orbit position at this BPM [m]

As the Libera Brilliance Plus electronics' Tango devices at SOLEIL (the
names SOLEIL's MML reads), in mm:
    XPosSA, ZPosSA — slow acquisition: the closed orbit
    XPosDD, ZPosDD — turn by turn (custom_tango/ioc/turn_by_turn): the
                     ring simulator's latest result at this BPM
    DDBufferSize   — turns; the twin tracks one beam for all BPMs, so a
                     write sets it for all of them (ring simulator's tbt_n_turns)
"""
import numpy as np
from tango import AttrWriteType, AttrDataFormat, DevState, DevDouble, EventType
from tango.server import Device, attribute, device_property
from tango import DeviceProxy

from dt4acc.core.utils.logger import get_logger
from dt4acc.custom_tango.ioc.devices.virtual_devices import RING_SIM_DEV
from dt4acc.custom_tango.ioc.turn_by_turn import M2MM, MAX_TURNS

logger = get_logger()


class BPMDevice(Device):
    """Read-only Tango device for a single BPM.
    Subscribes to orbit change events from RingSimulatorDevice.
    """

    lattice_id  = device_property(dtype=str, default_value="")
    s_pos       = device_property(dtype=float, default_value=0.0)
    orbit_index = device_property(dtype=int, default_value=-1)

    def init_device(self):
        super().init_device()
        self._x = 0.0
        self._y = 0.0
        #: turn by turn data of the ring simulator's result tbt_count [mm]
        self._tbt_count = None
        self._tbt_x = np.zeros(0)
        self._tbt_y = np.zeros(0)
        self._event_ids = []
        self._ringsim = None
        self._subscribed = False
        self.set_state(DevState.ON)
        logger.info("Initializing BPMDevice: %s lattice_id=%s orbit_index=%d",
                    self.get_name(), self.lattice_id, self.orbit_index)
        self._subscribe_orbit_events()

    def always_executed_hook(self):
        """Retry subscription if not yet connected — ringsimulator may not
        have been running when init_device was called."""
        if not self._subscribed:
            self._subscribe_orbit_events()

    def _subscribe_orbit_events(self):
        """Subscribe to orbit_x / orbit_y change events on RingSimulatorDevice.
        Called at init and retried via always_executed_hook until successful."""
        try:
            logger.info("BPMDevice %s: subscribing to %s orbit events (index=%d s_pos=%.3f)",
                        self.get_name(), RING_SIM_DEV, self.orbit_index, self.s_pos)
            ringsim = DeviceProxy(RING_SIM_DEV)
            ringsim.set_timeout_millis(3000)
            eid_x = ringsim.subscribe_event(
                "orbit_x", EventType.CHANGE_EVENT, self._on_orbit_x
            )
            eid_y = ringsim.subscribe_event(
                "orbit_y", EventType.CHANGE_EVENT, self._on_orbit_y
            )
            self._event_ids = [eid_x, eid_y]
            self._ringsim = ringsim  # keep reference alive
            self._subscribed = True
            logger.info("BPMDevice %s: subscribed OK (eid_x=%s eid_y=%s)",
                        self.get_name(), eid_x, eid_y)
        except Exception as exc:
            logger.debug("BPMDevice %s: subscription attempt failed (will retry): %s",
                         self.get_name(), exc)

    def _on_orbit_x(self, event):
        if event.err:
            logger.info("BPMDevice %s: orbit_x event error: %s",
                           self.get_name(), event.errors)
            return
        if self.orbit_index < 0:
            logger.info("BPMDevice %s: orbit_index=-1, cannot index orbit array",
                           self.get_name())
            return
        try:
            arr = event.attr_value.value
            if arr is None:
                logger.info("BPMDevice %s: orbit_x event value is None", self.get_name())
                return
            logger.debug("BPMDevice %s: orbit_x event len=%d index=%d",
                         self.get_name(), len(arr), self.orbit_index)
            if self.orbit_index < len(arr):
                self._x = float(arr[self.orbit_index])
            else:
                logger.info("BPMDevice %s: orbit_index=%d >= orbit_x len=%d",
                               self.get_name(), self.orbit_index, len(arr))
        except Exception as exc:
            logger.info("BPMDevice %s: _on_orbit_x failed: %s", self.get_name(), exc)

    def _on_orbit_y(self, event):
        if event.err:
            return
        if self.orbit_index < 0:
            return
        try:
            arr = event.attr_value.value
            if arr is not None and self.orbit_index < len(arr):
                self._y = float(arr[self.orbit_index])
        except Exception as exc:
            logger.info("BPMDevice %s: _on_orbit_y failed: %s", self.get_name(), exc)

    def delete_device(self):
        try:
            if hasattr(self, "_ringsim") and self._event_ids:
                for eid in self._event_ids:
                    self._ringsim.unsubscribe_event(eid)
        except Exception:
            pass

    @attribute(dtype=DevDouble, label="Horizontal position", unit="m",
               polling_period=1000)
    def x(self) -> float:
        return self._x

    @attribute(dtype=DevDouble, label="Vertical position", unit="m",
               polling_period=1000)
    def y(self) -> float:
        return self._y

    # --- as the Libera Brilliance Plus devices at SOLEIL [mm]
    @attribute(dtype=DevDouble, label="X.Pos.SA", unit="mm", format="%8.4f",
               description="Slow Acquisition: X (closed orbit)")
    def XPosSA(self) -> float:
        return self._x * M2MM

    @attribute(dtype=DevDouble, label="Z.Pos.SA", unit="mm", format="%8.4f",
               description="Slow Acquisition: Z (closed orbit)")
    def ZPosSA(self) -> float:
        return self._y * M2MM

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_TURNS,
               label="DD X Pos.", unit="mm", format="%8.4f", description="Turn by turn data: X Pos.")
    def XPosDD(self):
        self._update_turn_by_turn()
        return self._tbt_x

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_TURNS,
               label="DD Z Pos.", unit="mm", format="%8.4f", description="Turn by turn data: Z Pos.")
    def ZPosDD(self):
        self._update_turn_by_turn()
        return self._tbt_y

    @attribute(dtype=int, access=AttrWriteType.READ_WRITE, min_value=1, max_value=MAX_TURNS,
               label="DD Buffer Size", unit="turns",
               description="The number of samples to be read on DD data source (the twin: for all BPMs)")
    def DDBufferSize(self) -> int:
        return int(self._ring_simulator().read_attribute("tbt_n_turns").value)

    @DDBufferSize.write
    def DDBufferSize(self, value: int):
        self._ring_simulator().write_attribute("tbt_n_turns", int(value))

    def _ring_simulator(self) -> DeviceProxy:
        if self._ringsim is None:
            self._ringsim = DeviceProxy(RING_SIM_DEV)
            self._ringsim.set_timeout_millis(3000)
        return self._ringsim

    def _update_turn_by_turn(self):
        """fetch this BPM's share once per new result of the ring simulator"""
        if not self.lattice_id:
            return
        ringsim = self._ring_simulator()
        count = ringsim.read_attribute("tbt_count").value
        if count == self._tbt_count:
            return
        xy = np.asarray(ringsim.command_inout("TurnByTurnAt", self.lattice_id), dtype=np.float64)
        n = len(xy) // 2
        self._tbt_x, self._tbt_y = xy[:n] * M2MM, xy[n:] * M2MM
        self._tbt_count = count
