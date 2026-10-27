from typing import Callable, Dict, Sequence, Union, TypeVar

import numpy as np
import numpy.typing as npt
from softioc.pythonSoftIoc import RecordWrapper

from dt4acc.core.interfaces.controller_interface import ControllerInterface
from dt4acc.core.model.view import Monitor, Setpoint
from dt4acc.core.utils.logger import get_logger
from dt4acc_lib.model.output.result import ReadTogetherAndTranslated
from dt4acc_lib.model.utils.command import ReadCommand, Command, BehaviourOnError

logger = get_logger()

T = TypeVar("T")


def handle_returned_data(
    pkg: ReadTogetherAndTranslated, returned_data_type: str, force_type: Callable[[T], T]
) -> T:
    if returned_data_type == "single":
        return unpack_translated_reading_expecting_single_value(pkg, force_type)
    elif returned_data_type == "average":
        return unpack_translated_reading_calculate_average(pkg, force_type)
    else:
        raise AssertionError(
            f"Not prepared to handle returned_data {returned_data_type}"
        )


class NotSingleReading(Exception):
    pass


def unpack_translated_reading_expecting_single_value(
    pkg: ReadTogetherAndTranslated,
    force_type: Callable[[T], T]
) -> T:
    (translated,) = pkg.data
    L = len(translated.readings)
    if L != 1:
        raise NotSingleReading(
            f"received pkg of {L} items; request: {translated.cmd}"
            f", returned: {[r.cmd for r in translated.readings]}"
        )
    (expected_single,) = translated.readings
    val = force_type(expected_single.payload)
    return val


def unpack_translated_reading_calculate_average(
    pkg: ReadTogetherAndTranslated,
    force_type: Callable[[T], T]
) -> T:
    if len(pkg.data) == 1:
        # Todo: consider if this options should be here
        try:
            return unpack_translated_reading_expecting_single_value(pkg, force_type)
        except NotSingleReading as nsr:
            logger.info("pkg %s: was not a single reading %s", pkg.data[0].cmd, nsr)

    values = []
    for translated in pkg.data:
        # Todo: review if there should be more than one returned
        #       happens now for dx, but has to be analysed if that
        #       is what should happen ...
        # (expected_single,) = translated.readings
        for single in translated.readings:
            val = force_type(single.payload)
            values.append(val)

    val = np.mean(values)
    return force_type(val)


class PotentialLoopError(Exception):
    """Avoid calling us back again

    The read command is used as an index in the view to the record

    A setpoint specifies a read command that shall be used to create
    the appropriate Command to update the simulation. If the same
    command is in the list of reads, the setpoint will be updated
    when the result are dispachted to view.dispatch

    This will create an infinite loop
    """
    pass


async def build_ao_record(
    builder, model: Setpoint, controller: ControllerInterface
) -> RecordWrapper:
    initial_val = handle_returned_data(
        await controller.trigger_read([model.rcmd]), model.treat_returned_data, float
    )
    # don't forget the ones that should be updated
    # when this changes: e.g. read backs from power converters
    # but be aware: don't call the rcmd that is used as basis
    # to build the Command passed to update
    #
    # This command will then be received by view: the value will
    # be updated and everything starts all over again
    #
    # So only use the extra ones
    reads = model.reads or []
    if model.rcmd in reads:
        raise PotentialLoopError(
            f"For setpoint {model.pv_name} potential infinite loop detected:"
            f"{model.rcmd} is in (model) reads {reads}"
        )

    async def update(val: float):
        return await controller.update(
            cmd=Command(
                id=model.rcmd.id,
                property=model.rcmd.property,
                value=val,
                behaviour_on_error=BehaviourOnError.ignore,
            ),
            reads=reads,
            delayed_reads=[],
        )

    rec = builder.aOut(
        model.pv_name, initial_value=initial_val, on_update=update, PREC=model.prec, always_update=model.always_update
    )
    return rec


async def build_ai_record(builder, model: Monitor, controller: ControllerInterface):
    if model.update == "delayed":
        initial_val = np.nan
    else:
        initial_val = handle_returned_data(
            await controller.trigger_read([model.rcmd]), model.treat_returned_data, float
        )
    rec = builder.aIn(
        model.pv_name,
        initial_value=initial_val,
        PREC=model.prec,
    )
    return rec

