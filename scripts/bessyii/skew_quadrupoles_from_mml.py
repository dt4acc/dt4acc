"""Add BESSY II's skew quadrupoles (MML family CQS) to the twin's inputs:
``resources/storage_ring/input/magnets.yaml`` and ``power_converters.yaml``
(for create_managers_input.py) and the device database
``custom_epics/data/standard/accelerator_setup.json`` (for the PVs).

From MML's accelerator object (``ao``, HZB MML fork, BESSY II ``*init.m``):
16 skew quadrupoles ``CQS<f>M<n><sector>R``, each on its own supply
``CQS<f>P<n><sector>R`` (``Setpoint.ChannelNames``), coils on the sextupole
``S<f>M<n><sector>R`` (``AT.ATIndex``); ``K = HW2PhysicsParams * I`` at the
design energy (1.7185 GeV, brho 5.67229 T m), i.e. ``K * brho = slope * I``
with slope = HW2PhysicsParams * 5.67229 (the convention of the other magnets
in magnets.yaml). Existing CQS entries are replaced.

    python scripts/bessyii/skew_quadrupoles_from_mml.py <path to the MML ao export (bessyii_ao_cfg.json)>
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "src/dt4acc/custom_facility/bessyii/resources/storage_ring/input"
DEVICE_DB = ROOT / "src/dt4acc/custom_epics/data/standard/accelerator_setup.json"
BRHO = 5.67229387129245          # 1.7185 GeV, the twin's design energy (custom_epics/data/constants.py)


def host_of(magnet: str) -> str:
    """CQS3M1T1R -> S3M1T1R: the sextupole the skew coil is wound on"""
    assert magnet.startswith("CQ"), magnet
    return magnet[2:]


def main(ao_path: str):
    ao = json.loads(Path(ao_path).read_text())
    cqs = ao["CQS"]
    names = cqs["CommonNames"]
    supplies = [c.split(":")[0] for c in cqs["Setpoint"]["ChannelNames"]]
    gains = cqs["Setpoint"]["HW2PhysicsParams"]
    gains = gains if isinstance(gains, list) else [gains] * len(names)
    assert len(names) == len(supplies) == len(gains) == 16, (len(names), len(supplies), len(gains))

    magnets_file = INPUT / "magnets.yaml"
    text = magnets_file.read_text()
    magnets = yaml.safe_load(text)
    if any(m.get("type") == "skew_quadrupole" for m in magnets):
        sys.exit(f"{magnets_file}: has skew quadrupoles already")
    sextupoles = {m["elem_id"] for m in magnets if m["type"] == "sextupole"}
    for name in names:
        assert host_of(name) in sextupoles, f"{name}: host {host_of(name)} is not a sextupole"
    # appended in the file's own style (it is formatted by hand)
    blocks = [f"""- elem_id: {n}
  dev_id: {n}
  type: skew_quadrupole
  family_member: [ coupling_correction ]
  power_converter_id: {pc}
  conversion:
    intercept: 0.0
    slope: {float(g) * BRHO!r}
    conversion_type: linear
""" for n, pc, g in zip(names, supplies, gains)]
    magnets_file.write_text(text.rstrip("\n") + "\n\n# skew quadrupoles (MML CQS): coils on the sextupole of the "
                            "name without CQ; K * brho = slope * I\n" + "\n".join(blocks))

    pcs_file = INPUT / "power_converters.yaml"
    text = pcs_file.read_text()
    if "CQS" in text:
        sys.exit(f"{pcs_file}: has skew quadrupole supplies already")
    pcs_file.write_text(text.rstrip("\n") + "\n" + "".join(f"""- id: {pc}
  interface:
    setpoint: {pc}:set
    readback: {pc}:rdbk
  response:
    settle_time: 0.5
    timeout: 2.0
""" for pc in supplies))

    text = DEVICE_DB.read_text()
    if "SkewQuadrupoleCorrector" in text:
        sys.exit(f"{DEVICE_DB}: has skew quadrupoles already")
    entries = ",".join(json.dumps({"type": "SkewQuadrupoleCorrector", "name": n, "magnetic_strength": float(g) * BRHO,
                                   "pc": pc, "k": 0.0, "host": host_of(n)}, indent=2)
                       for n, pc, g in zip(names, supplies, gains))
    body = text.rstrip().rstrip("]").rstrip()
    DEVICE_DB.write_text(body + "," + entries + "]\n")
    json.loads(DEVICE_DB.read_text())          # still valid
    print(f"{len(names)} skew quadrupoles: {magnets_file.name}, {pcs_file.name}, {DEVICE_DB.name}")


if __name__ == "__main__":
    main(sys.argv[1])
