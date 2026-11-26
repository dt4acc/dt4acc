"""EPICS view of a transfer line

A line has no tune and no master clock: twiss updates only the optics
waveforms. Each monitor gets its own readings of the trajectory: BPMs and
striplines as the BPM system (``<bpm>:signal:sa:X`` / ``Y``,
:mod:`dt4acc.custom_epics.ioc.bpm_pvs`). Screens are no BPMs: they show an
image of the beam spot (:mod:`.screens`), ``<screen>:image``, from the beam
centre (``<screen>:x`` / ``y``) and size (``<screen>:sigma:x`` / ``y``: the
emittance, ``TL:beam:emittance:x`` / ``y``, and the optics at the screen).
A screen's mode (``<screen>:mode``, :class:`ScreenMode`, #76): Out (no image),
Observe (default: the beam passes) or Stop (the monitors after it see no beam,
nothing leaves the line). An artificial screen (``TL:screen:...``,
:func:`initialize_artificial_screen_pvs`) does the same at any element of the line.

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
import enum
import math
from copy import copy as _copy
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


class ScreenMode(enum.IntEnum):
    """What a screen does with the beam (``<screen>:mode``)

    * ``OUT``: retracted: no image, the beam passes
    * ``OBSERVE``: in the beam, shows its image, the beam passes (transparent)
    * ``STOP``: in the beam, shows its image and stops it: the monitors after
      it see no beam, nothing leaves the line
    """
    OUT = 0
    OBSERVE = 1
    STOP = 2


#: as the twin's screens did before they had a mode
DEFAULT_SCREEN_MODE = ScreenMode.OBSERVE
#: record id of the artificial screen (``TL:screen:...``): at any element of the line
ARTIFICIAL_SCREEN = "screen"


def _screen_records(builder, record_id: str, pv: str, geometry: ScreenGeometry) -> Dict[ReadCommand, RecordWrapper]:
    """a screen's beam centre, size and image; PVs ``<pv>:x``, ..., records keyed by ``record_id``"""
    d = dict()
    for plane in PLANES:
        d[ReadCommand(id=record_id, property=plane)] = builder.aIn(f"{pv}:{plane}", initial_value=0.0, PREC=6, EGU="mm")
        d[ReadCommand(id=record_id, property=f"sigma_{plane}")] = builder.aIn(
            f"{pv}:sigma:{plane}", initial_value=0.0, PREC=6, EGU="mm"
        )
    d[ReadCommand(id=record_id, property="image")] = builder.WaveformIn(
        f"{pv}:image", initial_value=np.zeros(geometry.width * geometry.height),
    )
    d[ReadCommand(id=record_id, property="image_width")] = builder.longIn(f"{pv}:image:width", initial_value=geometry.width)
    d[ReadCommand(id=record_id, property="image_height")] = builder.longIn(
        f"{pv}:image:height", initial_value=geometry.height
    )
    d[ReadCommand(id=record_id, property="image_pixel")] = builder.aIn(
        f"{pv}:image:pixel", initial_value=geometry.pixel, PREC=4, EGU="mm"
    )
    return d


#: the records the view fills for the artificial screen
ARTIFICIAL_SCREEN_RECORDS = {ReadCommand(id="screen", property=p) for p in ("x", "y", "sigma_x", "sigma_y", "image")}


def initialize_artificial_screen_pvs(
    view: "TransferLineView", builder=softioc_builder, geometry: ScreenGeometry = SCREEN
) -> Dict[ReadCommand, RecordWrapper]:
    """The artificial screen, under the model device (``TL:screen:...``): a
    screen at any element of the line, as the real ones (#76)

    * ``screen:element``: the element's name (empty: nowhere, the start); a
      name the line does not have exactly once rejects the write
    * ``screen:mode``: Out (the start), Observe or Stop (:class:`ScreenMode`)
    * ``screen:x`` / ``y``, ``screen:sigma:x`` / ``y``, ``screen:image``, ...: as a real screen's
    """

    def validate(record, value) -> bool:
        name = str(value).strip()
        return not name or view.elements.count(name) == 1

    d = _screen_records(builder, ARTIFICIAL_SCREEN, ARTIFICIAL_SCREEN, geometry)
    d[ReadCommand(id=ARTIFICIAL_SCREEN, property="element")] = builder.stringOut(
        f"{ARTIFICIAL_SCREEN}:element", initial_value=view.artificial_element or "", validate=validate,
        on_update=lambda value: view.set_artificial_screen(str(value).strip() or None),
    )
    d[ReadCommand(id=ARTIFICIAL_SCREEN, property="mode")] = builder.mbbOut(
        f"{ARTIFICIAL_SCREEN}:mode", *[mode.name.capitalize() for mode in ScreenMode],
        initial_value=int(view.artificial_mode), on_update=view.set_artificial_screen_mode,
    )
    return d


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
        d.update(_screen_records(builder, name, name, geometry))
    return d


def initialize_screen_mode_pvs(view: "TransferLineView", builder=softioc_builder) -> Dict[ReadCommand, RecordWrapper]:
    """``<screen>:mode``: Out, Observe or Stop (:class:`ScreenMode`), one per
    screen of ``view``; the line on its own follows at once, the injection
    twin's line at the next shot"""
    return {
        ReadCommand(id=name, property="mode"): builder.mbbOut(
            f"{name}:mode", *[mode.name.capitalize() for mode in ScreenMode],
            initial_value=int(view.screen_mode[name]),
            on_update=lambda value, name=name: view.set_screen_mode(name, value),
        )
        for name in view.screens
    }


