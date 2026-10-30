# Digital twin Version 2.0: status

What is planned for Version 2.0, what of it is implemented, and which pull
request / commit does it. Keep it up to date: when a PR is merged, add its
merge commit; when an issue is opened, add its number.

Sources:

* `Functional_Specifications_for_digital_twin_brainstorming.pdf` (section 3,
  "Ideas and Opinions for Version 2.0")
* `minutes-30-09-2026-twin-workshop-hzb.md` (twin workshop, HZB, 30.09.2026)

Out of scope here: Version 3.0 (hardware in the loop, power converter
response functions), and the minutes' "further requirements" (time dependent
behaviour of power converters: ramp, overshoot, ringing), which is the same
topic.

Status: **done** (merged), **in review** (PR open), **partial**, **open**
(nothing yet), **needs a user story** (not clear what it shall provide).
Commits are merge commits on `dev/main`; `lib` is dt4acc-lib.

## Overview

| # | Item | Source | Status | PR / commit | Issue |
|---|---|---|---|---|---|
| 1 | Machine complex: BESSY II transfer line + storage ring, tracking from the line into the ring | PDF, minutes | done (BESSY II) | dt4acc#66 `d2d4b55`, #67 `0fd645a`, #68 `85b81a9`; lib#32 `0b370bb`, lib#33 `29bd38d` | |
| 1s | the same for SOLEIL | minutes | open | | #72 |
| 1g | guide: setting up the complex for another facility | minutes | open | | #73 |
| 1a | single machines next to the whole complex | minutes | done | `dt4acc_bessyii`, `dt4acc_bessytl`, `dt4acc_bessyii_injection` (dt4acc#67 `0fd645a`) | |
| 1b | injection line to booster, booster | minutes (optional) | open | | #74 |
| 1c | kicker strength variations, start distribution at injection | PDF (discuss) | needs a user story | | #84 |
| 1u | BESSY II: undulators (gap, phase) and their effect on the beam | request for BESSY II | open | | #86 |
| 2 | Turn by turn data: turns, start vector, start element, where to output | PDF | done | lib#27 `fe31346`, lib#33 `29bd38d` (start_at) | |
| 2a | track an ensemble of particles; BPM centre of mass and sum (particles survived) | minutes | done | lib#27 `fe31346` (survived), BPM `tbt_x` / `tbt_y` / `tbt_sum` (view) | |
| 2b | arbitrary stops for the beam | minutes | open | | #75 |
| 2c | fluorescent screens: stop the beam or observe | minutes | open | | #76 |
| 2d | fault injection for turn by turn data | minutes | needs a user story | | #84 |
| 2e | kickers (injection, extraction) in turn by turn | minutes | open | | #77 |
| 3 | Beam current measurement: fixed value, ≈ 0 if the beam is lost | PDF, minutes, dt4acc#33 | in review | dt4acc#71, lib#35 | #33 |
| 3a | current decay (lifetime) and top-up | minutes | needs a user story | | #84 |
| 3b | different lifetimes per bunch; fill pattern | minutes | needs a user story | | #84 |
| 3c | BPM sum signal for the closed orbit (reflecting the current) | minutes | open | turn by turn sum exists (2a) | #78 |
| 4 | Pinhole camera: centre x, y and size σx, σy; image of the Gaussian beam from twiss and emittance | PDF, minutes | open | beam size at one location exists in lib#35 (`BeamSurvival.sigma`) | #79 |
| 5 | Inputs validated by hardware limits (static: power converter min / max current) | PDF | open | limits in the device data for MLS (dt4acc#69, `range`) | #80 |
| 6 | Different lattices (with errors, with corrections) loaded at run time | PDF | partial | lattice file at start: `DT4ACC_LATTICE_FILE` (`core/bl/handle_lattice.py`); no switch at run time | #81 |
| 7 | Output with noise (BPM readings, pinhole, beam current) | PDF, minutes | open | | #82 |
| 8 | Configuration needs to get better | minutes | needs a user story | | #84 |
| 9 | Mark clearly the PVs only provided by the twin | minutes | done (BESSY II) | dt4acc#64 `4dc7120`, #68 `85b81a9` (`pv_list.md`: column *machine*) | |
| 9a | the same for the other twins | minutes | done | PV wiki (dt4acc_agent `scripts/pv_wiki`: every PV a twin serves, live) | |
| 10 | Improve documentation | minutes | partial | dt4acc#29 `d80c8b1` (published doc), `pv_list.md` | |
| 11 | Better names: ring simulator reset → reinject beam, reinit → reset lattice to nominal | PDF | not planned (decided 2026-10-30) | | |

## Found while implementing (bugs)

| Item | Status | PR / commit | Issue |
|---|---|---|---|
| `beam:orbit:found` never set back to False | in review | dt4acc#71 | |
| `simulator_ring:reset` / `reinit` do not refresh the model PVs | in review | dt4acc#71 | |
| BESSY II: steerer `<magnet>:Cm:set` raises `KeyError` (no `main_strength_rdbk`); sextupole magnets have no `main_strength` lookup entry | open | | #83 |
| unstable ring (pyAT `AtError`) not handled as failed optics | in review | lib#35 | |

## Log

* 2026-10-30: document started; status checked against `dev/main` (dt4acc,
  dt4acc-lib) and the issues and PRs of both repositories. Issues #72 - #84
  opened; #86 (BESSY II undulators). Not planned: renaming reset / reinit. Twin only PVs: done with
  the PV wiki.
