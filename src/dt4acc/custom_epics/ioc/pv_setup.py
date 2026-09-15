import math
from typing import Dict, Iterable

from softioc.pythonSoftIoc import RecordWrapper
import numpy as np

from dt4acc_lib.model.utils.command import ReadCommand, Command
from dt4acc.core.interfaces.controller_interface import ControllerInterface
from ..data.constants import config, special_pvs, cavity_names
from dt4acc.config.data.querries import (
    get_unique_magnet_power_converters,
    get_elements_per_power_converter,
)
from ...core.utils.logger import get_logger

logger = get_logger()


def flag_not_handling(pv_name: str, val: object):
    logger.warning("Not handling update of pv %s to %s", pv_name, val)


async def initialize_magnet_pvs(
    builder, magnet, controller: ControllerInterface
) -> Dict[ReadCommand, RecordWrapper]:
    """
    Initializes the process variables (PVs) for a given magnet.

    Args:
        builder: The SoftIOC PV builder instance.
        magnet (dict): Magnet properties including name, type, and magnetic strength.

    PVs Created:
        - `<magnet_name>:Cm:set`: Setpoint for magnetic field strength
        - `<magnet_name>:im:I`: Measured current of the magnet
        - `<magnet_name>:x:set`: Horizontal position setpoint
        - `<magnet_name>:y:set`: Vertical position setpoint
    """
    magnet_name = magnet["name"]
    # Create an element representing the magnet
    # Create PVs and link to update logic
    # Todo: howto handle steerers here?
    #       it should be not that
    #       should use liasion manager here too
    d = dict()

    # retrieve the reference value for start
    rcmd_for_ref = ReadCommand(id=magnet_name, property="main_strength")
    try:
        vals = await controller.trigger_read([rcmd_for_ref])
        (single,) = vals.all_readings()
        val = single.payload
    except KeyError as ke:
        logger.error(f"No look up for {rcmd_for_ref}, {ke}")
        val = np.nan

    rcmd_for_rdbk = ReadCommand(id=magnet_name, property="main_strength_rdbk")
    rdbk = builder.aIn(f"{magnet_name}:Cm:rdbk", initial_value=val)
    d[rcmd_for_rdbk] = rdbk
    d[rcmd_for_ref] = builder.aOut(
        f"{magnet_name}:Cm:set",
        initial_value=val,
        on_update=lambda val: handle_magnet_update(
            device_id=magnet_name, property_id="main_strength", value=val
        ),
    )

    d[ReadCommand(id=magnet_name, property="driving_current")] = builder.aOut(
        f"{magnet_name}:im:I",
        initial_value=0.0,
        # Todo: what to do if current is set, should be rather read only
        # on_update=lambda val: handle_device_update(f"{magnet_name}:im:I", val)
        on_update=lambda val: handle_magnet_update(
            magnet_name, "powersupply_current", val
        ),
    )

    async def handle_magnet_update(device_id: str, property_id: str, value: float):
        logger.info("%s:%s updating setpoint val=%s", device_id, property_id, value)
        r = await controller.update(
            cmd=Command(
                id=device_id, property=property_id, value=value, behaviour_on_error=None
            ),
            reads=[rcmd_for_rdbk],
            delayed_reads=[],
        )
        return r

    d[ReadCommand(id=magnet_name, property="x")] = builder.aOut(
        f"{magnet_name}:x:set",
        initial_value=0.0,
        on_update=lambda val: controller.update(
            cmd=Command(
                id=magnet_name, property="x", value=val, behaviour_on_error=None
            ),
            reads=[],
            delayed_reads=[],
        ),
    )
    d[ReadCommand(id=magnet_name, property="y")] = builder.aOut(
        f"{magnet_name}:y:set",
        initial_value=0.0,
        on_update=lambda val: controller.update(
            cmd=Command(
                id=magnet_name, property="y", value=val, behaviour_on_error=None
            ),
            reads=[],
            delayed_reads=[],
        ),
    )
    return d


