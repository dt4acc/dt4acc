"""
virtual_devices.py
==================

Single virtual Tango device for the digital twin:

    simulator/ringsimulator/ringsimulator  (RingSimulatorDevice)

It holds the settings and the summary of the turn by turn data too
(``tbt_*``, :mod:`dt4acc.custom_tango.ioc.turn_by_turn`); the BPM devices
serve each BPM's share.

Injection on demand (set by an injection twin, :mod:`.mexec_config`):

* ``Inject(<start state>)``: a shot into a ring: its turn by turn data
  track the injected beam (``TBT_ON_DEMAND``: only then)
* ``Fire``: a shot through a transfer line: ``shot_x`` / ``shot_y`` take
  its trajectory as it is now; its BPM devices follow them (``SINGLE_PASS``)
"""
import math

import asyncio
from typing import Tuple

import numpy as np
from tango import DevState, DevFailed, DevDouble, DevString
from tango.server import Device, attribute, command, AttrDataFormat, device_property, AttrWriteType

from dt4acc.config.data.querries import get_rf_cavity_uuids
from dt4acc.core.bl.shared_event_loop import get_shared_event_loop
from dt4acc_lib.interfaces.backend.calculation_states import CalculationStates
from dt4acc_lib.model.utils.command import Command, BehaviourOnError, ReadCommand
from dt4acc.core.utils.logger import get_logger
from dt4acc.custom_tango.ioc.controller_registry import get_controller
from dt4acc.custom_tango.ioc.devices.write_value_sync import sync_write_value
from dt4acc.custom_tango.ioc.mexec_config import SIMULATOR_DEVICE, TBT_ON_DEMAND
from dt4acc.custom_tango.ioc.turn_by_turn import COORDINATES, MAX_TURNS, TurnByTurnFollower

logger = get_logger()

RING_SIM_DEV = SIMULATOR_DEVICE
MAX_ELEMS = 6000
MAX_BPMS  = 4096

# ---------------------------------------------------------------------------
# Module-level orbit cache — updated by RingSimulatorDevice.push_orbit_x/y
# and read by BPMDevice without any cross-process calls.
# ---------------------------------------------------------------------------
_orbit_x_cache: np.ndarray = np.array([], dtype=np.float64)
_orbit_y_cache: np.ndarray = np.array([], dtype=np.float64)


def get_orbit_at_index(index: int) -> Tuple[float, float]:
    """Return (x, y) from the latest orbit cache at the given AT element index.
    Returns (0.0, 0.0) if the cache is empty or index is out of range.

    Todo:
        consider if it should rather return (math.nan, math.nan) if it fails
    """
    if index < len(_orbit_x_cache) and index < len(_orbit_y_cache):
        return float(_orbit_x_cache[index]), float(_orbit_y_cache[index])
    return 0.0, 0.0


def _physics_engine_proxy():
    """the physics engine's SyncMexecProxy of this server process; None while not connected"""
    from dt4acc.custom_tango.ioc import single_server
    return single_server._sync_proxy


class AsyncMixin:
    def _start_async(self):
        self._loop = get_shared_event_loop()

    def _async(self, coro):
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return fut.result(timeout=10)
        except Exception as exc:
            raise DevFailed(str(exc))


