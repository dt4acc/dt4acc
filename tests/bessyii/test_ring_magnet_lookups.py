"""BESSY II storage ring: every magnet and supply of the device database has its
lookups (#83)

* a steerer's own value (``Cm:set`` / ``Cm:rdbk``: ``main_strength`` /
  ``main_strength_rdbk``) reaches the lattice and reads back
* the S1 sextupoles (S1MD1R ... S1MT8R) and their supply S1PR are known to
  the liaison manager and the translation service
"""
import asyncio
import json
from importlib import resources

import pytest

from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc.custom_facility.bessyii.liasion_translator_setup import load_managers
from dt4acc.custom_facility.bessyii.provide_lattice import provide_backend_encapsulating_lattice
from dt4acc_lib.bl.command_rewritter import CommandRewriter
from dt4acc_lib.model.utils.command import Command, ReadCommand

DEVICE_DB = ("custom_epics", "data", "standard", "accelerator_setup.json")
S1_MAGNETS = [f"S1M{dt}{n}R" for n in range(1, 9) for dt in ("D", "T")]


def device_db():
    with open(resources.files("dt4acc").joinpath(*DEVICE_DB), "rt") as fp:
        return json.load(fp)


@pytest.fixture
def twin():
    backend = provide_backend_encapsulating_lattice()
    _, lm, ts, _ = load_managers()
    mexec = TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=CommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )
    return backend, mexec


def read(mexec, dev, prop):
    """one value per lattice element behind the device (a supply: per magnet it
    drives; the PVs average them): they have to agree"""
    pkg = asyncio.run(mexec.trigger_read([ReadCommand(dev, prop)]))
    values = [r.payload for r in pkg.all_readings()]
    assert values and all(v == pytest.approx(values[0], rel=1e-12) for v in values), (dev, prop, values)
    return values[0]


def write(mexec, dev, prop, value):
    asyncio.run(mexec.set([Command(dev, prop, value, None)]))


def element(backend, name):
    (elem,) = [e for e in backend.acc.acc if e.FamName == name]
    return elem


def test_every_magnet_of_the_device_database_reads_its_own_value(twin) -> None:
    """``Cm:set`` and ``Cm:rdbk`` of every quadrupole, sextupole and steerer"""
    _, mexec = twin
    missing = []
    for magnet in device_db():
        if magnet["type"] not in ("Quadrupole", "Sextupole", "Steerer"):
            continue
        for prop in ("main_strength", "main_strength_rdbk"):
            try:
                read(mexec, magnet["name"], prop)
            except KeyError:
                missing.append((magnet["name"], prop))
    assert not missing, f"{len(missing)} without a lookup, e.g. {missing[:4]}"


def test_every_supply_of_the_device_database_reads_its_current(twin) -> None:
    _, mexec = twin
    missing = []
    for pc in sorted({m["pc"] for m in device_db() if m["type"] in ("Quadrupole", "Sextupole", "Steerer")}):
        for prop in ("set_current", "rdbk_current"):
            try:
                read(mexec, pc, prop)
            except KeyError:
                missing.append((pc, prop))
    assert not missing, f"{len(missing)} without a lookup, e.g. {missing[:4]}"


@pytest.mark.parametrize("steerer, host, plane", [("HS4M2D1R", "S4M2D1R", 0), ("VS2M1T1R", "S2M1T1R", 1)])
def test_steerer_magnet_value_reaches_the_lattice_and_reads_back(twin, steerer, host, plane) -> None:
    """a steerer's Cm:set (main_strength) sets its host's kick; Cm:rdbk follows"""
    backend, mexec = twin
    before = read(mexec, steerer, "main_strength")
    target = before + 1e-4
    write(mexec, steerer, "main_strength", target)
    assert read(mexec, steerer, "main_strength_rdbk") == pytest.approx(target, rel=1e-12)
    assert read(mexec, steerer, "main_strength") == pytest.approx(target, rel=1e-12)
    assert element(backend, host).KickAngle[plane] != 0.0
    assert element(backend, host).KickAngle[1 - plane] == 0.0


def test_s1_supply_drives_the_16_s1_sextupoles(twin) -> None:
    """S1PR drives S1MD1R ... S1MT8R: all 16 follow its current, the others not"""
    backend, mexec = twin
    assert sorted(m["name"] for m in device_db() if m["pc"] == "S1PR") == sorted(S1_MAGNETS)
    current = read(mexec, "S1PR", "rdbk_current")
    h_before = {name: element(backend, name).H for name in S1_MAGNETS}
    s2_before = element(backend, "S2M2D1R").H
    write(mexec, "S1PR", "set_current", current * 1.01)
    assert read(mexec, "S1PR", "rdbk_current") == pytest.approx(current * 1.01, rel=1e-12)
    for name in S1_MAGNETS:
        assert element(backend, name).H == pytest.approx(h_before[name] * 1.01, rel=1e-12), name
        assert read(mexec, name, "main_strength_rdbk") == pytest.approx(element(backend, name).H, rel=1e-12)
    assert element(backend, "S2M2D1R").H == s2_before


def test_supply_current_converts_with_the_beams_brho(twin) -> None:
    """K = slope * I / brho with the brho of the lattice's energy (1.7185 GeV: 5.7323 T m)"""
    import yaml
    from dt4acc.custom_facility.bessyii.liasion_translator_setup import design_brho

    backend, mexec = twin
    brho = backend.acc.acc.BRho
    assert design_brho() == pytest.approx(brho, rel=1e-12)
    assert brho == pytest.approx(5.7323, abs=1e-4)
    with open(resources.files("dt4acc").joinpath(
            "custom_facility", "bessyii", "resources", "storage_ring", "input", "magnets.yaml"), "rt") as fp:
        slopes = {m["elem_id"]: m["conversion"]["slope"] for m in yaml.safe_load(fp)}
    for magnet, pc in (("Q1M2D1R", "Q1PDR"), ("S1MD1R", "S1PR")):
        current = read(mexec, pc, "set_current")
        k = element(backend, magnet).PolynomB[1 if magnet.startswith("Q") else 2]
        assert k == pytest.approx(slopes[magnet] * current / brho, rel=1e-12), magnet
