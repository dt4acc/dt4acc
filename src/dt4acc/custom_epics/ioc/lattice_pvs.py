"""Load a lattice with small differences at run time (#81)

A lattice in a lattice directory replaces the simulated one, e.g. the ring
with its wavelength shifters inserted. It must hold every element the twin's
devices refer to, in the same order (dt4acc_lib's
``SimulatorBackend.load_lattice``); other elements may differ.

PVs (without the twin's prefix):

* ``simulator_ring:lattice``: write a file name of the lattice directory to
  load it, an empty string to return to the lattice the twin started with
* ``simulator_ring:lattice:message``: the result, ``loaded ...`` or
  ``refused: ...``

After a load the settings' PVs (supplies, magnets, master clock and cavities)
show the new lattice's values; nothing is written back to the lattice. The
client restores its own settings if it needs them (snapshot before, replay
after). The model PVs are recomputed.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional, Sequence

import numpy as np

from dt4acc_lib.model.utils.command import ReadCommand
from dt4acc_lib.pyat_simulator.accelerator_simulator import LatticeMismatch

from dt4acc.core.bl.controller import read_and_dispatch

logger = logging.getLogger("dt4acc")

#: longest message the message PV holds
MESSAGE_LENGTH = 256

#: settings PV (by the property of its read command) -> what to read for it
#: from the lattice; the id of the PV's read command unless given
_SETTINGS = {
    "set_current": "set_current",
    "rdbk_current": "set_current",
    "main_strength": "main_strength",
    "main_strength_rdbk": "main_strength_rdbk",
}
_MASTER_CLOCK = ReadCommand("master_clock", "reference_frequency")


def settings_read_commands(process_variables: Dict[ReadCommand, object]) -> Dict[ReadCommand, ReadCommand]:
    """{read command of a settings PV: read command of its value in the lattice}"""
    result = {}
    for rcmd in process_variables:
        if rcmd.property in _SETTINGS:
            result[rcmd] = ReadCommand(rcmd.id, _SETTINGS[rcmd.property])
        elif rcmd.property in ("freq", "freq_rdbk"):
            # master clock and cavities: the frequency of the master clock
            result[rcmd] = _MASTER_CLOCK
    return result


def set_unprocessed(record, value) -> None:
    """Set a record's value; an output record without processing it, so that
    its on_update (a write to the lattice) is not called. softioc's input
    records have no ``process`` argument."""
    try:
        record.set(value, process=False)
    except TypeError:
        record.set(value)


async def refresh_settings(controller, process_variables: Dict[ReadCommand, object]) -> int:
    """Set the settings PVs to the lattice's values, without processing them
    (no write back to the lattice); returns how many were set"""
    n = 0
    for rcmd, source in settings_read_commands(process_variables).items():
        try:
            vals = await controller.trigger_read([source])
            # a supply driving several magnets: one reading per magnet, the
            # mean as at startup (pv_setup.add_pc_pvs)
            value = float(np.mean([reading.payload for reading in vals.all_readings()]))
        except Exception as exc:
            logger.debug("lattice refresh: no value for %s: %s", rcmd, exc)
            continue
        set_unprocessed(process_variables[rcmd], value)
        n += 1
    return n


class LatticeSwitch:
    """Replace the simulated lattice by one of ``lattice_dir``

    Args:
        backend: the simulator backend (``load_lattice``)
        lattice_dir: the directory the lattices are loaded from; only file
            names are accepted, no paths
        load_file: reads a lattice file as the twin uses it
        start_lattice: the lattice the twin started with (an empty name)
        required_elements: element ids the twin refers to (magnets, cavities,
            monitors): see dt4acc_lib's ``check_replacement``
        after_load: e.g. refresh the PVs; awaited after a successful load
    """

    def __init__(
        self,
        *,
        backend,
        lattice_dir: Optional[Path],
        load_file: Callable[[Path], object],
        start_lattice,
        required_elements: Sequence[str],
        after_load: Callable[[], Awaitable[None]] = None,
    ):
        self.backend = backend
        self.lattice_dir = Path(lattice_dir) if lattice_dir is not None else None
        self.load_file = load_file
        self.start_lattice = start_lattice
        self.required_elements = list(required_elements)
        self.after_load = after_load

    async def load(self, name: str) -> str:
        """Load ``name`` (empty: the start lattice); returns the message"""
        name = (name or "").strip()
        if not name:
            lattice, label = self.start_lattice, "the start lattice"
        else:
            if self.lattice_dir is None:
                return "refused: no lattice directory configured"
            if Path(name).name != name or name in (".", ".."):
                return f"refused: {name!r} is not a file name of the lattice directory"
            path = self.lattice_dir / name
            if not path.is_file():
                return f"refused: {name} not in {self.lattice_dir}"
            try:
                lattice = await asyncio.to_thread(self.load_file, path)
            except Exception as exc:
                logger.exception("lattice %s could not be read", path)
                return f"refused: {name} could not be read: {exc}"
            label = name
        try:
            await self.backend.load_lattice(lattice, self.required_elements)
        except LatticeMismatch as exc:
            return f"refused: {name}: {exc}"
        logger.warning("lattice: loaded %s (%d elements)", label, len(lattice))
        if self.after_load is not None:
            await self.after_load()
        return f"loaded {label}: {len(lattice)} elements"


def initialize_lattice_pvs(builder, switch: LatticeSwitch) -> Dict[ReadCommand, object]:
    """``simulator_ring:lattice`` and ``simulator_ring:lattice:message``"""
    message = builder.longStringIn(
        "simulator_ring:lattice:message", initial_value="the start lattice", length=MESSAGE_LENGTH
    )

    async def on_update(name: str):
        text = await switch.load(name)
        if text.startswith("refused"):
            logger.warning("lattice: %s", text)
        message.set(text[: MESSAGE_LENGTH - 1])

    return {
        ReadCommand("simulator_ring", "lattice"): builder.longStringOut(
            "simulator_ring:lattice",
            initial_value="",
            length=MESSAGE_LENGTH,
            always_update=True,
            on_update=on_update,
        ),
        ReadCommand("simulator_ring", "lattice_message"): message,
    }


def required_elements(liaison_manager, lattice, monitors: Sequence[str]) -> list:
    """The element ids the twin refers to: the lattice elements of the liaison
    manager, the ``monitors`` and the RF cavities of ``lattice``"""
    import at

    names = [entry.lat_id.element_name for entry in liaison_manager.forward_lut.lut]
    names += [lat_p.element_name for entry in liaison_manager.inverse_lut.lut for lat_p in entry.lat_ids]
    names += list(monitors)
    names += [elem.FamName for elem in lattice if isinstance(elem, at.RFCavity)]
    return list(dict.fromkeys(names))


def after_load_refresh(controller, view, startup_reads: Sequence[ReadCommand]) -> Callable[[], Awaitable[None]]:
    """After a load: the settings PVs from the lattice, then the model PVs as at startup"""

    async def refresh():
        n = await refresh_settings(controller, view.process_variables)
        logger.info("lattice: %d settings PVs refreshed", n)
        await read_and_dispatch(controller=controller, view=view, rcmds=list(startup_reads))

    return refresh


__all__ = [
    "LatticeSwitch",
    "after_load_refresh",
    "initialize_lattice_pvs",
    "refresh_settings",
    "required_elements",
    "settings_read_commands",
]
