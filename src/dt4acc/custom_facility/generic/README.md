# Generic EPICS digital twin

This is the EPICS-side equivalent of `custom_facility/soleil/run_soleil_twin.py`
for Tango: a facility-agnostic launcher that starts an EPICS soft-IOC digital
twin from just a lattice file and an `accelerator_setup.json` catalog, no
code changes required. It is not tied to any specific facility — the FODO
lattice/catalog bundled under `resources/` is only the default test/demo
dataset used when no `--lattice`/`--accelerator-setup-file` is given (e.g. by
the CI smoke test).

## Usage

```bash
python -m dt4acc.custom_facility.generic.run_epics_twin \
    --lattice /path/to/lattice.json \
    --accelerator-setup-file /path/to/accelerator_setup.json \
    --prefix my-prefix
```

All three flags are optional:

- `--lattice` / `DT4ACC_LATTICE_FILE` — defaults to the bundled
  `resources/fodo_lattice.json`.
- `--accelerator-setup-file` / `DT4ACC_ACCELERATOR_SETUP_FILE` — defaults to
  the bundled `resources/accelerator_setup.json`.
- `--prefix` / `DT4ACC_PREFIX` — defaults to the current user name.

`DT4ACC_HEADLESS=1` switches the IOC to non-interactive mode (used by the CI
smoke test); interactive by default.

## Catalog schema

Unlike SOLEIL's Tango design-view (no power converters — the magnet device
writes straight to the lattice element), this generic schema models a simple
"one power converter per magnet" facility. `accelerator_setup.json` is a flat
JSON array; each entry needs `type`, `name`, `pc`, and (for magnets) `k`:

```json
{"type": "Quadrupole", "name": "QF_001", "magnetic_strength": 1.258, "pc": "QF_001_PC", "k": 1.258}
```

- `Quadrupole`/`Sextupole` elements map 1:1 to catalog entries.
- Each AT `Multipole` corrector element (combined H/V kick on one lattice
  element, e.g. `COR_001`) is driven by **two independent** `Steerer` power
  converters — `HCOR_001` (`PolynomB[0]`/`B1`) and `VCOR_001`
  (`PolynomA[0]`/`A1`). There is **no** separate catalog entry for the
  `Multipole` host itself — see the gotcha below.
- RF cavities are **not** in the catalog — they have no power converter of
  their own in this schema and are read straight off the loaded lattice
  (any AT `RFCavity` element).
- `Bend`, `Monitor` (BPM), and any other element types are ignored by this
  schema.

Only `Quadrupole`/`Sextupole`/`Steerer` catalog entries are consumed; the
catalog is read through `dt4acc.config.data.querries`
(`DT4ACC_ACCELERATOR_SETUP_FILE`/`configure_data_file()`), the same generic,
runtime-configurable module used by the Tango/SOLEIL launcher.

## How it's wired up

`liasion_translator_setup.py::build_managers(acc)` builds the
`YellowPages`/`LiaisonManager`/`TranslatorService` **dynamically, at every
launch**, straight from the configured catalog (`get_controlled_elements()`)
and the loaded lattice (`acc`, for cavity names and `BRho`) — mirroring
exactly how `custom_facility/soleil/liasion_translator_setup.py::build_managers()`
does it for Tango. There is no offline generation step and no YAML lookup
tables to regenerate by hand: point at a different lattice + catalog and the
twin picks it up on the next launch.

`run_epics_twin.py` is otherwise a straight port of
`custom_facility/bessyii/run_bessyii_twin.py` (PV setup, controller, orbit
server, IOC startup are identical); the facility-specific pieces are just
lattice loading (plain `lattice_loader` — no `lat2db` factory step needed
since the bundled lattice is already atjson v1) and the dynamic catalog/
lattice-driven `build_managers()` above.

## Gotchas found while wiring this up

### Combined-function correctors: steerer vs. multipole

