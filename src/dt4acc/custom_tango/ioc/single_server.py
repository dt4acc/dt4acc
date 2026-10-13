#!/usr/bin/env python3
"""
single_server.py
================

Entry point for each Tango server process.

Responsibilities
----------------
1. Connect to MexecService via multiprocessing.managers and get a SyncMexecProxy.
2. Wrap it in AsyncMexecAdapter so Tango devices and TangoController can
   `await mexec.set()` / `await mexec.trigger_read()` as if mexec were local.
3. Build a TangoController and store it in a process-global so device
   write-handlers can reach it via get_controller().
4. Call tango.server.run() which blocks until the server exits.
"""

import asyncio
import logging
import getpass
import os
import sys
from collections import defaultdict
from typing import Sequence

from dt4acc_lib.interfaces.backend.calculation_states import CalculationStates
from dt4acc_lib.model.utils.tango_resource_locator import TangoResourceLocator

from dt4acc.config.data.querries import get_controlled_elements, get_unique_magnet_power_converters, get_elements_per_power_converter
from dt4acc.config.data.querries import get_rf_cavity_uuids
from dt4acc.core.bl.controller import Controller
from dt4acc.custom_tango.views.view import TangoView
from dt4acc.custom_tango.ioc.mexec_server_for_physics_engine import (
    _connect_to_mexec_service,
    lattice_properties_for_device,
)
from dt4acc_lib.model.output.result import TranslatedReading, ReadTogetherAndTranslated, SingleReading
from dt4acc_lib.model.utils.command import ReadCommand, Command
from tango.server import run

from dt4acc.core.utils.logger import get_logger
from dt4acc.custom_tango.ioc.controller_registry import set_controller, get_controller
from dt4acc.custom_tango.ioc.tango_controller import TangoController, DEFAULT_DELAYED_READS

# Suppress transitions state machine INFO logs — they fire on every
# backend.set() call and flood the output (4 lines per state transition)
logging.getLogger("transitions").setLevel(logging.WARNING)
logging.getLogger("transitions.core").setLevel(logging.WARNING)

logger = get_logger()
logging.getLogger("dt4acc").setLevel(level=logging.WARNING)

# ---------------------------------------------------------------------------
# AsyncMexecAdapter — makes SyncMexecProxy look async to TangoController
# ---------------------------------------------------------------------------

class AsyncMexecAdapter:
    """
    Wraps the synchronous multiprocessing proxy (SyncMexecProxy) and exposes
    the async interface that TangoController expects:
        await mexec.set([cmd])
        await mexec.trigger_read([rcmd, ...])

    The sync calls run in a thread-pool executor so they don't block the
    asyncio event loop while waiting for the service process to respond.
    """

    def __init__(self, sync_proxy):
        self._proxy = sync_proxy

    async def set(self, cmds: Sequence[Command]) -> None:
        loop = asyncio.get_running_loop()
        for cmd in cmds:
            # Use lambda to capture args explicitly — multiprocessing.managers
            # proxy methods don't accept positional args via run_in_executor
            _id, _prop, _val = cmd.id, cmd.property, cmd.value
            await loop.run_in_executor(
                None,
                lambda: self._proxy.sync_set(_id, _prop, _val),
            )

    async def trigger_read(self, rcmds: Sequence[ReadCommand]) -> ReadTogetherAndTranslated:
        loop = asyncio.get_running_loop()
        ids   = [r.id for r in rcmds]
        props = [r.property for r in rcmds]

        raw = await loop.run_in_executor(
            None,
            lambda: self._proxy.sync_trigger_read(ids, props),
        )
        # raw is list of (rcmd_id, rcmd_property, payload) tuples
        # Reconstruct ReadTogetherAndTranslated for TangoController.view.dispatch()
        import datetime
        now = datetime.datetime.now()

        # Group by (id, property) — one TranslatedReading per ReadCommand
        groups = defaultdict(list)
        for rcmd_id, rcmd_prop, payload in raw:
            groups[(rcmd_id, rcmd_prop)].append(
                SingleReading(
                    name=f"{rcmd_id}-{rcmd_prop}",
                    payload=payload,
                    cmd=ReadCommand(id=rcmd_id, property=rcmd_prop),
                )
            )

        data = [
            TranslatedReading(
                cmd=ReadCommand(id=k[0], property=k[1]),
                readings=readings,
            )
            for k, readings in groups.items()
        ]
        return ReadTogetherAndTranslated(data=data, start=now, end=now)

    async def acknowledge(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._proxy.sync_acknowledge(),
        )

    def get_state(self) -> CalculationStates:
        # This function is not async: check at backend
        r = self._proxy.sync_get_state()
        return r


