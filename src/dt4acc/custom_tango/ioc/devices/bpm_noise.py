"""Noise on the BPM devices' readings (#82), Tango side

The settings are attributes of the ring simulator device (it inherits
:class:`BpmNoiseSettings`), as the twin's other settings for all BPMs
(``tbt_n_turns``):

* ``bpm_noise_sa_enable``, ``bpm_noise_sa_sigma`` [mm]: slow acquisition
  (the BPM devices' ``XPosSA`` / ``ZPosSA``)
* ``bpm_noise_tbt_enable``, ``bpm_noise_tbt_sigma`` [mm]: turn by turn
  (``XPosDD`` / ``ZPosDD``)

Off by default. Each write pushes a change event; every BPM device subscribes
to them and adds its own sample (:mod:`dt4acc.core.bl.noise`) when it gets a
new orbit or turn by turn result. The model (``orbit_x`` / ``orbit_y``, the
BPM devices' ``x`` / ``y`` in m) stays the model's.
"""
from typing import Sequence

from tango import AttrWriteType, DevDouble
from tango.server import Device, attribute

from dt4acc.core.bl.noise import BpmNoise

#: attribute name: (kind, setting)
NOISE_ATTRIBUTES = {
    f"bpm_noise_{kind}_{setting}": (kind, setting) for kind in ("sa", "tbt") for setting in ("enable", "sigma")
}


def apply_setting(noise: BpmNoise, attr_name: str, value) -> None:
    """set ``noise`` from one of :data:`NOISE_ATTRIBUTES`; ValueError for a sigma not finite and >= 0"""
    kind, setting = NOISE_ATTRIBUTES[attr_name]
    target = getattr(noise, kind)
    if setting == "enable":
        target.enabled = bool(value)
    else:
        target.set_sigma(value)


class BpmNoiseSettings(Device):
    """The BPM noise attributes; a device class inherits them"""

    def _bpm_noise(self) -> BpmNoise:
        if getattr(self, "_bpm_noise_settings", None) is None:
            self._bpm_noise_settings = BpmNoise()
            for name in NOISE_ATTRIBUTES:
                self.set_change_event(name, True, False)
        return self._bpm_noise_settings

    def _write_noise(self, attr_name: str, value) -> None:
        apply_setting(self._bpm_noise(), attr_name, value)
        kind, setting = NOISE_ATTRIBUTES[attr_name]
        target = getattr(self._bpm_noise(), kind)
        self.push_change_event(attr_name, target.enabled if setting == "enable" else target.sigma)

    @attribute(dtype=bool, access=AttrWriteType.READ_WRITE, label="BPM noise: slow acquisition",
               description="noise on the BPMs' XPosSA / ZPosSA: on / off (default)")
    def bpm_noise_sa_enable(self):
        return self._bpm_noise().sa.enabled

    @bpm_noise_sa_enable.write
    def bpm_noise_sa_enable(self, value):
        self._write_noise("bpm_noise_sa_enable", value)

    @attribute(dtype=DevDouble, access=AttrWriteType.READ_WRITE, unit="mm", min_value=0.0,
               label="BPM noise: slow acquisition sigma", description="its standard deviation, Gaussian")
    def bpm_noise_sa_sigma(self):
        return self._bpm_noise().sa.sigma

    @bpm_noise_sa_sigma.write
    def bpm_noise_sa_sigma(self, value):
        self._write_noise("bpm_noise_sa_sigma", value)

    @attribute(dtype=bool, access=AttrWriteType.READ_WRITE, label="BPM noise: turn by turn",
               description="noise on the BPMs' XPosDD / ZPosDD: on / off (default)")
    def bpm_noise_tbt_enable(self):
        return self._bpm_noise().tbt.enabled

    @bpm_noise_tbt_enable.write
    def bpm_noise_tbt_enable(self, value):
        self._write_noise("bpm_noise_tbt_enable", value)

    @attribute(dtype=DevDouble, access=AttrWriteType.READ_WRITE, unit="mm", min_value=0.0,
               label="BPM noise: turn by turn sigma", description="its standard deviation, Gaussian")
    def bpm_noise_tbt_sigma(self):
        return self._bpm_noise().tbt.sigma

    @bpm_noise_tbt_sigma.write
    def bpm_noise_tbt_sigma(self, value):
        self._write_noise("bpm_noise_tbt_sigma", value)


__all__: Sequence[str] = ["BpmNoiseSettings", "NOISE_ATTRIBUTES", "apply_setting"]
