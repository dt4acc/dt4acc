"""Transfer line -> ring: the hand over against plain pyAT tracking"""
import asyncio

import at
import numpy as np
import pytest

pytest.importorskip("lat2db.tools.pyat.bessy2_TL_reflat")

from dt4acc.custom_facility.bessyii.provide_lattice import provide_lattice  # noqa: E402
from dt4acc.custom_facility.bessyii_injection.handover import (  # noqa: E402
    INJECTION_ELEMENT,
    InjectionHandover,
    no_offset,
    to_ring,
)
from dt4acc.custom_facility.bessytl.twin_setup import bessytl_lattice, load_twiss_in  # noqa: E402
from dt4acc_lib.model.output.track import ParticleState  # noqa: E402
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator  # noqa: E402
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend  # noqa: E402

SEPTUM = "SEK2D1R"
GEOMETRY = ParticleState.from_sequence([-2e-3, 1e-4, 0.0, 0.0, 0.0, 0.0])


@pytest.fixture(scope="module")
def ring_lattice():
    return provide_lattice()


def monitors(ring):
    return [e.FamName for e in ring if isinstance(e, at.Monitor) and e.FamName.startswith("BPMZ")]


def handover(ring_lattice, kicks=None, geometry=GEOMETRY, n_turns=3):
    line = bessytl_lattice(end_after=SEPTUM)
    for name, angles in (kicks or {}).items():
        (elem,) = [e for e in line if e.FamName == name]
        elem.KickAngle = np.array(angles, dtype=float)
    tl = SimulatorBackend(name="tl", acc=PyATAcceleratorSimulator(at_lattice=line, twiss_in=load_twiss_in()))
    ring = SimulatorBackend(name="ring", acc=PyATAcceleratorSimulator(at_lattice=ring_lattice))
    h = InjectionHandover(line=tl, ring=ring, monitors=monitors(ring_lattice), geometry=geometry, n_turns=n_turns)
    return h, line


def reference(line, ring, geometry, n_turns):
    """Plain pyAT: track the entering centroid through the line, then the ring from the septum exit"""
    x0 = np.array(load_twiss_in().closed_orbit, dtype=float).reshape(6, 1)
    out, *_ = line.track(x0.copy(), refpts=len(line), nturns=1)
    exit_state = out[:, 0, 0, 0]
    injected = exit_state + geometry.as_array()
    (idx,) = [i for i, e in enumerate(ring) if e.FamName == INJECTION_ELEMENT]
    rotated = ring.rotate(idx)
    names = monitors(ring)
    refpts = [i for i, e in enumerate(rotated) if e.FamName in names]
    order = [rotated[i].FamName for i in refpts]
    out, *_ = rotated.track(injected.reshape(6, 1).copy(), refpts=refpts, nturns=n_turns)
    x = {name: out[0, 0, k, :] for k, name in enumerate(order)}
    y = {name: out[2, 0, k, :] for k, name in enumerate(order)}
    return exit_state, injected, x, y


def test_geometry_is_a_difference_state() -> None:
    line_state = ParticleState.from_sequence([1e-3, 2e-4, -5e-4, 1e-4, 1e-3, 0.0])
    np.testing.assert_allclose(to_ring(line_state, GEOMETRY).as_array(), line_state.as_array() + GEOMETRY.as_array())
    np.testing.assert_allclose(to_ring(line_state, no_offset()).as_array(), line_state.as_array())


@pytest.mark.parametrize(
    "kicks, geometry",
    [
        (None, GEOMETRY),
        ({"H5MT": [3e-4, 0.0], "V6MT": [0.0, -2e-4]}, GEOMETRY),
        # an energy offset of the injected beam (delta)
        ({"H5MT": [3e-4, 0.0]}, ParticleState.from_sequence([-2e-3, 1e-4, 0.0, 0.0, 2e-3, 0.0])),
    ],
)
def test_injected_turns_match_plain_pyat(ring_lattice, kicks, geometry) -> None:
    h, line = handover(ring_lattice, kicks, geometry=geometry)
    result = asyncio.run(h.compute())
    exit_state, injected, x_ref, y_ref = reference(line, ring_lattice, geometry, h.n_turns)
    np.testing.assert_allclose(result.line_exit.as_array(), exit_state, atol=1e-14)
    np.testing.assert_allclose(result.injected.as_array(), injected, atol=1e-14)
    x, y = result.x(), result.y()
    assert x.shape == (h.n_turns, len(result.monitors))
    for k, name in enumerate(result.monitors):
        np.testing.assert_allclose(x[:, k], x_ref[name], atol=1e-12, err_msg=name)
        np.testing.assert_allclose(y[:, k], y_ref[name], atol=1e-12, err_msg=name)
    assert result.survived()[-1] == 1


def test_line_steering_moves_the_injected_beam(ring_lattice) -> None:
    straight = asyncio.run(handover(ring_lattice)[0].compute())
    steered = asyncio.run(handover(ring_lattice, {"H5MT": [3e-4, 0.0]})[0].compute())
    assert straight.line_exit.x == pytest.approx(0.0, abs=1e-15)
    assert abs(steered.line_exit.x) > 1e-4
    assert not np.allclose(steered.x()[0], straight.x()[0])
