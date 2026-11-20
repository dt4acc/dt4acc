"""EPICS view of a transfer line

A line has no tune and no master clock: twiss updates only the optics
waveforms. Each monitor gets its own readings of the trajectory: BPMs and
striplines as the BPM system (``<bpm>:signal:sa:X`` / ``Y``,
:mod:`dt4acc.custom_epics.ioc.bpm_pvs`). Screens are no BPMs: they show an
image of the beam spot (:mod:`.screens`), ``<screen>:image``, from the beam
centre (``<screen>:x`` / ``y``) and size (``<screen>:sigma:x`` / ``y``: the
emittance, ``TL:beam:emittance:x`` / ``y``, and the optics at the screen).

PV names: the line's devices keep their machine names (``<P>:Q1PT:set``,
``<P>:BPMZ1T:signal:sa:X``, ``<P>:FOMZ1T:image``); its model is under
``TL`` (:data:`MODEL_DEVICE`): ``<P>:TL:beam:orbit:*``, ``<P>:TL:beam:twiss:*``,
``<P>:TL:beam:emittance:*``, ``<P>:TL:survey:*``, ``<P>:TL:ORBITCC:*``. The same
names whether the transfer line twin runs on its own or in the injection twin,
where the ring serves ``<P>:beam:*`` and ``<P>:ORBITCC:*``.

Single pass (``single_pass=True``): a line carries beam only during a shot.
Its monitors are triggered by the shot and keep its reading until the next
one; screens show the beam only while it passes. So the model (trajectory,
optics: ``TL:beam:orbit:*``, ``TL:beam:twiss:*``, ``TL:ORBITCC:rdModel``)
follows every change, but the monitors (``<bpm>:signal:sa:*``, the screens,
``TL:ORBITCC:rdBpm``) only show the beam when a shot is fired
(:meth:`TransferLineView.fire`). Without it (the transfer line twin on its
own) the monitors follow every change.
"""
from typing import Dict, Mapping, Optional, Sequence

import numpy as np
from softioc import builder as softioc_builder
from softioc.pythonSoftIoc import RecordWrapper

from dt4acc.custom_epics.ioc.bpm_pvs import M2MM, SA_FIELDS
from dt4acc.custom_epics.ioc.pv_setup import initialize_orbit_pvs, initialize_survey_info_pvs, initialize_twiss_pvs
from dt4acc.custom_epics.ioc.view import View
from dt4acc_lib.model.utils.command import ReadCommand

from .screens import SCREEN, ScreenGeometry, beam_size, screen_image
from .twin_setup import EMITTANCE

#: the device the line's model PVs are under: ``<P>:TL:beam:orbit:x``, ...
MODEL_DEVICE = "TL"
TWISS = ReadCommand("twiss", "parameters")
TRACK = ReadCommand("track", "pos")
PLANES = ("x", "y")


def model_device(prefix: str) -> str:
    """``<prefix>:TL``, or ``TL`` without a prefix"""
    return f"{prefix}:{MODEL_DEVICE}" if prefix else MODEL_DEVICE


def is_screen(name: str) -> bool:
    """a fluorescent screen (``FOMZ...``), not a BPM"""
    return name.startswith("FOMZ")


def initialize_monitor_pvs(
    names: Sequence[str], builder=softioc_builder, geometry: ScreenGeometry = SCREEN
) -> Dict[ReadCommand, RecordWrapper]:
    """the monitors' records

    * BPMs, striplines: ``<bpm>:signal:sa:X`` / ``Y`` [mm]
    * screens: ``<screen>:image`` (``image:height`` rows of ``image:width``
      pixels of ``image:pixel`` mm, row 0 at the top), the beam centre
      ``<screen>:x`` / ``y`` and size ``<screen>:sigma:x`` / ``y`` [mm]
    """
    d = dict()
    for name in names:
        if not is_screen(name):
            for plane, field in SA_FIELDS:
                d[ReadCommand(id=name, property=plane)] = builder.aIn(
                    f"{name}:{field}", initial_value=0.0, PREC=6, EGU="mm"
                )
            continue
        for plane in PLANES:
            d[ReadCommand(id=name, property=plane)] = builder.aIn(
                f"{name}:{plane}", initial_value=0.0, PREC=6, EGU="mm"
            )
            d[ReadCommand(id=name, property=f"sigma_{plane}")] = builder.aIn(
                f"{name}:sigma:{plane}", initial_value=0.0, PREC=6, EGU="mm"
            )
        d[ReadCommand(id=name, property="image")] = builder.WaveformIn(
            f"{name}:image", initial_value=np.zeros(geometry.width * geometry.height),
        )
        d[ReadCommand(id=name, property="image_width")] = builder.longIn(
            f"{name}:image:width", initial_value=geometry.width
        )
        d[ReadCommand(id=name, property="image_height")] = builder.longIn(
            f"{name}:image:height", initial_value=geometry.height
        )
        d[ReadCommand(id=name, property="image_pixel")] = builder.aIn(
            f"{name}:image:pixel", initial_value=geometry.pixel, PREC=4, EGU="mm"
        )
    return d