class RingSimulatorDevice(Device, AsyncMixin):
    """
    Single Tango device exposing all digital twin physics results.
    Device name: simulator/ringsimulator/ringsimulator
    """

    def init_device(self):
        super().init_device()
        self._loop = get_shared_event_loop()
        self._orbit_x = np.array([0.0], dtype=np.float64)
        self._orbit_y = np.array([0.0], dtype=np.float64)
        self._beta_x  = np.array([0.0], dtype=np.float64)
        self._beta_y  = np.array([0.0], dtype=np.float64)
        self._alpha_x = np.array([0.0], dtype=np.float64)
        self._alpha_y = np.array([0.0], dtype=np.float64)
        self._nu_x    = np.array([0.0], dtype=np.float64)
        self._nu_y    = np.array([0.0], dtype=np.float64)
        self._bpm_names = []
        self._bpm_x     = np.array([], dtype=np.float64)
        self._bpm_y     = np.array([], dtype=np.float64)
        self._tune_hor  = 0.0
        self._tune_vert = 0.0
        self._xi_x      = 0.0
        self._xi_y      = 0.0
        #: the trajectory at the last shot (Fire), as orbit_x / orbit_y; empty before
        self._shot_x    = np.array([], dtype=np.float64)
        self._shot_y    = np.array([], dtype=np.float64)
        self._reference_frequency = self._initial_reference_frequency()
        self._sync_write_value("reference_frequency", self._reference_frequency)
        self._rf_cavity_uuids = get_rf_cavity_uuids()
        for attr_name in ("orbit_x", "orbit_y",
                          "beta_x", "beta_y", "alpha_x", "alpha_y", "nu_x", "nu_y",
                          "bpm_x_attr", "bpm_y_attr", "hor", "vert", "tbt_count", "shot_x", "shot_y"):
            self.set_change_event(attr_name, True, False)
        if getattr(self, "_tbt", None) is None:  # one follower (and its thread), also after Init
            self._tbt = TurnByTurnFollower(proxy=_physics_engine_proxy, on_new=self._on_new_turn_by_turn,
                                           on_demand=TBT_ON_DEMAND)
        self.set_state(DevState.ON)

    def _initial_reference_frequency(self) -> float:
        try:
            from dt4acc.custom_tango.ioc.single_server import get_rf_reference_frequency_khz
            return get_rf_reference_frequency_khz()
        except Exception as exc:
            logger.warning("RingSimulatorDevice: could not initialise reference_frequency: %s", exc)
            return 0.0

    def _sync_write_value(self, attr_name: str, value) -> None:
        sync_write_value(self, attr_name, value)

    @command
    def RefreshFromCache(self) -> None:
        """Refresh RF aggregate read/write cache from the current lattice."""
        self._reference_frequency = self._initial_reference_frequency()
        self._sync_write_value("reference_frequency", self._reference_frequency)
        logger.info(
            "%s: RefreshFromCache done — reference_frequency=%.6f kHz",
            self.get_name(),
            self._reference_frequency,
        )

    # Orbit
    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS)
    def orbit_x(self): return self._orbit_x

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS)
    def orbit_y(self): return self._orbit_y

    # Single pass: what the beam position monitors saw at the last shot
    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS, unit="m",
               label="Shot: x", description="trajectory at the last shot (Fire), as orbit_x")
    def shot_x(self): return self._shot_x

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS, unit="m",
               label="Shot: y", description="trajectory at the last shot (Fire), as orbit_y")
    def shot_y(self): return self._shot_y

    @command
    def Fire(self):
        """A shot passes: shot_x / shot_y take the trajectory as it is now (a transfer line:
        its BPMs show it, single pass). NaN without a trajectory (optics failed): no beam seen"""
        proxy = _physics_engine_proxy()
        try:
            x, y = proxy.sync_trajectory() if proxy is not None else ([], [])
        except Exception as exc:
            logger.warning("%s.Fire: no trajectory: %s", self.get_name(), exc)
            x, y = [], []
        if not len(x):
            x = y = np.full(len(self._orbit_x), math.nan)
        self._shot_x = np.asarray(x, dtype=np.float64)
        self._shot_y = np.asarray(y, dtype=np.float64)
        self.push_change_event("shot_x", self._shot_x)
        self.push_change_event("shot_y", self._shot_y)

    # Twiss
    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS)
    def beta_x(self): return self._beta_x

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS)
    def beta_y(self): return self._beta_y

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS)
    def alpha_x(self): return self._alpha_x

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS)
    def alpha_y(self): return self._alpha_y

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS)
    def nu_x(self): return self._nu_x

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_ELEMS)
    def nu_y(self): return self._nu_y

    # BPM
    @attribute(dtype=DevString, dformat=AttrDataFormat.SPECTRUM,
               access=AttrWriteType.READ_WRITE, max_dim_x=MAX_BPMS)
    def bpm_names_attr(self): return self._bpm_names

    @bpm_names_attr.write
    def bpm_names_attr(self, values):
        self._bpm_names = [] if values is None else [str(v) for v in values]

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM,
               access=AttrWriteType.READ_WRITE, max_dim_x=MAX_BPMS)
    def bpm_x_attr(self): return self._bpm_x

    @bpm_x_attr.write
    def bpm_x_attr(self, values):
        self._bpm_x = np.asarray(values, dtype=np.float64)
        self.push_change_event("bpm_x_attr", self._bpm_x)

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM,
               access=AttrWriteType.READ_WRITE, max_dim_x=MAX_BPMS)
    def bpm_y_attr(self): return self._bpm_y

    @bpm_y_attr.write
    def bpm_y_attr(self, values):
        self._bpm_y = np.asarray(values, dtype=np.float64)
        self.push_change_event("bpm_y_attr", self._bpm_y)

    # Tune — READ ONLY. Tunes are computed by AT, not settable directly.
    @attribute(dtype=DevDouble, label="Horizontal tune")
    def hor(self): return self._tune_hor

    @attribute(dtype=DevDouble, label="Vertical tune")
    def vert(self): return self._tune_vert

    # Chromaticity — READ ONLY. Computed by AT alongside tune.
    @attribute(dtype=DevDouble, label="Horizontal chromaticity")
    def xi_x(self): return self._xi_x

    @attribute(dtype=DevDouble, label="Vertical chromaticity")
    def xi_y(self): return self._xi_y

    # Master clock
    @attribute(dtype=DevDouble, access=AttrWriteType.READ_WRITE,
               label="Reference frequency", unit="kHz")
    def reference_frequency(self): return self._reference_frequency

    @reference_frequency.write
    def reference_frequency(self, value: float):
        value = float(value)
        self._reference_frequency = value
        self._async(self._fan_out_frequency(value * 1000.0))  # kHz → Hz

    async def _fan_out_frequency(self, hz: float) -> None:
        for uuid in self._rf_cavity_uuids:
            await get_controller().update(
                cmd=Command(
                    id=uuid,
                    property="frequency",
                    value=hz,
                    behaviour_on_error=BehaviourOnError.stop,
                ),
                reads=[], delayed_reads=[],
            )

    # Orbit push commands
    @command(dtype_in=(float,))
    def push_orbit_x(self, values):
        global _orbit_x_cache
        arr = np.asarray(values, dtype=np.float64).ravel()
        self._orbit_x = arr
        _orbit_x_cache = arr
        self.push_change_event("orbit_x", arr)

    @command(dtype_in=(float,))
    def push_orbit_y(self, values):
        global _orbit_y_cache
        arr = np.asarray(values, dtype=np.float64).ravel()
        self._orbit_y = arr
        _orbit_y_cache = arr
        self.push_change_event("orbit_y", arr)

    # Twiss push commands
    @command(dtype_in=(float,))
    def push_beta_x(self, values):
        arr = np.asarray(values, dtype=np.float64).ravel()
        self._beta_x = arr
        self.push_change_event("beta_x", arr)

    @command(dtype_in=(float,))
    def push_beta_y(self, values):
        arr = np.asarray(values, dtype=np.float64).ravel()
        self._beta_y = arr
        self.push_change_event("beta_y", arr)

    @command(dtype_in=(float,))
    def push_alpha_x(self, values):
        arr = np.asarray(values, dtype=np.float64).ravel()
        self._alpha_x = arr
        self.push_change_event("alpha_x", arr)

    @command(dtype_in=(float,))
    def push_alpha_y(self, values):
        arr = np.asarray(values, dtype=np.float64).ravel()
        self._alpha_y = arr
        self.push_change_event("alpha_y", arr)

    @command(dtype_in=(float,))
    def push_nu_x(self, values):
        arr = np.asarray(values, dtype=np.float64).ravel()
        self._nu_x = arr
        self.push_change_event("nu_x", arr)

    @command(dtype_in=(float,))
    def push_nu_y(self, values):
        arr = np.asarray(values, dtype=np.float64).ravel()
        self._nu_y = arr
        self.push_change_event("nu_y", arr)

    @command(dtype_in=(float,))
    def push_tune(self, values):
        """Called by the heartbeat with [tune_x, tune_y] from AT."""
        if len(values) >= 2:
            self._tune_hor  = float(values[0])
            self._tune_vert = float(values[1])
            self.push_change_event("hor",  self._tune_hor)
            self.push_change_event("vert", self._tune_vert)

    @command(dtype_in=(float,))
    def push_chromaticity(self, values):
        """Called by the heartbeat with [xi_x, xi_y] from AT."""
        if len(values) >= 2:
            self._xi_x = float(values[0])
            self._xi_y = float(values[1])
            self.push_change_event("xi_x", self._xi_x)
            self.push_change_event("xi_y", self._xi_y)

    # Turn by turn data (custom_tango/ioc/turn_by_turn)
    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, access=AttrWriteType.READ_WRITE,
               max_dim_x=len(COORDINATES), label="Turn by turn: start offset",
               description="start offset from the closed orbit: " + ", ".join(COORDINATES) + " (m, rad, 1, m)")
    def tbt_offset(self):
        return np.asarray(self._tbt.offset, dtype=np.float64)

    @tbt_offset.write
    def tbt_offset(self, values):
        self._tbt.set_offset(values)

    @attribute(dtype=int, access=AttrWriteType.READ_WRITE, min_value=1, max_value=MAX_TURNS,
               label="Turn by turn: turns", description="turns tracked (all BPMs' DDBufferSize)")
    def tbt_n_turns(self):
        return self._tbt.n_turns

    @tbt_n_turns.write
    def tbt_n_turns(self, value):
        self._tbt.set_n_turns(value)

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=len(COORDINATES),
               label="Turn by turn: start", description="start state tracked: closed orbit + offset")
    def tbt_start(self):
        return np.asarray(self._tbt.summary.get("start", []), dtype=np.float64)

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_TURNS,
               label="Turn by turn: survived", description="particles still there after each turn")
    def tbt_survived(self):
        return np.asarray(self._tbt.summary.get("survived", []), dtype=np.float64)

    @attribute(dtype=DevString, dformat=AttrDataFormat.SPECTRUM, max_dim_x=MAX_BPMS,
               label="Turn by turn: BPMs", description="the BPMs' lattice ids, in ring order")
    def tbt_bpm_ids(self):
        return list(self._tbt.summary.get("bpm_ids", []))

    @attribute(dtype=int, label="Turn by turn: results", description="new results so far")
    def tbt_count(self):
        return self._tbt.count

    @command(dtype_in=str, dtype_out=(float,),
             doc_in="BPM lattice id", doc_out="x then y [m], turn after turn, of the latest result")
    def TurnByTurnAt(self, bpm_id):
        try:
            return np.asarray(self._tbt.at(bpm_id), dtype=np.float64)
        except Exception as exc:
            raise DevFailed(f"turn by turn at {bpm_id}: {exc}")

    @command(dtype_in=(float,),
             doc_in="the injected beam at the start of the lattice: " + ", ".join(COORDINATES) + " (m, rad, 1, m)")
    def Inject(self, values):
        """A shot: the turn by turn data track the injected beam for tbt_n_turns, against the
        closed orbit as it is now; tbt_count counts up when done"""
        try:
            self._tbt.inject(values)
        except ValueError as exc:
            raise DevFailed(str(exc))

    @attribute(dtype=DevDouble, dformat=AttrDataFormat.SPECTRUM, max_dim_x=len(COORDINATES),
               label="Turn by turn: closed orbit", description="closed orbit at the start of the lattice: start - offset")
    def tbt_closed_orbit(self):
        summary = self._tbt.summary
        if not summary.get("start"):
            return np.zeros(0)
        return np.asarray(summary["start"], dtype=np.float64) - np.asarray(summary["offset"], dtype=np.float64)

    def _on_new_turn_by_turn(self, summary):
        self.push_change_event("tbt_count", self._tbt.count)

    def _sync_tango_state(self):
        """Map backend calculation state to Tango device state (color in Jive)."""
        backend_state = get_controller().get_backend_state()
        if backend_state == CalculationStates.error:
            self.set_state(DevState.ALARM)
            self.set_status("Beam loss: optics calculation failed. Call Reset or Reinit.")
        elif backend_state == CalculationStates.acknowledged:
            self.set_state(DevState.ALARM)
            self.set_status("Beam loss acknowledged. Call Reset or Reinit.")
        else:
            self.set_state(DevState.ON)
            self.set_status("Running")

    # Reset
    @command
    def Recalculate(self):
        """
        Trigger a fresh twiss+orbit+tune calculation on the CURRENT lattice
        state without changing anything.

        Called by the calculation heartbeat every second, and can also be
        called manually after a measurement to get an updated result.
        Does NOT perturb the lattice — zero noise.
        """
        controller = get_controller()
        assert callable(controller.reread_default_readings)
        try:
            self._async(get_controller().reread_default_readings())
        except Exception as exc:
            logger.debug("RingSimulatorDevice.Recalculate: %s", exc)
        finally:
            self._sync_tango_state()
        # tracks again only if the lattice or the settings changed
        self._tbt.request()

    @command
    def Reset(self):
        """Reset the digital twin: calculations are possible now again"""
        logger.warning("RingSimulatorDevice.Reset: initiating backend reset...")
        # Todo: is there a state like reset?
        # self.set_state(DevState.RESET)
        try:
            self._start_async()
            get_controller().reset()
            self.RefreshFromCache()
            self.set_state(DevState.ON)
            logger.warning("RingSimulatorDevice.Reset: complete — recalculation queued")
        except Exception as exc:
            logger.error("RingSimulatorDevice.Reset failed: %s", exc)
            self.set_state(DevState.FAULT)
            raise DevFailed(str(exc))

    @command
    def Reinit(self):
        """Reset the digital twin to nominal state after beam loss."""
        logger.warning("RingSimulatorDevice.Reinit: re instantiating backend ...")
        self.set_state(DevState.INIT)
        try:
            self._start_async()
            get_controller().reinit()
            self.RefreshFromCache()
            self.set_state(DevState.ON)
            logger.warning("RingSimulatorDevice.Reinit: complete — nominal state restored")
        except Exception as exc:
            logger.error("RingSimulatorDevice.Reinit failed: %s", exc)
            self.set_state(DevState.FAULT)
            raise DevFailed(str(exc))
