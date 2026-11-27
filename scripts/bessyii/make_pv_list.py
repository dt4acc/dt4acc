"""Write the static BESSY II twin PV list (``custom_facility/bessyii/pv_list.md``)
from a PV dump of a running twin and the device database.

Groups: power supplies and magnets, each sub-grouped by magnet type (from
``accelerator_setup.json``: a supply has the type of the magnets it drives;
steerers split by plane), the ring BPMs, the virtual devices (tune, orbit, BPMs,
optics, survey, RF, beam, pinhole cameras, simulation, noise), then what only the
ring twin alone serves: turn by turn and the lattice loaded at run time. Per PV: a short description, what a write does, the
protocol (CA and PVA for the soft IOC's records, PVA only for the twin's p4p
server; measured: pvlist per server and caget) and whether the PV exists on
the real machine. PV names are given without the twin's prefix
(``DT4ACC_PREFIX``, e.g. ``BTWIN123:Q1PDR:set``).

    scripts/bessyii/dump_twin_pvs.sh <dump>       # with a twin running
    python scripts/bessyii/make_pv_list.py <dump>
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "src/dt4acc/custom_epics/data/standard/accelerator_setup.json"
OUT = ROOT / "src/dt4acc/custom_facility/bessyii/pv_list.md"

# on the machine: "yes" (names checked against the BESSY II MML channel names),
# "similar" (the twin's version of a machine PV; its name or format may differ
# on the machine: check before using it there), "no" (twin only)
YES, SIMILAR, NO = "yes", "similar", "no"
# write: what a write does in the twin
ACTS, NONE, RO = "acts", "no effect", ""

SUPPLY_FIELDS = [("set", "current setpoint (A)", ACTS, YES),
                 ("rdbk", "current readback (A)", NONE, YES)]
MAGNET_FIELDS = [("Cm:set", "main strength setpoint", ACTS, NO),
                 ("Cm:rdbk", "main strength readback", RO, NO),
                 ("im:I", "driving current (A)", ACTS, NO),
                 ("x:set", "horizontal offset (m)", ACTS, NO),
                 ("y:set", "vertical offset (m)", ACTS, NO)]
TYPES = [("Quadrupole", "Quadrupoles"), ("Sextupole", "Sextupoles"),
         ("Steerer:H", "Horizontal steerers"), ("Steerer:V", "Vertical steerers"),
         ("SkewQuadrupoleCorrector", "Skew quadrupoles (MML CQS; coils on sextupoles)")]

# virtual devices: (section, [(pv, description, write, machine)]); a PV the dump lacks is left out
VIRTUAL = [
    ("Tune", [
        ("TUNEZR:rdH", "horizontal tune frequency (kHz)", NONE, SIMILAR),
        ("TUNEZR:rdV", "vertical tune frequency (kHz)", NONE, SIMILAR),
        ("TUNEZR:count", "update counter", NONE, SIMILAR),
        ("TUNEZR:flq:rdH", "horizontal tune (phase advance / 2π)", NONE, NO),
        ("TUNEZR:flq:rdV", "vertical tune (phase advance / 2π)", NONE, NO),
    ]),
    ("BPMs", [
        ("ORBITCC:rdPos", "BPM positions, legacy waveform", RO, SIMILAR),
        ("ORBITCC:rdButtons", "BPM button signals, legacy waveform", RO, SIMILAR),
        ("ORBITCC:rdBpmNames", "BPM names", RO, SIMILAR),
        ("ORBITCC:count", "update counter", RO, SIMILAR),
        ("ORBITCC:rdBpm", "BPM data, structure (BPM, X, Y, buttons A–D, ...)", RO, SIMILAR),
        ("ORBITCC:rdModel", "model optics at the BPMs, structure (SPos, beta, ...)", RO, NO),
    ]),
    ("Closed orbit (every lattice element)", [
        ("beam:orbit:x", "horizontal orbit (m)", RO, NO),
        ("beam:orbit:y", "vertical orbit (m)", RO, NO),
        ("beam:orbit:found", "closed orbit found", RO, NO),
        ("beam:orbit:names", "element names", RO, NO),
        ("beam:orbit:uids", "element ids", RO, NO),
        ("beam:orbit:x0", "not updated", RO, NO),
    ]),
    ("Optics (every lattice element)", [
        ("beam:twiss:x:beta", "horizontal beta (m)", RO, NO),
        ("beam:twiss:y:beta", "vertical beta (m)", RO, NO),
        ("beam:twiss:x:alpha", "horizontal alpha", RO, NO),
        ("beam:twiss:y:alpha", "vertical alpha", RO, NO),
        ("beam:twiss:x:nu", "horizontal phase advance / 2π", RO, NO),
        ("beam:twiss:y:nu", "vertical phase advance / 2π", RO, NO),
        ("beam:twiss:x:tune", "horizontal tune", RO, NO),
        ("beam:twiss:y:tune", "vertical tune", RO, NO),
        ("beam:twiss:names", "element names", RO, NO),
        ("beam:twiss:uids", "element ids", RO, NO),
    ]),
    ("Survey", [
        ("survey:s", "position along the ring (m)", RO, NO),
        ("survey:names", "element names", RO, NO),
        ("survey:uids", "element ids", RO, NO),
    ]),
    ("RF", [
        ("MCLKHX251C:freq", "master clock, RF frequency setpoint", ACTS, YES),
        ("CAVH1T8R:freq", "cavity 1 frequency", RO, SIMILAR),
        ("CAVH2T8R:freq", "cavity 2 frequency", RO, SIMILAR),
        ("CAVH3T8R:freq", "cavity 3 frequency", RO, SIMILAR),
        ("CAVH4T8R:freq", "cavity 4 frequency", RO, SIMILAR),
        ("lattice_info:ref_freq", "reference RF frequency", RO, NO),
        ("lattice_info:ref_freq:khz:up", "reference RF frequency, integer kHz", RO, NO),
        ("lattice_info:ref_freq:khz:frac", "reference RF frequency, fraction (mHz)", RO, NO),
    ]),
    ("Beam / ring", [
        ("MDIZ3T5G:current", "stored beam current", NONE, YES),
        ("beam:rev_freq", "revolution frequency (kHz)", RO, NO),
        ("beam:machine:info:n_rf_buckets", "number of RF buckets (harmonic number)", RO, NO),
    ]),
    ("Pinhole cameras", [
        ("PINH3FD2L:rdCenterX", "horizontal beam centre (mm), at the entrance of BM2D2R (its source point PINH3 not in the lattice yet)", RO, SIMILAR),
        ("PINH3FD2L:rdSigmaX", "horizontal beam size (mm)", RO, SIMILAR),
        ("PINH3FD2L:rdCenterY", "vertical beam centre (mm), at the entrance of BM2D2R (its source point PINH3 not in the lattice yet)", RO, SIMILAR),
        ("PINH3FD2L:rdSigmaY", "vertical beam size (mm)", RO, SIMILAR),
        ("PINH3FD2L:image", "image of the Gaussian beam spot, rows from the top", RO, NO),
        ("PINH3FD2L:image:width", "pixels per row", RO, NO),
        ("PINH3FD2L:image:height", "rows", RO, NO),
        ("PINH3FD2L:image:pixel", "pixel size (mm); placeholder", RO, NO),
        ("PINH9FD5L:rdCenterX", "horizontal beam centre (mm), at the entrance of BM2D5R (its source point PINH9 not in the lattice yet)", RO, SIMILAR),
        ("PINH9FD5L:rdSigmaX", "horizontal beam size (mm)", RO, SIMILAR),
        ("PINH9FD5L:rdCenterY", "vertical beam centre (mm), at the entrance of BM2D5R (its source point PINH9 not in the lattice yet)", RO, SIMILAR),
        ("PINH9FD5L:rdSigmaY", "vertical beam size (mm)", RO, SIMILAR),
        ("PINH9FD5L:image", "image of the Gaussian beam spot, rows from the top", RO, NO),
        ("PINH9FD5L:image:width", "pixels per row", RO, NO),
        ("PINH9FD5L:image:height", "rows", RO, NO),
        ("PINH9FD5L:image:pixel", "pixel size (mm); placeholder", RO, NO),
        ("beam:emittance:x", "horizontal emittance of the stored beam (m rad), calculated from the lattice; the pinhole cameras' size", RO, NO),
        ("beam:emittance:y", "vertical emittance of the stored beam (m rad), calculated from the lattice: from coupling (skew quadrupoles), else about 0", RO, NO),
    ]),
    ("Simulation", [
        ("simulator_ring:reset", "a write clears the stored results and recalculates", ACTS, NO),
        ("simulator_ring:reinit", "a write puts the lattice back to its start values, then recalculates", ACTS, NO),
    ]),
    ("Noise on the BPMs' readings (#82)", [
        ("noise:bpm:sa:enable", "noise on the BPMs' slow acquisition (<bpm>:signal:sa:X / Y, ORBITCC:rdBpm): On / Off (default)", ACTS, NO),
        ("noise:bpm:sa:sigma", "its standard deviation (mm), Gaussian; placeholder 0.001", ACTS, NO),
        ("noise:bpm:tbt:enable", "noise on the BPMs' turn by turn data (<bpm>:signal:tbt:X / Y): On / Off (default)", ACTS, NO),
        ("noise:bpm:tbt:sigma", "its standard deviation (mm), Gaussian; placeholder 0.01", ACTS, NO),
    ]),
]

BPM_FIELDS = [("signal:sa:X", "horizontal position (mm)", RO, SIMILAR),
              ("signal:sa:Y", "vertical position (mm)", RO, SIMILAR)]
BPMS_INTRO = ["Position at each ring BPM, named as the BPM system: the closed orbit (slow acquisition)."]

# the ring twin alone: turn by turn (dt4acc.custom_epics.ioc.turn_by_turn)
TBT_INTRO = [
    "A beam started at the beginning of the ring lattice, at the closed orbit plus an offset (e.g. a",
    "kicked beam), tracked for some turns and read at the ring's BPMs. Recomputed when a setting",
    "changes and after each new closed orbit. Only the ring twin alone serves the `TBT:` PVs; the",
    "injection twin serves the BPMs' turn by turn PVs of its hand over instead (beam from the",
    "transfer line). The computation is shared by the twins, EPICS and Tango:",
    "`dt4acc.core.bl.turn_by_turn`; the PVs: `dt4acc.custom_epics.ioc.turn_by_turn`.",
]
_TBT_COORDS = [("x", "horizontal (m)", "horizontal (m)"),
               ("px", "horizontal angle (rad)", "horizontal angle (rad)"),
               ("y", "vertical (m)", "vertical (m)"),
               ("py", "vertical angle (rad)", "vertical angle (rad)"),
               ("delta", "momentum deviation", "momentum deviation"),
               ("ct", "path length (m)", "path length (m)")]
TBT_SETTINGS = (
    [(f"TBT:offset:{c}", f"start offset from the closed orbit, {d}", ACTS, NO) for c, d, _ in _TBT_COORDS]
    + [("TBT:n_turns", "turns tracked (1 ... 65536, as the BPM electronics)", ACTS, NO),
       ("TBT:stop_at", "element the beam ends at (one name; empty: none)", ACTS, NO)]
    + [(f"TBT:start:{c}", ("start state tracked: closed orbit + offset, " if c == "x" else "start state tracked, ") + d,
        RO, NO) for c, _, d in _TBT_COORDS]
    + [("TBT:count", "computations so far", RO, NO)]
)
TBT_BPM_FIELDS = [("signal:tbt:X", "horizontal position, turn after turn (mm)", RO, NO),
                  ("signal:tbt:Y", "vertical position, turn after turn (mm)", RO, NO),
                  ("signal:tbt:survived", "particles still there, turn after turn", RO, NO)]

# the ring twin alone: another lattice loaded at run time (#81)
LATTICE_INTRO = [
    "A lattice with small differences replaces the simulated one, e.g. the ring with its wavelength",
    "shifters inserted (`bessy2_storage_ring_wls.json`). It must hold every magnet, cavity and BPM of",
    "the twin, in the same order; other elements may differ, otherwise the load is refused and the",
    "lattice kept. Loaded from the lattice directory (`DT4ACC_LATTICE_DIR`, default the directory of",
    "the bundled lattice): a file name only. After a load the supplies', magnets' and RF PVs show",
    "the new lattice's values (nothing is written back) and the model is recomputed; a client",
    "restores its own settings itself. Only the ring twin alone serves these PVs.",
]
LATTICE = [
    ("simulator_ring:lattice", "a write loads that lattice file of the lattice directory (empty: the start lattice)", ACTS, NO),
    ("simulator_ring:lattice:message", "result of the last lattice load: `loaded ...` or `refused: ...`", RO, NO),
]

HEADER = """\
# BESSY II twin: PV list

