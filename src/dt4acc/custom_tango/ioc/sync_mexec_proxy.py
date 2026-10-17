import asyncio
import math
import os
import traceback
from typing import Sequence

from dt4acc.core.utils.logger import get_logger
from dt4acc.core.bl.handle_lattice import lattice_loader
from dt4acc_lib.interfaces.backend.calculation_states import CalculationStates
from dt4acc_lib.interfaces.utils.command_execution_engine import CommandExecutionEngine
from dt4acc_lib.model.utils.command import Command, BehaviourOnError, ReadCommand

logger = get_logger()


class SyncMexecProxy:
    """Synchronous wrapper around mexec for crossing the process boundary.

    Todo:
        on which side are you running on?
    """

    def __init__(self,*, mexec: CommandExecutionEngine, service_loop: asyncio.AbstractEventLoop):
        self.mexec = mexec
        self.service_loop = service_loop
        logger.warning("SyncMexecProxy: running in pid = %d", os.getpid())

    def sync_set(self, cmd_id: str, cmd_property: str, value: float):
        cmd = Command(
            id=cmd_id,
            property=cmd_property,
            value=value,
            behaviour_on_error=BehaviourOnError.stop,
        )
        fut = asyncio.run_coroutine_threadsafe(
            self.mexec.set([cmd]), self.service_loop
        )
        return fut.result(timeout=30)

    def sync_peek(self, element_id: str, prop: str) -> float:
        """Read a single element property directly from AT backend,
        bypassing liaison and translator. Used by MultipoleDevice polling
        to stay in sync with PC writes in device view.
        element_id is a FamName uuid (e.g. 'sqfi73'), prop is the AT
        property name (e.g. 'main_strength').
        """
        logger.debug("sync_peek: element_id=%r prop=%r", element_id, prop)

        async def _peek():
            return await self.mexec.backend.read(element_id, prop)

        fut = asyncio.run_coroutine_threadsafe(_peek(), self.service_loop)
        try:
            result = float(fut.result(timeout=5))
            logger.debug("sync_peek: element_id=%r -> %.6f", element_id, result)
            return result
        except Exception as exc:
            if prop == "main_strength" and element_id.startswith("B"):
                # Todo: delete this branch
                # currently only here for debug
                # it does the same as the code below
                logger.info("sync_peek failed for element_id=%r prop=%r: %s",
                                element_id, prop, exc)
                return 0.0
                # return math.nan

            tmp = traceback.format_exception(type(exc), exc, exc.__traceback__)  #: delete me
            logger.warning("sync_peek failed for element_id=%r prop=%r: %s",
                           element_id, prop, exc)
            # Todo: No value was retrieved: better return an invalid value
            # return math.nan
            return 0.0

    def sync_trigger_read(self, rcmd_ids: Sequence[str], rcmd_properties: Sequence[str]):
        rcmds = [
            ReadCommand(id=i, property=p)
            for i, p in zip(rcmd_ids, rcmd_properties)
        ]
        fut = asyncio.run_coroutine_threadsafe(
            self.mexec.trigger_read(rcmds), self.service_loop
        )
        result = fut.result(timeout=30)
        out = []
        for translated in result.data:
            for reading in translated.readings:
                out.append((translated.cmd.id, translated.cmd.property, reading.payload))
        return out

    def sync_reset(self):
        """
        Clear backend error state and stored optics without reloading the lattice.
        """
        logger.warning("SyncMexecProxy.sync_reset: clearing backend state (pid = %d)", os.getpid())
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self.mexec.backend.reset(), self.service_loop
            )
            fut.result(timeout=30)
            logger.warning("SyncMexecProxy.sync_reset: backend reset done")
        except Exception as exc:
            logger.error("SyncMexecProxy.sync_reset failed: %s", exc)
            raise

    def sync_reinit(self):
        """
        Reset backend to nominal state:
        1. Reload AT lattice from .m file
        2. Clear error state → pending
        3. Clear stored optics
        """
        logger.warning("SyncMexecProxy.sync_reinit: re-initialising back end")
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self.mexec.backend.reinit(), self.service_loop
            )
            fut.result(timeout=30)
            logger.warning("SyncMexecProxy.sync_reinit: backend reinit done")
            # the reloaded lattice file is not at the supplies' nominal
            # currents: settle it again, as at start-up
            from dt4acc.custom_tango.ioc.mexec_server_for_physics_engine import (
                _settle_supplies,
                settle_supplies_enabled,
            )
            if settle_supplies_enabled():
                n = asyncio.run_coroutine_threadsafe(
                    _settle_supplies(self.mexec), self.service_loop
                ).result(timeout=600)
                logger.warning("SyncMexecProxy.sync_reinit: %d power supplies set to their nominal current", n)
        except Exception as exc:
            logger.error("SyncMexecProxy.sync_reinit failed: %s", exc)
            raise

    def sync_acknowledge(self):
        logger.warning("SyncMexecProxy.sync_acknowledge: acknowledging error")
        try:
            async def _acknowledge_if_error():
                state = self.mexec.backend.get_state()
                if state == CalculationStates.error:
                    await self.mexec.backend.acknowledge()
                    return True, state
                return False, state

            fut = asyncio.run_coroutine_threadsafe(_acknowledge_if_error(), self.service_loop)
            acknowledged, state = fut.result(timeout=30)
            if not acknowledged:
                logger.warning(
                    "SyncMexecProxy.sync_acknowledge: backend state is %s, nothing to acknowledge",
                    state,
                )
                return
            logger.warning("SyncMexecProxy.sync_acknowledge: backend acknowledge done")
        except Exception as exc:
            logger.error("SyncMexecProxy.sync_acknowledge failed: %s", exc)
            raise

    def sync_get_state(self) -> CalculationStates:
        logger.debug("SyncMexecProxy.get_state: see what state ")
        r =  self.mexec.backend.get_state()
        return r


__all__  = ["SyncMexecProxy"]
