"""Readings are converted back to the device property that was asked for

One supply PC1 drives two quadrupoles QA and QB. Reading a magnet's strength
must give its K, not the current of the supply the forward lookup leads to.
"""
import asyncio
import logging

import at
import numpy as np
import pytest

from dt4acc.core.bl.translating_command_execution_engine import TranslatingCommandExecutionEngine
from dt4acc_lib.bl.command_rewritter import CommandRewriter
from dt4acc_lib.bl.liaison_manager import LiaisonManager
from dt4acc_lib.bl.translator_service import TranslatorService
from dt4acc_lib.model.utils.command import Command, ReadCommand
from dt4acc_lib.model.utils.identifiers import ConversionID, DevicePropertyID, LatticeElementPropertyID
from dt4acc_lib.model.utils.liaison_manager_lookup_table import (
    LiaisonManagerForwardLookupElement,
    LiaisonManagerForwardLookupTable,
    LiaisonManagerInverseLookupElement,
    LiaisonManagerInverseLookupTable,
)
from dt4acc_lib.model.utils.translator_manager_lookup_table import (
    PolynomCoefficients,
    TranslatorLookupTable,
    TranslatorLookupTableElement,
)
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

BRHO = 5.0
#: K per A, already divided by brho: K = G * I / brho
G = 0.1
K_A, K_B = 0.8, 0.8


def ring() -> at.Lattice:
    cells = []
    for i in range(8):
        cells += [
            at.Drift("D", 0.5),
            at.Quadrupole("QA" if i == 0 else f"QF{i}", 0.3, K_A if i == 0 else 1.0),
            at.Drift("D", 0.5),
            at.Dipole(f"B{i}", 1.0, 2 * np.pi / 8),
            at.Drift("D", 0.5),
            at.Quadrupole("QB" if i == 0 else f"QD{i}", 0.3, K_B if i == 0 else -1.0),
            at.Drift("D", 0.5),
        ]
    lattice = at.Lattice(cells, name="ring", energy=1.5e9, periodicity=1)
    lattice.disable_6d()
    return lattice


def lat(name):
    return LatticeElementPropertyID(element_name=name, property="main_strength")


def dev(name, prop):
    return DevicePropertyID(device_name=name, property=prop)


def engine(*, with_rdbk_conversion: bool = True) -> TranslatingCommandExecutionEngine:
    per_current = PolynomCoefficients([0.0, 1.0 / G], energy_dependent=True)
    same = PolynomCoefficients([0.0, 1.0], energy_dependent=False)
    fwd, inv, conv = [], [], []
    for magnet in ("QA", "QB"):
        fwd.append(LiaisonManagerForwardLookupElement(lat_id=lat(magnet), dev_ids=[dev("PC1", "set_current")]))
        inv.append(LiaisonManagerInverseLookupElement(dev_id=dev(magnet, "main_strength"), lat_ids=[lat(magnet)]))
        inv.append(LiaisonManagerInverseLookupElement(dev_id=dev(magnet, "main_strength_rdbk"), lat_ids=[lat(magnet)]))
        conv.append(TranslatorLookupTableElement(ConversionID(lat(magnet), dev("PC1", "set_current")), per_current))
        conv.append(TranslatorLookupTableElement(ConversionID(lat(magnet), dev(magnet, "main_strength")), same))
        if with_rdbk_conversion:
            conv.append(TranslatorLookupTableElement(ConversionID(lat(magnet), dev(magnet, "main_strength_rdbk")), same))
    inv.append(LiaisonManagerInverseLookupElement(dev_id=dev("PC1", "set_current"), lat_ids=[lat("QA"), lat("QB")]))
    lm = LiaisonManager(
        forward_lut=LiaisonManagerForwardLookupTable(fwd), inverse_lut=LiaisonManagerInverseLookupTable(inv)
    )
    ts = TranslatorService(lut=TranslatorLookupTable(lut=conv), brho=BRHO)
    backend = SimulatorBackend(acc=PyATAcceleratorSimulator(at_lattice=ring()), name="ring")
    return TranslatingCommandExecutionEngine(
        backend=backend,
        cmd_rewriter=CommandRewriter(liaison_manager=lm, translation_service=ts),
        expected_view_for_output="device",
        num_readings=1,
    )


def read(mexec, *rcmds):
    return asyncio.run(mexec.trigger_read([ReadCommand(*r) for r in rcmds]))


def test_magnet_strength_reads_as_strength() -> None:
    mexec = engine()
    result = read(mexec, ("QA", "main_strength"))
    (reading,) = result.all_readings()
    assert reading.payload == pytest.approx(K_A)
    assert reading.cmd == ReadCommand("QA", "main_strength")


def test_supply_reads_as_current_for_each_magnet() -> None:
    mexec = engine()
    result = read(mexec, ("PC1", "set_current"))
    # one reading per magnet the supply drives, in that order
    assert len(result.data) == 2
    assert [r.payload for r in result.all_readings()] == pytest.approx([K_A * BRHO / G] * 2)
    assert {r.cmd for r in result.all_readings()} == {ReadCommand("PC1", "set_current")}


def test_strength_follows_supply_current() -> None:
    mexec = engine()
    asyncio.run(mexec.set([Command("PC1", "set_current", 10.0, None)]))
    result = read(mexec, ("QA", "main_strength"), ("QB", "main_strength_rdbk"), ("PC1", "set_current"))
    payloads = [r.payload for r in result.all_readings()]
    k = G * 10.0 / BRHO
    assert payloads == pytest.approx([k, k, 10.0, 10.0])
    # one translated reading per backend read, in the order asked for
    assert [t.cmd for t in result.data] == [
        ReadCommand("QA", "main_strength"), ReadCommand("QB", "main_strength"),
        ReadCommand("QA", "main_strength"), ReadCommand("QB", "main_strength"),
    ]


def test_missing_conversion_falls_back_to_forward_device(caplog) -> None:
    mexec = engine(with_rdbk_conversion=False)
    with caplog.at_level(logging.WARNING, logger="dt4acc"):
        result = read(mexec, ("QA", "main_strength_rdbk"))
    (reading,) = result.all_readings()
    # as before the fix: the value of the forward device (the supply current)
    assert reading.payload == pytest.approx(K_A * BRHO / G)
    assert reading.cmd == ReadCommand("PC1", "set_current")
    assert "no conversion" in caplog.text
