"""Tango devices: integrated strengths at the device boundary (no Tango server needed)"""

import at
import pytest

pytest.importorskip("tango")

from dt4acc_lib.model.utils.identifiers import LatticeElementPropertyID  # noqa: E402

from dt4acc.core.utils import integrated_strength  # noqa: E402
from dt4acc.custom_tango.ioc import single_server  # noqa: E402
from dt4acc.custom_tango.ioc.sync_mexec_proxy import SyncMexecProxy  # noqa: E402


@pytest.fixture
def factors(monkeypatch):
    table = {("Q_uuid", "main_strength"): 0.4, ("COR_uuid", "B1"): -1.0}
    monkeypatch.setattr(single_server, "_strength_factors", table)
    return table


def test_device_lattice_round_trip(factors):
    assert single_server.to_device_value("Q_uuid", "main_strength", 2.0) == pytest.approx(0.8)
    assert single_server.to_lattice_value("Q_uuid", "main_strength", 0.8) == pytest.approx(2.0)
    assert single_server.to_device_value("COR_uuid", "B1", 1e-4) == pytest.approx(-1e-4)
    assert single_server.to_lattice_value("COR_uuid", "B1", -1e-4) == pytest.approx(1e-4)
    # not in the table: unchanged
    assert single_server.to_device_value("COR_uuid", "A1", 1e-4) == 1e-4
    assert single_server.to_device_value("CAV", "frequency", 352e6) == 352e6


def test_cached_values_are_device_values(factors, monkeypatch):
    monkeypatch.setattr(single_server, "_initial_values_cache", {"Q_uuid": {"main_strength": 2.0}})
    monkeypatch.setattr(single_server, "_nominal_cache", {"COR_uuid": {"B1": 1e-4, "A1": 2e-4}})
    assert single_server.get_initial_values("Q_uuid")["main_strength"] == pytest.approx(0.8)
    nominal = single_server.get_nominal_values("COR_uuid")
    assert nominal["B1"] == pytest.approx(-1e-4)
    assert nominal["A1"] == pytest.approx(2e-4)


def test_no_factors_publishes_lattice_values(monkeypatch):
    monkeypatch.setattr(single_server, "_strength_factors", {})
    assert single_server.to_device_value("Q_uuid", "main_strength", 2.0) == 2.0


class _FakeSimulator:
    def __init__(self, acc):
        self.acc = acc


class _FakeBackend:
    def __init__(self, acc):
        self.acc = _FakeSimulator(acc)


class _FakeMexec:
    def __init__(self, acc):
        self.backend = _FakeBackend(acc)


class _FakeLutElement:
    def __init__(self, lat_ids):
        self.lat_ids = lat_ids


class _FakeLiaison:
    def __init__(self, lat_ids):
        self.inverse_lut = type("L", (), {"lut": [_FakeLutElement(lat_ids)]})()


@pytest.fixture
def proxy(monkeypatch):
    quad = at.Quadrupole("QF", 0.4, 1.0)
    quad.UUID = "Q_uuid"
    cor = at.ThinMultipole("COR", [0.0], [0.0])
    cor.UUID = "COR_uuid"
    acc = at.Lattice([quad, cor, at.Drift("D", 1.0)], energy=1e9)
    lat_ids = [
        LatticeElementPropertyID(element_name="Q_uuid", property="main_strength"),
        LatticeElementPropertyID(element_name="COR_uuid", property="B1"),
        LatticeElementPropertyID(element_name="COR_uuid", property="A1"),  # factor 1: left out
        LatticeElementPropertyID(element_name="missing", property="B2"),  # not in the lattice
        LatticeElementPropertyID(element_name="CAV", property="frequency"),
    ]
    from dt4acc.custom_tango.ioc import mexec_server_for_physics_engine as mexec_server

    monkeypatch.setattr(mexec_server, "LOAD_MANAGERS_FN", lambda: (None, _FakeLiaison(lat_ids), None))
    return SyncMexecProxy(mexec=_FakeMexec(acc), service_loop=None)


def test_proxy_factor_table(proxy, monkeypatch):
    monkeypatch.setenv(integrated_strength.ENABLE_ENV, "1")
    table = proxy.sync_strength_factors()
    assert table == {
        ("Q_uuid", "main_strength"): pytest.approx(0.4),
        ("COR_uuid", "B1"): -1.0,
    }


def test_proxy_disabled(proxy, monkeypatch):
    monkeypatch.delenv(integrated_strength.ENABLE_ENV, raising=False)
    assert proxy.sync_strength_factors() == {}
