import asyncio
import itertools
import os
import traceback
from typing import Sequence

from dt4acc.core.interfaces.controller_interface import ControllerInterface
from dt4acc.core.interfaces.view_interface import ViewInterface
from dt4acc.core.utils.logger import get_logger
from dt4acc_lib.interfaces.backend.calculation_states import CalculationStates
from dt4acc_lib.interfaces.utils.command_execution_engine import CommandExecutionEngine
from dt4acc_lib.model.output.result import ReadTogetherAndTranslated
from dt4acc_lib.model.utils.command import Command, ReadCommand

logger = get_logger()


class Controller(ControllerInterface):
    def __init__(
        self,
        name: str,
        mexec: CommandExecutionEngine,
        view: ViewInterface,
        default_delayed_reads: Sequence[ReadCommand],
    ):
        self.name = name
        self.mexec = mexec
        self.view = view
        self.default_delayed_reads = default_delayed_reads
        self.cmd_queue: asyncio.Queue = None
        self.pending_task = None
        self.task_counter = itertools.count()

    def __repr__(self):
        return (
            f"{self.__class__.__name__}("
            f"name={self.name},"
            f" mexec={self.mexec},"
            f" view={self.view}"
            f" default_delayed_reads={self.default_delayed_reads}"
            ")"
        )

    def start_obsolete(self):
        """
        Todo:
            rework to be compatible to tango requirements

        """
        assert self.pending_task is None
        task_count = next(self.task_counter)
        self.pending_task = asyncio.create_task(
            self._queue_loop(),
            name=f"controller-delayed-execution-task-{task_count}",
        )

    def get_backend_state(self):
        return self.mexec.get_state()

    def get_default_delayed_reads(self) -> Sequence[ReadCommand]:
        return self.default_delayed_reads

    def start(self) -> None:
        """Start the delayed execution loop on the shared event loop."""
        assert (
            self.pending_task is None
        ), f"{self.__class__.__name__}.start() called twice"
        # Todo: should one assign some value to pending task (like true ?)
        #       just to minimise the time for race conditions

        from dt4acc.core.bl.shared_event_loop import get_shared_event_loop

        shared_loop = get_shared_event_loop()

        # Always use the shared loop — it's the one we control and is
        # guaranteed to be running. Tango's own loop is not reliable here.
        async def _create_queue_and_start():
            self.cmd_queue = asyncio.Queue()

        asyncio.run_coroutine_threadsafe(_create_queue_and_start(), shared_loop).result(
            timeout=5
        )

        fut = asyncio.run_coroutine_threadsafe(self._queue_loop(), shared_loop)
        # Todo: should this not assign to pending_task?
        #       compare to check at start
        self.pending_task = fut
        logger.info("%s delayed execution task started on shared loop", self.name)

    async def update(
        self,
        *,
        cmd: Command,
        reads: Sequence[ReadCommand],
        delayed_reads: Sequence[ReadCommand] = (),
    ) -> None:
        """
        Apply a command to the backend, push immediate reads to the view,
        then queue delayed reads (twiss, orbit, tune).

        Called from Tango device write handlers via _async().
        """
        # 1. Mutate the backend lattice
        await self.mexec.set([cmd])

        # 2. Immediate reads — e.g. readback current after setting a magnet
        if reads:
            read_result = await self.mexec.trigger_read(reads)
            for rcmd, translated in zip(reads, read_result.data):
                await self.view.dispatch(rcmd, translated)

        # 3. Queue delayed reads
        all_delayed = list(self.default_delayed_reads) + list(delayed_reads)
        await self._enqueue(all_delayed)

    async def trigger_read(
        self, reads: Sequence[ReadCommand]
    ) -> ReadTogetherAndTranslated:
        """Direct read from the backend — used for initial value peek at startup."""
        return await self.mexec.trigger_read(reads)

    async def reread_default_readings(self) -> None:
        # Better fail if no default readings are available
        # most probably the whole system will not work as the
        # developer / user expects
        assert self.default_delayed_reads, "No delayed reads were provided"
        await self._enqueue(self.default_delayed_reads)

    async def _push_invalid(self) -> None:
        """
        Push NaN arrays to all virtual devices when backend calculation fails.
        This signals to clients that the data is invalid (beam lost).
        """
        try:
            await self.view.push_invalid()
        except Exception as exc:
            logger.error("%s: failed to push invalid state: %s", self.name, exc)

    async def _enqueue(self, reads: Sequence[ReadCommand]) -> None:
        if self.cmd_queue is None:
            logger.warning(
                "%s: queue not yet started — delayed reads %s dropped", self.name, reads
            )
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*[self.cmd_queue.put(r) for r in reads]),
                timeout=0.1,
            )
        except asyncio.TimeoutError:
            logger.warning("%s: queue put timed out — delayed reads dropped", self.name)

    async def _queue_loop(self) -> None:
        for step in itertools.count():
            logger.debug("%s: queue loop step %d", self.name, step)
            try:
                await self._queue_step()
            except Exception as exc:
                logger.info("%s: queue loop step %d failed %exc", self.name, step, exc)

    async def _queue_step(self) -> None:
        # Check that backend is not in error mode
        # Todo: get_state / acknowlege: communicate messages to backend?
        #       should the queue be emptied if already in error state?
        logger.debug("Processing delayed command queue in pid %d", os.getpid())
        if self.mexec.get_state() in [CalculationStates.error]:

            await self._push_invalid()
            await self.mexec.acknowledge()
            return

        rcmds = await consume(queue=self.cmd_queue, delay=0.05)
        if not rcmds:
            return

        t_rcmds = tuple(set(rcmds))
        logger.debug("%s: executing delayed reads %s", self.name, t_rcmds)

        try:
            read_result = await self.mexec.trigger_read(t_rcmds)
        except Exception as exc:
            logger.error("%s: backend read failed for %s: %s", self.name, t_rcmds, exc)
            traceback.print_exc()
            # Push NaN to all virtual devices so clients know data is invalid
            await self._push_invalid()
            if self.mexec.get_state() in [CalculationStates.error]:
                await self.mexec.acknowledge()
            return  # never kill the loop

        if self.mexec.get_state() in [CalculationStates.error]:
            await self._push_invalid()
            await self.mexec.acknowledge()

        if len(read_result.data) != len(t_rcmds):
            logger.error(
                "%s: sent %d read commands, got %d results — skipping",
                self.name,
                len(t_rcmds),
                len(read_result.data),
            )
            await self._push_invalid()
            return

        for rcmd, translated in zip(t_rcmds, read_result.data):
            try:
                await self.view.dispatch(rcmd, translated)
            except Exception as exc:
                logger.error(
                    "%s: view dispatch failed for %s: %s", self.name, rcmd, exc
                )
                traceback.print_exc()
                # continue processing remaining results


