"""Screens (FOMZ...): an image of the beam spot, from its centre (the
trajectory) and its size (emittance and beta at the screen)"""
import asyncio
import math
from types import SimpleNamespace

import numpy as np
import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.custom_epics.ioc.pv_setup import initialize_orbit_pvs, initialize_twiss_pvs
from dt4acc.custom_facility.bessytl.screens import ScreenGeometry, beam_size, screen_image
from dt4acc.custom_facility.bessytl.view import (
    TRACK, TWISS, ScreenMode, TransferLineView, initialize_artificial_screen_pvs, initialize_monitor_pvs,
    initialize_screen_mode_pvs,
)
from dt4acc_lib.model.utils.command import ReadCommand

from tests.recording_builder import RecordingBuilder

GEOMETRY = ScreenGeometry(width=200, height=100, pixel=0.1)


def centre_and_size(image, geometry=GEOMETRY):
    """centre and rms size [mm] of an image, row 0 at the top"""
    cx = (np.arange(geometry.width) - geometry.width / 2 + 0.5) * geometry.pixel
    cy = (np.arange(geometry.height) - geometry.height / 2 + 0.5)[::-1] * geometry.pixel
    px, py = image.sum(axis=0), image.sum(axis=1)
    mx, my = (px * cx).sum() / px.sum(), (py * cy).sum() / py.sum()
    return (mx, my), (math.sqrt((px * (cx - mx) ** 2).sum() / px.sum()), math.sqrt((py * (cy - my) ** 2).sum() / py.sum()))


# --- the image
def test_image_of_a_spot_on_the_screen():
    image = screen_image(1.5, -0.8, 0.9, 0.4, geometry=GEOMETRY)
    assert image.shape == (GEOMETRY.height, GEOMETRY.width)
    assert image.sum() == pytest.approx(1.0, abs=1e-9), "the whole beam on the screen"
    (mx, my), (sx, sy) = centre_and_size(image)
    assert (mx, my) == pytest.approx((1.5, -0.8), abs=1e-6)
    # pixels add width^2 / 12 to the variance
    assert (sx, sy) == pytest.approx((math.hypot(0.9, 0.1 / math.sqrt(12)), math.hypot(0.4, 0.1 / math.sqrt(12))), rel=1e-3)


