"""BPM PVs of the EPICS twins, named as the machine's BPM system

* ``<bpm>:signal:sa:X``, ``<bpm>:signal:sa:Y``: position at the BPM [mm]
  (slow acquisition: the closed orbit of a ring, the trajectory of a line)
* ``<bpm>:signal:tbt:X``, ``<bpm>:signal:tbt:Y``: position at the BPM, turn
  after turn [mm]
* ``<bpm>:signal:tbt:survived``: particles still there at the BPM, turn after turn

The view keys the slow acquisition records ``ReadCommand(<bpm>, "x" / "y")``
and fills them from the track (:meth:`View.update_track`).
"""
from typing import Dict, Sequence

from softioc import builder as softioc_builder
from softioc.pythonSoftIoc import RecordWrapper

from dt4acc_lib.model.utils.command import ReadCommand

#: plane, PV field: slow acquisition
SA_FIELDS = (("x", "signal:sa:X"), ("y", "signal:sa:Y"))
#: plane, PV field: turn by turn
TBT_FIELDS = (("x", "signal:tbt:X"), ("y", "signal:tbt:Y"))
TBT_SURVIVED_FIELD = "signal:tbt:survived"
#: m -> mm: the model's positions [m] to the BPM PVs' [mm]
#: Todo: revisit how the BPM and turn by turn data are converted (e.g. when
#:       doing it for SOLEIL): with the translation service's objects, as
#:       the supplies and magnets, instead of a fixed factor here
M2MM = 1e3


def initialize_bpm_pvs(names: Sequence[str], builder=softioc_builder) -> Dict[ReadCommand, RecordWrapper]:
    """``<bpm>:signal:sa:X`` and ``<bpm>:signal:sa:Y``: position at the BPM [mm]"""
    return {
        ReadCommand(id=name, property=plane): builder.aIn(f"{name}:{field}", initial_value=0.0, PREC=6, EGU="mm")
        for name in names
        for plane, field in SA_FIELDS
    }


__all__: Sequence[str] = ["M2MM", "SA_FIELDS", "TBT_FIELDS", "TBT_SURVIVED_FIELD", "initialize_bpm_pvs"]
