"""Write the static BESSY II transfer line twin PV list
(``custom_facility/bessytl/pv_list.md``) from a PV dump of a running twin and
the device database.

Groups: power supplies and magnets, each sub-grouped by magnet type (from
``custom_epics/data/transfer_line/accelerator_setup.json``; steerers split by
plane), the monitors (FOMs, BPMs, striplines), then the virtual devices
(trajectory, optics, survey, BPM structures). Per PV: a short description,
what a write does, the protocol (CA and PVA for the soft IOC's records, PVA
only for the twin's p4p server; measured: pvlist per server and caget) and
whether the PV exists on the machine. PV names are given without the twin's
prefix (``DT4ACC_PREFIX``). The model (trajectory, optics, emittance, survey,
BPM structures) is under ``TL:``, as in the injection twin.

    scripts/bessyii/dump_twin_pvs.sh <dump>       # with the twin running
    python scripts/bessytl/make_pv_list.py <dump>
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "src/dt4acc/custom_epics/data/transfer_line/accelerator_setup.json"
OUT = ROOT / "src/dt4acc/custom_facility/bessytl/pv_list.md"

# on the machine: "similar" (named after the machine's device, PV name and
# format not checked against the machine), "no" (twin only)
SIMILAR, NO = "similar", "no"
# write: what a write does in the twin
ACTS, NONE, RO = "acts", "no effect", ""

SUPPLY_FIELDS = [("set", "current setpoint (A)", ACTS, SIMILAR),
                 ("rdbk", "current readback (A)", NONE, SIMILAR)]
QUAD_FIELDS = [("Cm:set", "K setpoint (1/m^2)", ACTS, NO),
               ("Cm:rdbk", "K readback (1/m^2), follows its supply", RO, NO),
               ("im:I", "driving current (A)", NONE, NO),
               ("x:set", "horizontal offset (m)", ACTS, NO),
               ("y:set", "vertical offset (m)", ACTS, NO)]
STEERER_FIELDS = [("Cm:set", "kick setpoint (rad)", ACTS, NO),
                  ("Cm:rdbk", "kick readback (rad), follows its supply", RO, NO),
                  ("im:I", "driving current (A)", NONE, NO),
                  ("x:set", "offset: a steerer cannot be moved", NONE, NO),
                  ("y:set", "offset: a steerer cannot be moved", NONE, NO)]
BEND_FIELDS = [("Cm:set", "bending angle setpoint (rad)", ACTS, NO),
               ("Cm:rdbk", "bending angle readback (rad), follows its supply", RO, NO),
               ("im:I", "driving current (A)", NONE, NO),
               ("x:set", "offset: a bend cannot be moved in the twin", NONE, NO),
               ("y:set", "offset: a bend cannot be moved in the twin", NONE, NO)]
TYPES = [("Quadrupole", "Quadrupoles", QUAD_FIELDS),
         ("Steerer:H", "Horizontal steerers", STEERER_FIELDS),
         ("Steerer:V", "Vertical steerers", STEERER_FIELDS),
         ("Bend", "Bends", BEND_FIELDS)]

#: screens: an image of the beam spot (custom_facility/bessytl/screens.py)
SCREEN_FIELDS = [("image", "image of the beam spot: image:height rows of image:width pixels, row 0 at the top (+y),"
                           " fraction of the beam per pixel", RO, NO),
                 ("image:width", "pixels per row", RO, NO),
                 ("image:height", "rows", RO, NO),
                 ("image:pixel", "pixel size (mm)", RO, NO),
                 ("x", "beam centre, horizontal (mm)", RO, NO),
                 ("y", "beam centre, vertical (mm)", RO, NO),
                 ("sigma:x", "beam size, horizontal (mm): sqrt(emittance beta)", RO, NO),
                 ("sigma:y", "beam size, vertical (mm): sqrt(emittance beta)", RO, NO),
                 ("mode", "what the screen does with the beam: Out (retracted, no image), Observe (default: shows it,"
                          " the beam passes), Stop (shows it, the monitors after it see no beam)", ACTS, NO)]
#: BPMs and striplines: named as the BPM system (dt4acc.custom_epics.ioc.bpm_pvs)
BPM_FIELDS = [("signal:sa:X", "horizontal beam position (mm)", RO, SIMILAR),
              ("signal:sa:Y", "vertical beam position (mm)", RO, SIMILAR)]
MONITORS = [("FOMZ", "FOMs (screens)"), ("BPMZ", "Beam position monitors"), ("SLZ", "Striplines (beam position monitors of another geometry)")]

# virtual devices: (section, [(pv, description, write, machine)]); a PV the dump lacks is left out
VIRTUAL = [
    ("BPMs (structures)", [
        ("TL:ORBITCC:rdBpm", "BPMZ* and striplines SLZ* positions, in lattice order (nm), structure (BPM, X, Y, ...)", RO, NO),
        ("TL:ORBITCC:rdModel", "model optics at the BPMs, structure (SPos, beta, ...)", RO, NO),
    ]),
    ("Trajectory (every lattice element and the exit of the line)", [
        ("TL:beam:orbit:x", "horizontal position (m)", RO, NO),
        ("TL:beam:orbit:y", "vertical position (m)", RO, NO),
        ("TL:beam:orbit:found", "trajectory computed", RO, NO),
        ("TL:beam:orbit:names", "element names (last: KIK4D1R:exit)", RO, NO),
        ("TL:beam:orbit:uids", "element ids", RO, NO),
        ("TL:beam:orbit:x0", "not updated", RO, NO),
    ]),
    ("Optics (every lattice element and the exit of the line)", [
        ("TL:beam:twiss:x:beta", "horizontal beta (m)", RO, NO),
        ("TL:beam:twiss:y:beta", "vertical beta (m)", RO, NO),
        ("TL:beam:twiss:x:alpha", "horizontal alpha", RO, NO),
        ("TL:beam:twiss:y:alpha", "vertical alpha", RO, NO),
        ("TL:beam:twiss:x:nu", "horizontal phase advance / 2π", RO, NO),
        ("TL:beam:twiss:y:nu", "vertical phase advance / 2π", RO, NO),
        ("TL:beam:twiss:x:tune", "not updated: a line has no tune", RO, NO),
        ("TL:beam:twiss:y:tune", "not updated: a line has no tune", RO, NO),
        ("TL:beam:twiss:names", "element names", RO, NO),
        ("TL:beam:twiss:uids", "element ids", RO, NO),
    ]),
    ("Beam", [
        ("TL:beam:emittance:x", "horizontal emittance of the beam (m rad), for the screens' images; placeholder", ACTS, NO),
        ("TL:beam:emittance:y", "vertical emittance of the beam (m rad), for the screens' images; placeholder", ACTS, NO),
    ]),
    ("Survey", [
        ("TL:survey:s", "position along the line (m)", RO, NO),
        ("TL:survey:names", "element names", RO, NO),
        ("TL:survey:uids", "element ids", RO, NO),
    ]),
]

HEADER = """\
# BESSY II transfer line twin: PV list

