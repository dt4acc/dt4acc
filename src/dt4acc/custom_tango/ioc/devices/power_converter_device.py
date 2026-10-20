import asyncio

from dt4acc.core.bl.shared_event_loop import get_shared_event_loop
from dt4acc_lib.model.utils import tango_resource_locator
from dt4acc_lib.model.utils.command import BehaviourOnError, Command
from tango import DevState, DevFailed
from tango.server import Device, attribute, command, device_property, AttrWriteType

from dt4acc.config.data.querries import get_elements_per_power_converter
from dt4acc.core.utils.logger import get_logger
from dt4acc.custom_tango.ioc.controller_registry import get_controller
from dt4acc.custom_tango.ioc.devices.write_value_sync import sync_write_value

logger = get_logger()


class PowerConverterDevice(Device):
    """
    Tango device representing a power converter.

    Device name IS the power converter identifier:
        AN10-AR/EM/SCF.11-pc

    All identity is derived from the Tango device name.
    No DB properties are required.

    Write handlers delegate to TangoController.update(), which:
      1. calls mexec.set([cmd]) to mutate the backend lattice
      2. queues delayed reads (track/pos, twiss/parameters, tune/x, tune/y)
         so orbit/twiss recalculation fires automatically after each set.
    """

    magnet_list = device_property(dtype=(str,), default_value=[])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init_device(self):
        super().init_device()
        self.set_state(DevState.INIT)

        full_name = self.get_name()
        self.trl = tango_resource_locator.TangoResourceLocator.from_trl(full_name)
        self.pc_name = full_name

        logger.info("Initializing PowerConverterDevice: %s", self.pc_name)

        self._loop = get_shared_event_loop()

        # Fetch initial current setpoint from the backend via the controller.
        # Falls back to 0.0 if the backend does not know this PC yet.
        self._current = self._peek_initial_current()
        self._current_rb = self._current
        self._voltage = 0.0
        sync_write_value(self, "current_set", self._current)

        self.set_state(DevState.ON)

    def _peek_initial_current(self) -> float:
        """The current that gives the lattice the twin starts from (its
        magnets' strengths translated forward, device view), so that a client
        reading the current and stepping it moves the magnets by the step
        only. 0.0 if the twin can not translate it."""
        from dt4acc.custom_tango.ioc.single_server import read_device_value

        value = read_device_value(self.pc_name, "set_current")
        if value is None:
            logger.warning("%s: initial current unknown, starting at 0 A", self.pc_name)
            return 0.0
        return value

    # ------------------------------------------------------------------
    # Async helper
    # ------------------------------------------------------------------

    def _async(self, coro):
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return fut.result(timeout=10)
        except Exception as exc:
            raise DevFailed(str(exc))

    # ------------------------------------------------------------------
    # Tango attributes
    # ------------------------------------------------------------------

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE,
               label="Current setpoint", unit="A")
    def current_set(self) -> float:
        return self._current

    @current_set.write
    def current_set(self, value: float) -> None:
        value = float(value)
        self._current = value
        self._current_rb = value
        self._async(
            get_controller().update(
                cmd=Command(
                    id=self.pc_name,
                    property="set_current",
                    value=value,
                    behaviour_on_error=BehaviourOnError.stop,
                ),
                reads=[],
                delayed_reads=[],
            )
        )

    @attribute(dtype=float, label="Current readback", unit="A")
    def current_readback(self) -> float:
        return self._current_rb

    @attribute(dtype=float, label="Voltage readback", unit="V")
    def voltage(self) -> float:
        return self._voltage


class CavityPowerConverterDevice(Device):
    """
    Shared RF power converter for all cavities.

    In design view the command rewriter does no liaison translation —
    commands go straight to the AT backend using the lattice element UUID as
    the identifier. This device therefore fans out to each cavity UUID directly,
    setting property "voltage" on every cavity it controls.

    The voltage readback is the average of all cavity voltages. Since all are
    set to the same value the readback equals the set value.
    """

    def init_device(self):
        super().init_device()
        self.set_state(DevState.INIT)

        self._loop = get_shared_event_loop()
        self.pc_name = self.get_name()
        self._current = 0.0
        self._voltage = 0.0

        cavities = get_elements_per_power_converter(self.pc_name)
        self._cavity_uuids = [c["uuid"] for c in cavities if c.get("uuid")]
        logger.info("%s: controlling cavity UUIDs: %s", self.pc_name, self._cavity_uuids)

        self._current = self._initial_cavity_voltage()
        self._voltage = self._current
        sync_write_value(self, "current_set", self._current)
        self.set_state(DevState.ON)

    def _initial_cavity_voltage(self) -> float:
        try:
            from dt4acc.custom_tango.ioc.single_server import refresh_one_from_lattice, get_initial_values
            for uuid in self._cavity_uuids:
                refresh_one_from_lattice(uuid, ("voltage",))
            voltages = [
                get_initial_values(uuid).get("voltage", 0.0)
                for uuid in self._cavity_uuids
            ]
            voltages = [float(value) for value in voltages if value is not None]
            if voltages:
                return sum(voltages) / len(voltages)
        except Exception as exc:
            logger.debug("%s: could not initialise RF PC voltage: %s", self.pc_name, exc)
        return 0.0

    def _async(self, coro):
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return fut.result(timeout=10)
        except Exception as exc:
            raise DevFailed(str(exc))

    async def _fan_out_voltage(self, value: float) -> None:
        """Send voltage to every controlled cavity UUID in the AT lattice."""
        for uuid in self._cavity_uuids:
            await get_controller().update(
                cmd=Command(
                    id=uuid,
                    property="voltage",
                    value=value,
                    behaviour_on_error=BehaviourOnError.stop,
                ),
                reads=[],
                delayed_reads=[],
            )

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE,
               label="Current setpoint", unit="A")
    def current_set(self) -> float:
        return self._current

    @current_set.write
    def current_set(self, value: float) -> None:
        value = float(value)
        self._current = value
        self._voltage = value  # all cavities share the same value → average = value
        self._async(self._fan_out_voltage(value))

    @attribute(dtype=float, label="Current readback", unit="A")
    def current_readback(self) -> float:
        return self._current

    @attribute(dtype=float, label="Voltage readback", unit="V")
    def voltage(self) -> float:
        return self._voltage

    @command
    def RefreshFromCache(self) -> None:
        try:
            self._current = self._initial_cavity_voltage()
            self._voltage = self._current
            sync_write_value(self, "current_set", self._current)
            logger.info(
                "%s: RefreshFromCache done — current_set=%.3f voltage=%.3f",
                self.pc_name,
                self._current,
                self._voltage,
            )
        except Exception as exc:
            logger.error("%s: RefreshFromCache failed: %s", self.pc_name, exc)