# Process-global cache: uuid -> {property: value}
# Populated by _preload_initial_values() before init_device() runs.
# Re-populated by refresh_cache_from_lattice() after reset.
_initial_values_cache: dict = {}    # uuid -> {property: value}
_initial_strength_cache: dict = {}  # uuid -> float (main_strength)
_nominal_cache: dict = {}           # uuid -> {property: value}
_my_magnet_uuids: list = []         # UUIDs of elements in this server process
_uuid_to_prop: dict = {}            # uuid -> lattice properties
_sync_proxy = None                  # MexecService proxy for live reads
_device_view = False                # True only for device-view facilities (e.g. MAX IV)


def _default_lattice_values() -> dict:
    return {
        "main_strength": 0.0,
        "A1": 0.0,
        "B1": 0.0,
        "A2": 0.0,
        "B2": 0.0,
        "B3": 0.0,
        "B4": 0.0,
        "frequency": 0.0,
        "voltage": 0.0,
    }


def enable_device_view_readback() -> None:
    """Call from facility startup script to enable live AT readback on polling.
    Must be called before tango.server.run() — e.g. in run_maxiv_r1_twin.py.
    In design view (SOLEIL) this is never called so peek_from_lattice returns 0.0.
    """
    global _device_view
    _device_view = True


def peek_from_lattice(element_id: str, prop: str) -> float:
    """Live read of a single element property from AT via MexecService.
    Only active in device view (MAX IV). Returns 0.0 in design view (SOLEIL)
    so the cached value is kept unchanged — no regression for SOLEIL.
    """
    global _sync_proxy, _device_view # noqa: F824
    if not _device_view or _sync_proxy is None:
        return 0.0
    try:
        return _sync_proxy.sync_peek(element_id, prop)
    except Exception:
        return 0.0


def _properties_for_uuid(uuid: str, uuid_to_prop: dict = None) -> list:
    value = (uuid_to_prop or {}).get(uuid, "main_strength")
    if isinstance(value, (set, list, tuple)):
        return list(value)
    return [value]


def _properties_for_uuid_or_spec(uuid: str, prop_spec=None) -> list:
    if prop_spec is not None:
        if isinstance(prop_spec, (set, list, tuple)):
            return list(prop_spec)
        return [prop_spec]
    if uuid in _uuid_to_prop:
        return _properties_for_uuid(uuid, _uuid_to_prop)
    if uuid in set(get_rf_cavity_uuids()):
        return ["frequency", "voltage"]
    return ["main_strength"]


def _properties_for_element(name: str, mtype: str = "", subtype: str = "") -> list:
    """Which AT lattice-element properties this device controls.

    Sourced from the active facility's liaison manager (via
    lattice_properties_for_device) instead of re-derived from device-name
    patterns or magnet type/subtype — that used to duplicate (and drift out
    of sync with) what liasion_translator_setup.py already computes
    correctly for each facility.
    """
    return lattice_properties_for_device(name)


def _add_cache_element(
    *,
    uuid: str,
    props: list,
    uuids: list,
    seen_uuids: set,
    uuid_to_prop: dict,
) -> None:
    if not uuid:
        return
    if uuid not in seen_uuids:
        uuids.append(uuid)
        seen_uuids.add(uuid)
    uuid_to_prop.setdefault(uuid, set()).update(props)


def get_initial_strength(uuid: str) -> float:
    """Called by MagnetDevice.init_device() to get cached initial value."""
    return _initial_strength_cache.get(uuid, 0.0)


def get_initial_values(uuid: str) -> dict:
    """Called by Tango devices to get cached initial lattice values."""
    values = _default_lattice_values()
    values.update(_initial_values_cache.get(uuid, {}))
    return values


def get_nominal_values(uuid: str) -> dict:
    """Called by MagnetDevice.RefreshFromCache() after reset."""
    values = _default_lattice_values()
    values.update(_nominal_cache.get(uuid, {}))
    return values


def get_rf_reference_frequency_khz() -> float:
    frequencies = []
    for uuid in get_rf_cavity_uuids():
        frequency = _nominal_cache.get(uuid, {}).get("frequency")
        if frequency is not None and frequency > 0.0:
            frequencies.append(float(frequency) * 1e-3)
    if frequencies:
        return sum(frequencies) / len(frequencies)

    for values in _nominal_cache.values():
        frequency = values.get("frequency")
        if frequency is None or frequency <= 0.0:
            continue
        return float(frequency) * 1e-3
    return 0.0


