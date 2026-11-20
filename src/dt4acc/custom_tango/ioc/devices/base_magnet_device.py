"""
base_magnet_device.py
=====================
Shared base class for all accelerator magnet Tango devices.
Contains only lifecycle logic — no attributes or commands.
Each subclass exposes only the attributes relevant to its physical type.
"""

import asyncio

from dt4acc_lib.model.utils import tango_resource_locator
from tango import DevState, DevFailed
from tango.server import Device, device_property

from dt4acc.core.utils.logger import get_logger
from dt4acc.custom_tango.ioc.controller_registry import get_controller
from dt4acc.core.bl.shared_event_loop import get_shared_event_loop
from dt4acc.custom_tango.ioc.devices.write_value_sync import sync_write_value

logger = get_logger()


class BaseMagnetDevice(Device):
    """
    Shared base for all magnet device types across all facilities.

    Subclasses add only the attributes that make physical sense:
        MultipoleDevice         → magnetic_strength + readback
        HorizontalSteererDevice → magnetic_strength
        VerticalSteererDevice   → magnetic_strength
        SkewQuadDevice          → magnetic_strength
        CavityDevice            → frequency + voltage
    """

    element_uuid = device_property(dtype=str, default_value="")

    def init_device(self):
        super().init_device()
        self.set_state(DevState.INIT)

        full_name = self.get_name()
        self.trl = tango_resource_locator.TangoResourceLocator.from_trl(full_name)

        self.magnet_name = full_name
        self.domain      = self.trl.domain
        self.family      = self.trl.family
        self.member      = self.trl.member

        # UUID is the unique key into the pyAT lattice.
        # Falls back to member name if not set (shouldn't happen after registration).
        self.lattice_id = self.element_uuid if self.element_uuid else self.member
        # the id the device writes and reads by, see _command_id
        self.command_id = self._command_id()

        logger.info("Initializing %s: %s lattice_id=%s",
                    self.__class__.__name__, self.magnet_name, self.lattice_id)

        self._loop = get_shared_event_loop()
        self.set_state(DevState.ON)

    def _command_id(self) -> str:
        """The id of the device's commands: its own name when the engine
        translates them (the liaison manager and the translation service
        convert its values to its lattice element's), else its lattice
        element (see mexec_server_for_physics_engine.translated_design_view)."""
        from dt4acc.custom_tango.ioc.mexec_server_for_physics_engine import translated_design_view

        return self.magnet_name if translated_design_view() else self.lattice_id

    def _set_unit(self, attr_name: str, unit: str) -> None:
        """Set the unit of the attribute ``attr_name``, for a unit known only
        at run time (e.g. integrated strengths or not, see
        dt4acc.custom_facility.model.at_integrated_strength.enabled)"""
        attr = self.get_device_attr().get_attr_by_name(attr_name)
        props = attr.get_properties()
        if props.unit != unit:
            props.unit = unit
            attr.set_properties(props)

    def _async(self, coro):
        """Submit coroutine to shared loop, block until done, raise DevFailed on error."""
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return fut.result(timeout=10)
        except Exception as exc:
            raise DevFailed(str(exc))

    def _send(self, property_name: str, value: float) -> None:
        """Send a set command to the backend via TangoController.

        cmd.id = self.command_id: the device's name when the engine
        translates its commands (the device's value converted to its lattice
        element's there), else its lattice element (the AT element uuid
        stored in element_uuid DB property), written as is.
        """
        from dt4acc_lib.model.utils.command import Command, BehaviourOnError

        self._async(
            get_controller().update(
                cmd=Command(
                    id=self.command_id,
                    property=property_name,
                    value=value,
                    behaviour_on_error=BehaviourOnError.stop,
                ),
                reads=[],
                delayed_reads=[],
            )
        )

    def _sync_write_value(self, attr_name: str, value) -> None:
        sync_write_value(self, attr_name, value)
