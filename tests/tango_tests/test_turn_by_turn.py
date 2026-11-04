"""Turn by turn data of the Tango twins (custom_tango/ioc/turn_by_turn)

* the physics engine's service on the SOLEIL II lattice: the BPMs from the
  device database, a beam off the closed orbit oscillates with the tunes,
  tracked again only after a change (skipped without the SOLEIL files)
* the ring simulator's follower, with the service in process
* a BPM device as SOLEIL's Libera devices (XPosDD / ZPosDD, XPosSA / ZPosSA
  in mm, DDBufferSize), served in a Tango test context (no database), next
  to a stand in for the ring simulator
"""
import os
import threading
from pathlib import Path

import numpy as np
import pytest

from dt4acc.config.data.querries import configure_data_file, get_bpms, get_data_file
from dt4acc.core.bl.handle_lattice import lattice_loader
from dt4acc.custom_tango.ioc.turn_by_turn import M2MM, MAX_TURNS, TurnByTurnFollower, TurnByTurnService
from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

#: the files the SOLEIL twin runs with (custom_facility/soleil/utils/command_line_interface)
SOLEIL_DATA = Path(os.environ.get("DT4ACC_SOLEIL_DATA", Path.home() / "Documents" / "dt4acc_config_data"))
SOLEIL_LATTICE = SOLEIL_DATA / "SOLEIL_II_V3635_STAB_SYM1_SB3_MULT7_4SX60_V001_Nomenclature.m"
SOLEIL_SETUP = SOLEIL_DATA / "accelerator_setup.json"


def peak_tune(signal) -> float:
    s = np.asarray(signal) - np.mean(signal)
    n = 16 * len(s)
    return np.fft.rfftfreq(n)[np.argmax(np.abs(np.fft.rfft(s * np.hanning(len(s)), n)))]


@pytest.fixture(scope="module")
def soleil_service():
    if not (SOLEIL_LATTICE.exists() and SOLEIL_SETUP.exists()):
        pytest.skip(f"SOLEIL lattice / device database not found in {SOLEIL_DATA}")
    previous = get_data_file()
    configure_data_file(SOLEIL_SETUP)
    try:
        lattice_loader.set_lattice_file(SOLEIL_LATTICE)
        backend = SimulatorBackend(name="soleil", acc=PyATAcceleratorSimulator(at_lattice=lattice_loader.load()))
        yield TurnByTurnService(backend)
    finally:
        configure_data_file(previous)


def test_soleil_bpms_from_the_device_database(soleil_service):
    ids = soleil_service.tbt.monitors
    # SOLEIL's values stay out of the repository: compared with its device database
    in_db = {bpm["uuid"] for bpm in get_bpms()}
    assert len(ids) > 0 and set(ids) <= in_db


@pytest.mark.parametrize("plane", [0, 1])
def test_soleil_oscillates_with_the_tunes(soleil_service, plane):
    offset = [1e-4, 0, 0, 0, 0, 0] if plane == 0 else [0, 0, 1e-4, 0, 0, 0]
    soleil_service.configure(offset, 128)
    summary = soleil_service.update()
    assert summary["n_turns"] == 128 and summary["survived"][-1] == 1
    xy = np.asarray(soleil_service.at(summary["bpm_ids"][0]))
    signal = xy[:128] if plane == 0 else xy[128:]
    _, ring_data, _ = soleil_service.tbt.backend.acc.acc.get_optics()
    q = ring_data.tune[plane]
    assert peak_tune(signal) == pytest.approx(min(q, 1 - q), abs=2e-3)


def test_soleil_tracks_again_only_after_a_change(soleil_service):
    soleil_service.configure([1e-4, 0, 1e-4, 0, 0, 0], 16)
    generation = soleil_service.update()["generation"]
    assert soleil_service.update()["generation"] == generation, "nothing changed"
    soleil_service.configure([2e-4, 0, 1e-4, 0, 0, 0], 16)
    assert soleil_service.update()["generation"] == generation + 1


class InProcessProxy:
    """the physics engine's SyncMexecProxy, for the follower, without processes"""

    def __init__(self, service: TurnByTurnService):
        self.service = service

    def sync_tbt_configure(self, offset, n_turns):
        self.service.configure(offset, n_turns)

    def sync_tbt_update(self):
        return self.service.update()

    def sync_tbt_at(self, bpm_id):
        return self.service.at(bpm_id)


