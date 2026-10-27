# BESSY II injection twin: transfer line and storage ring together

The transfer line twin (`../bessytl`) and the storage ring twin (`../bessyii`)
in one IOC, with the beam handed from the line to the ring.

## How they are put together

* **Two models, two submachines.** As in MML (where a transfer line is a
  submachine of its own, next to the storage ring), each keeps its devices,
  its lookup tables and its simulation engine: the ring computes its closed
  orbit and tunes, the line its trajectory and optics from the entering beam.
* **Stages.** As in LUME's `StagedModel`: the beam leaving the first model is
  the beam entering the second. Each element belongs to one model only, and
  the element where the beam is handed over belongs to the downstream one:
  the line ends at the septum exit (after `SEK2D2R`); the screen `FOMZ2D1R`
  and the kickers `KIK3D1R`, `KIK4D1R` are the ring's.
* **Hand over** (`coupler.py`): the centroid leaving the line (line frame),
  plus the injection geometry (the line's axis against the ring's axis at the
  septum exit), is the injected beam at the ring's `MSEPEXIT`. It is tracked
  from there for `n_turns` and read at the ring's BPMs. The ring lattice
  starts with a drift up to `MSEPEXIT`: the beam is moved back through it to
  the start of the lattice, where tracking begins.
* The hand over is recomputed whenever the line or the ring is recalculated
  (any supply change) or its settings change.

## Run

```bash
python src/dt4acc/custom_facility/bessyii_injection/run_bessyii_injection_twin.py
```

PVs, prefixed with `DT4ACC_PREFIX` (`<P>`, default: the user name):

| PVs | what |
|---|---|
| `<P>:Q1PDR:set`, `<P>:beam:orbit:x`, `<P>:ORBITCC:rdBpm`, ... | the storage ring, as the ring twin |
| `<P>:TL:Q1PT:set`, `<P>:TL:FOMZ1T:x`, `<P>:TL:beam:orbit:x`, `<P>:TL:ORBITCC:rdBpm`, ... | the transfer line up to the septum exit, as the transfer line twin, one level down |
| `<P>:INJ:geometry:{x,xp,y,yp}` | line axis against ring axis at the septum exit [m, rad] (writable) |
| `<P>:INJ:n_turns` | turns tracked in the ring (1 ... 256, writable) |
| `<P>:INJ:line_exit:{x,xp,y,yp}` | centroid leaving the line, line frame |
| `<P>:INJ:injected:{x,xp,y,yp}` | the injected beam, ring frame, at `MSEPEXIT` |
| `<P>:INJ:tbt:x`, `<P>:INJ:tbt:y`, `<P>:INJ:tbt:names` | position at the ring BPMs: turn 1 at all BPMs, then turn 2, ... [m] |
| `<P>:<bpm>:tbt:x`, `<P>:<bpm>:tbt:y` | one ring BPM, turn after turn [m] |
| `<P>:INJ:survived` | particles still there after each turn |
| `<P>:INJ:count` | hand overs computed so far |

## Check

```bash
pytest tests/bessyii_injection                                     # no EPICS
DT4ACC_PREFIX=<P> python scripts/bessyii_injection/check_twin.py  # against a running twin
```

Both compare with plain pyAT: the line tracked up to the septum exit, the
ring tracked from `MSEPEXIT` (the ring lattice rotated to start there).

## Not yet known (placeholders)

* **Injection geometry**: 0 (the line's axis on the ring's axis). Needs the
  septum position and angle against the ring axis.
* **Entering beam of the line**: see `../bessytl/README.md`.
* **One particle**: the centroid. A bunch (emittance, energy spread of the
  booster beam) and apertures (so that particles can be lost) are next.
* **Kickers**: `KIK1D1R` ... `KIK4D1R` are drifts in the ring lattice: no
  injection bump; the injected beam oscillates around the closed orbit.
