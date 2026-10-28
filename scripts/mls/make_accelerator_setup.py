"""Write the MLS twin's device database (``custom_facility/mls/resources/input/
accelerator_setup.json``) from MML's accelerator object (``ao_mls.json``, same
folder; exported from the HZB MML fork, ``machine/MLS/StorageRing/mlsinit.m``)

Per magnet of the families Q1-Q3, S1-S3, HCM, VCM: its name (``CommonNames``),
type, family, the supply that drives it (``Setpoint.ChannelNames`` without the
field) and MML's calibration (``amp2k.m``: ``k = polyval(amp2k, I / scale) /
Brho``; ``Setpoint.HW2PhysicsParams``) with the setpoint range. Steerers are
named after the magnet they kick (``HS3M2K1RP`` kicks ``S3M2K1RP``).

    python scripts/mls/make_accelerator_setup.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "src/dt4acc/custom_facility/mls/resources/input"

#: MML family: type in the device database
FAMILIES = {"Q1": "Quadrupole", "Q2": "Quadrupole", "Q3": "Quadrupole",
            "S1": "Sextupole", "S2": "Sextupole", "S3": "Sextupole",
            "HCM": "Steerer", "VCM": "Steerer"}


def per_device(value, n):
    """MML stores a field once for the family or once per device"""
    if isinstance(value, list) and len(value) == n:
        return value
    return [value] * n


def main():
    ao = json.loads((INPUT / "ao_mls.json").read_text())
    out = []
    for family, kind in FAMILIES.items():
        f = ao[family]
        sp = f["Setpoint"]
        names = f["CommonNames"]
        n = len(names)
        params = sp["HW2PhysicsParams"]
        coeffs = params[0]
        scales = per_device(params[1], n) if len(params) > 1 else [1.0] * n
        ranges = per_device(sp.get("Range"), n)
        for i, name in enumerate(names):
            scale = scales[i][0] if isinstance(scales[i], list) else scales[i]
            out.append({
                "type": kind,
                "family": family,
                "name": name,
                "pc": sp["ChannelNames"][i].split(":")[0],
                "amp2k": [float(c) for c in coeffs[i]],
                "amp2k_scale": float(scale),
                "range": [float(x) for x in ranges[i]] if ranges[i] and None not in ranges[i] else None,
            })
    path = INPUT / "accelerator_setup.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{path}: {len(out)} magnets, {len({e['pc'] for e in out})} supplies")


if __name__ == "__main__":
    main()