def test_follower_publishes_new_results(soleil_service):
    news = []
    arrived = threading.Event()

    def on_new(summary):
        news.append(summary)
        arrived.set()

    follower = TurnByTurnFollower(proxy=lambda: InProcessProxy(soleil_service), on_new=on_new)
    follower.set_n_turns(32)
    assert arrived.wait(30) and follower.count == 1 and news[-1]["n_turns"] == 32
    xy = follower.at(news[-1]["bpm_ids"][5])
    assert len(xy) == 2 * 32
    with pytest.raises(ValueError):
        follower.set_n_turns(MAX_TURNS + 1)
    with pytest.raises(ValueError):
        follower.set_offset([0.0] * 5)


def test_tracking_runs_on_the_service_loop(monkeypatch):
    """pyAT's tracking is not thread safe: all use of the lattice on one thread (the service
    loop), turn by turn too, else optics and tracking in two threads crash the physics engine"""
    import asyncio

    from dt4acc.custom_tango.ioc import sync_mexec_proxy, turn_by_turn

    threads = []

    class Service:
        def __init__(self, backend):
            pass

        def update(self):
            threads.append(threading.current_thread())
            return {}

    monkeypatch.setattr(turn_by_turn, "TurnByTurnService", Service)
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    try:
        proxy = sync_mexec_proxy.SyncMexecProxy(mexec=object(), service_loop=loop)
        monkeypatch.setattr(proxy, "mexec", type("M", (), {"backend": None})())
        proxy.sync_tbt_update()
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join()
    assert threads == [loop_thread]


# --- BPM device, in a Tango test context
tango = pytest.importorskip("tango")
from tango.server import Device, attribute, command  # noqa: E402
from tango.test_context import MultiDeviceTestContext  # noqa: E402

N_TURNS = 8
#: x, then y [m]
XY = np.concatenate([np.arange(N_TURNS) * 1e-4, -np.arange(N_TURNS) * 1e-4])


class RingSimulatorStandIn(Device):
    """the ring simulator's turn by turn interface, with a fixed result"""

    def init_device(self):
        super().init_device()
        self._n_turns = N_TURNS
        self._count = 1

    @attribute(dtype=int, access=tango.AttrWriteType.READ_WRITE)
    def tbt_n_turns(self):
        return self._n_turns

    @tbt_n_turns.write
    def tbt_n_turns(self, value):
        self._n_turns = value
        self._count += 1

    @attribute(dtype=int)
    def tbt_count(self):
        return self._count

    @command(dtype_in=str, dtype_out=(float,))
    def TurnByTurnAt(self, bpm_id):
        assert bpm_id == "TEST_BPM"
        return XY


@pytest.fixture(scope="module")
def bpm_device():
    from dt4acc.custom_tango.ioc.devices import bpm_device as module

    devices_info = [
        {"class": RingSimulatorStandIn, "devices": [{"name": "test/ringsim/1"}]},
        {"class": module.BPMDevice,
         "devices": [{"name": "test/bpm/1", "properties": {"lattice_id": "TEST_BPM", "orbit_index": 3}}]},
    ]
    # from before the BPM device starts: with its real name it would reach a twin
    # running on this machine (TANGO_HOST, /etc/tangorc)
    module_ring_sim, module.RING_SIM_DEV = module.RING_SIM_DEV, "tango://localhost:1/no/ring/simulator#dbase=no"
    try:
        with MultiDeviceTestContext(devices_info, process=False) as context:
            ring_sim = context.get_device_access("test/ringsim/1")
            # the BPM device finds the ring simulator under this name (no database)
            module.RING_SIM_DEV = ring_sim
            yield context.get_device("test/bpm/1"), ring_sim
    finally:
        module.RING_SIM_DEV = module_ring_sim


def test_bpm_turn_by_turn_in_mm(bpm_device):
    bpm, _ = bpm_device
    np.testing.assert_allclose(bpm.XPosDD, XY[:N_TURNS] * M2MM)
    np.testing.assert_allclose(bpm.ZPosDD, XY[N_TURNS:] * M2MM)
    assert bpm.get_attribute_config("XPosDD").unit == "mm"


def test_bpm_buffer_size_is_the_ring_simulators_turns(bpm_device):
    bpm, ring_sim = bpm_device
    assert bpm.DDBufferSize == N_TURNS
    bpm.DDBufferSize = 64
    assert tango.DeviceProxy(ring_sim).tbt_n_turns == 64 and bpm.DDBufferSize == 64


def test_bpm_slow_acquisition_in_mm(bpm_device):
    bpm, _ = bpm_device
    # no ring simulator orbit events here: the closed orbit is still 0
    assert bpm.XPosSA == 0.0 and bpm.ZPosSA == 0.0
    assert bpm.get_attribute_config("ZPosSA").unit == "mm"