def test_row_zero_is_the_top():
    image = screen_image(0.0, 3.0, 0.2, 0.2, geometry=GEOMETRY)
    rows = image.sum(axis=1)
    assert rows[: GEOMETRY.height // 2].sum() > 0.99, "a beam above the axis is in the upper rows"


def test_part_of_the_beam_misses_the_screen():
    edge = GEOMETRY.width * GEOMETRY.pixel / 2
    assert screen_image(edge, 0.0, 1.0, 1.0, geometry=GEOMETRY).sum() == pytest.approx(0.5, abs=1e-6)
    assert screen_image(edge + 20, 0.0, 1.0, 1.0, geometry=GEOMETRY).sum() == pytest.approx(0.0, abs=1e-12)


def test_no_beam_dark_image():
    assert not screen_image(math.nan, 0.0, 1.0, 1.0, geometry=GEOMETRY).any()
    assert not screen_image(0.0, 0.0, math.nan, 1.0, geometry=GEOMETRY).any()


def test_point_beam_in_one_pixel():
    image = screen_image(0.05, 0.05, 0.0, 0.0, geometry=GEOMETRY)
    assert image.sum() == 1.0 and np.count_nonzero(image) == 1


def test_beam_size():
    assert beam_size(1e-7, 10.0) == pytest.approx(1e-3)


# --- the view: the screens' records
SCREENS = ["FOMZ1T", "FOMZ2T"]
MONITORS = ["BPMZ1T", *SCREENS]
NAMES = ["D1", *MONITORS]


def track_package(x_at):
    track = [SimpleNamespace(x=x_at.get(n, 0.0), y=0.0, fam_name=n, uid=f"{n}:0") for n in NAMES]
    return SimpleNamespace(readings=[SimpleNamespace(payload=SimpleNamespace(track=track))])


def twiss_package(beta):
    def at(n):
        b = beta.get(n, (1.0, 1.0))
        return SimpleNamespace(
            fam_name=n, uid=f"{n}:0",
            x=SimpleNamespace(beta=b[0], alpha=0.0, nu=0.0), y=SimpleNamespace(beta=b[1], alpha=0.0, nu=0.0),
        )
    return SimpleNamespace(readings=[SimpleNamespace(payload=SimpleNamespace(twiss=[at(n) for n in NAMES]))])


def make_view(single_pass):
    builder = RecordingBuilder()
    view = TransferLineView(monitors=MONITORS, single_pass=single_pass, emittance={"x": 1e-7, "y": 1e-8},
                            screen=GEOMETRY)
    view.update_process_variables({
        **initialize_monitor_pvs(MONITORS, builder=builder, geometry=GEOMETRY),
        **initialize_orbit_pvs(builder, n_elements=len(NAMES)),
        **initialize_twiss_pvs(builder, n_elements=len(NAMES)),
    })
    return view


def rec(view, name, prop):
    return view.process_variables[ReadCommand(name, prop)].get()


def image(view, name):
    return np.asarray(rec(view, name, "image")).reshape(GEOMETRY.height, GEOMETRY.width)


def test_screen_records_not_bpm_records():
    view = make_view(single_pass=False)
    assert ReadCommand("FOMZ1T", "image") in view.process_variables
    assert ReadCommand("BPMZ1T", "image") not in view.process_variables
    assert view.bpms == {"BPMZ1T"}, "screens are no BPMs"
    assert rec(view, "FOMZ1T", "image_width") == GEOMETRY.width


def test_line_on_its_own_screens_follow_trajectory_optics_and_emittance():
    view = make_view(single_pass=False)
    view.update_track(TRACK, track_package({"FOMZ1T": 1e-3, "BPMZ1T": 2e-3}))
    view.update_twiss(TWISS, twiss_package({"FOMZ1T": (10.0, 4.0)}))
    assert rec(view, "FOMZ1T", "x") == pytest.approx(1.0)
    assert rec(view, "FOMZ1T", "sigma_x") == pytest.approx(1.0), "sqrt(1e-7 m rad * 10 m) = 1 mm"
    assert rec(view, "FOMZ1T", "sigma_y") == pytest.approx(0.2)
    assert centre_and_size(image(view, "FOMZ1T"))[0] == pytest.approx((1.0, 0.0), abs=1e-6)
    assert rec(view, "BPMZ1T", "x") == pytest.approx(2.0), "BPMs as before"

    view.set_emittance("x", 4e-7)
    assert rec(view, "FOMZ1T", "sigma_x") == pytest.approx(2.0), "the emittance acts at once"


def test_single_pass_screens_show_the_beam_only_at_a_shot():
    view = make_view(single_pass=True)
    view.update_twiss(TWISS, twiss_package({"FOMZ1T": (10.0, 4.0)}))
    view.update_track(TRACK, track_package({"FOMZ1T": 1e-3}))
    view.set_emittance("x", 4e-7)
    assert not image(view, "FOMZ1T").any(), "no shot: dark"
    assert view.fire()
    assert rec(view, "FOMZ1T", "sigma_x") == pytest.approx(2.0)
    assert image(view, "FOMZ1T").sum() == pytest.approx(1.0, abs=1e-4), "4.5 sigma to the edge"

    view.update_track(TRACK, track_package({"FOMZ1T": -1e-3}))
    assert rec(view, "FOMZ1T", "x") == pytest.approx(1.0), "keeps the last shot"


def test_failed_calculation_dark_image():
    view = make_view(single_pass=True)
    view.update_twiss(TWISS, twiss_package({}))
    view.update_track(TRACK, track_package({"FOMZ1T": 1e-3}))
    asyncio.run(view.push_invalid())
    view.fire()
    assert not image(view, "FOMZ1T").any()
    assert math.isnan(rec(view, "FOMZ1T", "x"))


# --- a screen's mode (#76): out, observe, stop
MODE_MONITORS = ["FOMZ1T", "BPMZ1T", "FOMZ2T", "BPMZ2T"]


def mode_view(single_pass=False):
    builder = RecordingBuilder()
    view = TransferLineView(monitors=MODE_MONITORS, single_pass=single_pass, emittance={"x": 1e-7, "y": 1e-8},
                            screen=GEOMETRY, elements=MODE_MONITORS)
    view.update_process_variables({
        **initialize_monitor_pvs(MODE_MONITORS, builder=builder, geometry=GEOMETRY),
        **initialize_screen_mode_pvs(view, builder=builder),
        **initialize_artificial_screen_pvs(view, builder=builder, geometry=GEOMETRY),
        **initialize_orbit_pvs(builder, n_elements=len(MODE_MONITORS)),
        **initialize_twiss_pvs(builder, n_elements=len(MODE_MONITORS)),
    })
    track = [SimpleNamespace(x=1e-3, y=0.0, fam_name=n, uid=f"{n}:0") for n in MODE_MONITORS]
    view.update_twiss(TWISS, SimpleNamespace(readings=[SimpleNamespace(payload=SimpleNamespace(twiss=[
        SimpleNamespace(fam_name=n, uid=f"{n}:0", x=SimpleNamespace(beta=10.0, alpha=0.0, nu=0.0),
                        y=SimpleNamespace(beta=4.0, alpha=0.0, nu=0.0)) for n in MODE_MONITORS
    ]))]))
    view.update_track(TRACK, SimpleNamespace(readings=[SimpleNamespace(payload=SimpleNamespace(track=track))]))
    return view, builder


def sees_beam(view, name):
    return math.isfinite(rec(view, name, "x"))


def test_observe_by_default_the_beam_passes():
    view, builder = mode_view()
    assert builder.records["FOMZ1T:mode"].value == ScreenMode.OBSERVE
    assert all(sees_beam(view, m) for m in MODE_MONITORS)
    assert image(view, "FOMZ1T").any() and not view.beam_stopped()


def test_out_no_image_the_beam_passes():
    view, _ = mode_view()
    view.set_screen_mode("FOMZ1T", ScreenMode.OUT)
    assert not image(view, "FOMZ1T").any() and math.isnan(rec(view, "FOMZ1T", "sigma_x"))
    assert all(sees_beam(view, m) for m in MODE_MONITORS[1:]), "acts at once, the beam passes"
    assert not view.beam_stopped()


def test_stop_the_monitors_after_it_see_no_beam():
    view, _ = mode_view()
    view.set_screen_mode("FOMZ1T", ScreenMode.STOP)
    assert sees_beam(view, "FOMZ1T") and image(view, "FOMZ1T").any(), "the screen itself sees the beam"
    for name in MODE_MONITORS[1:]:
        assert not sees_beam(view, name), name
    assert not image(view, "FOMZ2T").any()
    assert view.beam_stopped()
    # the model is not changed: the beam stops, the trajectory is the same
    assert math.isfinite(rec(view, "beam", "x")[-1])
    view.set_screen_mode("FOMZ1T", ScreenMode.OBSERVE)
    assert all(sees_beam(view, m) for m in MODE_MONITORS)


def test_the_mode_pv_sets_it():
    made = {}

    class Builder:
        def mbbOut(self, name, *states, **kwargs):
            made[name] = (states, kwargs)

    view = TransferLineView(monitors=MODE_MONITORS, single_pass=True)
    initialize_screen_mode_pvs(view, builder=Builder())
    assert set(made) == {"FOMZ1T:mode", "FOMZ2T:mode"}
    states, kwargs = made["FOMZ2T:mode"]
    assert states == ("Out", "Observe", "Stop")
    kwargs["on_update"](2)
    assert view.screen_mode["FOMZ2T"] == ScreenMode.STOP and view.beam_stopped()
    with pytest.raises(ValueError):
        view.set_screen_mode("BPMZ1T", ScreenMode.STOP)


def test_single_pass_a_mode_acts_at_the_next_shot():
    view, _ = mode_view(single_pass=True)
    assert view.fire()
    view.set_screen_mode("FOMZ1T", ScreenMode.STOP)
    assert sees_beam(view, "BPMZ2T"), "no shot yet: the last one"
    assert view.fire()
    assert not sees_beam(view, "BPMZ2T")



# --- the artificial screen (#76): a screen at any element of the line
def test_artificial_screen_nowhere_and_out_at_start():
    view, builder = mode_view()
    assert builder.records["screen:mode"].value == ScreenMode.OUT and builder.records["screen:element"].value == ""
    assert math.isnan(rec(view, "screen", "x")) and not image(view, "screen").any()
    assert all(sees_beam(view, m) for m in MODE_MONITORS)


def test_artificial_screen_observes_at_an_element():
    view, _ = mode_view()
    view.set_artificial_screen("BPMZ1T")
    assert math.isnan(rec(view, "screen", "x")), "still out"
    view.set_artificial_screen_mode(ScreenMode.OBSERVE)
    assert rec(view, "screen", "x") == pytest.approx(1.0)
    assert rec(view, "screen", "sigma_x") == pytest.approx(1.0), "sqrt(1e-7 m rad * 10 m) = 1 mm"
    assert image(view, "screen").sum() == pytest.approx(1.0, abs=1e-3)
    assert all(sees_beam(view, m) for m in MODE_MONITORS) and not view.beam_stopped()


def test_artificial_screen_stops_the_beam():
    view, _ = mode_view()
    view.set_artificial_screen("BPMZ1T")
    view.set_artificial_screen_mode(ScreenMode.STOP)
    assert sees_beam(view, "FOMZ1T") and sees_beam(view, "BPMZ1T"), "before it and at it"
    assert not sees_beam(view, "FOMZ2T") and not sees_beam(view, "BPMZ2T"), "after it"
    assert view.beam_stopped()
    view.set_artificial_screen(None)
    assert all(sees_beam(view, m) for m in MODE_MONITORS) and not view.beam_stopped(), "nowhere: no stop"


def test_artificial_screen_unknown_element_rejected():
    made = {}

    class Builder(RecordingBuilder):
        def stringOut(self, name, **kwargs):
            made[name] = kwargs
            return RecordingBuilder.__getattr__(self, "stringOut")(name, **kwargs)

    view = TransferLineView(monitors=MODE_MONITORS, single_pass=True, elements=MODE_MONITORS)
    initialize_artificial_screen_pvs(view, builder=Builder(), geometry=GEOMETRY)
    validate = made["screen:element"]["validate"]
    assert validate(None, "BPMZ2T") and validate(None, "") and not validate(None, "NOPE")
    with pytest.raises(ValueError, match="NOPE"):
        view.set_artificial_screen("NOPE")
    assert view.artificial_element is None
