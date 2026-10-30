# MLS storage ring twin

The Metrology Light Source (MLS) storage ring, 629 MeV, as an EPICS soft IOC
(Channel Access and PV Access), on pyAT through dt4acc-lib.

## Inputs

* lattice: lat2db's `lat2db.tools.pyat.mls_sr_reflat.mlsLattice` (183 elements, 48 m,
  tunes 3.178 / 2.232). Its sextupoles are off ("needs to be updated" in the deck).
* `resources/input/ao_mls.json`: MML's accelerator object for the MLS (HZB MML fork,
  `machine/MLS/StorageRing/mlsinit.m`)
* `resources/input/accelerator_setup.json`: the device database, written from it by
  `scripts/mls/make_accelerator_setup.py`: 76 magnets of the families Q1-Q3, S1-S3,
  HCM, VCM, the supply that drives each (59 supplies; a sextupole supply drives a
  string of 2 or 4) and MML's calibration.

Calibration as MML's `amp2k.m`: `K = polyval(amp2k, I) / Brho`. Quadrupoles and
steerers are linear (exact); the sextupoles have a 5th-order term (up to 5 % at
60 A): they use the polynomial itself (dt4acc-lib's `PolynomialCalibration`;
current for a strength: the real root closest to the linear solution, as MML's
`k2amp`). A steerer kicks the sextupole it is wound on (`HS3M2K1RP` kicks
`S3M2K1RP`).

## Run

```bash
dt4acc_mls                                    # or python -m dt4acc.custom_facility.mls.run_mls_twin
DT4ACC_PREFIX=MLS dt4acc_mls                  # PV prefix, default: the user name
```

## PVs

Prefixed with `DT4ACC_PREFIX` (`<P>`). Named as on the machine where MML knows them:

| PVs | what |
|---|---|
| `<P>:<supply>:setCur`, `<P>:<supply>:rdCur` | supply current [A]; a write to `setCur` acts, `rdCur` follows (e.g. `Q1P2K1RP`, `S1P1RP`, `HS3P2K1RP`) |
| `<P>:<bpm>:rdX`, `<P>:<bpm>:rdY` | closed orbit at the 28 BPMs [mm] (`BPMZ5K1RP`, ...) |
| `<P>:MCLKHGP:setFrq`, `<P>:MCLKHGP:rdFrq` | RF frequency [kHz]; `setFrq` acts, `rdFrq` follows |
| `<P>:CUM1ZK3RP:rdCur` | beam current (not computed) |

Twin only:

| PVs | what |
|---|---|
| `<P>:<magnet>:Cm:setCur`, `Cm:rdCur`, `im:I`, `x:setCur`, `y:setCur` | one magnet: strength (K, H or kick), its readback (follows its supply), offsets [m] |
| `<P>:beam:orbit:*`, `<P>:beam:twiss:*`, `<P>:survey:*` | closed orbit, optics, positions at every element |
| `<P>:TUNEZR:flq:rdH`, `rdV`, `<P>:TUNEZR:rdH`, `rdV` | tunes, tune frequencies |
| `<P>:ORBITCCP:rdBpm`, `<P>:ORBITCCP:rdModel` | BPM and model structures (PV Access only) |
| `<P>:simulator_ring:reset`, `reinit` | simulation state |

## Not yet

* octupoles (OCTU), skew quadrupoles (CQS) and the dipole supply (BEND, cubic amp2k)
  are in `ao_mls.json` but not controlled
* sextupole settings of the operating lattice; tune PV names of the machine
* `CAV:freq` does not follow the master clock (as in the BESSY II twin)

Tests: `tests/mls/test_mls_twin.py` (calibration against MML's amp2k, PV names,
design currents within MML's setpoint ranges, tunes).
