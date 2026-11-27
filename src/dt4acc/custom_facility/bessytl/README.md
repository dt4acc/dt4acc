# BESSY II transfer line twin

To start, use and test the BESSY II twins: [user guide](../bessyii/README.md).

The transfer line brings the beam from the booster (extraction septum
`SEK1S12B`) to the storage ring (injection septa `SEK1D1R`, `SEK2D1R`, kickers
`KIK3D1R`, `KIK4D1R`). This directory holds its twin, and describes how it
relates to the storage ring twin.

It is not the injection line: at BESSY II that is the line from the LINAC to
the booster, which dt4acc does not model. "Injection" in the injection twin
(`../bessyii_injection`) is the injection into the storage ring, at the end
of this line.

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
| lat2db `lat2db.tools.pyat.bessy2_TL_reflat` | lattice: 97 elements, 25.3 m; 9 dipoles (bends B1M1T, B1M2T, B2MT; booster extraction and ring injection septa; 2 ring kickers), 11 quadrupoles, 15 steerers, 17 monitors |
| `custom_epics/data/transfer_line/accelerator_setup.json` | magnets, their supply (`pc`) and calibration (`magnetic_strength`): quadrupoles T/m per A, steerers rad per A, bends T per A (transfer function `t_f`), the current giving the design angle (`reference_current`), design angle (`bending_angle`) and `length` |
| `resources/input/operating_currents.yaml` | supply currents the twin starts with |
| `resources/input/twiss_in.yaml` | beam entering the line (or `DT4ACC_BESSYTL_TWISS_IN=<file>`) |

Energy 1.7185 GeV (full energy injection). The calibrations agree with it:
the steerer field integral per current of the magnet table (0.00375 T m/A)
over the kick per current of the setup (0.000662 rad/A) gives B rho = 5.67 T m.
lat2db's script sets 0.629 GeV; the twin overrides it.

Conversions, one supply per magnet (B1PT: both B1M1T and B1M2T):

* quadrupole: `K = g * I / (B rho)`, `g` = `magnetic_strength` [T/m/A]
* steerer: `kick = k * I`, `k` = `magnetic_strength` [rad/A] at 1.7185 GeV
  (stored as field integral `k * B rho` [T m/A], so the kick scales with energy)
* bend: the lattice keeps the design angle (`BendingAngle`, the geometry); the
  current sets the field error `PolynomB[0] = t_f * (I - I_ref) / (B rho)`,
  `t_f` = `magnetic_strength` [T/A]. `I_ref` is the current giving the design
  angle: `reference_current` at 1.7185 GeV, scaled with B rho at another
  energy, as the design field is. More current, more field: the beam is bent
  more. Linear: no saturation; the small change of edge and body focusing is
  left out. `<magnet>:Cm` is the bending angle, `design angle + length *
  PolynomB[0]`.

| supply | magnets | design angle | length | `I_ref` (operating current) | `t_f` [T/A] | limits (control system) |
|---|---|---|---|---|---|---|
| B1PT | B1M1T, B1M2T | 22 deg (0.384 rad) each | 1.778 m | 232.75 A | 5.3187e-3 | 0 ... 365 A |
| B2PT | B2MT | 0.1352 rad | 1.02 m | 1.486 A | 0.5113 | 0.1 ... 2.0 A |

Wiring, operating currents and limits from BESSY II operations (2026-11-11);
`t_f` is estimated from the design field at the operating current,
`t_f = (B rho) * angle / (length * I_ref)`, until a measured calibration is
known. The twin does not enforce the limits. With the
twin's optics the line is sensitive to the bends: B1PT +0.1 % (0.23 A) moves
the beam by -7.2 mm at BPMZ5T and -21.5 mm at FOMZ7T.

### Not yet known (placeholders)

* **Entering beam**: `twiss_in.yaml` holds the entrance optics that keep the
  largest beta along the line smallest (61 m) with the operating currents. It
  is a fit, not booster data. Replace it with the booster extraction optics.
* **Bend calibration**: `t_f` estimated from the design angles at the
  operating currents (above); a measured field per current (and saturation)
  replaces it.
