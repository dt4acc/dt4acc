"""
steerer_device.py
==================
Tango devices for horizontal and vertical dipole correctors (steerers).

HorizontalSteererDevice → magnetic_strength, mapped to B1/PolynomB[0]
VerticalSteererDevice   → magnetic_strength, mapped to A1/PolynomA[0]

magnetic_strength: the kick angle in rad (-PolynomB[0] * L horizontally,
+PolynomA[0] * L vertically) when the twin publishes integrated strengths
(DT4ACC_INTEGRATED_STRENGTH=1), else the lattice coefficient PolynomB[0] /
PolynomA[0] itself, per metre on a thick element (opposite sign to the
kick angle horizontally). The attribute's unit follows, see _strength_unit.

Steerers can share a UUID in the AT lattice. The lattice_property DB property
routes horizontal devices to B1/PolynomB[0] and vertical devices to
A1/PolynomA[0].
"""

from tango.server import attribute, command, device_property
from tango import DevState, AttrWriteType

from dt4acc.custom_tango.ioc.devices.base_magnet_device import BaseMagnetDevice
from dt4acc.core.utils.logger import get_logger

logger = get_logger()


def _strength_unit() -> str:
    """Unit of a steerer's magnetic_strength: rad (kick angle) with
    integrated strengths, else 1/m (PolynomB[0] / PolynomA[0] of a thick
    element)"""
    from dt4acc.custom_facility.model import at_integrated_strength

    return "rad" if at_integrated_strength.enabled() else "1/m"


class HorizontalSteererDevice(BaseMagnetDevice):
    """
    Tango device for horizontal dipole correctors (CDLH, CDRH).
    Exposes magnetic_strength.
    """
    lattice_property = device_property(dtype=str, default_value="B1")

    def init_device(self):
        super().init_device()
        self._set_unit("magnetic_strength", _strength_unit())
        from dt4acc.custom_tango.ioc.single_server import get_initial_values
        self._magnetic_strength = get_initial_values(self.command_id).get(
            self.lattice_property,
            0.0,
        )
        self._sync_write_value("magnetic_strength", self._magnetic_strength)

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE,
               label="Magnetic strength", unit="1/m")
    def magnetic_strength(self) -> float:
        return self._magnetic_strength

    @magnetic_strength.write
    def magnetic_strength(self, value: float) -> None:
        value = float(value)
        self._magnetic_strength = value
        self._send(self.lattice_property, value)

    @command
    def reset(self) -> None:
        self._magnetic_strength = 0.0
        logger.info("%s: reset", self.trl.as_trl())
        self.set_state(DevState.STANDBY)

    @command
    def RefreshFromCache(self) -> None:
        try:
            from dt4acc.custom_tango.ioc.single_server import refresh_one_from_lattice, get_nominal_values
            refresh_one_from_lattice(self.command_id)
            vals = get_nominal_values(self.command_id)
            self._magnetic_strength = vals.get(self.lattice_property, 0.0)
            self._sync_write_value("magnetic_strength", self._magnetic_strength)
            logger.info("%s: RefreshFromCache done — magnetic_strength=%.6f",
                        self.trl.as_trl(), self._magnetic_strength)
        except Exception as exc:
            logger.error("%s: RefreshFromCache failed: %s", self.trl.as_trl(), exc)


class VerticalSteererDevice(BaseMagnetDevice):
    """
    Tango device for vertical dipole correctors (CDLV, CDRV).
    Exposes magnetic_strength.
    """
    lattice_property = device_property(dtype=str, default_value="A1")

    def init_device(self):
        super().init_device()
        self._set_unit("magnetic_strength", _strength_unit())
        from dt4acc.custom_tango.ioc.single_server import get_initial_values
        self._magnetic_strength = get_initial_values(self.command_id).get(
            self.lattice_property,
            0.0,
        )
        self._sync_write_value("magnetic_strength", self._magnetic_strength)

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE,
               label="Magnetic strength", unit="1/m")
    def magnetic_strength(self) -> float:
        return self._magnetic_strength

    @magnetic_strength.write
    def magnetic_strength(self, value: float) -> None:
        value = float(value)
        self._magnetic_strength = value
        self._send(self.lattice_property, value)

    @command
    def reset(self) -> None:
        self._magnetic_strength = 0.0
        logger.info("%s: reset", self.trl.as_trl())
        self.set_state(DevState.STANDBY)

    @command
    def RefreshFromCache(self) -> None:
        try:
            from dt4acc.custom_tango.ioc.single_server import refresh_one_from_lattice, get_nominal_values
            refresh_one_from_lattice(self.command_id)
            vals = get_nominal_values(self.command_id)
            self._magnetic_strength = vals.get(self.lattice_property, 0.0)
            self._sync_write_value("magnetic_strength", self._magnetic_strength)
            logger.info("%s: RefreshFromCache done — magnetic_strength=%.6f",
                        self.trl.as_trl(), self._magnetic_strength)
        except Exception as exc:
            logger.error("%s: RefreshFromCache failed: %s", self.trl.as_trl(), exc)
