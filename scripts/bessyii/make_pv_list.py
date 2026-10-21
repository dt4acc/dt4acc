"""Write the static BESSY II twin PV list (``custom_facility/bessyii/PV_LIST.md``)
from a ``pvlist`` dump of a running twin and the device database.

Groups: power supplies and magnets, each sub-grouped by magnet type (from
``accelerator_setup.json``: a supply has the type of the magnets it drives;
steerers split by plane), then the virtual devices (tune, orbit, BPMs, optics,
survey, RF, beam). PV names are given without the twin's prefix
(``DT4ACC_PREFIX``, e.g. ``BTWIN123:Q1PDR:set``).

    pvlist                      # one GUID per PVA server of the twin
    pvlist <GUID> > pvs.txt     # for each server (a twin has two), appended
    python scripts/bessyii/make_pv_list.py pvs.txt
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "src/dt4acc/custom_epics/data/standard/accelerator_setup.json"
OUT = ROOT / "src/dt4acc/custom_facility/bessyii/PV_LIST.md"

SUPPLY_FIELDS = [("set", "current setpoint (A)"), ("rdbk", "current readback (A)")]
MAGNET_FIELDS = [("Cm:set", "main strength setpoint"), ("Cm:rdbk", "main strength readback"),
                 ("im:I", "driving current (A)"), ("x:set", "horizontal offset (m)"),
                 ("y:set", "vertical offset (m)")]
TYPES = [("Quadrupole", "Quadrupoles"), ("Sextupole", "Sextupoles"),
         ("Steerer:H", "Horizontal steerers"), ("Steerer:V", "Vertical steerers")]

# virtual devices: (section, [(pv, description)]); a PV the dump lacks is left out
VIRTUAL = [
    ("Tune", [
        ("TUNEZR:flq:rdH", "horizontal tune (phase advance / 2π)"),
        ("TUNEZR:flq:rdV", "vertical tune (phase advance / 2π)"),
        ("TUNEZR:rdH", "horizontal tune frequency (kHz)"),
        ("TUNEZR:rdV", "vertical tune frequency (kHz)"),
        ("TUNEZR:count", "update counter"),
    ]),
    ("Closed orbit (every lattice element)", [
        ("beam:orbit:x", "horizontal orbit (m)"),
        ("beam:orbit:y", "vertical orbit (m)"),
        ("beam:orbit:found", "closed orbit found"),
        ("beam:orbit:names", "element names"),
        ("beam:orbit:uids", "element ids"),
        ("beam:orbit:x0", "not updated"),
    ]),
    ("BPMs", [
        ("ORBITCC:rdBpm", "BPM data, PVA structure (BPM, X, Y, buttons A–D, ...)"),
        ("ORBITCC:rdModel", "model optics at the BPMs, PVA structure (SPos, beta, ...)"),
        ("ORBITCC:rdPos", "BPM positions, legacy waveform"),
        ("ORBITCC:rdButtons", "BPM button signals, legacy waveform"),
        ("ORBITCC:rdBpmNames", "BPM names"),
        ("ORBITCC:count", "update counter"),
    ]),
    ("Optics (every lattice element)", [
        ("beam:twiss:x:beta", "horizontal beta (m)"),
        ("beam:twiss:y:beta", "vertical beta (m)"),
        ("beam:twiss:x:alpha", "horizontal alpha"),
        ("beam:twiss:y:alpha", "vertical alpha"),
        ("beam:twiss:x:nu", "horizontal phase advance / 2π"),
        ("beam:twiss:y:nu", "vertical phase advance / 2π"),
        ("beam:twiss:x:tune", "horizontal tune"),
        ("beam:twiss:y:tune", "vertical tune"),
        ("beam:twiss:names", "element names"),
        ("beam:twiss:uids", "element ids"),
    ]),
    ("Survey", [
        ("survey:s", "position along the ring (m)"),
        ("survey:names", "element names"),
        ("survey:uids", "element ids"),
    ]),
    ("RF", [
        ("MCLKHX251C:freq", "master clock, RF frequency setpoint"),
        ("CAVH1T8R:freq", "cavity 1 frequency"),
        ("CAVH2T8R:freq", "cavity 2 frequency"),
        ("CAVH3T8R:freq", "cavity 3 frequency"),
        ("CAVH4T8R:freq", "cavity 4 frequency"),
        ("lattice_info:ref_freq", "reference RF frequency"),
        ("lattice_info:ref_freq:khz:up", "reference RF frequency, integer kHz"),
        ("lattice_info:ref_freq:khz:frac", "reference RF frequency, fraction (mHz)"),
    ]),
    ("Beam / ring", [
        ("MDIZ3T5G:current", "stored beam current"),
        ("beam:rev_freq", "revolution frequency (kHz)"),
        ("beam:machine:info:n_rf_buckets", "number of RF buckets (harmonic number)"),
    ]),
]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pvlist", type=Path, help="pvlist output of the running twin, all its servers")
    p.add_argument("--db", type=Path, default=DB)
    p.add_argument("--out", type=Path, default=OUT)
    return p.parse_args()


def strip_prefix(names):
    """Drop the twin's prefix (the first field, common to all names)."""
    prefixes = {n.split(":", 1)[0] for n in names}
    assert len(prefixes) == 1, f"expected one prefix, got {sorted(prefixes)[:5]}"
    (prefix,) = prefixes
    return prefix, sorted(n.split(":", 1)[1] for n in names)


