import json
from importlib import resources

import at

from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend


def provide_backend_encapsulating_lattice():
    lattice = provide_lattice()
    return provide_backend(lattice)


def provide_lattice():
    filename = resources.files("dt4acc").joinpath(
        "custom_facility/bessyii/resources/storage_ring/input/bessy2_storage_ring_reflat.json"
    )
    acc = bessyii_pyat_lattice(filename=filename)
    return acc


def provide_backend(lattice):
    backend = SimulatorBackend(
        name="BESSYII_on_PyAT",
        acc=PyATAcceleratorSimulator(at_lattice=lattice),
    )
    return backend


def bessyii_pyat_lattice_from_dics(seq, energy: float = 1.7185e9):
    r = at.Lattice(seq, name="BESSY II storage ring", energy=energy)
    r.enable_6d()
    r.cavpts = "CAV*"
    r.set_cavity_phase(cavpts=r.cavpts)
    return r


def bessyii_pyat_lattice(filename: str, energy: float = 1.7185e9) -> at.Lattice:
    from lat2db.tools.factories.pyat import factory

    with open(filename, "rt") as fp:
        d = json.load(fp)
    seq = factory(d, energy=energy)
    return bessyii_pyat_lattice_from_dics(seq, energy=energy)
