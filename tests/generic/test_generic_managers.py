"""Managers of the generic EPICS twin, built from the bundled FODO lattice/catalog

No IOC needed: checks the yellow pages, liaison manager and translator
service that ``run_epics_twin`` builds at startup.
"""

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

_RESOURCES = resources.files("dt4acc").joinpath("custom_facility/generic/resources")


@pytest.fixture(scope="module")
def managers():
    previous = querries.get_data_file()
    querries.configure_data_file(_RESOURCES.joinpath("accelerator_setup.json"))
    try:
        loader = LatticeLoader()
        loader.set_lattice_file(_RESOURCES.joinpath("fodo_lattice.json"))
        yield load_managers(loader.load())
    finally:
        querries.configure_data_file(previous)


def test_cavities_through_get(managers):
    yp, _, _ = managers
    assert len(yp.get("cavities")) > 0


@pytest.mark.parametrize(
    "steerer, host, lattice_property",
    [("HCOR_001", "COR_001", "B1"), ("VCOR_001", "COR_001", "A1")],
)
def test_steerer_main_strength_rdbk(managers, steerer, host, lattice_property):
    """A steerer's read back resolves to its host's kick, converted as identity"""
    _, lm, ts = managers
    dev_p = DevicePropertyID(device_name=steerer, property="main_strength_rdbk")
    lat_p = LatticeElementPropertyID(element_name=host, property=lattice_property)

    assert list(lm.inverse(dev_p)) == [lat_p]

    conversion = ts.lut.get(ConversionID(lat_p, dev_p))
    assert isinstance(conversion, PolynomCoefficients)
    assert list(conversion.coeffs) == [0.0, 1.0]
    assert not conversion.energy_dependent


def test_quadrupole_main_strength_rdbk_still_there(managers):
    _, lm, ts = managers
    dev_p = DevicePropertyID(device_name="QF_001", property="main_strength_rdbk")
    (lat_p,) = lm.inverse(dev_p)
    assert lat_p == LatticeElementPropertyID(element_name="QF_001", property="main_strength")
    assert ts.lut.get(ConversionID(lat_p, dev_p)) is not None