async def consume(queue: asyncio.Queue, delay: float) -> Sequence[ReadCommand]:
    """Drain the queue, waiting up to `delay` seconds for the first item."""
    rcmds = []
    while True:
        try:
            rcmd = await asyncio.wait_for(queue.get(), timeout=delay)
        except asyncio.TimeoutError:
            break
        rcmds.append(rcmd)
        queue.task_done()
    return rcmds


async def read_and_dispatch(
    controller: ControllerInterface, view: ViewInterface, rcmds: Sequence[ReadCommand]
):
    read_result = [await read_one_by_one(controller, rcmd) for rcmd in rcmds]
    # Need to combine translated...
    for rcmd, translated in read_result:
        if translated is None:
            logger.warning(f"Omitting pushing {rcmd} to view as no translated data available")
            continue
        for data in translated.data:
            await view.dispatch(rcmd, data)
        logger.debug(f"Controller/View: successful startup at {rcmd}")


async def read_one_by_one(controller: ControllerInterface, rcmd: ReadCommand):
    # so that we can log the ones that fail
    try:
        r = await controller.trigger_read([rcmd])
    except Exception as ex:
        logger.warning(f"{controller} failed to retrieve data for {rcmd}. Reason {ex}")
        # can be still useful to report in one batch
        return rcmd, None
    return rcmd, r


__all__ = ["Controller", "read_and_dispatch", "read_one_by_one"]
