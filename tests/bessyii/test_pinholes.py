"""Pinhole cameras (#79): views of their element, the ring's view hands them
the orbit and optics there; beam centre, size sqrt(emittance beta) and image"""
import asyncio
import math
from types import SimpleNamespace

import numpy as np
import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.core.bl.beam_spot import CameraGeometry
from dt4acc.core.bl.pinhole import NO_BEAM, PinholeCamera, beam_spot
from dt4acc.custom_epics.ioc.pinhole_pvs import BeamEmittance, initialize_pinhole_pvs
from dt4acc.custom_epics.ioc.view import View
from dt4acc.custom_facility.bessyii.pinholes import EMITTANCE, PINHOLES
from dt4acc_lib.model.output.result import SingleReading, TranslatedReading
from dt4acc_lib.model.utils.command import ReadCommand

from tests.recording_builder import RecordingBuilder

GEOMETRY = CameraGeometry(width=50, height=40, pixel=0.05)
CAMERA = PinholeCamera("CAM1", element="B1", geometry=GEOMETRY)
NAMES = ["Q1", "B1", "Q2"]


# --- the spot
def test_beam_spot():
    spot = beam_spot(1e-4, -2e-4, {"x": 0.5, "y": 20.0}, {"x": 8e-9, "y": 2e-11})
    assert (spot.x, spot.y) == (1e-4, -2e-4)
    assert spot.sigma_x == pytest.approx(math.sqrt(8e-9 * 0.5))
    assert spot.sigma_y == pytest.approx(math.sqrt(2e-11 * 20.0))


def test_beam_spot_no_beam():
    spot = beam_spot(math.nan, math.nan, {"x": math.nan, "y": math.nan}, {"x": 8e-9, "y": 2e-11})
    assert all(math.isnan(v) for v in (spot.x, spot.y, spot.sigma_x, spot.sigma_y))


# --- a ring view hands the cameras their share
def reading(rcmd, payload):
    return TranslatedReading(rcmd, [SingleReading(cmd=rcmd, name="test", payload=payload)])


def orbit(x_at_b1):
    track = [SimpleNamespace(fam_name=n, uid=n, x=x_at_b1 if n == "B1" else 9.0, y=-x_at_b1 if n == "B1" else 9.0)
             for n in NAMES]
    return reading(ReadCommand("track", "pos"), SimpleNamespace(track=track))


def optics(beta_x_at_b1):
    def at(n):
        bx = beta_x_at_b1 if n == "B1" else 99.0
        return SimpleNamespace(fam_name=n, uid=n, x=SimpleNamespace(beta=bx, alpha=0.0, nu=0.0),
                               y=SimpleNamespace(beta=10.0, alpha=0.0, nu=0.0))
    return reading(ReadCommand("twiss", "parameters"), SimpleNamespace(twiss=[at(n) for n in NAMES]))


class Record:
    def __init__(self):
        self.value = None

    def set(self, value, *args, **kwargs):
        self.value = value

    def get(self):
        return self.value


@pytest.fixture
def ring():
    """a ring view with the records it fills, and one camera at B1"""
    view = View()
    view.update_process_variables({ReadCommand("beam", p): Record() for p in ("x", "y", "found", "names", "uids")})
    view.update_process_variables(
        {ReadCommand("twiss", f"{pl}:{p}"): Record() for pl in "xy" for p in ("beta", "alpha", "nu")}
    )
    view.update_process_variables({ReadCommand("twiss", p): Record() for p in ("names", "uids")})
    view.update_tune = lambda *args: None
    builder = RecordingBuilder()
    (camera,) = initialize_pinhole_pvs([CAMERA], {"x": 1e-8, "y": 1e-10}, builder=builder)
    view.add_element_views([camera])
    return view, camera, builder.records


def value(records, name):
    return records[f"CAM1:{name}"].get()


def test_no_data_yet_no_beam(ring):
    _, camera, records = ring
    assert camera.spot == NO_BEAM and math.isnan(value(records, "rdSigmaX"))


