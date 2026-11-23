"""Managers of the generic EPICS twin, built from the bundled FODO lattice/catalog

No IOC needed: checks the yellow pages, liaison manager and translator
service that ``run_epics_twin`` builds at startup.
"""

import os
from importlib import resources

import pytest
from dt4acc_lib.model.utils.identifiers import (
    ConversionID,
    DevicePropertyID,
    LatticeElementPropertyID,
)
from dt4acc_lib.model.utils.translator_manager_lookup_table import PolynomCoefficients

from dt4acc.config.data import querries
from dt4acc.core.bl.handle_lattice import LatticeLoader
from dt4acc.custom_facility.generic.liasion_translator_setup import load_managers
from dt4acc.custom_facility.model import at_integrated_strength

_RESOURCES = resources.files("dt4acc").joinpath("custom_facility/generic/resources")


def _build(integrated_strength: bool):
    previous = querries.get_data_file()
    previous_env = os.environ.pop(at_integrated_strength.ENABLE_ENV, None)
    if integrated_strength:
        os.environ[at_integrated_strength.ENABLE_ENV] = "1"
    querries.configure_data_file(_RESOURCES.joinpath("accelerator_setup.json"))
    try:
        loader = LatticeLoader()
        loader.set_lattice_file(_RESOURCES.joinpath("fodo_lattice.json"))
        return load_managers(loader.load())
    finally:
        querries.configure_data_file(previous)
        os.environ.pop(at_integrated_strength.ENABLE_ENV, None)
        if previous_env is not None:
            os.environ[at_integrated_strength.ENABLE_ENV] = previous_env


@pytest.fixture(scope="module")
def managers():
    """Integrated strengths enabled (DT4ACC_INTEGRATED_STRENGTH=1)"""
    return _build(integrated_strength=True)


@pytest.fixture(scope="module")
def plain_managers():
    """Default: the magnets publish the lattice coefficients"""
    return _build(integrated_strength=False)


def test_cavities_through_get(managers):
    yp, _, _ = managers
    assert len(yp.get("cavities")) > 0


@pytest.mark.parametrize("prop", ["main_strength", "main_strength_rdbk"])
@pytest.mark.parametrize(
    "steerer, host, lattice_property, slope",
    # thin correctors: kick angle in rad, horizontal = -PolynomB[0]
    [("HCOR_001", "COR_001", "B1", -1.0), ("VCOR_001", "COR_001", "A1", 1.0)],
)
def test_steerer_kick_angle(managers, prop, steerer, host, lattice_property, slope):
    """A steerer resolves to its host's kick, published as the kick angle"""
    _, lm, ts = managers
    dev_p = DevicePropertyID(device_name=steerer, property=prop)
    lat_p = LatticeElementPropertyID(element_name=host, property=lattice_property)

    assert list(lm.inverse(dev_p)) == [lat_p]

    conversion = ts.lut.get(ConversionID(lat_p, dev_p))
    assert isinstance(conversion, PolynomCoefficients)
    assert list(conversion.coeffs) == [0.0, slope]
    assert not conversion.energy_dependent


@pytest.mark.parametrize("prop", ["main_strength", "main_strength_rdbk"])
@pytest.mark.parametrize("magnet, length", [("QF_001", 0.4), ("QD_001", 0.4), ("SF_001", 0.1), ("SD_001", 0.1)])
def test_quad_sext_integrated_strength(managers, prop, magnet, length):
    """Quadrupoles and sextupoles publish K * L"""
    _, lm, ts = managers
    dev_p = DevicePropertyID(device_name=magnet, property=prop)
    (lat_p,) = lm.inverse(dev_p)
    assert lat_p == LatticeElementPropertyID(element_name=magnet, property="main_strength")

    conversion = ts.lut.get(ConversionID(lat_p, dev_p))
    assert isinstance(conversion, PolynomCoefficients)
    assert list(conversion.coeffs) == pytest.approx([0.0, length])
    assert not conversion.energy_dependent


def test_quadrupole_round_trip(managers):
    """Writing K * L gives K in the lattice, reading K gives K * L back"""
    _, _, ts = managers
    lat_p = LatticeElementPropertyID(element_name="QF_001", property="main_strength")
    dev_p = DevicePropertyID(device_name="QF_001", property="main_strength")
    conv = ts.get(ConversionID(lat_p, dev_p))
    assert conv.inverse(0.8) == pytest.approx(2.0)
    assert conv.forward(2.0) == pytest.approx(0.8)


def test_power_converter_current_unchanged(managers):
    """The power converters' currents are no strengths: not rescaled"""
    _, lm, ts = managers
    for lat_p in lm.inverse(DevicePropertyID(device_name="QF_001", property="main_strength")):
        (dev_p,) = [d for d in lm.forward(lat_p) if d.property == "set_current"]
        conversion = ts.lut.get(ConversionID(lat_p, dev_p))
        assert list(conversion.coeffs) == [0.0, 1.0]


@pytest.mark.parametrize(
    "device, host, lattice_property",
    [
        ("HCOR_001", "COR_001", "B1"),
        ("VCOR_001", "COR_001", "A1"),
        ("QF_001", "QF_001", "main_strength"),
        ("SF_001", "SF_001", "main_strength"),
    ],
)
def test_default_publishes_lattice_coefficients(plain_managers, device, host, lattice_property):
    """Not enabled: slope 1, as before the integrated strengths"""
    _, _, ts = plain_managers
    for prop in ("main_strength", "main_strength_rdbk"):
        conversion = ts.lut.get(ConversionID(
            LatticeElementPropertyID(element_name=host, property=lattice_property),
            DevicePropertyID(device_name=device, property=prop),
        ))
        assert list(conversion.coeffs) == [0.0, 1.0]
