"""Record of the element the turn by turn tracking's beam ends at: ``TBT:stop_at``, ``INJ:stop_at``

One lattice element name, e.g. ``caput <pv> Q3M1D1R``; empty: no stop. A name
the lattice does not have exactly once rejects the write.
"""
import logging
from typing import Callable, Optional, Sequence

from softioc import builder as softioc_builder

from dt4acc.core.bl.turn_by_turn import check_stop_at, parse_stop_at

logger = logging.getLogger("dt4acc")


def stop_at_record(name: str, backend, set_stop_at: Callable[[Optional[str]], None], builder=softioc_builder):
    """``set_stop_at`` gets the element (None: no stop) each valid write asks for"""

    def validate(record, value: str) -> bool:
        try:
            check_stop_at(backend, parse_stop_at(value))
        except ValueError as exc:
            logger.warning("%s: write rejected: %s", name, exc)
            return False
        return True

    return builder.stringOut(
        name, initial_value="", validate=validate,
        on_update=lambda value: set_stop_at(parse_stop_at(value)),
    )


__all__: Sequence[str] = ["stop_at_record"]
