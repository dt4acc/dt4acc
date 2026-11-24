"""BESSY II: the pinhole cameras at the dipoles BM2D2R and BM2D5R

Device names as on the machine. Source points: from lat2db's former BESSY II
lattice (``bessy2_export_draft.py``), which has the markers ``M_PINHOLE3`` /
``M_PINHOLE9`` after the first slice of these dipoles.
"""
from dt4acc.core.bl.beam_spot import CameraGeometry
from dt4acc.core.bl.pinhole import PinholeCamera, RingPinholes
from dt4acc_lib.pyat_simulator.simulator_backend import SimulatorBackend

#: placeholder: not the cameras' real pixels (2 mm x 2 mm)
GEOMETRY = CameraGeometry(width=100, height=100, pixel=0.02)

PINHOLES = (
    PinholeCamera("PINH3FD2L", element="BM2D2R", offset=0.2812, geometry=GEOMETRY),
    PinholeCamera("PINH9FD5L", element="BM2D5R", offset=0.278008, geometry=GEOMETRY),
)

#: [m rad] x: natural emittance of the lattice (pyAT radiation_parameters);
#: y: PLACEHOLDER, 1 % of it (the model is not coupled)
EMITTANCE = {"x": 7.64e-9, "y": 7.64e-11}
#: of the lattice (pyAT radiation_parameters)
ENERGY_SPREAD = 7.05e-4


def ring_pinholes(backend: SimulatorBackend) -> RingPinholes:
    return RingPinholes(backend, PINHOLES, emittance=EMITTANCE, energy_spread=ENERGY_SPREAD)
