"""
skew_quad_device.py
===================
Tango device for CQLN and CQLT correctors mounted on octupoles.

    CQLN (QuadrupoleCorrector)     → lattice_property="B2" → PolynomB[1]
    CQLT (SkewQuadrupoleCorrector) → lattice_property="A2" → PolynomA[1]

The lattice_property DB property is set at registration time by
tango_device_setup.py based on the magnet subtype. The device uuid
is the plain host octupole UUID — no compound IDs.
"""

from tango.server import attribute, command, device_property
from tango import DevState, AttrWriteType

from dt4acc.custom_facility.model import at_integrated_strength
from dt4acc.custom_tango.ioc.devices.base_magnet_device import BaseMagnetDevice
from dt4acc.core.utils.logger import get_logger

logger = get_logger()


def _strength_unit() -> str:
    """Unit of magnetic_strength: 1/m (K * L) with integrated strengths
    (DT4ACC_INTEGRATED_STRENGTH=1), else 1/m² (the lattice coefficient K of
    a thick element)"""
    return "1/m" if at_integrated_strength.enabled() else "1/m²"


class SkewQuadDevice(BaseMagnetDevice):
    """
    Tango device for CQLN/CQLT correctors on octupoles.
    Exposes magnetic_strength (READ_WRITE).

    lattice_property is set by tango_device_setup.py:
        QuadrupoleCorrector     (CQLN) → "B2"
        SkewQuadrupoleCorrector (CQLT) → "A2"
    """

    # Set at registration time — "B2" for CQLN, "A2" for CQLT
    lattice_property = device_property(dtype=str, default_value="A2")

    def init_device(self):
        super().init_device()
        self._set_unit("magnetic_strength", _strength_unit())
        from dt4acc.custom_tango.ioc.single_server import get_initial_values
        self._magnetic_strength = get_initial_values(self.command_id).get(
            self.lattice_property,
            0.0,
        )
        self._sync_write_value("magnetic_strength", self._magnetic_strength)
        logger.info("Initializing %s: %s lattice_id=%s lattice_property=%s",
                    self.__class__.__name__, self.get_name(),
                    self.lattice_id, self.lattice_property)

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE,
               label="Magnetic strength", unit="1/m²")
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
        logger.info("%s: reset", self.magnet_name)
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
                        self.magnet_name, self._magnetic_strength)
        except Exception as exc:
            logger.error("%s: RefreshFromCache failed: %s", self.magnet_name, exc)
