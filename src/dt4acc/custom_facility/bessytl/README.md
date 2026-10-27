# BESSY II transfer line twin

The transfer line brings the beam from the booster (extraction septum
`SEK1S12B`) to the storage ring (injection septa `SEK1D1R`, `SEK2D1R`, kickers
`KIK3D1R`, `KIK4D1R`). This directory holds its twin, and describes how it
relates to the storage ring twin.

## 1. The transfer line alone

A ring has a periodic solution: its optics and closed orbit follow from the
lattice alone. A transfer line has none. Its optics and the beam position at
its monitors follow from the beam *entering* it. dt4acc-lib's line mode does
this: give `PyATAcceleratorSimulator` the entering beam as `twiss_in` and

* optics are propagated from the entering beam (`at.get_optics(twiss_in=...)`),
* monitors read the trajectory of the beam centroid,
* tune and chromaticity are not defined (NaN, no tune PVs),
* the last point of the optics is the exit of the line (`KIK4D1R:exit`).

### Inputs

| file | what |
|---|---|
| lat2db `lat2db.tools.pyat.bessy2_TL_reflat` | lattice: 97 elements, 25.3 m; 9 dipoles, 11 quadrupoles, 15 steerers, 17 monitors |
| `custom_epics/data/transfer_line/accelerator_setup.json` | magnets, their supply (`pc`) and calibration (`magnetic_strength`): quadrupoles T/m per A, steerers rad per A |
| `resources/input/operating_currents.yaml` | supply currents the twin starts with |
| `resources/input/twiss_in.yaml` | beam entering the line (or `DT4ACC_BESSYTL_TWISS_IN=<file>`) |

Energy 1.7185 GeV (full energy injection). The calibrations agree with it:
the steerer field integral per current of the magnet table (0.00375 T m/A)
over the kick per current of the setup (0.000662 rad/A) gives B rho = 5.67 T m.
lat2db's script sets 0.629 GeV; the twin overrides it.

Conversions, one supply per magnet:

* quadrupole: `K = g * I / (B rho)`, `g` = `magnetic_strength` [T/m/A]
* steerer: `kick = k * I`, `k` = `magnetic_strength` [rad/A] at 1.7185 GeV
  (stored as field integral `k * B rho` [T m/A], so the kick scales with energy)

### Not yet known (placeholders)

* **Entering beam**: `twiss_in.yaml` holds the entrance optics that keep the
  largest beta along the line smallest (61 m) with the operating currents. It
  is a fit, not booster data. Replace it with the booster extraction optics.
* **Operating currents**: from the magnet table of 2020. With the setup's
  polarities and the opposite ones the line reaches a similar largest beta
  (61 m vs 64 m), so these currents alone do not confirm the polarity
  convention.
* Steerers H7, V7, V8: the 2020 table gives 0.005 T m/A, the setup the same
  kick per current as the other steerers.
* The second injection septum is `SEK2D1R`; lat2db's lattice calls it `SEK2D2R` (a typo), the twin renames it when loading.

### Run

```bash
python src/dt4acc/custom_facility/bessytl/run_bessytl_twin.py
```

All PVs, with what a write does and the protocol: [pv_list.md](pv_list.md)
(`scripts/bessyii/dump_twin_pvs.sh` + `scripts/bessytl/make_pv_list.py` from a running twin).
In short, prefixed with `DT4ACC_PREFIX` (default: the user name):

| PV | what |
|---|---|
| `<supply>:set`, `<supply>:rdbk` | supply current [A]: `Q1PT` ... `Q12PT`, `H1PT` ... `H7PT`, `V1PT` ... `V8PT` |
| `<monitor>:x`, `<monitor>:y` | trajectory at the monitor [mm]: `FOMZ*` (FOMs, screens), `BPMZ*` (BPMs), `SLZ*` (striplines) |
| `beam:orbit:{x,y,names,uids}` | trajectory along the line, at every element and the exit |
| `beam:twiss:{x,y}:{beta,alpha,nu}`, `beam:twiss:{names,uids}` | optics along the line |
| `survey:s` | position along the line [m] |
| PVA `ORBITCC:rdBpm`, `ORBITCC:rdModel` | BPMZ* only (nm), as the ring twin |

### Check

```bash
pytest tests/bessytl                        # supplies -> magnets -> trajectory, no EPICS
DT4ACC_PREFIX=<prefix> python scripts/bessytl/check_twin.py   # against a running twin
```

The check sets steerer and quadrupole supplies over EPICS and compares every
monitor and the optics with plain pyAT on the same lattice, currents and
entering beam.

`<magnet>:Cm:set` / `:Cm:rdbk` read back in lattice units: K [1/m^2] for
quadrupoles, kick [rad] for steerers.

Known: steerer magnets also get `:x:set` / `:y:set` PVs (shared PV setup),
which pyAT correctors cannot act on.

## 2. Storage ring and transfer line as two twins

Both twins run side by side, each in its own process, with the same or
different `DT4ACC_PREFIX`. Their PV names do not collide: the transfer line
supplies end in `PT` (`Q1PT`), the ring's in `R` (`Q1PDR`). Each twin computes
its own machine: the ring its closed orbit and tunes, the line its trajectory
for the beam that enters it. Nothing passes between them.

## 3. Combining them

Start-to-end frameworks chain sections, each a model of its own, and hand the
beam from one to the next (e.g. LUME's `StagedModel`: the particles leaving one
stage are the initial particles of the next; a variable belongs to one stage
only; the handoff element belongs to the downstream stage). For the transfer
line and the ring this means:

* the beam at the exit of the line, transformed to ring coordinates at the
  injection septum (offset and angle of the line against the ring axis),
* is the start of the ring's first turns (dt4acc's turn by turn tracking),
* the septa and kickers are elements of one model only: the kickers act on
  the stored beam, so they belong to the ring.

This is the injection twin: [../bessyii_injection](../bessyii_injection/README.md).
Still needed: the injection geometry and the entering beam above.