async def initialize_power_converter_pvs(
    builder, controller: ControllerInterface
):
    """
    Initializes power converter PVs and associated magnets.

    Args:
        builder: The SoftIOC PV builder instance.
        prefix (str): The prefix used for PV naming.
    """
    d = dict()
    for pc_name in get_unique_magnet_power_converters():
        d.update(await add_pc_pvs(builder, pc_name, controller))
    return d


async def add_pc_pvs(
    builder, pc_name: str, controller: ControllerInterface
) -> Dict[str, RecordWrapper]:
    """
    Adds PVs for a specific power converter and its associated magnets.

    Args:
        builder: The SoftIOC PV builder instance.
        pc_name (str): Power converter name.
        prefix (str): Prefix for PVs.
    """
    magnets = get_elements_per_power_converter(pc_name)
    element = {"magnets": [item["name"] for item in magnets]}
    element_cache = {}  # Store magnet information for reference
    element_cache[pc_name] = element

    d = dict()
    # Initialize PVs for each magnet connected to this (pc_name) power converter
    for magnet_data in magnets:
        d.update(await initialize_magnet_pvs(builder, magnet_data, controller))

    # Create power converter setpoint and readback PVs
    # Todo: put it to power converters directly
    # Todo: add input data to config so that exception does not need to be
    #       handled
    try:
        vals = await controller.trigger_read([ReadCommand(pc_name, "set_current")])
        start_val = np.mean([v.payload for v in vals.all_readings()]).mean()
    except KeyError as ke:
        logger.warning(f"At startup peeking failed for {pc_name} 'set_current': {ke}")
        start_val = np.nan

    rdbk = builder.aOut(f"{pc_name}:rdbk", initial_value=start_val, PREC=2)
    d[ReadCommand(id=pc_name, property="rdbk_current")] = rdbk
    d[ReadCommand(id=pc_name, property="set_current")] = builder.aOut(
        f"{pc_name}:set",
        initial_value=start_val,
        on_update=lambda val: handle_pc_update(pc_name, "set_current", val),
        PREC=2,
    )

    async def handle_pc_update(device_id: str, property_id: str, value: float):
        logger.warning("%s:%s updating setpoint val=%s", device_id, property_id, value)
        r = await controller.update(
            cmd=Command(
                id=device_id, property=property_id, value=value, behaviour_on_error=None
            ),
            reads=[ReadCommand(id=pc_name, property="rdbk_current")],
            delayed_reads=[],
        )
        logger.debug("%s:%s updating rdbk val=%s", device_id, property_id, value)
        rdbk.set(value)
        return r

    return d


def initialize_orbit_pvs(
    builder, n_elements: int = config.n_elements
) -> Dict[ReadCommand, RecordWrapper]:
    """
    Initializes PVs related to beam orbit measurements.

    Args:
        builder: The SoftIOC PV builder instance.
        n_elements: Waveform length, sized to the loaded lattice. Defaults to
            the facility-wide constant used by BESSY II.
    """
    return {
        ReadCommand(id="beam", property="x"): builder.WaveformIn(
            f"beam:orbit:x", initial_value=[0.0], length=n_elements
        ),
        ReadCommand(id="beam", property="y"): builder.WaveformIn(
            f"beam:orbit:y", initial_value=[0.0], length=n_elements
        ),
        ReadCommand(id="beam", property="x0"): builder.WaveformIn(
            f"beam:orbit:x0", initial_value=[0.0], length=n_elements
        ),
        ReadCommand(id="beam", property="names"): builder.WaveformIn(
            f"beam:orbit:names", initial_value=[""], length=n_elements
        ),
        ReadCommand(id="beam", property="uids"): builder.WaveformIn(
            f"beam:orbit:uids", initial_value=[""], length=n_elements
        ),
        ReadCommand(id="beam", property="found"): builder.boolIn(
            f"beam:orbit:found", initial_value=False
        ),
    }


