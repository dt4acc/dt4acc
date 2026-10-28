"""Read a twin's static PV list (``pv_list.md``, written by make_pv_list.py)

What a test needs from it: the fields per device group (rows ``<supply>:set``,
``<magnet>:Cm:set``, ...), the device names of each group, and the PVs listed
by name, with their protocol (CA + PVA: a soft IOC record; PVA: the twin's own
PV Access server, not made by the builder).
"""
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROW = re.compile(r"^\| `([^`]+)` \|[^|]*\|[^|]*\| ([^|]+?) \|")


def read(path: Path) -> Tuple[Dict[str, Set[str]], Set[str], Set[str]]:
    """({placeholder: fields}, soft IOC PVs listed by name, PVA only PVs)

    placeholder: ``supply``, ``magnet``, ``monitor``; device names of a group
    are in the ``text`` block after its table.
    """
    fields: Dict[str, Set[str]] = {}
    named, pva_only = set(), set()
    for line in path.read_text().splitlines():
        m = ROW.match(line)
        if not m:
            continue
        pv, protocol = m.group(1), m.group(2).strip()
        p = re.match(r"<(\w+)>:(.+)", pv)
        if p:
            fields.setdefault(p.group(1), set()).add(p.group(2))
        elif protocol == "PVA":
            pva_only.add(pv)
        else:
            named.add(pv)
    return fields, named, pva_only


def group_devices(path: Path) -> Dict[str, List[str]]:
    """{"<section> / <group title>": device names} from the ``text`` blocks

    A block line is either "<family> (<n>): <name> <name> ..." or
    "<name> (<supply>) <name> (<supply>) ..." or plain names.
    """
    out, section, title, block = {}, "", "", None
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif line.startswith("#### "):
            title = re.sub(r" \(\d+\)$", "", line[5:].strip())
        elif line.strip() == "```text":
            block = []
        elif line.strip() == "```" and block is not None:
            out[f"{section} / {title}"] = block
            block = None
        elif block is not None:
            names = re.sub(r"^\S+ \(\d+\):", "", line)
            block.extend(w for w in names.split() if not w.startswith("("))
    return out
