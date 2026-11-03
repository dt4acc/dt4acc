"""EPICS view of the MLS storage ring: as the BESSY II ring, plus the slow
acquisition per BPM (``<bpm>:signal:sa:X``, ``<bpm>:signal:sa:Y`` in mm,
:mod:`dt4acc.custom_epics.ioc.bpm_pvs`)"""
from typing import Sequence

from dt4acc.custom_epics.ioc.bpm_pvs import initialize_bpm_pvs
from dt4acc.custom_epics.ioc.view import View


class MLSView(View):
    def __init__(self, *, bpms: Sequence[str], **kwargs):
        super().__init__(bpms=bpms, **kwargs)


__all__ = ["MLSView", "initialize_bpm_pvs"]