def refresh_cache_from_lattice(sync_proxy, magnet_uuids: list, uuid_to_prop: dict = None) -> None:
    """
    Bulk-read current lattice values for all magnets after reset.
    Uses per-uuid lattice_property — same approach as _preload_initial_values.
    """
    global _initial_values_cache, _initial_strength_cache, _nominal_cache
    if not magnet_uuids:
        return

    prop_groups = defaultdict(list)
    for uuid in magnet_uuids:
        for prop in _properties_for_uuid(uuid, uuid_to_prop):
            prop_groups[prop].append(uuid)

    logger.warning("Refreshing nominal cache for %d magnets...",
                   sum(len(v) for v in prop_groups.values()))
    new_cache = {
        uuid: {prop: 0.0 for prop in _properties_for_uuid(uuid, uuid_to_prop)}
        for uuid in magnet_uuids
    }

    for prop, ids in prop_groups.items():
        try:
            props = [prop] * len(ids)
            raw = sync_proxy.sync_trigger_read(ids, props)
            for rcmd_id, rcmd_prop, payload in raw:
                if payload is not None and rcmd_id in new_cache:
                    try:
                        new_cache[rcmd_id][prop] = float(payload)
                    except (TypeError, ValueError):
                        pass
        except Exception as exc:
            logger.warning("refresh_cache_from_lattice: %s failed: %s", prop, exc)

    _nominal_cache = new_cache
    _initial_values_cache = dict(new_cache)
    _initial_strength_cache = {
        uuid: v.get("main_strength", 0.0) for uuid, v in new_cache.items()
    }
    logger.warning("Nominal cache refreshed for %d magnets.", len(new_cache))


def refresh_one_from_lattice(uuid: str, prop_spec=None) -> None:
    """Refresh one cached element from the lattice for direct RefreshFromCache."""
    if _sync_proxy is None or not uuid:
        return

    props = _properties_for_uuid_or_spec(uuid, prop_spec)
    try:
        raw = _sync_proxy.sync_trigger_read([uuid] * len(props), props)
    except Exception as exc:
        logger.debug("refresh_one_from_lattice: %s failed: %s", uuid, exc)
        return

    values = _nominal_cache.setdefault(uuid, {})
    for rcmd_id, rcmd_prop, payload in raw:
        if rcmd_id != uuid or payload is None:
            continue
        try:
            values[rcmd_prop] = float(payload)
        except (TypeError, ValueError):
            pass
    _initial_values_cache[uuid] = dict(values)
    _initial_strength_cache[uuid] = values.get("main_strength", 0.0)


def _preload_initial_values(sync_proxy, magnet_uuids: list, uuid_to_prop: dict = None) -> None:
    """
    Bulk-read initial values for all magnets before Tango starts.
    Uses per-uuid lattice_property to avoid sending "main_strength"
    to octupole/corrector elements that don't support it.
    """
    global _initial_values_cache, _initial_strength_cache, _nominal_cache # noqa: F824
    if not magnet_uuids:
        return

    # Group uuids by their lattice_property — one batch per property
    prop_groups = defaultdict(list)
    for uuid in magnet_uuids:
        for prop in _properties_for_uuid(uuid, uuid_to_prop):
            prop_groups[prop].append(uuid)

    logger.warning("Pre-loading initial values for %d element properties...",
                   sum(len(v) for v in prop_groups.values()))
    new_cache = {
        uuid: {prop: 0.0 for prop in _properties_for_uuid(uuid, uuid_to_prop)}
        for uuid in magnet_uuids
    }
    for prop, ids in prop_groups.items():
        try:
            props = [prop] * len(ids)
            raw = sync_proxy.sync_trigger_read(ids, props)
            for rcmd_id, rcmd_prop, payload in raw:
                if payload is not None and rcmd_id in new_cache:
                    try:
                        new_cache[rcmd_id][prop] = float(payload)
                    except (TypeError, ValueError):
                        pass
        except Exception as exc:
            logger.warning("Bulk pre-load failed for %s: %s — devices will start at 0.0",
                           prop, exc)
    _nominal_cache = new_cache
    _initial_values_cache = dict(new_cache)
    _initial_strength_cache = {
        uuid: values.get("main_strength", 0.0)
        for uuid, values in new_cache.items()
    }
    logger.warning("Pre-loaded initial values for %d elements.", len(_nominal_cache))

def _inject_controller(prefix: str) -> None:
    """
    Build AsyncMexecAdapter + TangoController and register in controller_registry.
    Called before tango.server.run() so init_device() can call get_controller().
    """
    sync_proxy, sync_reset, sync_reinit = _connect_to_mexec_service()
    global _sync_proxy
    _sync_proxy = sync_proxy
    mexec = AsyncMexecAdapter(sync_proxy)

    controller = TangoController(
        name = "tango-ctrl",
        controller_delegate = Controller(
            name = "tango-dlgte-ctrl",
            mexec = mexec,
            default_delayed_reads = DEFAULT_DELAYED_READS,
             # todo: find out which view is needed here
            view = TangoView(prefix=prefix),
            ),
            sync_reset = sync_reset,
            sync_reinit = sync_reinit,
    )

    set_controller(controller)
    logger.info("TangoController created and registered for prefix=%s", prefix)


