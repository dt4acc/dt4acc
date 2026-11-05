# dt4acc — TANGO Digital Twin Server (SOLEIL II)

A TANGO-based digital twin of the SOLEIL II storage ring, built on top of pyAT
and the `dt4acc_lib` accelerator model library.

The transfer line TL2 alone (`src/dt4acc/custom_facility/soleil_tl2/README.md`) and TL2 with the
ring, the beam handed over (`src/dt4acc/custom_facility/soleil_injection/README.md`: how to run,
containers, what moves what, what to take care of) are set up the same way.

Turn by turn data: the BPM devices' `XPosDD`, `ZPosDD` [mm], `DDBufferSize` (turns, shared by all
BPMs) and the ring simulator's `tbt_*` (`dt4acc.custom_tango.ioc.turn_by_turn`).

---

## Architecture Overview

```
src/dt4acc/custom_facility/soleil/run_soleil_twin.py  ← SOLEIL launch script (facility config)
    │
    └── dt4acc.custom_tango.ioc.server_manager.main()
            │
            ├── MexecService  (mp.Process, daemon)
            │     Loads the AT lattice once from a .m file.
            │     Runs TranslatingCommandExecutionEngine (mexec).
            │     Exposes SyncMexecProxy via TCP socket (port 50200).
            │
            ├── TangoServerProcess × N  (one per domain/family)
            │     Each connects to MexecService.
            │     Runs tango.server.run([MultipoleDevice, ...])
            │
            └── calculation-heartbeat-thread
                  Calls RingSimulatorDevice.Recalculate() every second.
                  No lattice writes — zero noise.
```

### Device classes

| Class | JSON type | Attributes |
|---|---|---|
| `MultipoleDevice` | Quadrupole, Sextupole, Octupole | `magnetic_strength`, `magnetic_strength_readback` |
| `HorizontalSteererDevice` | Steerer (CDLH/CDRH) | `x_kick` |
| `VerticalSteererDevice` | Steerer (CDLV/CDRV) | `y_kick` |
| `SkewQuadDevice` | SkewQuadrupole (CQLN/CQLT) | `skew_quad_strength` |
| `CavityDevice` | RFCavity | `frequency` |
| `RingSimulatorDevice` | — | `orbit_x/y`, `beta/alpha/nu_x/y`, `bpm_x/y_attr`, `hor`, `vert`, `reference_frequency` |

### Single virtual device

All physics results are published to one device:

```
simulator/ringsimulator/ringsimulator  (RingSimulatorDevice)
```

Commands: `Recalculate`, `Reset`

---

## Prerequisites

- Python 3.10+
- pyAT, PyTango, `dt4acc_lib` installed in virtualenv
- SOLEIL II lattice `.m` file
- SOLEIL II `accelerator_setup.json` (generated from the YAML by `yml2json_soleil.py`)
- A running Tango database (see below)

---

## Step 1 — Start the Tango Database

The Tango database runs inside an Apptainer container provided by SOLEIL:

```bash
apptainer run oras://gitlab-registry.synchrotron-soleil.fr/software-control-system/containers/apptainer/tango:latest
```

Verify it is reachable:

```bash
export TANGO_HOST=localhost:10000
tango_admin --ping-database
```

---

## Step 2 — Prepare the JSON database

If you have updated the YAML lattice file, regenerate the JSON:

```bash
cd src/dt4acc/custom_facility/soleil
python yml2json_soleil.py
# Output: accelerator_setup.json
# Move it to ~/Documents/dt4acc_soleil_twin_data/
```

---

## Step 3 — Clean the Tango database (on restart)

When device names or types have changed, wipe all existing dt4acc devices before restarting:

```bash
# Preview what will be deleted (safe — no changes)
python src/dt4acc/custom_facility/soleil/cleanup_tango_db.py --dry-run

# Delete everything
python src/dt4acc/custom_facility/soleil/cleanup_tango_db.py --yes
```

This removes all `MultipoleDevice`, `HorizontalSteererDevice`, `VerticalSteererDevice`,
`SkewQuadDevice`, `CavityDevice`, and `RingSimulatorDevice` registrations, plus their
server entries. Old class names (`MagnetDevice`, `TwissOrbitDevice`, etc.) are also
cleaned up.

---

## Step 4 — Start the digital twin

