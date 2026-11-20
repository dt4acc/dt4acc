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
from dt4acc.custom_facility.bessytl.view import TRACK, TWISS, TransferLineView, initialize_monitor_pvs
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
