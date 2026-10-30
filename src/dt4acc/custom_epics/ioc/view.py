from copy import copy as _copy
import math
from typing import Optional, Dict, Sequence

import numpy as np
from softioc import pythonSoftIoc

from dt4acc.core.interfaces.view_interface import ViewInterface
from dt4acc.core.utils.logger import get_logger
from dt4acc_lib.model.output.result import TranslatedReading, SingleReading
from dt4acc_lib.model.output.result import TranslatedReading
from .orbit_pva import OrbitTwinServer
from dt4acc_lib.model.utils.command import ReadCommand

logger = get_logger()

#: EPICS string PVs (DBF_STRING) cannot hold more than 39 characters.
MAX_EPICS_STRING_LENGTH = 39

#: beam current [mA] while the beam is stored (zero order: no lifetime, no
#: injection), see :meth:`View.update_beam_survival`
DEFAULT_BEAM_CURRENT = 300.0


def orbit_found(x: Sequence[float], y: Sequence[float]) -> bool:
    """a closed orbit: finite at every element"""
    return len(x) > 0 and bool(np.all(np.isfinite(x)) and np.all(np.isfinite(y)))


def assert_epics_string_lengths(values, *, context: str) -> None:
    """Raise a clear error if any string exceeds the EPICS PV limit.

    Silently truncating (the previous behaviour) risks turning distinct
    uids into duplicates and hides a data problem that should be fixed
    at the source instead.
    """
    too_long = [v for v in values if len(v) > MAX_EPICS_STRING_LENGTH]
    if too_long:
        raise ValueError(
            f"{context}: {len(too_long)} value(s) exceed the EPICS string "
            f"limit of {MAX_EPICS_STRING_LENGTH} characters: {too_long}. "
            "Fix the source lattice/element data instead of truncating."
        )


