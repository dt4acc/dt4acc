"""BESSY II: the pinhole cameras at the dipoles BM2D2R and BM2D5R

Device names as on the machine; the twin serves those of the yellow pages'
family :data:`PINHOLE_FAMILY`. Their beam size follows the stored beam's
emittance, calculated from the lattice (:mod:`dt4acc.core.bl.emittance`). Their source points (``PINH3``, ``PINH9``;
``M_PINHOLE3`` / ``M_PINHOLE9`` in lat2db's former BESSY II lattice, about
0.28 m into these dipoles) are not in bessy2reflat yet: until they are, a
camera shows the orbit and optics at the dipole's entrance. Once the lattice
has the markers, ``element`` is the marker's name.
"""
from dt4acc.core.bl.beam_spot import CameraGeometry
from dt4acc.core.bl.pinhole import PinholeCamera

#: placeholder: not the cameras' real pixels (2 mm x 2 mm)
GEOMETRY = CameraGeometry(width=100, height=100, pixel=0.02)

PINHOLES = (
    # Todo: element="PINH3" / "PINH9" (the source points' markers) once bessy2reflat has them
    PinholeCamera("PINH3FD2L", element="BM2D2R", geometry=GEOMETRY),
    PinholeCamera("PINH9FD5L", element="BM2D5R", geometry=GEOMETRY),
)

#: the yellow pages' family of the pinhole cameras
PINHOLE_FAMILY = "pinhole_cameras"


def pinholes(names):
    """the cameras of ``names`` (the yellow pages' family); ValueError for a name without a camera here"""
    by_name = {camera.name: camera for camera in PINHOLES}
    unknown = sorted(set(names) - set(by_name))
    if unknown:
        raise ValueError(f"pinhole cameras without source point here: {unknown}")
    return [by_name[name] for name in names]
