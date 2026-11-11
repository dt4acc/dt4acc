"""
calculation_result_view.py
==========================

Pushes calculation results from the backend into the TANGO virtual devices
(TwissOrbitDevice, BPMManagerDevice, TuneDevice) via DeviceProxy.

This module is protocol-agnostic with respect to the source objects — it only
cares about duck-typed attribute access:

    push_orbit(orbit_result):
        orbit_result.x      : array-like of float  (all elements, ordered)
        orbit_result.y      : array-like of float
        orbit_result.names  : list[str]

    push_twiss(twiss_result):
        twiss_result.x.alpha : array-like of float
        twiss_result.x.beta  : array-like of float
        twiss_result.x.nu    : array-like of float
        twiss_result.y.alpha : array-like of float
        twiss_result.y.beta  : array-like of float
        twiss_result.y.nu    : array-like of float

    push_tune(tune_result):
        tune_result.x        : float
        tune_result.y        : float

Callers pass adapter objects (e.g. _OrbitAdapter, _TwissAdapter from
tango_controller.py) that provide the right shape from the new accml_lib
backend types. No old dt4acc.core model classes are required.
"""

import asyncio

import numpy as np
from tango import DeviceProxy

from dt4acc.custom_tango.ioc.mexec_config import SIMULATOR_DEVICE
from dt4acc.core.utils.logger import get_logger

logger = get_logger()


def to_float_list(x) -> list[float]:
    """
    Convert anything array-like to a 1D Python list of Python floats.
    Also sanitizes NaN/inf to 0.0.
    """
    arr = np.asarray(x, dtype=np.float64).ravel()
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return [float(v) for v in arr]


async def update_orbit_dev(dev_name: str, orbit_result) -> None:
    """
    Push orbit x/y arrays to TwissOrbitDevice via commands.

    orbit_result must have:
        .x      : array-like of float
        .y      : array-like of float
    """
    device = DeviceProxy(dev_name)
    x_payload = to_float_list(orbit_result.x)
    y_payload = to_float_list(orbit_result.y)

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None, lambda: device.command_inout("push_orbit_x", x_payload)
        )
    except Exception as exc:
        logger.error("push_orbit_x FAILED for %s: %s", dev_name, exc)
        raise

    try:
        await loop.run_in_executor(
            None, lambda: device.command_inout("push_orbit_y", y_payload)
        )
    except Exception as exc:
        logger.error("push_orbit_y FAILED for %s: %s", dev_name, exc)
        raise


async def update_bpms_dev(dev_name: str, orbit_result) -> None:
    """
    Filter orbit_result to BPM elements and push to BPMManagerDevice.

    orbit_result must have:
        .names  : list[str]
        .x      : array-like of float
        .y      : array-like of float

    BPM elements are identified by name starting with 'BPM' (case-insensitive).
    """
    names = list(orbit_result.names)
    x = to_float_list(orbit_result.x)
    y = to_float_list(orbit_result.y)

    bpm_mask = [n.upper().startswith("BPM") or n.upper().startswith("FBPM")
                for n in names]
    bpm_names = [n for n, keep in zip(names, bpm_mask) if keep]
    bpm_x     = [v for v, keep in zip(x,     bpm_mask) if keep]
    bpm_y     = [v for v, keep in zip(y,     bpm_mask) if keep]

    if not bpm_names:
        logger.warning("update_bpms_dev: no BPM elements found in orbit result")
        return

    device = DeviceProxy(dev_name)
    loop = asyncio.get_running_loop()

    await loop.run_in_executor(
        None, lambda: device.write_attribute("bpm_names_attr", bpm_names)
    )
    await loop.run_in_executor(
        None, lambda: device.write_attribute("bpm_x_attr", bpm_x)
    )
    await loop.run_in_executor(
        None, lambda: device.write_attribute("bpm_y_attr", bpm_y)
    )


async def update_twiss_dev(dev_name: str, twiss_result) -> None:
    """
    Push twiss arrays to TwissOrbitDevice via commands.

    twiss_result must have:
        .x.alpha, .x.beta, .x.nu : array-like of float
        .y.alpha, .y.beta, .y.nu : array-like of float
    """
    device = DeviceProxy(dev_name)

    alpha_x = to_float_list(twiss_result.x.alpha)
    beta_x  = to_float_list(twiss_result.x.beta)
    nu_x    = to_float_list(twiss_result.x.nu)
    alpha_y = to_float_list(twiss_result.y.alpha)
    beta_y  = to_float_list(twiss_result.y.beta)
    nu_y    = to_float_list(twiss_result.y.nu)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: device.command_inout("push_alpha_x", alpha_x))
    await loop.run_in_executor(None, lambda: device.command_inout("push_beta_x",  beta_x))
    await loop.run_in_executor(None, lambda: device.command_inout("push_nu_x",    nu_x))
    await loop.run_in_executor(None, lambda: device.command_inout("push_alpha_y", alpha_y))
    await loop.run_in_executor(None, lambda: device.command_inout("push_beta_y",  beta_y))
    await loop.run_in_executor(None, lambda: device.command_inout("push_nu_y",    nu_y))


