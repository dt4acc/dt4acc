"""EPICS PVs of the noise on the beam position monitors' readings (:mod:`dt4acc.core.bl.noise`)

* ``noise:bpm:sa:enable``, ``noise:bpm:tbt:enable``: noise on (1) or off (0, default)
* ``noise:bpm:sa:sigma``, ``noise:bpm:tbt:sigma``: its standard deviation [mm]

``sa``: slow acquisition (``<bpm>:signal:sa:X`` / ``Y``, ``ORBITCC:rdBpm``);
``tbt``: turn by turn (``<bpm>:signal:tbt:X`` / ``Y``, ``INJ:tbt:x`` / ``y``).

The noise itself works in SI units (m); the sigma PVs show it in mm, as the
BPMs' PVs: the conversion is done here, for display only. A change acts at
once when ``on_change`` republishes the readings (e.g. the view's latest
closed orbit), else on the next reading the twin publishes.
"""
from typing import Callable, Dict, Mapping, Optional, Sequence

from softioc import builder as softioc_builder
from softioc.pythonSoftIoc import RecordWrapper

from dt4acc.core.bl.noise import BpmNoise, GaussianAdditiveNoise
from dt4acc.custom_epics.ioc.bpm_pvs import M2MM


def _noise_records(
    builder, name: str, noise: GaussianAdditiveNoise, on_change: Optional[Callable[[], None]]
) -> Dict[str, RecordWrapper]:
    def changed():
        if on_change is not None:
            on_change()

    def set_enabled(value):
        noise.enabled = bool(value)
        changed()

    def validate_sigma(record, value_mm) -> bool:
        try:
            noise.set_sigma(value_mm / M2MM)
        except (TypeError, ValueError):
            return False
        return True

    def set_sigma(value_mm):
        noise.set_sigma(value_mm / M2MM)
        changed()

    return {
        f"{name}:enable": builder.boolOut(
            f"noise:bpm:{name}:enable", initial_value=noise.enabled, ZNAM="Off", ONAM="On", on_update=set_enabled
        ),
        f"{name}:sigma": builder.aOut(
            f"noise:bpm:{name}:sigma", initial_value=(noise.sigma or 0.0) * M2MM, PREC=6, EGU="mm", DRVL=0.0,
            validate=validate_sigma, on_update=set_sigma,
        ),
    }


def initialize_bpm_noise_pvs(
    noise: BpmNoise,
    builder=softioc_builder,
    kinds: Sequence[str] = ("sa", "tbt"),
    on_change: Optional[Mapping[str, Callable[[], None]]] = None,
) -> Dict[str, RecordWrapper]:
    """the records of ``kinds`` (a line without turn by turn: ``("sa",)``), by
    ``"sa:enable"``, ``"sa:sigma"``, ``"tbt:enable"``, ``"tbt:sigma"``

    ``on_change``: by kind, what republishes its readings after a change
    (e.g. ``{"sa": view.republish_monitors, "tbt": tbt_pvs.trigger}``)"""
    on_change = dict(on_change or {})
    records = {}
    for kind in kinds:
        records.update(_noise_records(builder, kind, getattr(noise, kind), on_change.get(kind)))
    return records


__all__: Sequence[str] = ["initialize_bpm_noise_pvs"]
