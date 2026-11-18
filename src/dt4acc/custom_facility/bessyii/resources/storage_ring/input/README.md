# BESSY II storage ring: input data

## Lattice: `bessy2_storage_ring.json`

The lattice the twin loads (`provide_lattice.py`), in pyAT's own JSON format.
It is exported from the reference lattice in
[bessy2reflat](https://gitlab.helmholtz-berlin.de/acc-tools/reference-lattices/bessy2reflat)
(`bessy2_storage_ring()`) by `scripts/bessyii/export_lattice.py`:

| | |
| --- | --- |
| bessy2reflat | `main` at `23b4f68` (2026-11-12), version 0.6.1, with reflat-tools 0.4.2 |
| exported with | pyAT 0.9.0 (loads with pyAT 0.8.0) |
| lattice | 1137 elements, 240.008390 m, 1.7185 GeV, harmonic number 400 |
| tunes | 0.84807, 0.72678 |
| wavelength shifters | not inserted (bessy2reflat's default at that commit) |

To refresh it: export again with the script, then update this table.

### Changes against the previous lattice (lat2db JSON, 1093 elements)

Every magnet and cavity setting is identical; tunes, RF and closed orbit are
unchanged. The differences come from bessy2reflat:

* injection kickers `KIK1D1R` ... `KIK4D1R`: drifts → correctors
  (`KickAngle` 0), with the drifts around them adjusted to keep the length
* new correctors (`KickAngle` 0): warm steerers of the wavelength
  shifters `MHW7I1T1R`, `MHW7I2T1R`, `MHW7I1T7R`, `MHW7I2T7R`; diagnostic
  kickers `KDHKR`, `KDVKR`
* new markers and drifts: diagnostic striplines (`DIAG_STRIPLINE_*`), the
  diagnostic kicker, the wavelength shifters' start/end markers
* removed: the markers `MBAMWLS1`, `MBAMWLS2`

## Lattice with the wavelength shifters: `bessy2_storage_ring_wls.json`

Not loaded at start: the ring twin loads it at run time (#81),
`caput <prefix>:simulator_ring:lattice bessy2_storage_ring_wls.json`, and
goes back with an empty string (`pv_list.md`, *Lattice at run time*).
Exported by `scripts/bessyii/export_lattice.py --wavelength-shifters` from
the same bessy2reflat commit: `add_wavelength_shifters()` with its defaults,
both wavelength shifters, 20 slices per pole, tunes and RF re-matched.

| | start lattice | with the wavelength shifters |
| --- | --- | --- |
| elements | 1137 | 1255 (+124 pole slices and edges; 6 drifts and markers replaced) |
| tunes | 0.84807, 0.72678 | 0.84807, 0.72678 (re-matched) |
| RF (Hz) | 499 636 630.203 | 499 636 629.871 |
| changed | | K of the 64 Q3 quadrupoles, the 4 main cavities' frequency |

## Other files

`magnets.yaml`, `power_converters.yaml`: magnets and their power supplies.