def initialize_model_pvs(builder, view: "TransferLineView", *, n_elements: int) -> Dict[ReadCommand, RecordWrapper]:
    """The line's model: trajectory, optics, survey, and the beam's emittance
    (writable: the screens' images); under :data:`MODEL_DEVICE`, which the
    caller sets as the builder's device name (:func:`model_device`)"""
    d = {
        **initialize_survey_info_pvs(builder, n_elements=n_elements),
        **initialize_orbit_pvs(builder, n_elements=n_elements),
        **initialize_twiss_pvs(builder, n_elements=n_elements),
    }
    for plane in PLANES:
        d[ReadCommand("emittance", plane)] = builder.aOut(
            f"beam:emittance:{plane}", initial_value=view.emittance[plane], PREC=12, EGU="m rad", DRVL=0.0,
            on_update=lambda value, plane=plane: view.set_emittance(plane, value),
        )
    return d


class TransferLineView(View):
    def __init__(
        self,
        *,
        monitors: Sequence[str],
        single_pass: bool = False,
        emittance: Mapping[str, float] = None,
        screen: ScreenGeometry = SCREEN,
        **kwargs,
    ):
        # BPMs and striplines follow the trajectory (View.update_bpms), screens show an image
        super().__init__(bpms=[m for m in monitors if not is_screen(m)], **kwargs)
        self.monitors = set(monitors)
        self.screens = [m for m in monitors if is_screen(m)]
        self.screen = screen
        self.emittance = dict(EMITTANCE if emittance is None else emittance)
        self.single_pass = single_pass
        #: single pass: the latest trajectory, what the next shot will show
        self.trajectory: Optional[Sequence] = None

    # --- the beam at the monitors
    def update_monitors(self, track) -> None:
        if self.single_pass:
            self.trajectory = track
            return
        super().update_monitors(track)
        self.update_screens(track)

    def fire(self) -> bool:
        """A shot passes the line: the monitors show the latest trajectory

        False if there is no trajectory yet.
        """
        if self.trajectory is None:
            return False
        super().update_monitors(self.trajectory)
        self.update_screens(self.trajectory)
        return True

    def update_screens(self, track) -> None:
        """The screens' images: the beam centre from ``track``, its size from
        the emittance and the latest optics"""
        if not self.screens:
            return
        centre = {pos.fam_name: (pos.x, pos.y) for pos in track}
        twiss = self.last_data_cache.get(TWISS)
        beta = {pos.fam_name: (pos.x.beta, pos.y.beta) for pos in twiss.twiss} if twiss is not None else {}
        for name in self.screens:
            if name not in centre:
                continue
            xy = [v * M2MM for v in centre[name]]
            sigma = [
                beam_size(self.emittance[plane], b) * M2MM if b is not None else float("nan")
                for plane, b in zip(PLANES, beta.get(name, (None, None)))
            ]
            for plane, c, s in zip(PLANES, xy, sigma):
                self._set(name, plane, c)
                self._set(name, f"sigma_{plane}", s)
            self._set(name, "image", screen_image(*xy, *sigma, geometry=self.screen).ravel())

    def _set(self, name: str, prop: str, value) -> None:
        rec = self.process_variables.get(ReadCommand(id=name, property=prop))
        if rec is not None:
            rec.set(value)

    def _refresh_screens(self) -> None:
        """The line on its own: the screens follow the optics and the emittance
        at once; single pass: at the next shot"""
        if self.single_pass:
            return
        track = self.last_data_cache.get(TRACK)
        if track is not None:
            self.update_screens(track.track)

    def set_emittance(self, plane: str, value: float) -> None:
        self.emittance[plane] = float(value)
        self._refresh_screens()

    # --- model
    def update_twiss(self, var: ReadCommand, pkg):
        super().update_twiss(var, pkg)
        self._refresh_screens()

    def update_special_values(self, var: ReadCommand, value) -> bool:
        if var.id == "twiss":
            self.update_twiss(var, value)
            return True
        return super().update_special_values(var, value)
