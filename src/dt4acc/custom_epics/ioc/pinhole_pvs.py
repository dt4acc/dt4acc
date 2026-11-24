"""EPICS PVs of a storage ring twin's pinhole cameras (:mod:`dt4acc.core.bl.pinhole`)

* ``<camera>:rdCenterX`` / ``rdCenterY``: beam centre [mm]
* ``<camera>:rdSigmaX`` / ``rdSigmaY``: beam size [mm]
* ``<camera>:image``: ``image:height`` rows of ``image:width`` pixels of
  ``image:pixel`` mm, row 0 at the top (:mod:`dt4acc.core.bl.beam_spot`)
* ``beam:emittance:x`` / ``y`` [m rad], ``beam:energy_spread``: of the stored
  beam, writable

Recomputed after each new closed orbit and when a setting changes. Without a
closed orbit: NaN and a dark image.
"""
import asyncio
import logging
from typing import Sequence

import numpy as np
from softioc import builder as softioc_builder

from dt4acc.core.bl.beam_spot import spot_image
from dt4acc.core.bl.pinhole import NO_BEAM, PLANES, RingPinholes
from dt4acc.core.bl.shared_event_loop import get_shared_event_loop
from dt4acc.custom_epics.ioc.bpm_pvs import M2MM

logger = logging.getLogger("dt4acc")


class PinholePVs:
    """Records of the pinhole cameras; recomputes when the settings or the closed orbit change"""

    def __init__(self, pinholes: RingPinholes, builder=softioc_builder):
        self.pinholes = pinholes
        self._dirty = False
        self._running = False
        self.rec = {}
        for plane in PLANES:
            self.rec[f"emittance:{plane}"] = builder.aOut(
                f"beam:emittance:{plane}", initial_value=pinholes.emittance[plane], PREC=12, EGU="m rad", DRVL=0.0,
                DRVH=1.0, on_update=lambda value, plane=plane: self._set_emittance(plane, value),
            )
        self.rec["energy_spread"] = builder.aOut(
            "beam:energy_spread", initial_value=pinholes.energy_spread, PREC=8, DRVL=0.0, DRVH=1.0,
            on_update=self._set_energy_spread,
        )
        for camera in pinholes.cameras:
            name, geometry = camera.name, camera.geometry
            for plane in PLANES:
                for what, field in (("", "rdCenter"), ("sigma_", "rdSigma")):
                    self.rec[f"{name}:{what}{plane}"] = builder.aIn(
                        f"{name}:{field}{plane.upper()}", initial_value=0.0, PREC=6, EGU="mm"
                    )
            self.rec[f"{name}:image"] = builder.WaveformIn(
                f"{name}:image", initial_value=np.zeros(geometry.width * geometry.height)
            )
            for prop in ("width", "height"):
                builder.longIn(f"{name}:image:{prop}", initial_value=getattr(geometry, prop))
            builder.aIn(f"{name}:image:pixel", initial_value=geometry.pixel, PREC=4, EGU="mm")

    # --- settings
    def _set_emittance(self, plane: str, value: float):
        self.pinholes.set_emittance(plane, value)
        self.trigger()

    def _set_energy_spread(self, value: float):
        self.pinholes.energy_spread = value
        self.trigger()

    # --- recompute, coalescing requests that arrive while it runs
    def trigger(self):
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

    def update(self):
        try:
            spots = self.pinholes.compute()
        except Exception as exc:
            logger.error("pinhole cameras: computation failed: %s", exc)
            spots = {camera.name: NO_BEAM for camera in self.pinholes.cameras}
        self.publish(spots)

    def publish(self, spots):
        for camera in self.pinholes.cameras:
            spot = spots[camera.name]
            mm = {k: getattr(spot, k) * M2MM for k in ("x", "y", "sigma_x", "sigma_y")}
            for prop, value in mm.items():
                self.rec[f"{camera.name}:{prop}"].set(value)
            self.rec[f"{camera.name}:image"].set(spot_image(**mm, geometry=camera.geometry).ravel())


def hook_pinholes(view, pinholes: PinholePVs):
    """After the view publishes a new closed orbit (or none), update the pinhole cameras"""
    update_track = view.update_track

    def update_track_and_pinholes(var, pkg):
        update_track(var, pkg)
        pinholes.trigger()

    view.update_track = update_track_and_pinholes
    return view


__all__: Sequence[str] = ["PinholePVs", "hook_pinholes"]
