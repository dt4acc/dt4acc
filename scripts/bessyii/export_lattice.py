"""Export the BESSY II storage ring lattice the twin loads, from bessy2reflat

Writes ``custom_facility/bessyii/resources/storage_ring/input/bessy2_storage_ring.json``
(pyAT's own JSON format, ``atjson``), or with ``--wavelength-shifters``
``bessy2_storage_ring_wls.json`` (both wavelength shifters inserted by
``add_wavelength_shifters()`` with its defaults: tunes and RF re-matched; a
lattice the twin loads at run time, #81), from the reference lattice of
`bessy2reflat <https://gitlab.helmholtz-berlin.de/acc-tools/reference-lattices/bessy2reflat>`_
(``bessy2_storage_ring()``). bessy2reflat and reflat-tools are needed only
here, not by the twin:

    pip install <reflat-tools checkout> <bessy2reflat checkout>
    python scripts/bessyii/export_lattice.py [--wavelength-shifters]

Then update the source given in ``resources/storage_ring/input/README.md``.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "src/dt4acc/custom_facility/bessyii/resources/storage_ring/input"
OUT = INPUT / "bessy2_storage_ring.json"
OUT_WLS = INPUT / "bessy2_storage_ring_wls.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wavelength-shifters", action="store_true",
                        help="insert both wavelength shifters (bessy2reflat defaults)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out = args.out or (OUT_WLS if args.wavelength_shifters else OUT)

    import at
    import bessy2reflat
    from bessy2reflat.storage_ring import add_wavelength_shifters, bessy2_storage_ring

    ring = bessy2_storage_ring()
    if args.wavelength_shifters:
        ring = add_wavelength_shifters(ring)
    ring.save(out)
    print(
        f"{out}: bessy2reflat {bessy2reflat.__version__}, pyAT {at.__version__},"
        f" {len(ring)} elements, {ring.circumference:.6f} m, {ring.energy / 1e9} GeV,"
        f" tunes {ring.get_tune()[:2]}"
    )


if __name__ == "__main__":
    main()
