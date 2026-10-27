"""Data model for instaniating the view

Warning: currently very EPICS specific
"""
from collections import defaultdict
from typing import Annotated, Literal, Sequence, Union

from pydantic import BaseModel, StringConstraints

from dt4acc_lib.model.utils.command import ReadCommand


EpicsPVCompatibleString = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9_\-:+\[\]<>.;]+$",
        min_length=1,
        max_length=60,
    ),
]


class _ProcessVariableView(BaseModel):
    """

    Todo:
        for EPICS following fields would be available too


    """

    rcmd: ReadCommand
    """the command that is used to retrieve the data"""

    pv_name: EpicsPVCompatibleString
    """the associated pv name of this process variable"""

    prec: int
    """number of digits"""

    update: Literal["immediate", "delayed"] = "immediate"
    """how shall the controller treat the read command?

    Most values will be updated immediately e.g. power converter
    readback or setpoint. Some will be delayed e.g. as
    beam position monitor.

    To explain in detail:
    * immediate:

        * for setpoints: as soon as the view will be changed the
          read command will be dispatched to the controller (as
          an update command)

        * For monitors: the read command will be used to retrieve
          the data

    * delayed:
        * the read commmand will be added to the delayed evaluations

    * never:
        * the controller shall ignore the read command given here
          something else (the view ?) takes care to fill these
          data
    Please note: this setting is (mainly) used at startup. Monitors
    (like power converter readback) can be read immediately at
    initialisation. Beam position data or Twiss data are typically
    obtained as delayed ones: these are derived from optics data.
    Optics calculation is on only performed after all setpoints
    have been set.

    Todo:
        review if it should be handled differently ?
        e.g. all BPM declare a read command of ['track', 'pos']
        then view dispatches it to them
        or converter object does it ...
    """

    treat_returned_data: Literal["single", "average"] = "single"
    """Process to apply for returned data

    * single: only a single value is returned
    * average: take the average of all returned data
    """

    default_waveform_length: int = -1
    """waveform default length

    Note: only evaluated for waveforms! must be specified explicitly!
          for waveforms

    Ignored for other record types

    """

    device_suffix: str = ""
    """Use a device suffix to encode some extra info

    Result of using ReadCommand as lookup for the process variable

    Todo:
        fix this hack!
    """

    def get_pvid(self) -> ReadCommand:
        if self.device_suffix:
            return ReadCommand(
                f"{self.rcmd.id}:{self.device_suffix}", self.rcmd.property
            )
        return self.rcmd


class Monitor(_ProcessVariableView):
    """A process variable that is read"""

    record_type: Literal["ai", "longin", "waveform_in[float]"]


class Setpoint(_ProcessVariableView):
    """a process variable that can also be set"""

    record_type: Literal["ao", "longout", "waveform_out[str]", "waveform_out[float]"]
    always_update: bool = False
    reads: Sequence[ReadCommand]
    """Which reads to add to dispatch to the controller when the update is made

    For example:

           when a power converter setpoint is set, the
           associated readback shall be read back too.
    """


class ProcessVariableCollection(BaseModel):
    """A collection of process variables

    simplifying storage
    """

    vars: Sequence[Union[Monitor, Setpoint]]

    def get_pv_name_clashes(self):
        d = defaultdict(list)
        for var in self.vars:
            d[var.pv_name].append(var)
        return {k: v for k, v in d.items() if len(v) > 1}


__all__ = ["Monitor", "Setpoint"]