async def update_tune_dev(dev_name: str, tune_result) -> None:
    """
    Push tune scalars to RingSimulatorDevice via push_tune command.
    hor/vert are read-only attributes — values are pushed via command.

    tune_result must have:
        .x : float  (horizontal tune)
        .y : float  (vertical tune)
    """
    device = DeviceProxy(dev_name)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: device.command_inout("push_tune", [float(tune_result.x), float(tune_result.y)])
    )


class CalculationResultView:
    """
    Pushes calculation results to TANGO virtual devices.

    Expects duck-typed objects — see module docstring for the required interface.
    No dependency on old dt4acc.core model classes (Orbit, TwissWithAggregatedKValues).
    Use adapter objects from tango_controller.py to bridge new accml_lib types.
    """

    def __init__(self, *, prefix: str):
        self.prefix = prefix

    def _twiss_orbit_dev(self) -> str:
        return SIMULATOR_DEVICE

    def _bpm_dev(self) -> str:
        return SIMULATOR_DEVICE

    def _tune_dev(self) -> str:
        return SIMULATOR_DEVICE

    async def push_orbit(self, orbit_result) -> None:
        """
        Push orbit x/y to TwissOrbitDevice and BPM data to BPMManagerDevice.

        orbit_result must have: .x, .y (flat arrays), .names (list[str])
        """
        try:
            await update_orbit_dev(self._twiss_orbit_dev(), orbit_result)
        except Exception as exc:
            logger.warning("Orbit push failed: %s", exc)
            raise

        try:
            await update_bpms_dev(self._bpm_dev(), orbit_result)
        except Exception as exc:
            logger.warning("BPM push failed: %s", exc)
            # Don't raise — BPM failure should not block orbit publishing

    async def push_twiss(self, twiss_result) -> None:
        """
        Push twiss arrays to TwissOrbitDevice.

        twiss_result must have: .x.alpha/beta/nu and .y.alpha/beta/nu (flat arrays)
        """
        if twiss_result is None:
            return
        await update_twiss_dev(self._twiss_orbit_dev(), twiss_result)

    async def push_tune(self, tune_result) -> None:
        """
        Push tune scalars to TuneDevice.

        tune_result must have: .x (float), .y (float)
        """
        if tune_result is None:
            return
        await update_tune_dev(self._tune_dev(), tune_result)

    async def push_chromaticity(self, chroma_result) -> None:
        """Push chromaticity (xi_x, xi_y) to RingSimulatorDevice."""
        if chroma_result is None:
            return
        device = DeviceProxy(self._tune_dev())  # same device — ringsimulator
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: device.command_inout(
                "push_chromaticity",
                [float(chroma_result.x), float(chroma_result.y)]
            )
        )

    async def push_value(self, elm_update) -> None:
        """Element update — no-op for now."""
        pass

    async def push_invalid(self) -> None:
        """
        Push sentinel values to all virtual devices to signal beam loss.

        Uses zeros/empty arrays instead of NaN because:
        - Tango READ_WRITE attributes reject NaN (API_WAttrOutsideLimit)
        - TwissOrbitDevice is in the same process — DeviceProxy causes
          thread lock conflict (serialization monitor). TwissOrbitDevice
          has push_change_event which works in-process via the event system.

        For TwissOrbitDevice we push a single-element zero array so clients
        can detect the length change (4238 elements → 1) as a beam-loss signal.
        BPM and Tune get zeros.
        """
        loop = asyncio.get_running_loop()
        zero_arr = [0.0]

        # TwissOrbitDevice — push via commands (same process, different thread,
        # but command_inout can deadlock). Use a short timeout and swallow errors.
        # Note: push_orbit_x/y are included here — individual BPMDevices subscribe
        # to orbit_x/y change events and will receive zeros automatically.
        try:
            dev = DeviceProxy(self._twiss_orbit_dev())
            dev.set_timeout_millis(500)
            for cmd in ("push_orbit_x", "push_orbit_y",
                        "push_beta_x",  "push_beta_y",
                        "push_alpha_x", "push_alpha_y",
                        "push_nu_x",    "push_nu_y"):
                try:
                    await loop.run_in_executor(
                        None, lambda c=cmd: dev.command_inout(c, zero_arr))
                except Exception:
                    pass  # best-effort — don't block on monitor contention
        except Exception as exc:
            logger.debug("push_invalid: TwissOrbitDevice push failed: %s", exc)

        # TuneDevice — push via command (hor/vert are read-only attributes)
        try:
            tune = DeviceProxy(self._tune_dev())
            await loop.run_in_executor(
                None, lambda: tune.command_inout("push_tune", [0.0, 0.0]))
            await loop.run_in_executor(
                None, lambda: tune.command_inout("push_chromaticity", [0.0, 0.0]))
        except Exception as exc:
            logger.debug("push_invalid: TuneDevice push failed: %s", exc)