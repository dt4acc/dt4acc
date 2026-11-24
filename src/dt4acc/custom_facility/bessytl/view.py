"""EPICS view of a transfer line

A line has no tune and no master clock: twiss updates only the optics
waveforms. Each monitor gets its own readings of the trajectory: BPMs and
striplines as the BPM system (``<bpm>:signal:sa:X`` / ``Y``,
:mod:`dt4acc.custom_epics.ioc.bpm_pvs`), screens ``<screen>:x`` / ``y``.

Single pass (``single_pass=True``): a line carries beam only during a shot.
Its monitors are triggered by the shot and keep its reading until the next
one; screens show the beam only while it passes. So the model (trajectory,
optics: ``beam:orbit:*``, ``beam:twiss:*``, ``ORBITCC:rdModel``) follows
every change, but the monitors (``<bpm>:signal:sa:*``, ``<screen>:x`` / ``y``,
``ORBITCC:rdBpm``) only show the trajectory when a shot is fired
(:meth:`TransferLineView.fire`). Without it (the transfer line twin on its
own) the monitors follow every change, as before.
"""
from typing import Dict, Optional, Sequence

from softioc import builder as softioc_builder
from softioc.pythonSoftIoc import RecordWrapper

from dt4acc.custom_epics.ioc.bpm_pvs import SA_FIELDS
from dt4acc.custom_epics.ioc.view import View
from dt4acc_lib.model.utils.command import ReadCommand


def is_screen(name: str) -> bool:
    """a fluorescent screen (``FOMZ...``), not a BPM"""
    return name.startswith("FOMZ")


def initialize_monitor_pvs(names: Sequence[str], builder=softioc_builder) -> Dict[ReadCommand, RecordWrapper]:
    """trajectory at the monitor [mm]: ``<bpm>:signal:sa:X`` / ``Y`` (BPMs,
    striplines), ``<screen>:x`` / ``y`` (screens)"""
    d = dict()
    for name in names:
        fields = (("x", "x"), ("y", "y")) if is_screen(name) else SA_FIELDS
        for plane, field in fields:
            d[ReadCommand(id=name, property=plane)] = builder.aIn(
                f"{name}:{field}", initial_value=0.0, PREC=6, EGU="mm"
            )
    return d


class TransferLineView(View):
    def __init__(self, *, monitors: Sequence[str], single_pass: bool = False, **kwargs):
        # every monitor's records follow the trajectory (View.update_bpms)
        super().__init__(bpms=monitors, **kwargs)
        self.monitors = set(monitors)
        self.single_pass = single_pass
        #: single pass: the latest trajectory, what the next shot will show
        self.trajectory: Optional[Sequence] = None

    def update_monitors(self, track) -> None:
        if self.single_pass:
            self.trajectory = track
            return
        super().update_monitors(track)

    def fire(self) -> bool:
        """A shot passes the line: the monitors show the latest trajectory

        False if there is no trajectory yet.
        """
        if self.trajectory is None:
            return False
        super().update_monitors(self.trajectory)
        return True

    def update_special_values(self, var: ReadCommand, value) -> bool:
        if var.id == "twiss":
            self.update_twiss(var, value)
            return True
        return super().update_special_values(var, value)
