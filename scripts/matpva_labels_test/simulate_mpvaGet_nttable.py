"""
simulate_mpvaGet_nttable.py
=============================
Pure-Python reproduction of matpva's mpvaGet.m NTTable branch — NOT a
run of matpva itself (that requires MATLAB, which this deliberately
avoids). matpva is MATLAB glue code that calls into p4p via MATLAB's
Python bridge; this script makes the exact same p4p calls directly,
so you can verify the "labels" fix without installing MATLAB.

The currently-deployed (unpatched) mpvaGet.m does, for an NTTable PV:

    a           = struct(todict(PV)).labels;
    aa          = string(cell(a));
    numElement  = numel(aa);

    type_struct = struct(py.dict(struct(py.dict(type(PV))).value));
    val_struct  = struct(struct(todict(PV)).value);

    for iElement = 1 : numElement
        e_type = type_struct.(aa(iElement));
        v      = val_struct.(aa(iElement));
        ...
    end

(source: https://github.com/slaclab/matpva/blob/main/mpvaGet.m — the
same lines PR slaclab/matpva#3 proposes to change, which is the "field
labels is missing" failure point when a PV lacks the labels field.)

This is exactly: get(pv) -> Value, then Value.todict()["labels"], then
per-column access into value's type and data. That's what this script
does with plain p4p, no MATLAB involved.

Usage:
    1. In one terminal:
         python3 scripts/matpva_labels_test/run_orbit_pv_server.py
    2. In another (same venv, p4p installed):
         python3 scripts/matpva_labels_test/simulate_mpvaGet_nttable.py
"""

import sys

from p4p.client.thread import Context

PV_NAMES = ["ORBITCC:rdBpm", "ORBITCC:rdModel"]


def simulate_mpvaGet_nttable(pv_name: str, value) -> None:
    """Reproduce mpvaGet.m's NTTable branch against an already-fetched Value."""
    nt_id = value.getID()
    if "NTTable" not in nt_id:
        raise AssertionError(f"{pv_name}: not an NTTable ({nt_id!r})")

    # a = struct(todict(PV)).labels;
    d = value.todict()
    try:
        labels = d["labels"]
    except KeyError:
        raise AssertionError(
            f"{pv_name}: 'field labels is missing' — this is the exact "
            "failure the colleague reported. The fix in orbit_pva.py is "
            "not in effect for this PV."
        )

    print(f"  labels = {list(labels)}")

    # type_struct / val_struct: per-column type + data, keyed by label
    value_struct = d["value"]
    for label in labels:
        if label not in value_struct:
            raise AssertionError(
                f"{pv_name}: label {label!r} has no matching column in 'value' "
                f"(columns present: {list(value_struct.keys())})"
            )
        col = value_struct[label]
        print(f"    value.{label} ({type(col).__name__}) = {list(col)}")

    print(f"  PASS: {pv_name} — labels present and every label has a matching column\n")


def main() -> int:
    ctxt = Context("pva")
    all_ok = True
    for pv_name in PV_NAMES:
        print(f"--- {pv_name} ---")
        try:
            value = ctxt.get(pv_name, timeout=5.0)
        except TimeoutError:
            print(
                f"  FAIL: timed out getting {pv_name!r} — is "
                "run_orbit_pv_server.py running?\n"
            )
            all_ok = False
            continue

        try:
            simulate_mpvaGet_nttable(pv_name, value)
        except AssertionError as exc:
            print(f"  FAIL: {exc}\n")
            all_ok = False

    ctxt.close()

    print("============================")
    print("ALL PASSED" if all_ok else "SOME CHECKS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
