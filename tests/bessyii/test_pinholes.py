"""Pinhole cameras: beam centre, size and image at the source points (#79)"""
import asyncio
import math

import at
import numpy as np
import pytest
# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.core.bl.pinhole import PinholeCamera, RingPinholes, _map_to
from dt4acc.custom_epics.ioc.pinhole_pvs import PinholePVs, hook_pinholes
from dt4acc.custom_facility.bessyii.pinholes import EMITTANCE, ENERGY_SPREAD, PINHOLES, ring_pinholes
from dt4acc.custom_facility.bessyii.provide_lattice import provide_backend_encapsulating_lattice
from tests.recording_builder import RecordingBuilder


@pytest.fixture
def backend():
    return provide_backend_encapsulating_lattice()


def optics_in_split_lattice(lattice, camera):
    """reference: pyAT's optics of the ring with the dipole split at the source point"""
    ring = lattice.deepcopy()
    (i,) = ring.get_uint32_index(camera.element)
    f = camera.offset / ring[i].Length
    ring[i:i + 1] = ring[i].divide([f, 1 - f])
    _, _, data = ring.get_optics(at.All)
    return data[i + 1]


def kick(backend, name, kx, ky):
    async def both():
        for plane, value in (("x_kick", kx), ("y_kick", ky)):
            await backend.set(name, plane, value)
    asyncio.run(both())


def assert_as_split_lattice(backend, pinholes):
    spots = pinholes.compute()
    for camera in PINHOLES:
        d, spot = optics_in_split_lattice(backend.acc.acc, camera), spots[camera.name]
        # the split changes the dipole's integration steps, and so the ring's
        # closed orbit itself (some 10 nm); the propagation: the next test
        assert spot.x == pytest.approx(d["closed_orbit"][0], abs=1e-7)
        assert spot.y == pytest.approx(d["closed_orbit"][2], abs=1e-7)
        for k, (plane, sigma) in enumerate((("x", spot.sigma_x), ("y", spot.sigma_y))):
            expected = math.sqrt(EMITTANCE[plane] * d["beta"][k] + (d["dispersion"][2 * k] * ENERGY_SPREAD) ** 2)
            assert sigma == pytest.approx(expected, rel=1e-3), (camera.name, plane)


def test_spot_is_that_of_the_lattice_split_at_the_source_point(backend):
    assert_as_split_lattice(backend, ring_pinholes(backend))


@pytest.mark.parametrize("camera", PINHOLES, ids=lambda c: c.name)
def test_orbit_propagates_exactly_to_the_source_point(backend, camera):
    """from the split ring's own closed orbit at the dipole's entrance"""
    ring = backend.acc.acc.deepcopy()
    (i,) = ring.get_uint32_index(camera.element)
    dipole = ring[i]
    f = camera.offset / dipole.Length
    ring[i:i + 1] = dipole.divide([f, 1 - f])
    _, _, data = ring.get_optics(at.All)
    orbit, _ = _map_to(dipole, camera.offset, np.array(data.closed_orbit[i]), ring.energy)
    assert orbit[:4] == pytest.approx(data.closed_orbit[i + 1][:4], abs=1e-11)


def test_spot_follows_the_closed_orbit_and_optics(backend):
    pinholes = ring_pinholes(backend)
    before = pinholes.compute()
    kick(backend, "S4M2D1R", 1e-4, 5e-5)
    assert_as_split_lattice(backend, pinholes)
    after = pinholes.compute()
    assert abs(after["PINH3FD2L"].x - before["PINH3FD2L"].x) > 1e-6
    assert abs(after["PINH3FD2L"].y - before["PINH3FD2L"].y) > 1e-6


def test_emittance_and_energy_spread_are_those_of_the_lattice(backend):
    p = backend.acc.acc.radiation_parameters()
    assert EMITTANCE["x"] == pytest.approx(p.emittances[0], rel=2e-3)
    assert ENERGY_SPREAD == pytest.approx(p.sigma_e, rel=2e-3)


def test_set_emittance_and_energy_spread(backend):
    pinholes = ring_pinholes(backend)
    pinholes.energy_spread = 0.0
    before = pinholes.compute()["PINH3FD2L"]
    pinholes.set_emittance("y", 4 * EMITTANCE["y"])
    after = pinholes.compute()["PINH3FD2L"]
    assert after.sigma_y == pytest.approx(2 * before.sigma_y, rel=1e-9)
    assert after.sigma_x == before.sigma_x
    for bad in (-1e-9, math.nan):
        with pytest.raises(ValueError):
            pinholes.set_emittance("x", bad)
        with pytest.raises(ValueError):
            pinholes.energy_spread = bad


@pytest.mark.parametrize("camera", [PinholeCamera("P", "NOT_THERE", 0.0), PinholeCamera("P", "BM2D2R", 1.0)])
def test_source_point_has_to_be_in_the_lattice(backend, camera):
    with pytest.raises(ValueError):
        RingPinholes(backend, [camera], emittance=EMITTANCE, energy_spread=0.0)


def test_source_point_at_the_ends_of_the_element(backend):
    cameras = [PinholeCamera("start", "BM2D2R", 0.0), PinholeCamera("end", "BM2D2R", 0.855)]
    spots = RingPinholes(backend, cameras, emittance=EMITTANCE, energy_spread=0.0).compute()
    (i,) = backend.acc.acc.get_uint32_index("BM2D2R")
    _, _, data = backend.acc.acc.get_optics(at.All)
    for name, k in (("start", i), ("end", i + 1)):
        assert spots[name].sigma_x == pytest.approx(math.sqrt(EMITTANCE["x"] * data.beta[k, 0]), rel=1e-3)


def test_pvs(backend):
    builder = RecordingBuilder()
    pvs = PinholePVs(ring_pinholes(backend), builder=builder)
    pvs.update()
    spot = pvs.pinholes.compute()["PINH9FD5L"]
    value = lambda name: builder.records[name].get()  # noqa: E731
    assert value("PINH9FD5L:rdCenterX") == pytest.approx(spot.x * 1e3)
    assert value("PINH9FD5L:rdSigmaX") == pytest.approx(spot.sigma_x * 1e3)
    assert value("PINH9FD5L:rdSigmaY") == pytest.approx(spot.sigma_y * 1e3)
    image = np.asarray(value("PINH9FD5L:image"))
    assert image.size == value("PINH9FD5L:image:width") * value("PINH9FD5L:image:height")
    assert image.sum() == pytest.approx(1.0, abs=1e-9), "the whole beam in view"


def test_no_closed_orbit_nan_and_dark_image(backend, monkeypatch):
    builder = RecordingBuilder()
    pvs = PinholePVs(ring_pinholes(backend), builder=builder)
    monkeypatch.setattr(backend, "get_optics", lambda: ([], [], None))
    pvs.update()
    assert math.isnan(builder.records["PINH3FD2L:rdSigmaX"].get())
    assert not np.asarray(builder.records["PINH3FD2L:image"].get()).any()


def test_view_updates_trigger_the_cameras():
    class View:
        def __init__(self):
            self.tracks = []

        def update_track(self, var, pkg):
            self.tracks.append(pkg)

    class Pinholes:
        n = 0

        def trigger(self):
            self.n += 1

    view, pinholes = View(), Pinholes()
    hook_pinholes(view, pinholes)
    view.update_track("track", "data")
    assert view.tracks == ["data"] and pinholes.n == 1