What the dt4acc BESSY II twin serves: {n} PVs, with a short description each. No values: read
them from a running twin. Generated by `scripts/bessyii/make_pv_list.py` from a running twin
(`scripts/bessyii/dump_twin_pvs.sh`). Names are given without the twin's prefix: the IOC
prepends `DT4ACC_PREFIX`, e.g. `BTWIN123:Q1PDR:set`.

> **Not every PV here exists on the real machine.** The twin adds PVs of its own: magnet PVs
> (at BESSY II magnets are driven through their power supplies, so `<magnet>:Cm:set` and
> the other magnet PVs exist only in the twin), the model's optics, orbit at every element,
> survey and lattice information. A script that uses them runs against the twin but not in
> the control room. Use the PVs marked **yes** under *machine* for anything that should
> also run on BESSY II.

Columns:

* **write**: *acts*: the twin acts on a write (the lattice is updated and recalculated);
  *no effect*: the record accepts a write but the twin ignores it (it overwrites the
  value itself, or nothing uses it); empty: read only.
* **protocol**: *CA + PVA*: a record of the twin's soft IOC, served over Channel Access and
  PV Access (e.g. `caget` / `pvget`, pyepics / p4p); *PVA*: served by the twin's own PV
  Access server only (structures; not readable with `caget` or pyepics).
