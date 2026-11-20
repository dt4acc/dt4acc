"""SOLEIL TL2's yellow pages, as soleil_yellow_pages for the ring: from the
configured accelerator_setup.json. The correctors' direction comes from their
family in TL2's database (HCOR, VCOR)."""
import json

from dt4acc.config.data.querries import get_data_file
from dt4acc.custom_facility.soleil.soleil_yellow_pages import YellowPages

HORIZONTAL_FAMILY = "HCOR"
VERTICAL_FAMILY = "VCOR"


def soleil_tl2_yellow_pages() -> YellowPages:
    """Creates a YellowPages instance for TL2 using the configured accelerator_setup.json."""
    elements = json.loads(get_data_file().read_text())

    quadrupoles = [e["name"] for e in elements if e["type"] == "Quadrupole"]
    bends = [e["name"] for e in elements if e["type"] == "Bend"]
    steerers = [e for e in elements if e["type"] == "Steerer"]
    horizontal_steerers = [e["name"] for e in steerers if e.get("FamName") == HORIZONTAL_FAMILY]
    vertical_steerers = [e["name"] for e in steerers if e.get("FamName") == VERTICAL_FAMILY]

    return YellowPages(dict(
        quadrupoles=quadrupoles,
        bends=bends,
        horizontal_steerers=horizontal_steerers,
        vertical_steerers=vertical_steerers,
    ))
