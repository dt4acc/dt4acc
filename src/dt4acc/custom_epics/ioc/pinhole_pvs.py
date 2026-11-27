"""EPICS PVs of a storage ring twin's pinhole cameras (:mod:`dt4acc.core.bl.pinhole`)

* ``<camera>:rdCenterX`` / ``rdCenterY``: beam centre [mm]
* ``<camera>:rdSigmaX`` / ``rdSigmaY``: beam size [mm]
* ``<camera>:image``: ``image:height`` rows of ``image:width`` pixels of
  ``image:pixel`` mm, row 0 at the top (:mod:`dt4acc.core.bl.beam_spot`)
* ``beam:emittance:x`` / ``y`` [m rad]: of the stored beam, calculated from
  the ring's lattice after each new closed orbit
  (:mod:`dt4acc.core.bl.emittance`); read only

Each camera is a view of its lattice element (:class:`PinholeCameraView`):
the ring's view hands it the orbit and optics there after each new
calculation (:meth:`View.add_element_views`). Without a closed orbit: NaN and
a dark image.
"""
import asyncio
import logging
from typing import Callable, Dict, List, Mapping, Sequence

import numpy as np
from softioc import builder as softioc_builder

from dt4acc.core.bl.emittance import ring_emittance
from dt4acc.core.bl.shared_event_loop import get_shared_event_loop

from dt4acc.core.bl.beam_spot import spot_image
from dt4acc.core.bl.pinhole import NO_BEAM, PLANES, BeamSpot, PinholeCamera, beam_spot
from dt4acc.custom_epics.ioc.bpm_pvs import M2MM


logger = logging.getLogger("dt4acc")


class BeamEmittance:
    """the stored beam's emittance [m rad] per plane (NaN: not known); ``listeners`` follow a change"""

    def __init__(self, emittance: Mapping[str, float] = None):
        self.value: Dict[str, float] = {plane: float("nan") for plane in PLANES}
        self.listeners: List[Callable[[], None]] = []
        if emittance is not None:
            self.update(emittance)

    @staticmethod
    def _check(value: float) -> None:
        if not (np.isnan(value) or (np.isfinite(value) and value >= 0.0)):
            raise ValueError(f"emittance: expected finite and >= 0 (or NaN), got {value}")

    def update(self, emittance: Mapping[str, float]) -> None:
        for plane in PLANES:
            self._check(emittance[plane])
        self.value.update({plane: float(emittance[plane]) for plane in PLANES})
        for listener in self.listeners:
            listener()


class RingEmittancePVs:
    """``beam:emittance:x`` / ``y``: calculated from ``lattice()`` (the ring
    backend's lattice) after each new closed orbit (:func:`hook_emittance`);
    requests that arrive while it runs are coalesced"""

    def __init__(self, lattice: Callable[[], object], emittance: BeamEmittance, builder=softioc_builder):
        self.lattice = lattice
        self.emittance = emittance
        self._dirty = False
        self._running = False
        self.rec = {
            plane: builder.aIn(f"beam:emittance:{plane}", initial_value=0.0, PREC=12, EGU="m rad")
            for plane in PLANES
        }

    def trigger(self) -> None:
        self._dirty = True
        if not self._running:
            self._running = True
            asyncio.run_coroutine_threadsafe(self._run(), get_shared_event_loop())

    async def _run(self):
        try:
            while self._dirty:
                self._dirty = False
                self.update()
        finally:
            self._running = False

    def update(self) -> None:
        """calculate now"""
        try:
            value = ring_emittance(self.lattice())
        except Exception as exc:
            logger.error("emittance: calculation failed: %s", exc)
            value = {plane: float("nan") for plane in PLANES}
        for plane in PLANES:
            self.rec[plane].set(value[plane])
        self.emittance.update(value)


def hook_emittance(view, emittance: RingEmittancePVs):
    """After the view publishes a new closed orbit (or none), calculate the emittance again"""
    update_track = view.update_track

    def update_track_and_emittance(var, pkg):
        update_track(var, pkg)
        emittance.trigger()

    view.update_track = update_track_and_emittance
    return view


class PinholeCameraView:
    """One camera: shows the beam at ``camera.element``"""

    def __init__(self, camera: PinholeCamera, emittance: BeamEmittance, builder=softioc_builder):
        self.camera = camera
        self.elements = [camera.element]
        self.emittance = emittance
        self.spot = NO_BEAM
        self._orbit = None
        self._twiss = None
        name, geometry = camera.name, camera.geometry
        self.rec = {}
        for plane in PLANES:
            for what, field in (("", "rdCenter"), ("sigma_", "rdSigma")):
                self.rec[f"{what}{plane}"] = builder.aIn(
                    f"{name}:{field}{plane.upper()}", initial_value=0.0, PREC=6, EGU="mm"
                )
        self.rec["image"] = builder.WaveformIn(f"{name}:image", initial_value=np.zeros(geometry.width * geometry.height))
        for prop in ("width", "height"):
            builder.longIn(f"{name}:image:{prop}", initial_value=getattr(geometry, prop))
        builder.aIn(f"{name}:image:pixel", initial_value=geometry.pixel, PREC=4, EGU="mm")
        emittance.listeners.append(self.refresh)

    def update(self, orbit: Mapping, twiss: Mapping) -> None:
        """the ring view's orbit and optics at the camera's element"""
        self._orbit = orbit.get(self.camera.element, self._orbit)
        self._twiss = twiss.get(self.camera.element, self._twiss)
        self.refresh()

    def refresh(self) -> None:
        """the spot from the latest orbit and optics and the emittance now"""
        if self._orbit is None or self._twiss is None:
            spot = NO_BEAM
        else:
            beta = {plane: getattr(self._twiss, plane).beta for plane in PLANES}
            spot = beam_spot(self._orbit.x, self._orbit.y, beta, self.emittance.value)
        self.publish(spot)

    def publish(self, spot: BeamSpot) -> None:
        self.spot = spot
        mm = {k: getattr(spot, k) * M2MM for k in ("x", "y", "sigma_x", "sigma_y")}
        for prop, value in mm.items():
            self.rec[prop].set(value)
        self.rec["image"].set(spot_image(**mm, geometry=self.camera.geometry).ravel())


def initialize_pinhole_pvs(
    cameras: Sequence[PinholeCamera], emittance: BeamEmittance, builder=softioc_builder
) -> List[PinholeCameraView]:
    """the cameras' views and records; hand them to the ring's view
    (:meth:`View.add_element_views`). ``emittance``: e.g. that of
    :class:`RingEmittancePVs`"""
    return [PinholeCameraView(camera, emittance, builder=builder) for camera in cameras]


__all__: Sequence[str] = [
    "BeamEmittance", "PinholeCameraView", "RingEmittancePVs", "hook_emittance", "initialize_pinhole_pvs",
]