* **Operating currents**: quadrupoles from the magnet table (`bact2_bessyii`,
  committed 2020, origin of its numbers not documented). With the setup's
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
(`scripts/bessyii/dump_twin_pvs.sh` + `scripts/bessytl/make_pv_list.py` from a running twin;
`tests/bessytl/test_bessytl_pvs.py` checks that the twin serves exactly these).
In short, prefixed with `DT4ACC_PREFIX` (default: the user name). Devices keep their
machine names; the line's model is under `TL:`. These are the same names as in the
injection twin, where the ring serves `beam:*` and `ORBITCC:*` without `TL:`.

| PV | what |
|---|---|
| `<supply>:set`, `<supply>:rdbk` | supply current [A]: `Q1PT` ... `Q12PT`, `H1PT` ... `H7PT`, `V1PT` ... `V8PT` |
| `<bpm>:signal:sa:X`, `<bpm>:signal:sa:Y` | trajectory at the BPMs `BPMZ*` and striplines `SLZ*` [mm] |
| `<screen>:image`, `<screen>:image:{width,height,pixel}` | screens `FOMZ*`: image of the beam spot (see below) |
| `<screen>:x`, `<screen>:y`, `<screen>:sigma:x`, `<screen>:sigma:y` | beam centre and size at the screen [mm] |
| `TL:beam:orbit:{x,y,names,uids}` | trajectory along the line, at every element and the exit |
| `TL:beam:twiss:{x,y}:{beta,alpha,nu}`, `TL:beam:twiss:{names,uids}` | optics along the line |
| `TL:beam:emittance:{x,y}` | emittance of the beam [m rad], writable: the screens' beam size (placeholder) |
| `TL:survey:s` | position along the line [m] |
| PVA `TL:ORBITCC:rdBpm`, `TL:ORBITCC:rdModel` | `rdBpm`: BPMZ* and striplines SLZ*, in lattice order (BPMZ1T, SLZ1T, SLZ2T, BPMZ2T ... BPMZ5T, SLZ3T), nm; as the ring twin's `ORBITCC:*` |
| `noise:bpm:sa:enable`, `noise:bpm:sa:sigma` (no `TL:`) | noise on the BPMs' and striplines' readings (`signal:sa:X` / `Y`, `TL:ORBITCC:rdBpm`): on / off (default off), size [mm]; the model PVs stay exact |

### Screens

A fluorescent screen (`FOMZ*`) is no BPM: the beam hits a fluorescent plate
(and, at the machine, stops there) and a camera records the light, an image of
the beam spot. The twin computes it (`screens.py`) from

* the beam centre: the trajectory at the screen (`<screen>:x` / `y`),
* the beam size: `sigma = sqrt(emittance * beta)` (`<screen>:sigma:x` / `y`),
  the emittance (`TL:beam:emittance:x` / `y`) and beta at the screen. The
  beam's phase space ellipse (from the Twiss parameters) projected on the
  screen: alpha tilts the ellipse in (x, x'), which the screen does not see.

`<screen>:image`: a Gaussian spot, `image:height` rows of `image:width` pixels of
`image:pixel` mm (placeholder: 100 x 100 of 0.2 mm), centred on the line's axis, row 0
at the top (+y). A pixel holds the fraction of the beam that hits it: the image sums to
1 when the whole beam is on the screen. No trajectory (the calculation failed): a dark
image.

Not yet: the energy spread (dispersion), the screens stopping the beam (the
twin's screens are transparent), the cameras' real geometry and the booster's
emittance (placeholder 100 nm rad / 10 nm rad, `twin_setup.EMITTANCE`).

### Check

```bash
pytest tests/bessytl                        # supplies -> magnets -> trajectory, PVs, screens; no EPICS
DT4ACC_PREFIX=<prefix> python scripts/bessytl/check_twin.py   # against a running twin
```

The check sets steerer and quadrupole supplies over EPICS and compares every
monitor and the optics with plain pyAT on the same lattice, currents and
entering beam, and the screens' beam size and image centre with pyAT's beta
and trajectory.

`<magnet>:Cm:set` / `:Cm:rdbk` read back in lattice units: K [1/m^2] for
quadrupoles, kick [rad] for steerers, bending angle [rad] for bends.

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
