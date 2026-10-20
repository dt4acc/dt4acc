"""
multipole_device.py
====================
Tango device for Quadrupoles, Sextupoles, Octupoles and Multipoles.
Exposes: magnetic_strength (READ_WRITE) + magnetic_strength_readback (READ).

The `lattice_property` DB property stores the correct AT property name
per subtype (B2/B3/B4 in device view, main_strength in design view).
"""

from tango.server import attribute, command, device_property
from tango import DevState, AttrWriteType

from dt4acc.custom_tango.ioc.devices.base_magnet_device import BaseMagnetDevice
from dt4acc.core.utils.logger import get_logger

logger = get_logger()


class MultipoleDevice(BaseMagnetDevice):
    """
    Tango device for Quadrupoles, Sextupoles, Octupoles and Multipoles.
    Exposes magnetic_strength and its readback.
    """

    # AT property name — set at registration time by tango_device_setup.py.
    # Quad→"B2", Sext→"B3", Oct→"B4" in device view.
    # Defaults to "main_strength" (design view).
    lattice_property = device_property(dtype=str, default_value="main_strength")

    def init_device(self):
        super().init_device()
        from dt4acc.custom_tango.ioc.single_server import get_initial_values
        vals = get_initial_values(self.lattice_id)
        self._magnetic_strength = vals.get(self.lattice_property,
                                           vals.get("main_strength", 0.0))
        self._magnetic_strength_readback = self._magnetic_strength
        self._sync_write_value("magnetic_strength", self._magnetic_strength)

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE,
               label="Magnetic strength", unit="1/m",
               polling_period=1000)
    def magnetic_strength(self) -> float:
        try:
            from dt4acc.custom_tango.ioc.single_server import peek_from_lattice
            val = peek_from_lattice(self.lattice_id, self.lattice_property)
            if val != 0.0:
                self._magnetic_strength = val
                self._magnetic_strength_readback = val
        except Exception:
            pass
        return self._magnetic_strength

    @magnetic_strength.write
    def magnetic_strength(self, value: float) -> None:
        value = float(value)
        self._magnetic_strength = value
        self._send(self.lattice_property, value)
        self._magnetic_strength_readback = value

    @attribute(dtype=float, label="Magnetic strength readback", unit="1/m")
    def magnetic_strength_readback(self) -> float:
        return self._magnetic_strength_readback

    @command
    def reset(self) -> None:
        self._magnetic_strength = 0.0
        self._magnetic_strength_readback = 0.0
        logger.info("%s: reset", self.magnet_name)
        self.set_state(DevState.STANDBY)

    @command
    def RefreshFromCache(self) -> None:
        """Read nominal values from process-local cache after system reset."""
        try:
            from dt4acc.custom_tango.ioc.single_server import refresh_one_from_lattice, get_nominal_values
            refresh_one_from_lattice(self.lattice_id)
            vals = get_nominal_values(self.lattice_id)
            self._magnetic_strength = vals.get(self.lattice_property,
                                               vals.get("main_strength", 0.0))
            self._magnetic_strength_readback = self._magnetic_strength
            self._sync_write_value("magnetic_strength", self._magnetic_strength)
            logger.info("%s: RefreshFromCache done — strength=%.6f",
                        self.magnet_name, self._magnetic_strength)
        except Exception as exc:
            logger.error("%s: RefreshFromCache failed: %s", self.magnet_name, exc)