def initialize_model_pvs(builder, view: "TransferLineView", *, n_elements: int) -> Dict[ReadCommand, RecordWrapper]:
    """The line's model: trajectory, optics, survey, and the beam's emittance
    (writable: the screens' images); under :data:`MODEL_DEVICE`, which the
    caller sets as the builder's device name (:func:`model_device`)"""
    d = {
        **initialize_survey_info_pvs(builder, n_elements=n_elements),
        **initialize_orbit_pvs(builder, n_elements=n_elements),
        **initialize_twiss_pvs(builder, n_elements=n_elements),
        **initialize_artificial_screen_pvs(view, builder=builder, geometry=view.screen),
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
        elements: Sequence[str] = (),
        **kwargs,
    ):
        """``elements``: the line's element names, where the artificial screen
        can be put (:meth:`set_artificial_screen`)"""
        # BPMs and striplines follow the trajectory (View.update_bpms), screens show an image
        super().__init__(bpms=[m for m in monitors if not is_screen(m)], **kwargs)
        self.monitors = set(monitors)
        self.screens = [m for m in monitors if is_screen(m)]
        self.screen_mode: Dict[str, ScreenMode] = {name: DEFAULT_SCREEN_MODE for name in self.screens}
        self.elements = list(elements)
        #: the artificial screen: a screen at any element of the line, none at start
        self.artificial_element: Optional[str] = None
        self.artificial_mode = ScreenMode.OUT
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
        track = self.stopped(track)
        super().update_monitors(track)
        self.update_screens(track)

    def stopped(self, track):
        """``track`` as far as the beam gets: after the first screen that
        stops it (``ScreenMode.STOP``) no beam (NaN); the screen itself sees it"""
        out, lost = [], False
        for pos in track:
            if lost:
                pos = _copy(pos)
                pos.x = pos.y = math.nan
            out.append(pos)
            lost = lost or self._stops_at(pos.fam_name)
        return out

    def _stops_at(self, name: str) -> bool:
        """a screen at element ``name`` stops the beam: a real one, or the artificial one"""
        return self.screen_mode.get(name) == ScreenMode.STOP or (
            name == self.artificial_element and self.artificial_mode == ScreenMode.STOP
        )

    def beam_stopped(self) -> bool:
        """a screen stops the beam: nothing leaves the line"""
        return any(mode == ScreenMode.STOP for mode in self.screen_mode.values()) or (
            self.artificial_element is not None and self.artificial_mode == ScreenMode.STOP
        )

    def set_artificial_screen(self, element: Optional[str]) -> None:
        """put the artificial screen at ``element`` (None or empty: nowhere);
        ValueError unless the line has exactly one element of that name"""
        element = element or None
        if element is not None and self.elements.count(element) != 1:
            raise ValueError(
                f"artificial screen at {element!r}: expected one element of that name, found {self.elements.count(element)}"
            )
        self.artificial_element = element
        self._refresh_monitors()

    def set_artificial_screen_mode(self, mode) -> None:
        self.artificial_mode = ScreenMode(int(mode))
        self._refresh_monitors()

    def set_screen_mode(self, name: str, mode) -> None:
        """ValueError for a name that is no screen of this line or an unknown mode"""
        if name not in self.screen_mode:
            raise ValueError(f"{name}: no screen of this line")
        self.screen_mode[name] = ScreenMode(int(mode))
        self._refresh_monitors()

    def fire(self) -> bool:
        """A shot passes the line: the monitors show the latest trajectory

        False if there is no trajectory yet.
        """
        if self.trajectory is None:
            return False
        trajectory = self.stopped(self.trajectory)
        super().update_monitors(trajectory)
        self.update_screens(trajectory)
        return True

    def update_screens(self, track) -> None:
        """The screens' images: the beam centre from ``track``, its size from
        the emittance and the latest optics"""
        centre = {pos.fam_name: (pos.x, pos.y) for pos in track}
        twiss = self.last_data_cache.get(TWISS)
        beta = {pos.fam_name: (pos.x.beta, pos.y.beta) for pos in twiss.twiss} if twiss is not None else {}
        for name in self.screens:
            if name in centre:
                self._show_screen(name, name, self.screen_mode[name], centre, beta)
        if ARTIFICIAL_SCREEN_RECORDS.issubset(self.process_variables):
            self._show_screen(ARTIFICIAL_SCREEN, self.artificial_element, self.artificial_mode, centre, beta)

    def _show_screen(self, record_id: str, element: Optional[str], mode: ScreenMode, centre, beta) -> None:
        """a screen's records (``record_id``): the beam at ``element``"""
        xy = [v * M2MM for v in centre.get(element, (math.nan, math.nan))]
        sigma = [
            beam_size(self.emittance[plane], b) * M2MM if b is not None else float("nan")
            for plane, b in zip(PLANES, beta.get(element, (None, None)))
        ]
        if mode == ScreenMode.OUT or not all(math.isfinite(v) for v in xy):
            # retracted, nowhere, or no beam reaches it: no spot, a dark image
            xy = sigma = [math.nan, math.nan]
        for plane, c, s in zip(PLANES, xy, sigma):
            self._set(record_id, plane, c)
            self._set(record_id, f"sigma_{plane}", s)
        self._set(record_id, "image", screen_image(*xy, *sigma, geometry=self.screen).ravel())

    def _set(self, name: str, prop: str, value) -> None:
        rec = self.process_variables.get(ReadCommand(id=name, property=prop))
        if rec is not None:
            rec.set(value)

    def _refresh_monitors(self) -> None:
        """The line on its own: monitors and screens follow a screen's mode at
        once; single pass: at the next shot"""
        if self.single_pass:
            return
        track = self.last_data_cache.get(TRACK)
        if track is not None:
            self.update_monitors(track.track)

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