def _get_dt4acc_prefix() -> str:
    if os.environ.get("DT4ACC_PREFIX"):
        return os.environ["DT4ACC_PREFIX"]
    try:
        return getpass.getuser()
    except Exception:
        return "dt4acc"


# ---------------------------------------------------------------------------
# main_loop — called by server_manager for each (server_name, instance_name)
# ---------------------------------------------------------------------------

def main_loop(server_name: str, instance_name: str, event=None):
    import logging
    logging.getLogger("transitions").setLevel(logging.WARNING)
    logging.getLogger("transitions.core").setLevel(logging.WARNING)

    logger.warning("single server start: name %s instance %s pid %d", server_name, instance_name, os.getpid())

    prefix = _get_dt4acc_prefix()

    # Inject controller BEFORE Tango initialises any device
    _inject_controller(prefix)

    # Bulk pre-load initial values for all magnets in this server/instance.
    # One RPC call for all magnets instead of one per magnet in init_device().
    try:
        sync_proxy, _, _ = _connect_to_mexec_service()

        # Collect UUIDs for magnets belonging to this server/instance
        my_uuids = []
        seen_uuids = set()
        uuid_to_prop = {}
        for pc_name in get_unique_magnet_power_converters():
            for m in get_elements_per_power_converter(pc_name):
                magnet_name = m["name"]
                uuid = m.get("uuid", "")
                mtype = m.get("type", "")
                subtype = m.get("subtype", "")
                props = _properties_for_element(magnet_name, mtype, subtype=subtype)

                if mtype == "RFCavity":
                    _add_cache_element(
                        uuid=uuid,
                        props=props,
                        uuids=my_uuids,
                        seen_uuids=seen_uuids,
                        uuid_to_prop=uuid_to_prop,
                    )

                try:
                    trl = TangoResourceLocator.from_trl(magnet_name)
                except AssertionError:
                    continue
                if trl.domain == server_name and trl.family == instance_name:
                    _add_cache_element(
                        uuid=uuid,
                        props=props,
                        uuids=my_uuids,
                        seen_uuids=seen_uuids,
                        uuid_to_prop=uuid_to_prop,
                    )

        for m in get_controlled_elements():
            if m.get("type") != "RFCavity":
                continue
            _add_cache_element(
                uuid=m.get("uuid", ""),
                props=_properties_for_element(m["name"], "RFCavity"),
                uuids=my_uuids,
                seen_uuids=seen_uuids,
                uuid_to_prop=uuid_to_prop,
            )

        global _my_magnet_uuids, _uuid_to_prop
        _my_magnet_uuids = my_uuids
        _uuid_to_prop = uuid_to_prop

        _preload_initial_values(sync_proxy, my_uuids, uuid_to_prop)
    except Exception as exc:
        logger.warning("Pre-load setup failed: %s — devices will start at 0.0", exc)

    def _post_init_cb():
        # Start the controller's delayed queue loop inside the Tango event loop
        try:
            get_controller().start()
            logger.warning("Server %s/%s ready — TangoController started", server_name, instance_name)
        except Exception as exc:
            logger.error("TangoController.start() failed: %s", exc)
        if event is not None:
            event.set()

    # Ensure an event loop exists for this process
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        # Import lazily here — after _inject_controller — to avoid circular imports
        from dt4acc.custom_tango.ioc.devices.tango_device_setup import get_all_device_classes
        device_classes = get_all_device_classes()
        logger.info(
            "Starting %s/%s with %d device classes",
            server_name, instance_name, len(device_classes),
        )
        run(
            device_classes,
            args=[server_name, instance_name],
            post_init_callback=_post_init_cb,
            raises=True,
            verbose=True,
        )
    except Exception as exc:
        sys.stderr.write(f"Tango server {server_name}/{instance_name} failed: {exc}\n")
        sys.stderr.flush()
        logger.error("Tango server %s/%s failed: %s", server_name, instance_name, exc)
        raise
    finally:
        try:
            asyncio.get_event_loop().close()
        except Exception:
            pass


def main():
    if len(sys.argv) != 3:
        print("Usage: single_server.py <server_name> <instance_name>")
        sys.exit(1)
    logger.warning("cli: single server start: name %s instance %s", sys.argv[1], sys.argv[2])
    main_loop(server_name=sys.argv[1], instance_name=sys.argv[2])


if __name__ == "__main__":
    main()
