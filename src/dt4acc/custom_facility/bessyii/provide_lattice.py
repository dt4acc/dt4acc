from importlib import resources

import at

from dt4acc_lib.pyat_simulator.accelerator_simulator import PyATAcceleratorSimulator
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

#: BESSY II storage ring lattice, exported from bessy2reflat (pyAT JSON;
#: source in resources/storage_ring/input/README.md)
LATTICE_FILE = "custom_facility/bessyii/resources/storage_ring/input/bessy2_storage_ring.json"


def provide_backend_encapsulating_lattice():
    lattice = provide_lattice()
    return provide_backend(lattice)


def provide_lattice() -> at.Lattice:
    with resources.as_file(resources.files("dt4acc").joinpath(LATTICE_FILE)) as filename:
        return bessyii_pyat_lattice(filename)


def provide_backend(lattice):
    backend = SimulatorBackend(
        name="BESSYII_on_PyAT",
        acc=PyATAcceleratorSimulator(at_lattice=lattice),
    )
    return backend


def bessyii_pyat_lattice(filename) -> at.Lattice:
    """The lattice in ``filename`` (pyAT JSON) as the twin uses it: 6D, the
    main cavities (CAV*) at the synchronous phase"""
    r = at.load_lattice(str(filename))
    r.enable_6d()
    r.cavpts = "CAV*"
    r.set_cavity_phase(cavpts=r.cavpts)
    return r
