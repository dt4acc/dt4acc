"""EPICS view of a transfer line

A line has no tune and no master clock: twiss updates only the optics
waveforms. Each monitor gets its own readings of the trajectory.
"""
from typing import Dict, Sequence

from softioc import builder as softioc_builder
from softioc.pythonSoftIoc import RecordWrapper

from dt4acc.custom_epics.ioc.view import View
from dt4acc_lib.model.utils.command import ReadCommand


def initialize_monitor_pvs(names: Sequence[str], builder=softioc_builder) -> Dict[ReadCommand, RecordWrapper]:
    """``<monitor>:x`` and ``<monitor>:y``: trajectory at the monitor [mm]"""
    d = dict()
    for name in names:
        for plane in ("x", "y"):
            d[ReadCommand(id=name, property=plane)] = builder.aIn(
                f"{name}:{plane}", initial_value=0.0, PREC=6, EGU="mm"
            )
    return d


class TransferLineView(View):
    def __init__(self, *, monitors: Sequence[str], **kwargs):
        super().__init__(**kwargs)
        self.monitors = set(monitors)

    def update_special_values(self, var: ReadCommand, value) -> bool:
        if var.id == "twiss":
            self.update_twiss(var, value)
            return True
        return super().update_special_values(var, value)

    def update_track(self, var: ReadCommand, pkg):
        super().update_track(var, pkg)
        (single_reading,) = pkg.readings
        for pos in single_reading.payload.track:
            if pos.fam_name not in self.monitors:
                continue
            self.process_variables[ReadCommand(id=pos.fam_name, property="x")].set(pos.x * 1e3)
            self.process_variables[ReadCommand(id=pos.fam_name, property="y")].set(pos.y * 1e3)
