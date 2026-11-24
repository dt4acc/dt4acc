"""Record of the turn by turn tracking's stops: ``TBT:stops``, ``INJ:stops``

Lattice element names separated by commas or blanks; empty: none. A name that
is not in the lattice rejects the write. A long string: write it with
``caput -S <pv> "Q1M2D1R, BPMZ3D1R"``, or ``pvput``.
"""
import logging
from typing import Callable, List, Sequence

from softioc import builder as softioc_builder

from dt4acc.core.bl.turn_by_turn import check_stops, parse_stops

logger = logging.getLogger("dt4acc")

#: characters of the PV
LENGTH = 1024


def stops_record(name: str, backend, set_stops: Callable[[List[str]], None], builder=softioc_builder):
    """``set_stops`` gets the stops each valid write asks for"""

    def validate(record, value: str) -> bool:
        try:
            check_stops(backend, parse_stops(value))
        except ValueError as exc:
            logger.warning("%s: write rejected: %s", name, exc)
            return False
        return True

    return builder.longStringOut(
        name, initial_value="", length=LENGTH, validate=validate,
        on_update=lambda value: set_stops(parse_stops(value)),
    )


__all__: Sequence[str] = ["stops_record"]