async def build_longout_record(builder, model: Setpoint, controller: ControllerInterface):
    reads = model.reads or []
    if model.rcmd in reads:
        raise PotentialLoopError(
            f"For setpoint {model.pv_name} potential infinite loop detected:"
            f"{model.rcmd} is in (model) reads {reads}"
        )

    initial_val = handle_returned_data(
        await controller.trigger_read([model.rcmd]), model.treat_returned_data, int
    )

    async def update(val: int):
        return await controller.update(
            cmd=Command(
                id=model.rcmd.id,
                property=model.rcmd.property,
                value=val,
                behaviour_on_error=BehaviourOnError.ignore,
            ),
            reads=reads,
            delayed_reads=[],
        )

    rec = builder.longOut(
        model.pv_name, initial_value=initial_val, on_update=update, always_update=model.always_update
    )
    return rec


def check_float_vector(inp: Sequence[float]) -> npt.NDArray[np.floating]:
    return np.asarray(inp, dtype=float)


def check_string_vector(inp: Sequence[str]) -> Sequence[str]:
    return [str(v) for v in inp]



async def build_waveform_in_record(builder, model: Monitor, controller: ControllerInterface):
    """
    Currently only handling float array
    """
    if model.update == "delayed":
        initial_val = [np.nan]
        length = model.default_waveform_length
    else:
        # Warning: this path has not been used yet!
        initial_val = handle_returned_data(
            await controller.trigger_read([model.rcmd]), model.treat_returned_data, check_float_vector
        )
        length = max(initial_val, model.default_waveform_length)
    rec =  builder.WaveformIn(
        model.pv_name,
        initial_value=initial_val,
        length=length,
    )
    return rec


async def build_waveform_out_record(
        builder, model: Setpoint, controller: ControllerInterface, type: str
):
    reads = model.reads or []
    if model.rcmd in reads:
        raise PotentialLoopError(
            f"For setpoint {model.pv_name} potential infinite loop detected:"
            f"{model.rcmd} is in (model) reads {reads}"
        )

    if type == "float":
        check = check_float_vector
    elif type == "str":
        check = check_string_vector
    else:
        raise AssertionError(f"Unknown type {type}")

    initial_val = handle_returned_data(
        await controller.trigger_read([model.rcmd]), model.treat_returned_data, check
    )

    async def update(val: int):
        return await controller.update(
            cmd=Command(
                id=model.rcmd.id,
                property=model.rcmd.property,
                value=val,
                behaviour_on_error=BehaviourOnError.ignore,
            ),
            reads=reads,
            delayed_reads=[],
        )

    if type == "str":
        if initial_val == []:
             initial_val = [""]

    try:
        rec = builder.WaveformOut(
            model.pv_name, initial_value=initial_val, on_update=update, length=model.default_waveform_length, always_update=model.always_update
        )
    except ValueError as ve:
        raise ve
    return rec


async def build_waveform_out_record_string(builder, model: Setpoint, controller: ControllerInterface):
    return await build_waveform_out_record(builder, model, controller, type="str")


async def build_waveform_out_record_float(builder, model: Setpoint, controller: ControllerInterface):
    return await build_waveform_out_record(builder, model, controller, type="float")


factory = {
    "ai": build_ai_record,
    "ao": build_ao_record,
    "longout": build_longout_record,
    "waveform_in[float]": build_waveform_in_record,
    "waveform_out[str]": build_waveform_out_record_string,
    "waveform_out[float]": build_waveform_out_record_float,
}


async def initialize_pvs_from_model(
    builder,
    models: Sequence[Union[Setpoint, Monitor]],
    controller: ControllerInterface,
) -> Dict[ReadCommand, RecordWrapper]:
    """initialise pvs based on their Setpoint or Monitor model

    Ignore pvs that can not be instantiated

    Todo:
        is that a good idea ?
    """

    async def instantiate(model):
        f = factory[model.record_type]
        rec = None
        try:
            rec = await f(builder, model, controller)
        except ValueError as ve:
            logger.error("Could not instantiate %s due to value error %s", model, ve)
            raise ve
        except KeyError as ke:
            logger.warning("Could not instantiate %s due to key error %s", model, ke)
        except PotentialLoopError as loop_error:
            logger.warning("Could not instantiate %s due to potential loop %s", model, loop_error)
        return rec

    r = {model.get_pvid(): await instantiate(model) for model in models}
    r = {pvid: rec for pvid, rec in r.items() if rec is not None}
    return r


__all__ = ["initialize_pvs_from_model"]