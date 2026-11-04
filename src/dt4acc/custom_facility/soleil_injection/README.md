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

SOLEIL's files are not in the repository: the defaults are the two twins' folders in
`~/Documents/dt4acc_config_data`.

```bash
cd ~/Documents/dt4acc_config_data/soleilii-tl
python -m dt4acc.custom_facility.soleil_tl2.yml2json_soleil_tl2
python -m dt4acc.custom_facility.soleil_injection.register_devices --tango-host HOST:PORT
python -m dt4acc.custom_facility.soleil_injection.run_soleil_injection_twin --tango-host HOST:PORT
```

Three processes: the ring twin, the TL2 twin, the hand over's device. If one ends, all end.

## Devices

| device | what |
|---|---|
| the ring's | as the ring twin, in its default view |
| TL2's | as the TL2 twin, in its default view |
| `simulator/ringsimulator/ringsimulator` | the ring's optics and turn by turn data; `tbt_offset` is set by the hand over |
| `simulator/tlsimulator/tlsimulator` | TL2's trajectory and optics |
| `simulator/injection/injection` | the hand over |
| a ring BPM device: `XPosDD`, `ZPosDD` | one ring BPM, turn after turn [mm] |

`simulator/injection/injection`:

| attribute | what |
|---|---|
| `geometry` | (x, px, y, py, delta, ct) line against ring at the injection point, writable |
| `n_turns` | turns tracked in the ring, writable |
| `line_exit` | centroid leaving TL2, line frame |
| `injected` | the same in the ring's frame |
| `survived` | particles still there after each turn |
| `count` | hand overs computed so far |

## Check

```bash
pytest tests/tango_tests/test_soleil_injection.py
```
