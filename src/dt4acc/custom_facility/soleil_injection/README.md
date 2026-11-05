# SOLEIL injection twin: TL2 and storage ring together

The TL2 twin (`../soleil_tl2`) and the storage ring twin (`../soleil`) on one Tango
database, with the beam handed from the line to the ring, as the BESSY II injection
twin (`../bessyii_injection`).

## How they are put together

* **Two models, two submachines.** Each twin keeps its devices, its liaison and its
  physics engine, and runs as it does on its own. TL2's simulator device is
  `simulator/tlsimulator/tlsimulator` (`DT4ACC_SIM_DEVICE`, set by this twin only: on
  their own, all twins keep `simulator/ringsimulator/ringsimulator`).
* **Stages.** The beam leaving TL2, plus the injection geometry (a difference state),
  is the beam entering the ring (`handover.py`).
* **Injection point.** TL2 ends at the middle of the injection straight, the ring
  lattice starts at its centre, `SD01ICENTER`. To be confirmed by SOLEIL, as the
  geometry there: a placeholder (no offset) until then, settable at run time.
* **Tracking.** On the ring's physics engine, as its turn by turn data: start = closed
  orbit + offset, with offset = injected - closed orbit (`tbt_offset`). So the ring's
  BPM devices serve the injected beam. Recomputed when TL2, the ring or the settings
  change. As in BESSY II, kickers and septa do not act on the beam yet (#77).

## Run

Three ways to run them, all need a Tango database, one per set of twins (SOLEIL's
`tango_db` image: `apptainer run oras://registry.synchrotron-soleil.fr/software_control_system_public/tango_db`;
it keeps `tango_database.db` in the folder it starts from, a file of an older image gives
`Incompatible SQLite schema`: start it from another folder).

SOLEIL's files are not in the repository, nor in the containers. Defaults:
`~/Documents/dt4acc_config_data` (ring: lattice `.m`, `accelerator_setup.json`) and its
`soleilii-tl` (TL2: `tl2_lattice_uuid.json`, `tl2_database.yaml`, `twiss_in.yaml`).
Elsewhere: the options of each script (`--help`).

TL2's device database is generated once, in the folder of its files:

```bash
cd ~/Documents/dt4acc_config_data/soleilii-tl
python -m dt4acc.custom_facility.soleil_tl2.yml2json_soleil_tl2
```

Registering is once per Tango database, then the twin starts in about a minute (ring:
over 130 servers); it is ready when the log says `All Tango processes ready`, once per
twin.

| twin | register | run |
|---|---|---|
| ring | `python -m dt4acc.custom_facility.soleil.register_devices --register-devices --tango-host H:P` | `python -m dt4acc.custom_facility.soleil.run_soleil_twin --tango-host H:P` |
| TL2 | `python -m dt4acc.custom_facility.soleil_tl2.register_devices --register-devices --tango-host H:P` | `python -m dt4acc.custom_facility.soleil_tl2.run_soleil_tl2_twin --tango-host H:P` |
| both, with the hand over | `python -m dt4acc.custom_facility.soleil_injection.register_devices --tango-host H:P` | `python -m dt4acc.custom_facility.soleil_injection.run_soleil_injection_twin --tango-host H:P` |

`export TANGO_HOST=H:P` first (the ring's registration reads it). In PyCharm: the same
files as scripts, the same parameters. If one process of the injection twin ends, all end.

The same in a container, one image per row (`pyat-tango-digital-twin`,
`recipies/soleil-*.sdef`): `apptainer exec IMAGE python -m ...` for the steps above,
`apptainer run IMAGE --tango-host H:P` for the twin.

## Devices

All of a kind: `tango.Database().get_device_exported_for_class("BPMDevice")`, or Jive; the full
lists are in the `accelerator_setup.json` of each twin (`name`: the magnet, `pc`: its supply).

| | TL2 | ring (examples) |
|---|---|---|
| BPMs | `LT2/DG-EPOS/BPM.01` ... `BPM.06` | `AN01-AR/DG-EPOS/BPM.02` |
| horizontal steerers | `LT2/EM-COR/COR.H.01` ... `COR.H.05` | `AN01-AR/EM-COR/SHF.01-CDLH.01` |
| vertical steerers | `LT2/EM-COR/COR.V.01` ... `COR.V.04` | `AN01-AR/EM-COR/SHF.01-CDLV.01` |
| quadrupoles | `LT2/EM-QP/QP.01` ... `QP.12` | `AN01-AR/EM-QP/QF01.01` |
| their supplies, `--view device` of TL2 alone | `LT2/AE-COR/COR.H.05`, `LT2/AE-QP/QP.12`, ... | |
| not controlled | bends `LT2/EM-DIP/DIP.01` ... `DIP.04`, kickers `BO-SDE/EM-EP/KEXT.01` ... `KEXT.04`, septa `LT2/EM-EP/SEP-EP.01`, `SEP-MI.01` | bends `AN01-AR/EM-DIP/DNC.01`, ... |

| device | attributes |
|---|---|
| `simulator/injection/injection`: the hand over | see below |
| `simulator/ringsimulator/ringsimulator`: ring | `orbit_x`, `orbit_y` [m], `beta_*`, `alpha_*`, `nu_*`, tunes `hor`, `vert`, chromaticity `xi_x`, `xi_y`, turn by turn `tbt_*` |
| `simulator/tlsimulator/tlsimulator`: TL2 | the same along the line: `orbit_*` is its trajectory; tunes and chromaticity NaN, no turn by turn: a line has none |
| magnets | `magnetic_strength`: quadrupoles K [1/m^2], steerers [rad in TL2] |
| BPMs | `XPosSA`, `ZPosSA`: position [mm]; ring also `XPosDD`, `ZPosDD`: turn after turn [mm], `DDBufferSize`: turns |
| supplies, `--view device` of the TL2 twin alone | `current_set`, `current_readback` |

`simulator/injection/injection`:

| attribute | what |
|---|---|
| `geometry` | (x, px, y, py, delta, ct) line against ring at the injection point [m, rad, 1, m], writable |
| `n_turns` | turns tracked in the ring, writable (default 2) |
| `line_exit` | centroid leaving TL2, line frame |
| `injected` | the same in the ring's frame: `line_exit` + `geometry` |
| `survived` | particles still there after each turn |
| `count` | hand overs computed so far |

## What moves what

Allow 1 to 2 s after a write (heartbeat 1 s). Jive: refresh, the arrays are not polled.

| write | what moves | what stays |
|---|---|---|
| TL2 steerer, e.g. `LT2/EM-COR/COR.H.05`, `magnetic_strength` | TL2's `orbit_*` and BPMs after it, `line_exit`, `injected`, the ring's `tbt_start`, `XPosDD` / `ZPosDD` | TL2's optics; BPMs before it; the ring's closed orbit (`orbit_*`, `XPosSA`) |
| TL2 quadrupole, e.g. `LT2/EM-QP/QP.12`, `magnetic_strength` | TL2's `beta_*`, `alpha_*`, `nu_*`; `line_exit` and what follows only if the beam is off centre in it | the ring |
| `geometry` | `injected`, `tbt_start`, `XPosDD` / `ZPosDD` | TL2 |
| `n_turns` | length of `XPosDD` / `ZPosDD`, `survived` | |
| ring steerer, e.g. `AN01-AR/EM-COR/SHF.01-CDLH.01` | ring's `orbit_*`, `XPosSA`; turn by turn data around the new closed orbit | TL2, `line_exit`, `injected` |
| ring quadrupole, e.g. `AN01-AR/EM-QP/QF01.01` | ring's optics, tunes; the betatron oscillation of `XPosDD` / `ZPosDD` | TL2, `line_exit`, `injected` |
| TL2 or ring bends, kickers, septa | nothing: not controlled, writes are refused (as the ring on its own) | |

A first look: `LT2/EM-COR/COR.H.05`, `magnetic_strength` = `1e-4`, then `injected` of
`simulator/injection/injection` and `XPosDD` of `AN01-AR/DG-EPOS/BPM.02`; `n_turns` = `128`
to see the oscillation. Vertical: `LT2/EM-COR/COR.V.04`, `ZPosDD`. Back: `0`.

## What to take care of

* **Placeholders.** Injection point and `geometry` (0) are not SOLEIL's yet: absolute
  numbers of the injected beam are not machine values.
* **`tbt_offset` of the ring simulator** belongs to the hand over here: it is overwritten
  within a second. To change the beam use `geometry`.
* **`n_turns`** up to 64 * 1024, but tracking runs on the ring's physics engine: writes to
  ring magnets wait for it, and may hit their 30 s timeout during very long runs. Keep it
  small while steering. `DDBufferSize` on a BPM is the same setting, for all BPMs.
* **Beam loss.** `survived` drops to 0 and `XPosDD` / `ZPosDD` read NaN; put the steerer
  back. If the ring's own optics fail (no closed orbit): `Reset` or `Reinit` on its
  simulator.
* **Units.** BPM attributes `XPos*` / `ZPos*` are mm, `orbit_*`, `line_exit`, `injected` m
  and rad, `x`, `y` of a BPM device m. Z is vertical (SOLEIL's names).
* **Ports.** One database per set of twins, `--tango-host`; the physics engines' ports
  (`--ring-port`, `--tl-port`) differ per run on one machine.
* **Twins alone on one database.** Ring and TL2 alone register the same simulator
  device: use two databases; this twin uses one and renames TL2's.
* **Stale devices.** Delete a twin's servers from the database (or use a new one) when
  changing between layouts.
* **Reading from a client.** `TANGO_HOST` selects the database. A client in plain Python:

```python
import tango
injection = tango.DeviceProxy("simulator/injection/injection")
injection.n_turns = 128
injection.geometry = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
print(injection.injected, injection.survived[-1])
tango.DeviceProxy("LT2/EM-COR/COR.H.05").magnetic_strength = 1e-4
bpm = tango.DeviceProxy("AN01-AR/DG-EPOS/BPM.02")
print(bpm.XPosDD)
```

## Check

```bash
pytest tests/tango_tests/test_soleil_injection.py
```
