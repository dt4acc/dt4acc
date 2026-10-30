"""Beam current PVs: 300 mA while the beam is stored (dt4acc-lib's beam
survival), 0 without a closed orbit or when the tracked particles are lost;
``beam:orbit:found`` follows the closed orbit"""
import math
from types import SimpleNamespace

import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.custom_epics.ioc.pv_setup import initialize_beam_current_pvs, initialize_other_pvs
from dt4acc.custom_epics.ioc.view import DEFAULT_BEAM_CURRENT, View
from dt4acc_lib.model.output.result import SingleReading, TranslatedReading
from dt4acc_lib.model.utils.command import ReadCommand

from tests.recording_builder import RecordingBuilder

PVS = ["TOPUPCC:rdCur", "MDIZ3T5G:current"]


class Record:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


def reading(rcmd: ReadCommand, payload):
    return TranslatedReading(rcmd, [SingleReading(cmd=rcmd, name="test", payload=payload)])


def track(x: float):
    pos = SimpleNamespace(fam_name="Q1", uid="Q1", x=x, y=0.0)
    return SimpleNamespace(track=[pos, SimpleNamespace(fam_name="Q2", uid="Q2", x=0.0, y=0.0)])


@pytest.fixture
def view():
    v = View()
    v.update_process_variables({ReadCommand("beam_current", name): Record() for name in PVS})
    v.update_process_variables({ReadCommand("beam", p): Record() for p in ("x", "y", "found")})
    return v


def currents(view):
    return [view.process_variables[ReadCommand("beam_current", name)].value for name in PVS]


@pytest.mark.parametrize("stored, current", [(True, DEFAULT_BEAM_CURRENT), (False, 0.0)])
def test_current_follows_beam_survival(view, stored, current):
    rcmd = ReadCommand("beam_survival", "stored")
    view.update_special_values(rcmd, reading(rcmd, SimpleNamespace(stored=stored)))
    assert currents(view) == [current, current]


def test_no_survival_data_no_current(view):
    rcmd = ReadCommand("beam_survival", "stored")
    view.update_special_values(rcmd, reading(rcmd, None))
    assert currents(view) == [0.0, 0.0]


def test_no_closed_orbit(view):
    rcmd = ReadCommand("track", "pos")
    survival = ReadCommand("beam_survival", "stored")
    view.update_special_values(rcmd, reading(rcmd, track(1e-3)))
    view.update_special_values(survival, reading(survival, SimpleNamespace(stored=True)))
    assert view.process_variables[ReadCommand("beam", "found")].value is True
    assert currents(view) == [DEFAULT_BEAM_CURRENT] * 2
    # the orbit is lost: invalid data (NaN), found goes back to False, no current
    view.update_special_values(rcmd, reading(rcmd, None))
    assert view.process_variables[ReadCommand("beam", "found")].value is False
    assert math.isnan(view.process_variables[ReadCommand("beam", "x")].value[0])
    assert currents(view) == [0.0, 0.0]


def test_pv_names():
    builder = RecordingBuilder()
    builder.SetDeviceName("TEST")
    pvs = {**initialize_other_pvs(builder), **initialize_beam_current_pvs(builder, ["TOPUPCC:rdCur"])}
    assert set(builder.names("TEST")) == set(PVS)
    assert set(pvs) == {ReadCommand("beam_current", name) for name in PVS}
