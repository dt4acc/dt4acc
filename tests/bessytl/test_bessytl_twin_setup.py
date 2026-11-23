"""BESSY II transfer line twin: supplies -> magnets -> trajectory, without EPICS"""
import asyncio
import math

import at
import numpy as np
import pytest

pytest.importorskip("lat2db.tools.pyat.bessy2_TL_reflat")

from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine  # noqa: E402
from dt4acc.custom_facility.bessytl.twin_setup import (  # noqa: E402
    BRHO,
    bend_field_error,
    bessytl_lattice,
    build_managers,
    calibration,
    load_accelerator_setup,
    load_operating_currents,
    load_twiss_in,
    monitor_names,
    slope,
)
from dt4acc_lib.bl.command_rewritter import CommandRewriter  # noqa: E402
from dt4acc_lib.model.utils.command import Command, ReadCommand  # noqa: E402
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator  # noqa: E402
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend  # noqa: E402

SETUP = {m["name"]: m for m in load_accelerator_setup()}
PC_OF = {m["name"]: m["pc"] for m in SETUP.values()}


@pytest.fixture
def twin():
    twiss_in = load_twiss_in()
    backend = SimulatorBackend(
        name="tl", acc=PyATAcceleratorSimulator(at_lattice=bessytl_lattice(), twiss_in=twiss_in)
    )
    lm, ts = build_managers()
    mexec = TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=CommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )
    return backend, mexec


def read(mexec, dev, prop):
    pkg = asyncio.run(mexec.trigger_read([ReadCommand(dev, prop)]))
    return [r.payload for r in pkg.all_readings()]


def write(mexec, dev, prop, value):
    asyncio.run(mexec.set([Command(dev, prop, value, None)]))


def element(backend, name):
    (elem,) = [e for e in backend.acc.acc if e.FamName == name]
    return elem


def reference_trajectory(kicks):
    """Plain pyAT: same lattice, same currents, steerer kicks [rad]; x, y at monitors"""
    line = bessytl_lattice()
    for name, (plane, kick) in kicks.items():
        (elem,) = [e for e in line if e.FamName == name]
        angles = np.array(elem.KickAngle, dtype=float)
        angles[0 if plane == "x" else 1] = kick
        elem.KickAngle = angles
    _, _, ed = line.get_optics(at.All, twiss_in=load_twiss_in().as_at())
    idx = line.get_uint32_index(at.Monitor)
    return {line[i].FamName: (ed.closed_orbit[i, 0], ed.closed_orbit[i, 2]) for i in idx}


def test_line_shape() -> None:
    line = bessytl_lattice()
    assert len(line) == 97
    assert monitor_names(line)[0] == "FOMZ1T"
    assert monitor_names(line)[-1] == "FOMZ2D1R"
    assert len(monitor_names(line)) == 17
    # every magnet of the setup is in the lattice
    names = {e.FamName for e in line}
    assert set(SETUP) <= names


def test_supplies_start_at_operating_currents(twin) -> None:
    _, mexec = twin
    for pc, current in load_operating_currents().items():
        # one reading per magnet it drives (B1PT: two)
        values = read(mexec, pc, "set_current")
        assert values == pytest.approx([current] * len(values), rel=1e-12), pc
    (value,) = read(mexec, "H1PT", "set_current")
    assert value == pytest.approx(0.0, abs=1e-12)


def test_supply_current_sets_quadrupole(twin) -> None:
    backend, mexec = twin
    write(mexec, "Q12PT", "set_current", 70.0)
    assert element(backend, "Q12MT").K == pytest.approx(slope(SETUP["Q12MT"]) * 70.0 / BRHO, rel=1e-12)
    (value,) = read(mexec, "Q12PT", "rdbk_current")
    assert value == pytest.approx(70.0, rel=1e-12)


@pytest.mark.parametrize("steerer, plane", [("H3MT", 0), ("V5MT", 1)])
def test_supply_current_sets_steerer(twin, steerer, plane) -> None:
    backend, mexec = twin
    write(mexec, PC_OF[steerer], "set_current", 1.5)
    # the setup gives the kick per current: 1.5 A -> 1.5 * magnetic_strength rad
    kick = element(backend, steerer).KickAngle[plane]
    assert kick == pytest.approx(1.5 * SETUP[steerer]["magnetic_strength"], rel=1e-12)
    assert element(backend, steerer).KickAngle[1 - plane] == 0.0


BENDS = ("B1M1T", "B1M2T", "B2MT")


def test_bends_start_at_their_design_angle(twin) -> None:
    """at the operating currents the bends bend as designed: no field error"""
    backend, mexec = twin
    assert PC_OF["B1M1T"] == PC_OF["B1M2T"] == "B1PT" and PC_OF["B2MT"] == "B2PT"
    currents = load_operating_currents()
    for name in BENDS:
        assert currents[PC_OF[name]] == SETUP[name]["reference_current"], name
        assert element(backend, name).PolynomB[0] == pytest.approx(0.0, abs=1e-15), name
        assert not np.any(getattr(element(backend, name), "KickAngle", np.zeros(2))), "no kick on a bend"
        (angle,) = read(mexec, name, "main_strength")
        assert angle == pytest.approx(element(backend, name).BendingAngle, rel=1e-12), name