```bash
# Activate your virtualenv
source venv_acc/bin/activate

# Default — uses the standard lattice path:
# ~/Documents/dt4acc_soleil_twin_data/SOLEIL_II_V3635_...m
python -m dt4acc.custom_facility.soleil.run_soleil_twin

# Custom lattice file
python -m dt4acc.custom_facility.soleil.run_soleil_twin \
    --lattice /path/to/SOLEIL_II_lattice.m

# Custom TANGO host
python -m dt4acc.custom_facility.soleil.run_soleil_twin \
    --tango-host tango-db.soleil.fr:10000

# Slower heartbeat (recalculate every 5s instead of 1s)
python -m dt4acc.custom_facility.soleil.run_soleil_twin --heartbeat-period 5

# Disable heartbeat entirely (manual Recalculate only)
python -m dt4acc.custom_facility.soleil.run_soleil_twin --heartbeat-period 0
```

On startup the server prints:

```
SOLEIL twin server starting
  Lattice          : /home/.../SOLEIL_II_V3635_...m
  TANGO            : localhost:10000
  Recalc period    : 1.0s (no lattice changes)
  MexecPort        : 50200
  View             : design
```

---

## Step 5 — Verify in Jive

Open Jive and browse to:

```
simulator/ringsimulator/ringsimulator
```

- Attributes tab: `orbit_x`, `orbit_y`, `beta_x`, `beta_y`, `hor`, `vert`, ...
- Commands tab: `Recalculate`, `Reset`

Browse to any magnet, e.g.:

```
AN01-AR/EM-COR/SCD.06-CDLV.04   (VerticalSteererDevice)
```

Write `y_kick = 1e-6` and watch `orbit_y` update in `RingSimulatorDevice`.

---

## Reset after beam loss

If the backend enters error state (e.g. after writing a large kick that causes
AT tracking to diverge), the heartbeat will log:

```
WARNING: SimulatorBackend is in error state — call Reset before writing
```

Recover by calling Reset on the simulator device:

```python
import tango
dp = tango.DeviceProxy("simulator/ringsimulator/ringsimulator")
dp.command_inout("Reset")
```

Or from Jive: `simulator/ringsimulator/ringsimulator → Commands → Reset`.

Reset reloads the nominal lattice from the `.m` file and restores all magnet
devices to their nominal values within ~1 second.

---

## On-demand recalculation

To trigger a fresh twiss/orbit/tune calculation without changing the lattice:

```python
import tango
dp = tango.DeviceProxy("simulator/ringsimulator/ringsimulator")
dp.command_inout("Recalculate")
```

This is useful after a measurement campaign to confirm the current lattice state.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `TANGO_HOST` | `localhost:10000` | Tango database host:port |
| `DT4ACC_LATTICE_FILE` | `~/Documents/dt4acc_soleil_twin_data/SOLEIL_II_...m` | AT lattice file path |
| `DT4ACC_TANGO_HOST` | `localhost:10000` | Overrides `--tango-host` |
| `DT4ACC_VIEW` | `design` | Command view (`design` or `device`) |

---

## File layout

```
src/dt4acc/
├── config/
│   └── data/
│       └── querries.py               ← JSON database access
├── custom_facility/
│   └── soleil/
│       ├── run_soleil_twin.py            ← SOLEIL launch script
│       ├── cleanup_tango_db.py           ← wipe Tango DB before restart
│       ├── yml2json_soleil.py            ← YAML → JSON converter
│       ├── liasion_translator_setup.py   ← SOLEIL liaison + translator
│       └── soleil_yellow_pages.py        ← SOLEIL element name registry
└── custom_tango/
    └── ioc/
        ├── server_manager.py             ← facility-agnostic process manager
        ├── single_server.py              ← per-process Tango server
        ├── tango_controller.py           ← backend update + queue loop
        └── devices/
            ├── base_magnet_device.py
            ├── multipole_device.py
            ├── steerer_device.py
            ├── skew_quad_device.py
            ├── cavity_device.py
            ├── virtual_devices.py        ← RingSimulatorDevice
            └── tango_device_setup.py     ← DB registration

src/dt4acc/custom_facility/soleil/
    ├── run_soleil_twin.py        ← SOLEIL launch script
    ├── cleanup_tango_db.py       ← wipe Tango DB before restart
    └── yml2json_soleil.py        ← YAML → JSON converter
```

---

## Adding a new facility

To run the digital twin for a different facility:

1. Create `src/dt4acc/custom_facility/<facility>/run_<facility>_twin.py` — set `LATTICE_FILE`,
   `LOAD_MANAGERS_FN`, and `HEARTBEAT_PERIOD`.
2. Add `src/dt4acc/custom_facility/<facility>/liasion_translator_setup.py`
   with facility-specific `build_managers()` and `load_managers()`.
3. Create `src/dt4acc/custom_facility/<facility>/<facility>_yellow_pages.py`
   with element name lists.
4. Register any facility-specific addon proxy types in `ADDON_PROXY_REGISTRY`
   inside `load_managers()`.

No core files need to change.