def initialize_tune_pvs(builder) -> Dict[ReadCommand, RecordWrapper]:
    d = dict()
    for axis, suffix in [("x", "rdH"), ("y", "rdV")]:
        d[ReadCommand(id="tune", property=f"flq_{axis}")] = builder.aOut(
            f"TUNEZR:flq:{suffix}", initial_value=0.0, PREC=9
        )
        d[ReadCommand(id="tune", property=f"{axis}")] = builder.aOut(
            f"TUNEZR:{suffix}", initial_value=0.0, PREC=3, EGU="kHz"
        )
    d[ReadCommand(id="tune", property="count")] = builder.longOut(
        f"TUNEZR:count", initial_value=0
    )
    return d


def initialize_twiss_pvs(builder, n_elements: int = config.n_elements):
    """
    Initializes PVs for Twiss parameters, which describe beam optics.

    Args:
        builder: The SoftIOC PV builder instance.
        n_elements: Waveform length, sized to the loaded lattice. Defaults to
            the facility-wide constant used by BESSY II.
    """
    d = dict()
    for axis in ["x", "y"]:
        d[ReadCommand("twiss", f"{axis}:alpha")] = builder.WaveformIn(
            f"beam:twiss:{axis}:alpha", initial_value=[0.0], length=n_elements
        )
        d[ReadCommand("twiss", f"{axis}:beta")] = builder.WaveformIn(
            f"beam:twiss:{axis}:beta", initial_value=[0.0], length=n_elements
        )
        d[ReadCommand("twiss", f"{axis}:nu")] = builder.WaveformIn(
            f"beam:twiss:{axis}:nu", initial_value=[0.0], length=n_elements
        )
        d[ReadCommand("twiss", f"{axis}:tune")] = builder.aIn(
            f"beam:twiss:{axis}:tune", initial_value=0.0, PREC=8
        )
    d[ReadCommand("twiss", "names")] = builder.WaveformIn(
        f"beam:twiss:names", initial_value=[""], length=n_elements
    )
    d[ReadCommand("twiss", "uids")] = builder.WaveformIn(
        f"beam:twiss:uids", initial_value=[""], length=n_elements
    )
    return d


def initialize_survey_info_pvs(
    builder, n_elements: int = config.n_elements
) -> Dict[ReadCommand, RecordWrapper]:
    return {
        ReadCommand(id="survey", property="s"): builder.WaveformIn(
            f"survey:s", initial_value=[0.0], EGU="m", length=n_elements
        ),
        ReadCommand(id="survey", property="names"): builder.WaveformIn(
            f"survey:names", initial_value=[""], length=n_elements
        ),
        ReadCommand(id="survey", property="uids"): builder.WaveformIn(
            f"survey:uids", initial_value=[""], length=n_elements
        ),
    }


def initialize_machine_info_pvs(
    builder, *, n_ref_buckets
) -> Dict[ReadCommand, RecordWrapper]:
    """configuration of the machine: e.g. number of bunches"""

    return {
        ReadCommand(id="ring", property="n_rf_buckets"): builder.longIn(
            # Todo: make this configureable ... this is 328 for ALS
            #       this data is accessible from AT
            f"beam:machine:info:n_rf_buckets",
            initial_value=n_ref_buckets,
        ),
        ReadCommand(id="ring", property="rev_freq"): builder.aIn(
            f"beam:rev_freq", initial_value=0.0, EGU="kHz"
        ),
    }