What the dt4acc BESSY II transfer line twin serves: {n} PVs, with a short description each.
No values: read them from a running twin. Generated by `scripts/bessytl/make_pv_list.py`
from a running twin (`scripts/bessyii/dump_twin_pvs.sh`). Names are given without the
twin's prefix: the IOC prepends `DT4ACC_PREFIX`, e.g. `<P>:Q1PT:set`. Devices keep their
machine names; the line's model is under `TL:` (`TL:beam:orbit:x`, `TL:ORBITCC:rdBpm`), the
same names as in the injection twin.

> **Not every PV here exists on the real machine.** Supplies and monitors are named after
> the machine's devices, but their PV names and formats are not checked against the
> machine. Magnet PVs, the trajectory and optics along the line and the survey exist only
> in the twin. Check a PV on the machine before using it there.

> The beam entering the line is a placeholder (`resources/input/twiss_in.yaml`, the emittance
> `TL:beam:emittance:*`): monitors read 0 until a steerer is set, the optics and the
> screens' beam size are those of an assumed entering beam.

Columns:

* **write**: *acts*: the twin acts on a write (the lattice is updated and recalculated);
  *no effect*: the record accepts a write but the twin ignores it (it overwrites the
  value itself, or nothing uses it); empty: read only.
* **protocol**: *CA + PVA*: a record of the twin's soft IOC, served over Channel Access and
  PV Access (e.g. `caget` / `pvget`, pyepics / p4p); *PVA*: served by the twin's own PV
  Access server only (structures; not readable with `caget` or pyepics).
* **machine**: *similar*: named after the machine's device, PV name and format not
  checked against the machine; *no*: twin only.