* **machine**: *yes*: the PV exists on BESSY II under this name; *similar*: the twin's
  version of a machine PV, its name or format may differ on the machine (check before
  using it there); *no*: twin only.
"""


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dump", type=Path, help="output folder of dump_twin_pvs.sh")
    p.add_argument("--db", type=Path, default=DB)
    p.add_argument("--out", type=Path, default=OUT)
    return p.parse_args()


def strip_prefix(names):
    """(prefix, names without it): the first field, common to all names."""
    prefixes = {n.split(":", 1)[0] for n in names}
    assert len(prefixes) == 1, f"expected one prefix, got {sorted(prefixes)[:5]}"
    (prefix,) = prefixes
    return prefix, {n: n.split(":", 1)[1] for n in names}


def read_dump(folder: Path):
    """{pv (no prefix): "CA + PVA" | "PVA"}, prefix."""
    pva = [ln.strip() for ln in (folder / "pvs_by_server.txt").read_text().splitlines()
           if ln.strip() and not ln.startswith("GUID")]
    ca = set((folder / "pvs_ca.txt").read_text().split())
    prefix, short = strip_prefix(sorted(set(pva)))
    unknown = ca - set(short)
    assert not unknown, f"CA PVs pvlist did not report: {sorted(unknown)[:5]}"
    return {short[n]: ("CA + PVA" if n in ca else "PVA") for n in short}, prefix


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


TABLE_HEAD = ["| PV | | write | protocol | machine |", "|---|---|---|---|---|"]


def row(pv, desc, write, proto, machine):
    return f"| `{pv}` | {desc} | {write} | {proto} | {machine} |"


def main(a):
    proto, prefix = read_dump(a.dump)
    db = json.loads(a.db.read_text())
    magnets = {e["name"]: magnet_type(e) for e in db}
    supplies = {}
    for e in db:
        if e.get("pc"):
            supplies.setdefault(e["pc"], set()).add(magnet_type(e))
    fields_of = defaultdict(set)
    for pv in proto:
        dev, _, f = pv.partition(":")
        fields_of[dev].add(f)
    seen = set()

    def group(title, fields, devices, placeholder, names=None):
        """Field table (one protocol per field over all devices) and the device names
        (``names``: their lines; default by family)."""
        out = [f"#### {title} ({len(devices)})", "", *TABLE_HEAD]
        for f, desc, write, machine in fields:
            pvs = [f"{d}:{f}" for d in devices]
            missing = [pv for pv in pvs if pv not in proto]
            assert not missing, f"missing in the dump: {missing[:5]}"
            (p,) = {proto[pv] for pv in pvs}
            seen.update(pvs)
            out.append(row(f"{placeholder}:{f}", desc, write, p, machine))
        return out + ["", "```text", *(device_lines(devices) if names is None else names), "```", ""]

    def table(title, pvdescs):
        """the PVs of ``pvdescs`` the dump has, as one table (nothing if none)"""
        rows = [r for r in pvdescs if r[0] in proto]
        seen.update(r[0] for r in rows)
        return [f"#### {title}", "", *TABLE_HEAD, *[row(pv, d, w, proto[pv], m) for pv, d, w, m in rows], ""] \
            if rows else []

    def bpms_with(field):
        """the BPMs (device names) with ``<bpm>:<field>``, in the order of their names"""
        return sorted(pv[: -len(field) - 1] for pv in proto if pv.endswith(f":{field}"))

    lines = [HEADER.format(n=len(proto)), "## Power supplies", "",
             "A supply drives one or more magnets (the Liaison Manager's tables); grouped by",
             "the type of the magnets it drives. These are the PVs to use for magnets on the machine.", ""]
    mixed = sorted(d for d, ts in supplies.items() if len(ts) > 1 and d in fields_of)
    assert not mixed, f"supplies driving several magnet types: {mixed}"
    for key, title in TYPES:
        lines += group(title, SUPPLY_FIELDS, sorted(d for d, ts in supplies.items()
                                                     if ts == {key} and d in fields_of), "<supply>")

    lines += ["## Magnets (twin only)", "",
              "Every magnet of the device database. There are no magnet PVs on BESSY II: magnets",
              "are only set through their power supplies. In the twin they are for debugging, to",
              "set one magnet directly (a write goes to that magnet's lattice elements, not to its",
              "supply); scripts meant for the machine use the supply PVs above.", ""]
    for key, title in TYPES:
        lines += group(title, MAGNET_FIELDS, sorted(d for d, t in magnets.items()
                                                    if t == key and d in fields_of), "<magnet>")

    bpms = bpms_with(BPM_FIELDS[0][0])
    if bpms:
        lines += ["## BPMs", "", *BPMS_INTRO, "",
                  *group("Ring BPMs", BPM_FIELDS, bpms, "<bpm>", [" ".join(bpms)])]

    lines += ["## Virtual devices", "",
              "Computed by the twin from the lattice; some mirror machine PVs (see *machine*).", ""]
    for title, pvdescs in VIRTUAL:
        lines += table(title, pvdescs)

    tbt_bpms = bpms_with(TBT_BPM_FIELDS[0][0])
    settings = table("Settings and results", TBT_SETTINGS)
    if settings or tbt_bpms:
        lines += ["## Turn by turn (ring twin alone)", "", *TBT_INTRO, "", *settings]
        if tbt_bpms:
            lines += group("Ring BPMs, turn by turn", TBT_BPM_FIELDS, tbt_bpms, "<bpm>", [" ".join(tbt_bpms)])

    lattice = table("Lattice", LATTICE)
    if lattice:
        lines += ["## Lattice at run time (ring twin alone)", "", *LATTICE_INTRO, "", *lattice]

    rest = sorted(pv for pv in proto if pv not in seen)
    if rest:
        lines += ["## Other", "", "Not described yet:", "", "```text", *rest, "```", ""]
    a.out.write_text("\n".join(lines))
    n_pva_only = sum(p == "PVA" for p in proto.values())
    print(f"{a.out}: {len(proto)} PVs (prefix {prefix} dropped), {n_pva_only} PVA only, "
          f"{len(rest)} not described")


if __name__ == "__main__":
    main(parse_args())
