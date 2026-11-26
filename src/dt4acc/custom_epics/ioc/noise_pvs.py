"""EPICS PVs of the noise on the beam position monitors' readings (:mod:`dt4acc.core.bl.noise`)

* ``noise:bpm:sa:enable``, ``noise:bpm:tbt:enable``: noise on (1) or off (0, default)
* ``noise:bpm:sa:sigma``, ``noise:bpm:tbt:sigma``: its standard deviation [mm]

``sa``: slow acquisition (``<bpm>:signal:sa:X`` / ``Y``, ``ORBITCC:rdBpm``);
``tbt``: turn by turn (``<bpm>:signal:tbt:X`` / ``Y``, ``INJ:tbt:x`` / ``y``).
A change acts on the next reading the twin publishes.
"""
from typing import Dict, Sequence

from softioc import builder as softioc_builder
from softioc.pythonSoftIoc import RecordWrapper

from dt4acc.core.bl.noise import BpmNoise, Noise


def _noise_records(builder, name: str, noise: Noise) -> Dict[str, RecordWrapper]:
    def set_enabled(value):
        noise.enabled = bool(value)

    def validate_sigma(record, value) -> bool:
        try:
            noise.set_sigma(value)
        except ValueError:
            return False
        return True

    return {
        f"{name}:enable": builder.boolOut(
            f"noise:bpm:{name}:enable", initial_value=noise.enabled, ZNAM="Off", ONAM="On", on_update=set_enabled
        ),
        f"{name}:sigma": builder.aOut(
            f"noise:bpm:{name}:sigma", initial_value=noise.sigma, PREC=6, EGU="mm", DRVL=0.0,
            validate=validate_sigma, on_update=noise.set_sigma,
        ),
    }


def initialize_bpm_noise_pvs(
    noise: BpmNoise, builder=softioc_builder, kinds: Sequence[str] = ("sa", "tbt")
) -> Dict[str, RecordWrapper]:
    """the records of ``kinds`` (a line without turn by turn: ``("sa",)``), by
    ``"sa:enable"``, ``"sa:sigma"``, ``"tbt:enable"``, ``"tbt:sigma"``"""
    records = {}
    for kind in kinds:
        records.update(_noise_records(builder, kind, getattr(noise, kind)))
    return records


__all__: Sequence[str] = ["initialize_bpm_noise_pvs"]
