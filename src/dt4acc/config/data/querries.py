# TODO
# this is a temporary solution to avoid the MongoDB dependency
# rework this to use the file repository along with mongodb

import json
import os
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional

# -----------------------------------------------------------------
# locate and load the data file — lazy, configurable at runtime
# -----------------------------------------------------------------

_DEFAULT_DATA_FILE = Path.home() / "Documents" / "dt4acc_config_data" / "accelerator_setup.json"
_DATA_FILE = Path(os.environ.get("DT4ACC_ACCELERATOR_SETUP_FILE", _DEFAULT_DATA_FILE))
_DATA: Optional[List[Dict[str, Any]]] = None


def configure_data_file(path: "str | Path") -> None:
    global _DATA_FILE, _DATA
    _DATA_FILE = Path(path)
    _DATA = None


def get_data_file() -> Path:
    return _DATA_FILE


def _data() -> List[Dict[str, Any]]:
    global _DATA
    if _DATA is None:
        with _DATA_FILE.open() as fp:
            _DATA = json.load(fp)
    return _DATA


# -----------------------------------------------------------------
# helper: Mongo-style $in filtering for the tiny use-cases we need
# -----------------------------------------------------------------
def _match(doc: Dict[str, Any], field: str, allowed: Iterable[str]) -> bool:
    return doc.get(field) in allowed


# -----------------------------------------------------------------
# public API
# -----------------------------------------------------------------
def get_controlled_elements():
    """Return all controlled accelerator elements as an iterator."""
    wanted = {
        "Quadrupole", "Sextupole", "Steerer", "SkewQuadrupoleCorrector",
        "RFCavity", "QuadrupoleCorrector", "Multipole", "Bend", "Octupole"
    }
    return (d for d in _data() if _match(d, "type", wanted))


def get_elements_per_power_converter(pc: str) -> List[Dict[str, Any]]:
    """Return all controlled elements driven by the given power-converter name."""
    return [d for d in _data() if d.get("pc") == pc]


def get_unique_magnet_power_converters() -> List[str]:
    """Distinct list of power-converter names for magnetic elements.
    Skips entries where pc is None (e.g. a design view without PCs)."""
    wanted = {
        "Quadrupole", "Sextupole", "Steerer", "SkewQuadrupoleCorrector", "QuadrupoleCorrector",
        "Multipole", "Bend", "Octupole"
    }
    return sorted({d["pc"] for d in _data()
                   if _match(d, "type", wanted) and d.get("pc")})


def get_unique_power_converters_for_types(type_list: Iterable[str]) -> List[str]:
    """Distinct list of power-converter names for the supplied magnet types."""
    wanted = set(type_list)
    return sorted({d["pc"] for d in _data()
                   if _match(d, "type", wanted) and d.get("pc")})


# Backward-compatible aliases for older call sites.
def get_magnets():
    return get_controlled_elements()


def get_magnets_per_power_converters(pc: str) -> List[Dict[str, Any]]:
    return get_elements_per_power_converter(pc)


def get_unique_power_converters() -> List[str]:
    return get_unique_magnet_power_converters()


def get_unique_power_converters_type_specified(type_list: Iterable[str]) -> List[str]:
    return get_unique_power_converters_for_types(type_list)


def get_rf_cavity_uuids() -> List[str]:
    """UUIDs of non-harmonic (main) RF cavities for design-view fan-out."""
    return [
        d["uuid"] for d in _data()
        if d.get("type") == "RFCavity"
        and "HARM" not in (d.get("FamName") or "")
        and d.get("uuid")
    ]


def get_bpms() -> List[Dict[str, Any]]:
    """Return all BPM entries from the setup JSON."""
    return [d for d in _data() if d.get("type") == "BPM"]