def test_supply_current_sets_its_bends_field(twin) -> None:
    """B1PT drives B1M1T and B1M2T: PolynomB[0] = t_f (I - I_ref) / brho, more current bends more"""
    backend, mexec = twin
    write(mexec, "B1PT", "set_current", 233.0)
    for name in ("B1M1T", "B1M2T"):
        m = SETUP[name]
        b0 = element(backend, name).PolynomB[0]
        assert b0 == pytest.approx(m["magnetic_strength"] * (233.0 - m["reference_current"]) / BRHO, rel=1e-12)
        assert b0 > 0.0
        assert element(backend, name).BendingAngle == m["bending_angle"], "the geometry stays the design's"
        (angle,) = read(mexec, name, "main_strength_rdbk")
        assert angle == pytest.approx(m["bending_angle"] + m["length"] * b0, rel=1e-12), "its own value: the bending angle"
        assert angle == pytest.approx(m["bending_angle"] * 233.0 / m["reference_current"], rel=1e-12), "linear in I"
    assert element(backend, "B2MT").PolynomB[0] == 0.0, "B2PT unchanged"
    assert read(mexec, "B1PT", "rdbk_current") == pytest.approx([233.0, 233.0], rel=1e-12)


def test_bend_change_moves_the_trajectory_as_a_field_error(twin) -> None:
    """the twin after B2PT +1 % against plain pyAT with B2MT's field 1 % up (PolynomB[0])"""
    backend, mexec = twin
    write(mexec, "B2PT", "set_current", 1.486 * 1.01)
    line = bessytl_lattice()
    (b2,) = [e for e in line if e.FamName == "B2MT"]
    b2.PolynomB[0] = b2.BendingAngle * 0.01 / b2.Length
    _, _, ed = line.get_optics(at.All, twiss_in=load_twiss_in().as_at())
    _, _, twin_ed = backend.acc.acc.get_optics(at.All, twiss_in=load_twiss_in().as_at())
    idx = line.get_uint32_index(at.Monitor)
    np.testing.assert_allclose(twin_ed.closed_orbit[idx, 0], ed.closed_orbit[idx, 0], rtol=1e-9, atol=1e-12)
    assert np.abs(ed.closed_orbit[idx, 0]).max() > 1e-4, "B2PT +1 % moves the beam at the monitors"


@pytest.mark.parametrize("name", BENDS)
@pytest.mark.parametrize("energy_ratio", (1.0, 0.9, 1.05))
def test_bend_calibration_follows_the_energy(name, energy_ratio) -> None:
    """the reference current scales with brho: at any energy I_ref gives the design angle,
    and the calibration (current <- PolynomB[0]) inverts bend_field_error"""
    m, brho = SETUP[name], BRHO * energy_ratio
    i_ref = m["reference_current"] * energy_ratio
    assert bend_field_error(m, i_ref, brho) == pytest.approx(0.0, abs=1e-15)
    c0, c1 = calibration(m).coeffs
    assert calibration(m).energy_dependent
    for current in (0.9 * i_ref, i_ref, 1.1 * i_ref):
        b0 = bend_field_error(m, current, brho)
        assert brho * (c0 + c1 * b0) == pytest.approx(current, rel=1e-12)
    # the design field: t_f * I_ref = brho * angle / length, at every energy
    assert m["magnetic_strength"] * i_ref == pytest.approx(brho * m["bending_angle"] / m["length"], rel=1e-12)


def test_magnets_read_back_in_lattice_units(twin) -> None:
    _, mexec = twin
    write(mexec, "Q3PT", "set_current", 30.0)
    write(mexec, "V4PT", "set_current", 0.7)
    (k,) = read(mexec, "Q3MT", "main_strength_rdbk")
    assert k == pytest.approx(slope(SETUP["Q3MT"]) * 30.0 / BRHO, rel=1e-12)
    (kick,) = read(mexec, "V4MT", "main_strength")
    assert kick == pytest.approx(0.7 * SETUP["V4MT"]["magnetic_strength"], rel=1e-12)
    (current,) = read(mexec, "Q3PT", "rdbk_current")
    assert current == pytest.approx(30.0, rel=1e-12)


def test_trajectory_matches_plain_pyat(twin) -> None:
    backend, mexec = twin
    write(mexec, "H1PT", "set_current", 0.2)
    write(mexec, "V2PT", "set_current", -0.3)
    (track,) = read(mexec, "track", "pos")
    got = {p.fam_name: (p.x, p.y) for p in track.track}
    expected = reference_trajectory({
        "H1MT": ("x", 0.2 * SETUP["H1MT"]["magnetic_strength"]),
        "V2MT": ("y", -0.3 * SETUP["V2MT"]["magnetic_strength"]),
    })
    for name, (x, y) in expected.items():
        assert got[name][0] == pytest.approx(x, abs=1e-12), name
        assert got[name][1] == pytest.approx(y, abs=1e-12), name
    # monitors before H1MT see nothing, the end of the line does
    assert got["FOMZ1T"] == (0.0, 0.0)
    assert abs(got["FOMZ7T"][0]) > 1e-4
    assert abs(got["FOMZ7T"][1]) > 1e-4


def test_line_has_no_tune(twin) -> None:
    backend, _ = twin
    tune = asyncio.run(backend.read("tune", "transversal"))
    assert math.isnan(tune.x) and math.isnan(tune.y)
