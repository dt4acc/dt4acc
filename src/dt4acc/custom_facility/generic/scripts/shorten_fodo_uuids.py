"""
shorten_fodo_uuids.py
======================
Shorten the UUID field of every element in fodo_lattice.json in place.

EPICS string PVs cannot hold more than 39 characters (DBF_STRING). The
UUIDs in fodo_lattice.json are "<FamName>_<32 hex chars>" — for the
7-character FamNames (BPM_xxx, COR_xxx) that's 7 + 1 + 32 = 40 chars,
one over the limit, which made custom_epics/ioc/view.py fail (or, with
its former [:39] truncation hack, silently corrupt/collide) when
pushing element uids (survey/track/twiss) to EPICS waveform records.

Truncates the hex suffix to 16 characters (64 bits — effectively no
collision risk for a lattice this size) so every UUID stays well under
the 39-character limit regardless of FamName length, and verifies
uniqueness is preserved after truncation before writing anything back.
"""

import json
import re
from pathlib import Path

LAT_FILE = Path(__file__).resolve().parent.parent / "resources" / "fodo_lattice.json"
HASH_LENGTH = 16
MAX_EPICS_STRING_LENGTH = 39


def shorten(lattice):
    seen = set()
    for elem in lattice["elements"]:
        uuid = elem.get("UUID")
        if uuid is None:
            continue
        fam_name = elem["FamName"]
        m = re.match(rf"^{re.escape(fam_name)}_([0-9a-f]+)$", uuid)
        assert m, f"Unexpected UUID format for {fam_name!r}: {uuid!r}"
        short = f"{fam_name}_{m.group(1)[:HASH_LENGTH]}"
        assert len(short) <= MAX_EPICS_STRING_LENGTH, (
            f"{short!r} ({len(short)} chars) still exceeds the EPICS string "
            f"limit of {MAX_EPICS_STRING_LENGTH} — shorten HASH_LENGTH further"
        )
        assert short not in seen, f"Truncation collision on {short!r}"
        seen.add(short)
        elem["UUID"] = short
    return lattice


def main():
    with LAT_FILE.open() as f:
        lattice = json.load(f)

    before = [e["UUID"] for e in lattice["elements"] if "UUID" in e]
    max_before = max(len(u) for u in before)

    lattice = shorten(lattice)

    after = [e["UUID"] for e in lattice["elements"] if "UUID" in e]
    max_after = max(len(u) for u in after)

    with LAT_FILE.open("w") as f:
        json.dump(lattice, f, indent=2)

    print(f"Shortened {len(after)} UUIDs in {LAT_FILE}")
    print(f"  max length before: {max_before}")
    print(f"  max length after:  {max_after}")


if __name__ == "__main__":
    main()