class View(ViewInterface):
    """Key/value interface to process variables.

    Each key is a :class:`ReadCommand`; each value is the corresponding
    ``RecordWrapper`` from pythonSoftIoc.

    Special cases (twiss, track/orbit, tune) are dispatched explicitly.
    The orbit path additionally pushes to the PVA NTTable via
    :class:`OrbitTwinServer` when one is registered.
    """

    def __init__(
        self,
        *,
        orbit_server: Optional[OrbitTwinServer] = None,
        beam_current: float = DEFAULT_BEAM_CURRENT,
    ):
        self.process_variables: Dict[ReadCommand, pythonSoftIoc.RecordWrapper] = dict()
        self.orbit_server = orbit_server
        #: beam current [mA] while the beam is stored
        self.beam_current = beam_current
        # used for creating invalid data
        self.last_data_cache = dict()

    def update_process_variables(
        self, variables: Dict[ReadCommand, pythonSoftIoc.RecordWrapper]
    ):
        self.process_variables.update(variables)

    async def push_invalid(self) -> None:
        rcmd = ReadCommand(id="twiss", property="transveral")
        self.update_twiss(
            rcmd,
            TranslatedReading(
                rcmd,
                [SingleReading(cmd=rcmd, name="invalidate-twiss", payload=None)]
            )
        )
        rcmd = ReadCommand(id="track", property="pos")
        self.update_track(
            rcmd,
            TranslatedReading(
                rcmd,
                [SingleReading(cmd=rcmd, name="invalidate-track", payload=None)]
            )
        )

    async def dispatch(self, var: ReadCommand, pkg):
        """Update the value of a process variable.

        Special-cased variables (tune, twiss, track) are dispatched to their
        own handlers; everything else takes the generic path.
        """
        if self.update_special_values(var, pkg):
            return

        record_wrapper = self.process_variables.get(var)
        (single_reading,) = pkg.readings
        value = single_reading.payload
        assert record_wrapper is not None, f"No process variable registered for {var}"
        record_wrapper.set(value)

    def update_special_values(self, var: ReadCommand, value) -> bool:
        if var.id == "tune":
            logger.warning("Tune not handled explicitly any more, but as part of twiss")
            return True
        elif var.id == "twiss":
            self.update_twiss(var, value)
            self.update_tune(var, value)
            return True
        elif var.id == "track":
            self.update_track(var, value)
            return True
        elif var.id == "turn_by_turn":
            self.update_turn_by_turn(var, value)
            return True
        elif var.id == "survey":
            self.update_survey(var, value)
            return True
        elif var.id == "beam_survival":
            self.update_beam_survival(var, value)
            return True
        return False

    def update_beam_survival(self, var: ReadCommand, pkg):
        """beam current: ``beam_current`` if the particles tracked around the
        closed orbit survived (dt4acc-lib's ``BeamSurvival``), else 0"""
        assert var.id == "beam_survival", f"Only prepared to process 'beam_survival' but got {var}"
        (single_reading,) = pkg.readings
        survival = single_reading.payload
        stored = survival is not None and survival.stored
        # Todo: decaying beam current (lifetime) and top-up mode: the current
        #       is now fixed (beam_current) or 0; lifetime from the lattice or
        #       a fixed value, top-up interval and step, per bunch / fill
        #       pattern. Needs a user story first (#84), can be a separate PR
        # Todo: beam loss monitors: BeamSurvival.lost says per particle if it
        #       is lost; keep where (element) and when (turn), as pyAT's loss
        #       map gives it, and serve it as BLM PVs at the facility's BLM
        #       positions, scaled to the beam current. Also for turn by turn
        #       tracking and the transfer line
        # Todo: fluorescent screens (real or artificial, #76): stop the beam
        #       (losses in the BLMs behind it) or observe it and let it pass
        self.set_beam_current(self.beam_current if stored else 0.0)

    def update_survey(self, var: ReadCommand, pkg):
        assert var.id == "survey"
        (single_reading,) = pkg.readings
        data = single_reading.payload

        rec_s = self.process_variables.get(ReadCommand(id="survey", property="s"))
        assert rec_s
        rec_s.set([datum.s for datum in single_reading.payload])

        rec_name = self.process_variables.get(ReadCommand(id="survey", property="names"))
        assert rec_name
        rec_name.set([datum.name for datum in single_reading.payload])

        rec_uid = self.process_variables.get(ReadCommand(id="survey", property="uids"))
        assert rec_uid
        uids = [datum.uid for datum in single_reading.payload]
        assert_epics_string_lengths(uids, context="survey uids")
        rec_uid.set(uids)

    def update_track(self, var: ReadCommand, pkg):
        assert var.id == "track", f"Only prepared to process 'track' but got {var}"
        (single_reading,) = pkg.readings
        value = single_reading.payload
        if value is None:
            ref_value = self.last_data_cache.get(ReadCommand("track", "pos"))
            if ref_value is None:
                logger.warning(
                    "%s.update_track got no data: calculation succeded?: but no reference data for producing invalid data",
                    self.__class__.__name__
                )
                self.set_beam_current(0.0)
                return
            value = _copy(ref_value)
            for pos in value.track:
                pos.x = pos.y = math.nan
        else:
            self.last_data_cache[var] = value

        if var.property == "pos":
            x_vals = [pos.x for pos in value.track]
            y_vals = [pos.y for pos in value.track]
            names = [pos.fam_name for pos in value.track]
            uids = [pos.uid for pos in value.track]

            rw_x = self.process_variables.get(ReadCommand(id="beam", property="x"))
            rw_y = self.process_variables.get(ReadCommand(id="beam", property="y"))
            assert rw_x is not None
            assert rw_y is not None
            rw_x.set(x_vals)
            rw_y.set(y_vals)

            rw_names = self.process_variables.get(
                ReadCommand(id="beam", property="names")
            )
            if rw_names is not None:
                rw_names.set(names)

            rw_uids = self.process_variables.get(
                ReadCommand(id="beam", property="uids")
            )
            if rw_uids is not None:
                assert_epics_string_lengths(uids, context="track uids")
                rw_uids.set(uids)

            rw_found = self.process_variables.get(
                ReadCommand(id="beam", property="found")
            )
            found = orbit_found(x_vals, y_vals)
            if rw_found is not None:
                rw_found.set(found)
            # without a closed orbit no beam; with one: beam_survival decides
            if not found:
                self.set_beam_current(0.0)

            # PVA NTTable
            if self.orbit_server is not None:
                try:
                    # BPM readings are in nanometer
                    self.orbit_server.push(
                        x=[v * 1e9 for v in x_vals],
                        y=[v * 1e9 for v in y_vals],
                    names=names
                    )
                except Exception as exc:
                    logger.error("OrbitTwinServer.push failed: %s", exc)
        else:
            raise AssertionError(f"Don't know track property {var.property}")

    def set_beam_current(self, value: float) -> None:
        """every beam current PV (``ReadCommand(id="beam_current", ...)``) [mA]"""
        for rc, record in self.process_variables.items():
            if rc.id == "beam_current":
                record.set(value)

    def update_turn_by_turn(self, var: ReadCommand, pkg):
        assert (
            var.id == "turn_by_turn"
        ), f"Only prepared to work on turn by turn data {var}"
        (single_reading,) = pkg.readings
        tbt_data = single_reading.payload
        for elem_tbt in tbt_data.per_element:
            # Assuming that the element names correspond to
            # id uses for the record names
            rcmd = ReadCommand(id=elem_tbt.uid.device_name, property="tbt_x")
            rc = self.process_variables.get(rcmd)
            x = elem_tbt.get_x().nanmean_per_turn()
            if rc is None:
                logger.warning("%s: no record for %s", self.__class__.__name__, rcmd)
            else:
                rc.set(x)
            rcmd = ReadCommand(id=elem_tbt.uid.device_name, property="tbt_y")
            rc = self.process_variables.get(rcmd)
            y = elem_tbt.get_y().nanmean_per_turn()
            if rc is None:
                logger.warning("%s: no record for %s", self.__class__.__name__, rcmd)
            else:
                rc.set(y)

            # Todo: handle sum signal in a smarter way
            #       should it be calculated in view ?
            #
            #       factor in the beam current: now it is the number of
            #       particles survived per turn; shall be proportional to
            #       beam_current (the fraction survived after a loss).
            #       Together with the closed orbit sum signal (#78)
            survived = elem_tbt.get_survived()
            n_particles = survived.get_n_particles_survived_per_turn()
            rcmd = ReadCommand(id=elem_tbt.uid.device_name, property="tbt_sum")
            rc = self.process_variables.get(rcmd)
            if rc is None:
                logger.warning("%s: no record for %s", self.__class__.__name__, rcmd)
            else:
                rc.set(n_particles)

    def master_clock_record(self):
        """The master clock's frequency record

        PVs made from the device database (``pv_setup``) key it
        ``master_clock:freq``, PVs made from the device model
        ``master_clock:reference_frequency``.
        """
        for prop in ("freq", "reference_frequency"):
            rec = self.process_variables.get(ReadCommand("master_clock", prop))
            if rec is not None:
                return rec
        raise KeyError("no master clock record (master_clock:freq or master_clock:reference_frequency)")

    def update_tune(self, var: ReadCommand, pkg):
        assert (
            var.id == "twiss"
        ), f"Only prepared to extract tune from 'twiss' but got {var}"
        (single_reading,) = pkg.readings
        value = single_reading.payload

        if value is None:
            for plane in ("x", "y"):
                rec = self.process_variables[
                    ReadCommand(id="tune", property=f"flq_{plane}")
                ]
                rec.set(math.nan)
                rec = self.process_variables[
                    ReadCommand(id="tune", property=f"{plane}")
                ]
                rec.set(math.nan)
            return

        for plane in ("x", "y"):
            twiss_data_of_last_element = getattr(value.twiss[-1], plane)
            # Hard coded dependency for AT: returns phase advance times 2pi
            flq = twiss_data_of_last_element.nu / (2 * math.pi)
            rec = self.process_variables[
                ReadCommand(id="tune", property=f"flq_{plane}")
            ]
            rec.set(flq)

            mc_rec = self.master_clock_record()
            # Todo: need to read the correct values e.g. from a variable
            n_buckets_rec = self.process_variables.get(
                ReadCommand("ring", "n_rf_buckets")
            )
            assert n_buckets_rec is not None
            n_buckets = n_buckets_rec.get()
            # todo: is this calculation in bact_math_utils ...
            #       then copy it together with tests
            #       further watch out ...
            #       some can do the whole integer fraction
            flq_frac = flq % 1.0
            rev_freq = mc_rec.get() / n_buckets
            tune_freq = flq_frac * rev_freq
            # Todo: need to readress where the scale should go
            #       perhaps tune should be handled over virtual devices
            tune_freq = tune_freq / 1000.0
            rec = self.process_variables[ReadCommand(id="tune", property=f"{plane}")]
            rec.set(tune_freq)
            logger.debug(f"Updated Tune for plane {plane}")
            pass


    def update_twiss(self, var: ReadCommand, pkg):
        """
        Todo:
            export uids too
        """
        assert var.id == "twiss", f"Only prepared to process 'twiss' but got {var}"

        (single_reading,) = pkg.readings
        value = single_reading.payload
        if value is None:
            ref_value = self.last_data_cache.get(ReadCommand("twiss", "parameters"))
            if ref_value is None:
                logger.warning(
                    "%s.update_twiss got no data: calculation succeded?: but no reference data for producing invalid data",
                    self.__class__.__name__
                )
                return
            value = _copy(ref_value)
            for item in value.twiss:
                for vals_plane in item.x, item.y:
                    vals_plane.beta = vals_plane.alpha = vals_plane.mu = math.nan
            del item, vals_plane
        else:
            self.last_data_cache[var] = value

        for plane in ("x", "y"):

            rw = self.process_variables.get(ReadCommand("twiss", f"{plane}:nu"))
            assert rw is not None
            rw.set([getattr(pos, plane).nu / (2 * math.pi) for pos in value.twiss])

            for param in ("beta", "alpha"):
                rw = self.process_variables.get(
                    ReadCommand("twiss", f"{plane}:{param}")
                )
                assert rw is not None
                rw.set([getattr(getattr(pos, plane), param) for pos in value.twiss])

        rw_names = self.process_variables.get(ReadCommand("twiss", "names"))
        assert rw_names is not None
        rw_names.set([pos.fam_name for pos in value.twiss])

        rw_names = self.process_variables.get(ReadCommand("twiss", "uids"))
        assert rw_names is not None
        twiss_uids = [pos.uid for pos in value.twiss]
        assert_epics_string_lengths(twiss_uids, context="twiss uids")
        rw_names.set(twiss_uids)

        pi2 = 2 * math.pi

        if self.orbit_server is not None:
            rec_s = self.process_variables.get(ReadCommand("survey", "s"))
            s_pos = rec_s.get()

            try:
                self.orbit_server.push_model_data(
                    bpm_names=[pos.fam_name for pos in value.twiss],
                    beta_hor=[pos.x.beta for pos in value.twiss],
                    beta_vert=[pos.y.beta for pos in value.twiss],
                    phase_advance_hor=[pos.x.nu / (pi2) for pos in value.twiss],
                    phase_advance_vert=[pos.y.nu / (pi2) for pos in value.twiss],
                    s_pos=s_pos,
                )
            except Exception as exc:
                logger.error("OrbitTwinServer.push failed: %s", exc)
