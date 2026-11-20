# SOLEIL TL2 transfer line twin (Tango)

Set up as the SOLEIL ring twin (`../soleil`): the same files, its command line and
environment variables. With the ring, the beam handed over: `../soleil_injection`, whose
README also has how to run, what moves what, what to take care of.

Different, because it is a line:

* the beam entering it: `--twiss-in` / `DT4ACC_TWISS_IN_FILE`, no closed orbit: `orbit_*`
  of its simulator device is the trajectory; tunes, chromaticity NaN, no turn by turn
* correctors are `at.Corrector` elements: `x_kick` / `y_kick`; direction from their
  family, `soleil_tl2_yellow_pages`
* BPMs are markers in SOLEIL's file; no RF

| write | what moves |
|---|---|
| steerer, `LT2/EM-COR/COR.H.01` ... `COR.H.05`, `COR.V.01` ... `COR.V.04`, `magnetic_strength` [rad] | `orbit_*` and BPMs (`LT2/DG-EPOS/BPM.01` ... `BPM.06`: `XPosSA`, `ZPosSA`) after it |
| quadrupole, `LT2/EM-QP/QP.01` ... `QP.12`, `magnetic_strength` | `beta_*`, `alpha_*`, `nu_*`; trajectory if the beam is off centre in it |
| bends, kickers, septa | nothing: not controlled, as in the ring; writes are refused |

**Supplies** (`LT2/AE-QP/QP.12`, `LT2/AE-COR/COR.H.05`, ...), `--view device` on `register_devices`
and the twin: `current_set` drives its magnets with factor 1, no current to strength data yet: the value is the
magnet's strength, not amperes. Magnets and supplies follow each other's writes (magnets
polled: up to about 1.5 s). The default view, `design`, serves the magnets only.

SOLEIL's files are not in the repository, see `../soleil_injection/README.md`.