"""


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dump", type=Path, help="output folder of scripts/bessyii/dump_twin_pvs.sh")
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


def number(name: str) -> int:
    m = re.search(r"\d+", name)
    return int(m.group(0)) if m else 0


TABLE_HEAD = ["| PV | | write | protocol | machine |", "|---|---|---|---|---|"]


def row(pv, desc, write, proto, machine):
    return f"| `{pv}` | {desc} | {write} | {proto} | {machine} |"


def main(a):
    proto, prefix = read_dump(a.dump)
    db = json.loads(a.db.read_text())
    magnets = {e["name"]: magnet_type(e) for e in db}
    supplies = {e["pc"]: magnet_type(e) for e in db if e.get("pc")}
    supply_of = {e["name"]: e["pc"] for e in db if e.get("pc")}
    devices_with_pvs = {pv.partition(":")[0] for pv in proto}
    seen = set()

    def group(title, fields, devices, placeholder, names=None):
        """Field table (one protocol per field over all devices) and the device names."""
        out = [f"#### {title} ({len(devices)})", "", *TABLE_HEAD]
        for f, desc, write, machine in fields:
            pvs = [f"{d}:{f}" for d in devices]
            missing = [pv for pv in pvs if pv not in proto]
            assert not missing, f"missing in the dump: {missing[:5]}"
            (p,) = {proto[pv] for pv in pvs}
            seen.update(pvs)
            out.append(row(f"{placeholder}:{f}", desc, write, p, machine))
        listed = names or [" ".join(devices)]
        return out + ["", "```text", *listed, "```", ""]

    lines = [HEADER.format(n=len(proto)), "## Power supplies", "",
             "One supply drives one magnet, B1PT the two bends B1M1T and B1M2T (the Liaison",
             "Manager's tables). These are the PVs to set the line with. A bend's current",
             "sets its field error (PolynomB[0]): the design angle at the operating current",
             "(B1PT 232.75 A, B2PT 1.486 A), the beam bent more or less at another current.", ""]
    for key, title, _ in TYPES:
        devs = sorted((d for d, t in supplies.items() if t == key and d in devices_with_pvs), key=number)
        lines += group(title, SUPPLY_FIELDS, devs, "<supply>")

    lines += ["## Magnets (twin only)", "",
              "Every magnet of the device database, with the supply that drives it. In the twin",
              "they are for debugging: a write sets that magnet directly (not its supply); its",
              "readback follows the supply.", ""]
    for key, title, fields in TYPES:
        devs = sorted((d for d, t in magnets.items() if t == key and d in devices_with_pvs), key=number)
        lines += group(title, fields, devs, "<magnet>", [" ".join(f"{d} ({supply_of[d]})" for d in devs)])

    lines += ["## Monitors", "",
              "Beam position at each monitor of the lattice, in lattice order: the trajectory of",
              "the beam entering the line. BPMs and striplines are named as the BPM system",
              "(`<bpm>:signal:sa:X` / `Y`). Screens are no BPMs: they show an image of the beam",
              "spot, from its centre (the trajectory) and its size (the emittance and beta at the",
              "screen).", ""]
    monitor_devs = [d for d in devices_with_pvs if any(d.startswith(m) for m, _ in MONITORS)]
    for stem, title in MONITORS:
        devs = sorted((d for d in monitor_devs if d.startswith(stem)), key=lambda d: (d.endswith("R"), number(d)))
        if devs:
            if stem == "FOMZ":
                lines += group(title, SCREEN_FIELDS, devs, "<screen>")
            else:
                lines += group(title, BPM_FIELDS, devs, "<bpm>")

    lines += ["## Virtual devices", "", "Computed by the twin from the lattice.", ""]
    for title, pvdescs in VIRTUAL:
        rows = [r for r in pvdescs if r[0] in proto]
        if rows:
            lines += [f"#### {title}", "", *TABLE_HEAD,
                      *[row(pv, d, w, proto[pv], m) for pv, d, w, m in rows], ""]
            seen.update(r[0] for r in rows)

    rest = sorted(pv for pv in proto if pv not in seen)
    if rest:
        lines += ["## Other", "", "Not described yet:", "", "```text", *rest, "```", ""]
    a.out.write_text("\n".join(lines))
    n_pva_only = sum(p == "PVA" for p in proto.values())
    print(f"{a.out}: {len(proto)} PVs (prefix {prefix} dropped), {n_pva_only} PVA only, "
          f"{len(rest)} not described")


if __name__ == "__main__":
    main(parse_args())