async def initialize_master_clock_pvs(
    builder, controller: ControllerInterface, master_clock_pv_name: str | None = None
) -> Dict[ReadCommand, RecordWrapper]:
    """initialise master clock pv

    Args:
        master_clock_pv_name: PV base name for the master clock. Defaults to
            ``special_pvs['master_clock']`` (a BESSY II legacy device name);
            facilities without a matching real device should pass an explicit
            lattice/catalog-independent name instead.

    Warning:
        note for running the twin as a shadow it will
        require precise frequency tuning

    Todo:
        Foresee dedicated variables for allowing only a difference shift
        Provide the frequency the code starts with
    """

    vals = await controller.trigger_read(
        [ReadCommand("master_clock", "reference_frequency")]
    )
    start_val = np.mean([v.payload for v in vals.all_readings()])

    pv_name = master_clock_pv_name if master_clock_pv_name is not None else special_pvs['master_clock']

    d = dict()

    d[ReadCommand(id="master_clock", property="freq")] = builder.aOut(
        f"{pv_name}:freq",
        initial_value=start_val,
        always_update=True,
        EGU="kHz",
        PREC=3,
        on_update=lambda val: controller.update(
            cmd=Command(
                id="master_clock",
                property="reference_frequency",
                value=val,
                behaviour_on_error=None,
            ),
            reads=[],
            delayed_reads=[],
        ),
    )

    #: todo ... comment these values
    d[ReadCommand(id="lattice_info", property="ref_freq")] = builder.aIn(
        "lattice_info:ref_freq", initial_value=start_val, EGU="kHz", PREC=1
    )
    d[ReadCommand(id="lattice_info", property="ref_freq:khz:up")] = builder.longIn(
        "lattice_info:ref_freq:khz:up", initial_value=int(start_val), EGU="kHz"
    )
    frac = (start_val % 1) * 1e6
    d[ReadCommand(id="lattice_info", property="ref_freq:khz:frac")] = builder.longIn(
        "lattice_info:ref_freq:khz:frac", initial_value=int(frac), EGU="mHz"
    )
    return d


def initialize_other_pvs(builder, current_pv_name: str | None = None) -> Dict[ReadCommand, RecordWrapper]:
    """Initialises miscellaneous PVs (dummy values).

    Args:
        builder: The SoftIOC PV builder instance.
        current_pv_name: PV base name for the beam current. Defaults to
            ``special_pvs['current']`` (a BESSY II legacy device name);
            facilities without a matching real device should pass an explicit
            lattice/catalog-independent name instead.
    """
    pv_name = current_pv_name if current_pv_name is not None else special_pvs['current']
    return {
        ReadCommand("ring", "current"): builder.aOut(
            f"{pv_name}:current", initial_value=0
        )
    }


def initialize_bpm_pvs_obsolete(builder):
    tmp = np.empty([2048], np.int16)
    tmp.fill(-(2 ** 15) + 1)
    # bpm pv names from default
    builder.WaveformOut(
        f"{special_pvs['bpm_pv']}:bdata", initial_value=tmp, length=len(tmp)
    )
    builder.longOut(f"{special_pvs['bpm_pv']}:count", initial_value=0)


def initialize_orbit_object_pvs(builder) -> Dict[ReadCommand, RecordWrapper]:
    """
    Todo:
        combine them to a data object
    """
    d = dict()
    n_bpms = 128
    tmp = np.ravel(np.empty([n_bpms, 2], float))
    tmp.fill(np.nan)
    d[ReadCommand("orbit", "pos")] = builder.WaveformIn(
        "ORBITCC:rdPos", initial_value=tmp, length=len(tmp)
    )
    tmp = np.ravel(np.empty([n_bpms, 4], float))
    tmp.fill(np.nan)
    d[ReadCommand("orbit", "buttons")] = builder.WaveformIn(
        "ORBITCC:rdButtons", initial_value=tmp, length=len(tmp)
    )
    d[ReadCommand("orbit", "bpm_names")] = builder.WaveformIn(
        "ORBITCC:rdBpmNames", initial_value=[""], length=n_bpms
    )
    d[ReadCommand("orbit", "count")] = builder.longIn("ORBITCC:count", initial_value=0)
    return d


async def initialize_cavity_pvs(
    builder, controller: ControllerInterface, cavity_names: Iterable[str] = cavity_names
):
    """
    Initializes PVs for RF cavities.

    Args:
        builder: The SoftIOC PV builder instance.
        cavity_names: RF cavity names to expose. Defaults to the BESSY II
            facility constant of the same name.

    Todo:
        check that these are updated if the master clock changes
    """
    vals = await controller.trigger_read(
        [ReadCommand("master_clock", "reference_frequency")]
    )
    start_val = np.mean([v.payload for v in vals.all_readings()]).mean()

    return {
        # cavity frequency is determined by master clock ... perhaps some
        # little shift for eigen frequency
        ReadCommand(id=cavity_name, property="freq"):
        builder.aIn(f"{cavity_name}:freq", initial_value=start_val, EGU="kHz", PREC=3)
        for cavity_name in cavity_names
    }
