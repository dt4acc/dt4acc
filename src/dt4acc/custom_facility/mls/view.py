"""EPICS view of the MLS storage ring: as the BESSY II ring, plus a reading
per BPM as on the machine (``<bpm>:rdX``, ``<bpm>:rdY`` in mm)"""
from typing import Dict, Sequence

from softioc import builder as softioc_builder
from softioc.pythonSoftIoc import RecordWrapper

from dt4acc.custom_epics.ioc.view import View
from dt4acc_lib.model.utils.command import ReadCommand

#: MML: BPMx / BPMy Monitor.ChannelNames
BPM_FIELDS = (("x", "rdX"), ("y", "rdY"))


def initialize_bpm_pvs(names: Sequence[str], builder=softioc_builder) -> Dict[ReadCommand, RecordWrapper]:
    """``<bpm>:rdX`` and ``<bpm>:rdY``: closed orbit at the BPM [mm]"""
    return {
        ReadCommand(id=name, property=plane): builder.aIn(f"{name}:{field}", initial_value=0.0, PREC=6, EGU="mm")
        for name in names
        for plane, field in BPM_FIELDS
    }


class MLSView(View):
    def __init__(self, *, bpms: Sequence[str], **kwargs):
        super().__init__(**kwargs)
        self.bpms = set(bpms)

    def update_track(self, var: ReadCommand, pkg):
        super().update_track(var, pkg)
        (single_reading,) = pkg.readings
        for pos in single_reading.payload.track:
            if pos.fam_name not in self.bpms:
                continue
            self.process_variables[ReadCommand(id=pos.fam_name, property="x")].set(pos.x * 1e3)
            self.process_variables[ReadCommand(id=pos.fam_name, property="y")].set(pos.y * 1e3)
