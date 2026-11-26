# BESSY II digital twin: user guide

Start, use and test the BESSY II twin: which PV to move, what to plot, turn by turn
data, lattices, injection. Numbers in "you should see" were read from running twins
(dt4acc `dev/main` `724edd7`, pyAT 0.8 / 0.9).

1. [Which twin](#1-which-twin)
2. [Start it](#2-start-it)
3. [First five minutes: move a PV, see the result](#3-first-five-minutes-move-a-pv-see-the-result)
4. [Plot](#4-plot)
5. [Turn by turn data](#5-turn-by-turn-data)
6. [Lattices](#6-lattices)
7. [Injection: from the transfer line into the ring](#7-injection-from-the-transfer-line-into-the-ring)
8. [Test the twin thoroughly](#8-test-the-twin-thoroughly)
9. [If something goes wrong, known limits](#9-if-something-goes-wrong-known-limits)
10. [Where to read more](#10-where-to-read-more)

## 1. Which twin

| twin | command | what it has | lattice at run time | turn by turn |
|---|---|---|---|---|
| ring | `dt4acc_bessyii` | storage ring alone | yes | `TBT:*`, a kicked beam |
| transfer line | `dt4acc_bessytl` | booster -> ring line alone | no | - |
| injection | `dt4acc_bessyii_injection` | ring + line + hand over | no | `INJ:*`, the injected beam |

Start with the **ring** twin, use the **injection** twin to inject. "Injection" is into
the storage ring; the LINAC -> booster injection line is not modelled.

## 2. Start it

### Prefix and network (optional)

PVs start with `DT4ACC_PREFIX` (default: the user name). To keep the twin on your own
machine, on a shared or control room network in particular, put this into a file
`twin-env.sh` and run `source twin-env.sh` in **every** terminal that starts or talks to
a twin:

```bash
export DT4ACC_PREFIX=BT
export EPICS_CAS_INTF_ADDR_LIST=127.0.0.1  EPICS_CA_ADDR_LIST=127.0.0.1  EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_PVAS_INTF_ADDR_LIST=127.0.0.1 EPICS_PVA_ADDR_LIST=127.0.0.1 EPICS_PVA_AUTO_ADDR_LIST=NO
```

`caget`, `caput`, `pvget` come from EPICS base. Examples below use the prefix `BT`;
without `DT4ACC_PREFIX`, write your user name instead.

### A. From Python

Python 3.10 or later:

```bash
python3 -m venv venv && source venv/bin/activate
pip install "dt4acc-lib @ git+https://github.com/dt4acc/dt4acc-lib.git" \
            "dt4acc[epics,bessyii,test] @ git+https://github.com/dt4acc/dt4acc.git" matplotlib
dt4acc_bessyii                 # or dt4acc_bessytl, dt4acc_bessyii_injection
```

(dt4acc needs a dt4acc-lib newer than the one on PyPI: install both from git.)
For the scripts and tests below, also clone the repository. From a clone, the start
scripts do the same:

```bash
git clone https://github.com/dt4acc/dt4acc.git && cd dt4acc
python src/dt4acc/custom_facility/bessyii/run_bessyii_twin.py
python src/dt4acc/custom_facility/bessytl/run_bessytl_twin.py
python src/dt4acc/custom_facility/bessyii_injection/run_bessyii_injection_twin.py
```

### B. With the container (Apptainer)

One image, all three twins, chosen with `TWIN`:

```bash
apptainer pull bessyii-injection-twin.sif \
  oras://registry.hzdr.de/hzb/digital-twins/accelerator/containers/pyat-softioc-digital-twin:bessyii-injection-latest

TWIN=bessyii apptainer run bessyii-injection-twin.sif     # ring alone
TWIN=bessytl apptainer run bessyii-injection-twin.sif     # transfer line alone
apptainer run bessyii-injection-twin.sif                  # injection twin (default)
```

`bessyii-injection-latest` is the newest published image; pull again (`apptainer pull -F`)
to update. It is version 1.1.5 as of 2026-11-25: dt4acc `67dc55d`, dt4acc-lib `aaa9363`.

The scripts of sections 4, 7 and 8 are in the image, e.g.
`apptainer exec bessyii-injection-twin.sif python /twin/scripts/bessyii_injection/demo.py`.
For your own lattices (section 6), `DT4ACC_LATTICE_DIR` has to be a directory the
container sees: your home usually is, otherwise add `--bind <directory>`.

The image has no EPICS command line tools: use your own. Build and publishing:
[container repository](https://codebase.helmholtz.cloud/hzb/digital-twins/accelerator/containers/pyat-softioc-digital-twin).

### Is it up? Stop it

```bash
caget BT:Q1PDR:set             # 218.458
```

Takes about 10 s. The twin's terminal is a Python shell: `dbl()` lists the PVs,
`exit()` or Ctrl-D stops the twin. Without a terminal, keep its input open
(`tail -f /dev/null | dt4acc_bessyii`), otherwise it ends at once.

## 3. First five minutes: move a PV, see the result

Ring twin. Write to **supplies** (`<supply>:set`, A), as at the machine. The PVs to
look at follow by themselves, in a few seconds.

| move | start value | look at | you should see |
|---|---|---|---|
| `caput BT:HS4P1D1R:set 0.1` (horizontal steerer) | 0 | `BT:BPMZ1D1R:signal:sa:X` [mm] | 0.017 -> -1.368 |
| `caput BT:VS2P1D1R:set 1` (vertical steerer) | 0 | `BT:BPMZ1D1R:signal:sa:Y` [mm] | 0 -> -1.98 |
| `caput BT:Q1PDR:set 219` (quadrupole) | 218.458 | `BT:TUNEZR:flq:rdH`, `rdV` | 17.8481, 6.7268 -> 17.8748, 6.7117 |
| `caput BT:MCLKHX251C:freq 499637.63` (RF [kHz], +1 kHz) | 499636.630203 | `BT:BPMZ1D1R:signal:sa:X` [mm] | 0.017 -> -1.293 (dispersion orbit) |

Set each back to its start value before the next. Show enough digits with
`caget -f6 BT:MCLKHX251C:freq`.

What else to read:

| PV | what |
|---|---|
| `<bpm>:signal:sa:X` / `Y` | closed orbit at one of the 123 BPMs [mm] |
| `beam:orbit:x` / `y` | closed orbit at every element [m] |
| `beam:twiss:x:beta`, `alpha`, `nu` (and `y`) | optics at every element |
| `survey:s`, `survey:names` | where the elements are [m] |
| `TUNEZR:flq:rdH` / `rdV` | tunes, with integer part |
| `TUNEZR:rdH` / `rdV` | tune frequency (the unit says kHz, the value is in MHz: 1.059) |
| `ORBITCC:rdBpm` | all BPMs as one structure, `pvget` only |

Magnets (`<magnet>:Cm:set`, `x:set`, `y:set`) exist only in the twin, for debugging.
All PVs, and which exist on the machine: [pv_list.md](pv_list.md).

## 4. Plot

Run the scripts in `scripts/bessyii_injection` (from a clone), with the **injection**
twin: it has the ring too.

```bash
dt4acc_bessyii_injection                         # terminal 1: the twin
python scripts/bessyii_injection/live_plot.py    # terminal 2: the plot
python scripts/bessyii_injection/demo.py         # terminal 3: moves PVs step by step
```

`demo.py` says at each step what it changes and what to expect, fires a shot, prints the
result and puts everything back at the end (Enter between steps, `--no-wait` without).
`live_plot.py` shows the trajectory in the transfer line, the injected beam at the ring
BPMs turn after turn (x and y) with the ring's closed orbit, and the hand over.

To plot your own change, move a PV of section 3 or 7, then fire a shot: the plot
redraws at shots only.

```bash
caput BT:HS4P1D1R:set 0.1
caput BT:INJ:trigger 1
```

Both scripts use `DT4ACC_PREFIX`. They do not work with the ring twin alone.

## 5. Turn by turn data

### Ring twin: a kicked beam

A particle starts at the first lattice element (`MRING_START`), at the closed orbit plus
an offset, and is read at every BPM. Nothing to trigger: a changed setting or a new
closed orbit recomputes it.

```bash
caput BT:TBT:n_turns 1024           # 1 ... 65536, default 128
caput BT:TBT:offset:x 0.002         # start offset [m], default 1 mm in x and y
caget BT:TBT:count                  # goes up when new data are there
caget -# 5 BT:BPMZ1D1R:signal:tbt:X # first 5 turns [mm]
```

| PV | what |
|---|---|
| `TBT:n_turns` | number of turns |
| `TBT:offset:{x,px,y,py,delta,ct}` | start offset from the closed orbit [m, rad, 1] |
| `TBT:start:*` | the start really tracked |
| `<bpm>:signal:tbt:X` / `Y` | one value per turn [mm], NaN once lost |
| `<bpm>:signal:tbt:survived` | particles left per turn (1 or 0: one particle) |

1024 turns take about 0.2 s. With an offset of 2 mm instead of 1 mm, the first three
turns at `BPMZ1D1R` go from -0.763, 0.195, 0.848 to -1.433, 0.402, 1.745 mm.

### End the beam at an element

Write an element's name to `TBT:stop_at` and the beam ends there: the BPMs up to that
element still see it in turn 1, the BPMs after it and all later turns show NaN. Empty: no
stop. A name the lattice does not have is refused (the PV keeps its old value).

```bash
caput BT:TBT:stop_at Q3M1D1R        # the beam ends at Q3M1D1R
caget -# 3 BT:BPMZ1D1R:signal:tbt:X # a BPM before it: turn 1 only, then NaN
caput BT:TBT:stop_at ""             # no stop again
```

One element at a time. In the injection twin the same is `INJ:stop_at`, used at the next
shot.

### Injection twin

There the data are the injected beam's: `INJ:n_turns` (1 ... 256, default 2), updated
**only at a shot** (section 7). `TBT:*` does not exist there.

## 6. Lattices

### Where they are

| what | where |
|---|---|
| ring, start lattice | `resources/storage_ring/input/bessy2_storage_ring.json` in this directory (name fixed by `LATTICE_FILE` in `provide_lattice.py`) |
| ring with both wavelength shifters | `resources/storage_ring/input/bessy2_storage_ring_wls.json` |
| transfer line | not a file here: lat2db's `bessy2_TL`, adapted in `../bessytl/twin_setup.py`; supply currents in `../bessytl/resources/input/` |

Where they come from: [resources/storage_ring/input/README.md](resources/storage_ring/input/README.md).

### Change the ring lattice while the twin runs (ring twin only)

```bash
caput -S BT:simulator_ring:lattice bessy2_storage_ring_wls.json   # file name in the lattice directory
caget -S BT:simulator_ring:lattice:message                        # loaded ...: 1255 elements
caput -S BT:simulator_ring:lattice ""                             # back to the start lattice
```

Always read `message`: it says `loaded ...` or `refused: ...` (then the old lattice
stays). With the wavelength shifters, `Q3PD1R:set` goes from 183.087 to 182.810 A, the
tunes stay (re-matched).

**Your settings are not kept.** A load sets every supply, magnet and RF PV to the new
lattice's values (a steerer at 0.1 A goes back to 0). Note your settings before, write
them again after.

### Your own directory, separate from the code

Already possible: set `DT4ACC_LATTICE_DIR` **before** starting the ring twin.

```bash
mkdir -p ~/bessyii_lattices
cp src/dt4acc/custom_facility/bessyii/resources/storage_ring/input/bessy2_storage_ring_wls.json ~/bessyii_lattices/
export DT4ACC_LATTICE_DIR=~/bessyii_lattices
dt4acc_bessyii
```

It replaces the built in directory: copy there what you want to load. New files can be
added while the twin runs. Only plain file names are accepted, no paths.

Make a lattice of your own, e.g. a quadrupole 0.1 mm off in x:

```python
import os
import at
from importlib import resources

src = resources.files("dt4acc") / "custom_facility/bessyii/resources/storage_ring/input/bessy2_storage_ring.json"
ring = at.load_lattice(str(src))
quad = next(e for e in ring if e.FamName == "Q3M1D1R")
at.shift_elem(quad, 1e-4, 0.0)             # x, y [m]
ring.save(os.path.expanduser("~/bessyii_lattices/q3_shifted.json"))
```

`caput -S BT:simulator_ring:lattice q3_shifted.json`: `BPMZ1D1R:signal:sa:X` goes to
-0.412 mm.

### What is accepted: only wavelength shifters, or more?

Only the wavelength shifters have a lattice in the repository and automated tests. The
twin itself accepts **any** lattice that has

* the same devices: every magnet, cavity and BPM of the twin, same names, same order
  (other elements may be added or removed),
* the energy 1.7185 GeV,
* fewer than 1500 elements.

| lattice | result |
|---|---|
| wavelength shifters | loaded; tested in `tests/bessyii/test_runtime_lattice.py` |
| gradient errors (0.1 % rms on all quadrupoles) | loaded, tunes 17.8428, 6.7246; tried by hand, no automated test |
| a misaligned quadrupole | loaded, orbit changes; tried by hand, no automated test |
| corrections (other strengths) | same check as gradient errors, not tried |
| undulators | not covered: no lattice yet (issue #86) |
| a magnet missing | `refused: 1 element(s) not in the new lattice: Q3M1D1R` |
| magnets in another order | `refused: element order differs ...` |
| another energy | `refused: ... the twin expects 1718500000.0` |
| 1500 elements or more | **not refused, breaks**: `Value too long for waveform` in the log, the message keeps its old text, model PVs are stale. Load `""` again |
| file formats | pyAT JSON (use this) and `.mat` load; `.m` as saved by pyAT was refused |

A lattice's own errors become its starting point: supply PVs then show the currents that
give the lattice's strengths. The check is on names and order, not on physics: a lattice
that has no stable beam is loaded and gives NaN.

### Not possible today, and how it could move out

| wish | today | what is needed |
|---|---|---|
| start the ring twin with another lattice | no: `LATTICE_FILE` is fixed; BESSY II does not read `DT4ACC_LATTICE_FILE` | `provide_lattice()` reading that variable, the bundled file as default |
| lattices kept outside the repository | run time loads only (`DT4ACC_LATTICE_DIR`) | the point above, plus a shared directory or lattice repository as the default |
| another lattice in the injection twin | no, no `simulator_ring:lattice` there | serve `initialise_lattice_pvs` there; the check must also require `MSEPEXIT` |
| another transfer line lattice | no, it is lat2db's | a lattice file for the line |
| a lattice sent as data over a PV | no, file name only | not planned |

Until the first is done, the start lattice is changed by exporting it again
(`scripts/bessyii/export_lattice.py`) over the bundled file, then running the tests.

## 7. Injection: from the transfer line into the ring

Use the injection twin: `dt4acc_bessyii_injection`.

### Where the beam goes

```text
booster -> SEK1S12B  ... transfer line, 23.4 m ...  SEK1D1R, SEK2D1R | MSEPEXIT -> ring (240 m)
           (line start)                              septa    line end | ring start
                                                         hand over point
```

| point | where |
|---|---|
| start of the line | booster extraction septum `SEK1S12B`; the entering beam is `../bessytl/resources/input/twiss_in.yaml` |
| **hand over point**, line side | exit of the septum `SEK2D1R`, the last element of the line (s = 23.374 m) |
| **injection point**, ring side | `MSEPEXIT` (s = 0.56 m in the ring) |
| after it, ring elements | `FOMZ2D1R`, `KIK3D1R`, `KIK4D1R`, first BPM `BPMZ5D1R` (s = 2.756 m) |

The injection and hand over points are one physical place, seen from both models. What
is handed over is one particle, the beam's centre: **injected = line exit + geometry**,
where the geometry is the line's axis against the ring's axis at that point. Turn 1
starts at `MSEPEXIT` (the ring twin's `TBT` data start at `MRING_START`).

### When and how to inject

Nothing is injected at start. Inject whenever you want to see the beam: **one write to
`INJ:trigger` is one shot**. The line's BPMs and screens and the ring's `tbt` data change
only at a shot and keep it until the next. The models (`TL:beam:*`, the ring's closed
orbit) follow every change at once.

```bash
caput BT:H5PT:set 0.4               # 1. prepare: e.g. a line steerer [A]
caput BT:INJ:n_turns 20             #    turns to track, 1 ... 256
caget BT:INJ:count                  # 2. note the count
caput BT:INJ:trigger 1              # 3. shot
caget BT:INJ:count                  # 4. one more: the data are there
caget BT:INJ:line_exit:x BT:INJ:injected:x BT:INJ:injected:xp
caget -# 20 BT:INJ:survived BT:BPMZ1D1R:signal:tbt:X
```

You should see -1.173 mm, -1.173 mm, +0.664 mrad (PVs in m and rad) and 8.476, 10.920,
5.798 ... mm at `BPMZ1D1R`.

Set up everything first, then trigger. Wait for `INJ:count` before the next trigger:
triggers that come while a shot is computed are merged into one. Repeated shots, e.g.
10 at 1 Hz, each waited for:

```bash
dt4acc_bessyii_injection_mockup --shots 10 --rate 1
```

| PV | what |
|---|---|
| `INJ:trigger` | 1: fire a shot (goes back to 0) |
| `INJ:count` | shots done |
| `INJ:n_turns` | turns **per shot**, not a number of shots; more than 256 becomes 256 |
| `INJ:geometry:{x,xp,y,yp,delta,ct}` | line against ring axis [m, rad, 1, m], 0 by default; e.g. `INJ:geometry:x -0.002` |
| `INJ:line_exit:*`, `INJ:injected:*` | the beam before and after the hand over |
| `INJ:tbt:x` / `y` / `names` | all BPMs: turn 1, then turn 2, ... [m] |
| `<bpm>:signal:tbt:X` / `Y` | one BPM, turn after turn [mm] |
| `INJ:survived` | particles left after each turn (1 or 0) |
| `INJ:stop_at` | the ring element the injected beam ends at (section 5), empty: none |
| `BPMZ1T:signal:sa:X`, `FOMZ3T:x`, `FOMZ3T:image` | line BPM [mm], screen centre [mm] and image |

### Screens: out, observe or stop the beam

The line's fluorescent screens (`FOMZ1T` ... `FOMZ8T`) each have a mode, `<screen>:mode`:

| mode | the screen | the beam |
|---|---|---|
| `Observe` (default) | shows the beam: `x`, `y`, `sigma:x`, `sigma:y`, `image` | passes |
| `Out` | retracted: dark image, NaN | passes |
| `Stop` | shows the beam | ends there: the BPMs and screens after it show NaN, nothing reaches the ring |

```bash
caput BT:FOMZ3T:mode Stop           # the beam ends at FOMZ3T
caput BT:INJ:trigger 1              # shot: FOMZ3T shows the beam, BPMZ4T ... and the ring NaN
caput BT:FOMZ3T:mode Observe        # back to normal (acts at the next shot)
```

**A screen anywhere: the artificial screen.** `TL:screen:element` puts a screen at any
element of the line (empty: nowhere). It works as a real one, with `TL:screen:mode` (`Out`
at the start, `Observe`, `Stop`) and the same readings under `TL:screen:...`. A name the
line does not have is refused.

```bash
caput BT:TL:screen:element Q4MT     # a screen at Q4MT
caput BT:TL:screen:mode Observe
caput BT:INJ:trigger 1
caget BT:TL:screen:x BT:TL:screen:sigma:x   # beam centre and size there [mm]
```

In the injection twin the modes act at the next shot, as every setting. The transfer line
twin on its own (`dt4acc_bessytl`) shows a change at once, without a trigger.

### Watch it

With `live_plot.py` and `demo.py`, section 4. What `demo.py` gives:

| step | injected beam | ring BPMs, x rms per turn [mm] |
|---|---|---|
| nothing changed | 0 | 0.012, 0.012: on the closed orbit |
| `H5PT:set 0.4` | -1.173 mm, +0.664 mrad | 6.0, 5.6: betatron oscillation |
| + `INJ:geometry:x -0.002`, `xp 1e-4` | -3.173 mm, +0.764 mrad | 7.4, 6.6 |
| + `INJ:n_turns 5` | the same | 7.4, 6.6, 6.8, 7.0, 6.6 |
| + `Q1PDR:set` +1 % | the same | 7.8, 9.6, 13.4, then NaN: lost in turn 4 |

### What the injection does not model yet

Geometry and entering beam are placeholders, not measured. The kickers `KIK1D1R` ...
`KIK4D1R` do not fire, there is no injection bump. One particle, no bunch, no
apertures. A shot does not change the stored beam or its current. A screen that observes does not
scatter the beam (at the machine the beam grows a little behind it).

## 8. Test the twin thoroughly

1. Without EPICS, from a clone (91 tests, under a minute):

   ```bash
   python -m pytest tests/bessyii tests/bessytl tests/bessyii_injection
   ```

2. Against running twins, compared with plain pyAT (must end with `0 failure(s)`):

   ```bash
   python scripts/bessyii_injection/check_twin.py   # injection twin running
   python scripts/bessytl/check_twin.py             # transfer line twin running
   ```

   There is no such script for the ring alone: use the list below.

3. By hand, each with the values above:

   - [ ] ring twin up: `Q1PDR:set` 218.458, tunes 17.8481 and 6.7268
   - [ ] the four moves of section 3, each put back
   - [ ] `TBT:n_turns 1024`: `TBT:count` goes up, 1024 values
   - [ ] wavelength shifters loaded (1255 elements), back with `""` (1137)
   - [ ] a wrong file name is refused, the lattice stays
   - [ ] your own lattice from `DT4ACC_LATTICE_DIR`
   - [ ] beam loss: `Q1PDR:set 0` gives NaN, 218.458 brings the orbit back
   - [ ] injection twin: before a shot `INJ:count` is 0 and the line BPMs read 0
   - [ ] `demo.py` gives the table of section 7

## 9. If something goes wrong, known limits

| you see | reason, what to do |
|---|---|
| `Channel connect timed out` | other terminal without `twin-env.sh`, other prefix, twin not up yet, or a PV of another twin (section 1) |
| two twins on one machine, `caget` finds only one | Channel Access on 127.0.0.1 reaches one server per port. Start the second with `EPICS_CAS_SERVER_PORT=5066` and use `EPICS_CA_ADDR_LIST="127.0.0.1:5064 127.0.0.1:5066"`, or use `pvget` / `pvput` |
| the twin ends at once | its input is closed, see section 2 |
| NaN in tunes, orbit, BPMs | no stable beam; set the last change back |
| a lattice load gives the start lattice | `caput` without `-S` does not send the name; use `caput -S` / `caget -S` |
| line BPMs or `tbt` do not move (injection twin) | no shot: `INJ:trigger` |
| `caget -# N` shows 0 at the end | fewer turns than N |
| `simulator_ring:reinit` does not bring the twin back | known: it resets the lattice, but PVs keep their old values and the model is not published. In the ring twin load `""` instead; else write one supply |
| `beam:orbit:found` stays set after beam loss | known: look for NaN in the orbit |
| `MDIZ3T5G:current` is 0 | the beam current is not simulated yet (issue #33) |
| `CAV*:freq` does not follow `MCLKHX251C:freq` | known; it is updated at a lattice load only |

Supply limits are not enforced (issue #80), and there is no noise on the BPMs (#82).

## 10. Where to read more

* PVs: [ring](pv_list.md), [transfer line](../bessytl/pv_list.md), [injection](../bessyii_injection/pv_list.md)
* how it is built, and the physics: [injection twin](../bessyii_injection/README.md), [transfer line](../bessytl/README.md)
* ring lattice and its source: [input data](resources/storage_ring/input/README.md)
* V2.0 status: [docs/notes/v2_status.md](../../../../docs/notes/v2_status.md)