`COR_001` is **one** AT `Multipole` lattice element carrying both a
horizontal kick (`PolynomB[0]`) and a vertical kick (`PolynomA[0]`).
`HCOR_001`/`VCOR_001` are the two **steerers** — the actual
power-converter-driven correctors — that act on it. Terminology that
matters here: the *steerer* is the corrector; the *multipole* is just
the magnet/lattice element it sits on. There is no separate
`accelerator_setup.json` entry for the multipole host itself — it has
no power converter of its own — but both steerers' liaison-manager
entries correctly point back at the **same** lattice element name
(`COR_001`), distinguished only by property (see next gotcha).
Verify with:

```python
lm.inverse(DevicePropertyID("HCOR_001", "main_strength"))
# -> [LatticeElementPropertyID("COR_001", "B1")]
lm.inverse(DevicePropertyID("VCOR_001", "main_strength"))
# -> [LatticeElementPropertyID("COR_001", "A1")]
```

### Multipole property naming: `B1`/`A1`, not `x_kick`/`y_kick` or `B0`/`A0`

AT's `PolynomA`/`PolynomB` arrays are 0-indexed, but `dt4acc_lib`'s
simulator backend (`ElementProxyFactory`) names multipole properties
using the **European convention** (dipole = order 1, quadrupole =
order 2, ...). So the corrector's dipole term at Python index
`PolynomB[0]`/`PolynomA[0]` is addressed as **`B1`/`A1`** — not `B0`/
`A0` (order 0 doesn't exist in this convention; `dt4acc_lib` asserts
against it) and not `x_kick`/`y_kick` (that route goes through the
element's `KickAngle` attribute instead, which our `Multipole`-class
correctors don't carry — AT only builds `KickAngle` for `at.Corrector`
elements, not generic `at.Multipole`).

`dt4acc_lib`'s generic `Multipole` property handler
(`pyat_simulator/element_properties/multipole.py`) already writes
straight into the `PolynomB`/`PolynomA` arrays — it just wasn't wired
up for order 1. Fixed in the sibling `dt4acc-lib` checkout
(`pyat_simulator/proxies/proxy_factory.py`): the multipole property
range was widened from `range(2, 20)` to `range(1, 20)`, so `B1`/`A1`
are now resolvable and write directly to `PolynomB[0]`/`PolynomA[0]`.
**If you're pulling in a released `dt4acc-lib` rather than this
sibling checkout, confirm that widened range made it in** — otherwise
`B1`/`A1` won't resolve and you'll see the same
`can't resolve ... known properties: [...]` error this session started
from.

### EPICS string length limit (39 characters)

`fodo_lattice.json`'s `UUID` field is `"<FamName>_<hex hash>"`. For
7-character `FamName`s (`BPM_xxx`, `COR_xxx`) that came out to 40
characters — one over what an EPICS string PV (`DBF_STRING`) can hold
(39). `custom_epics/ioc/view.py` used to silently truncate uids with
`[:39]` when pushing them to `survey`/`track`/`twiss` waveform PVs,
which risks turning distinct uids into duplicates. Fixed both ends:

- **Source data**: `scripts/shorten_fodo_uuids.py` truncated the hash
  suffix from 32→16 hex characters in `fodo_lattice.json` (still
  effectively collision-free for a lattice this size), bringing the
  max UUID length down to 24. Rerun it if new elements ever push a
  `FamName` long enough to matter again.
- **`view.py`**: replaced the `[:39]` truncation with
  `assert_epics_string_lengths()`, which raises a clear `ValueError`
  naming the offending value(s) instead of silently cutting them —
  so a future over-length uid fails loudly at the source rather than
  corrupting data downstream.

## File map

| File | Role |
|---|---|
| `resources/fodo_lattice.json` | Default/demo lattice (atjson v1), used when `--lattice` is omitted. |
| `resources/accelerator_setup.json` | Default/demo catalog, used when `--accelerator-setup-file` is omitted. |
| `scripts/shorten_fodo_uuids.py` | One-off/rerunnable fix for over-length element UUIDs in `resources/fodo_lattice.json`. |
| `liasion_translator_setup.py` | Builds `YellowPages`/`LiaisonManager`/`TranslatorService` dynamically from the configured catalog + loaded lattice (`build_managers(acc)`). |
| `run_epics_twin.py` | Starts the twin (EPICS soft-IOC); CLI + wiring. |