def test_the_camera_shows_the_orbit_and_optics_at_its_element(ring):
    view, camera, records = ring
    asyncio.run(view.dispatch(ReadCommand("track", "pos"), orbit(2e-4)))
    asyncio.run(view.dispatch(ReadCommand("twiss", "parameters"), optics(0.4)))
    assert value(records, "rdCenterX") == pytest.approx(0.2) and value(records, "rdCenterY") == pytest.approx(-0.2)
    assert value(records, "rdSigmaX") == pytest.approx(math.sqrt(1e-8 * 0.4) * 1e3)
    assert value(records, "rdSigmaY") == pytest.approx(math.sqrt(1e-10 * 10.0) * 1e3)
    image = np.asarray(value(records, "image")).reshape(GEOMETRY.height, GEOMETRY.width)
    assert image.sum() == pytest.approx(1.0, abs=1e-6)
    # a new orbit: the camera follows, with the optics it has
    asyncio.run(view.dispatch(ReadCommand("track", "pos"), orbit(-1e-4)))
    assert value(records, "rdCenterX") == pytest.approx(-0.1)
    assert value(records, "rdSigmaX") == pytest.approx(math.sqrt(1e-8 * 0.4) * 1e3)


def test_emittance_acts_at_once(ring):
    view, camera, records = ring
    asyncio.run(view.dispatch(ReadCommand("track", "pos"), orbit(0.0)))
    asyncio.run(view.dispatch(ReadCommand("twiss", "parameters"), optics(0.4)))
    assert "beam:emittance:x" in records
    camera.emittance.set("x", 4e-8)
    assert value(records, "rdSigmaX") == pytest.approx(math.sqrt(4e-8 * 0.4) * 1e3)


def test_no_closed_orbit_nan_and_dark_image(ring):
    view, camera, records = ring
    asyncio.run(view.dispatch(ReadCommand("track", "pos"), orbit(2e-4)))
    asyncio.run(view.dispatch(ReadCommand("twiss", "parameters"), optics(0.4)))
    # the calculation fails: the view publishes NaN
    asyncio.run(view.push_invalid())
    assert math.isnan(value(records, "rdCenterX")) and math.isnan(value(records, "rdSigmaX"))
    assert not np.asarray(value(records, "image")).any()


def test_emittance_finite_and_not_negative():
    beam = BeamEmittance({"x": 1e-8, "y": 1e-10})
    for bad in (-1e-9, math.nan):
        with pytest.raises(ValueError):
            beam.set("x", bad)
    assert beam.value["x"] == 1e-8


# --- BESSY II
def test_bessyii_cameras_at_the_dipoles_entrance_until_the_lattice_has_their_source_points():
    assert {(c.name, c.element) for c in PINHOLES} == {("PINH3FD2L", "BM2D2R"), ("PINH9FD5L", "BM2D5R")}


def test_bessyii_horizontal_emittance_is_that_of_the_lattice():
    from dt4acc.custom_facility.bessyii.provide_lattice import provide_backend_encapsulating_lattice

    p = provide_backend_encapsulating_lattice().acc.acc.radiation_parameters()
    assert EMITTANCE["x"] == pytest.approx(p.emittances[0], rel=2e-3)


def test_bessyii_pvs():
    builder = RecordingBuilder()
    cameras = initialize_pinhole_pvs(PINHOLES, EMITTANCE, builder=builder)
    assert [c.elements for c in cameras] == [["BM2D2R"], ["BM2D5R"]]
    names = set(builder.records)
    for camera in ("PINH3FD2L", "PINH9FD5L"):
        assert {f"{camera}:{f}" for f in ("rdCenterX", "rdCenterY", "rdSigmaX", "rdSigmaY", "image",
                                           "image:width", "image:height", "image:pixel")} <= names
    assert {"beam:emittance:x", "beam:emittance:y"} <= names and "beam:energy_spread" not in names