def magnet_type(entry) -> str:
    t = entry["type"]
    if t == "Steerer":
        return "Steerer:H" if entry["name"].startswith("H") else "Steerer:V"
    return t


def family(name: str) -> str:
    """Q1M1D1R -> Q1, HS4P2D3R -> HS4, VS2PD5R -> VS2."""
    m = re.match(r"[A-Z]+\d?", name)
    return m.group(0) if m else name


def device_lines(names):
    by_fam = defaultdict(list)
    for n in sorted(names):
        by_fam[family(n)].append(n)
    return [f"{fam} ({len(ns)}): " + " ".join(ns) for fam, ns in sorted(by_fam.items())]


def section(title, fields, devices, placeholder):
    out = [f"#### {title} ({len(devices)})", "", f"| PV | |", "|---|---|"]
    out += [f"| `{placeholder}:{f}` | {d} |" for f, d in fields]
    out += ["", "```text", *device_lines(devices), "```", ""]
    return out


def main(a):
    raw = [ln.strip() for ln in a.pvlist.read_text().splitlines() if ln.strip() and not ln.startswith("GUID")]
    prefix, pvs = strip_prefix(sorted(set(raw)))
    db = json.loads(a.db.read_text())
    magnets = {e["name"]: magnet_type(e) for e in db}
    supplies = {}
    for e in db:
        if e.get("pc"):
            supplies.setdefault(e["pc"], set()).add(magnet_type(e))

    devices = defaultdict(set)
    for pv in pvs:
        devices[pv.split(":", 1)[0]].add(pv.split(":", 1)[1] if ":" in pv else "")
    seen = set()

    def check(dev, fields):
        missing = {f for f, _ in fields} - devices[dev]
        assert not missing, f"{dev}: missing {missing}"
        seen.update(f"{dev}:{f}" for f, _ in fields)

    lines = ["# BESSY II twin: PV list", "",
             f"The PVs the dt4acc BESSY II twin serves (CA and PVA), {len(pvs)} in all, generated by",
             "`scripts/bessyii/make_pv_list.py` from `pvlist` of a running twin. Names are given",
             "without the twin's prefix: the IOC prepends `DT4ACC_PREFIX` (e.g. `BTWIN123:Q1PDR:set`).",
             "Writable: `set` / `Cm:set` / `im:I` / `x:set` / `y:set`, `MCLKHX251C:freq`, `MDIZ3T5G:current`.", "",
             "## Power supplies", "",
             "A supply drives one or more magnets (the Liaison Manager's tables); grouped by",
             "the type of the magnets it drives.", ""]
    for key, title in TYPES:
        devs = sorted(d for d, ts in supplies.items() if ts == {key} and d in devices)
        for d in devs:
            check(d, SUPPLY_FIELDS)
        lines += section(title, SUPPLY_FIELDS, devs, "<supply>")
    mixed = sorted(d for d, ts in supplies.items() if len(ts) > 1 and d in devices)
    assert not mixed, f"supplies driving several magnet types: {mixed}"

    lines += ["## Magnets", "", "Every magnet of the device database; a write goes through its supply's",
              "conversion to the lattice.", ""]
    for key, title in TYPES:
        devs = sorted(d for d, t in magnets.items() if t == key and d in devices)
        for d in devs:
            check(d, MAGNET_FIELDS)
        lines += section(title, MAGNET_FIELDS, devs, "<magnet>")

    lines += ["## Virtual devices", "", "Computed by the twin from the lattice (no hardware counterpart),",
              "except RF and beam current, which mirror machine PVs.", ""]
    for title, pvdescs in VIRTUAL:
        rows = [(pv, d) for pv, d in pvdescs if pv in pvs]
        if rows:
            lines += [f"#### {title}", "", "| PV | |", "|---|---|", *[f"| `{pv}` | {d} |" for pv, d in rows], ""]
            seen.update(pv for pv, _ in rows)

    rest = [pv for pv in pvs if pv not in seen]
    if rest:
        lines += ["## Other", "", "Not described yet:", "", "```text", *rest, "```", ""]
    a.out.write_text("\n".join(lines))
    print(f"{a.out}: {len(pvs)} PVs (prefix {prefix} dropped), {len(rest)} not described")


if __name__ == "__main__":
    main(parse_args())
