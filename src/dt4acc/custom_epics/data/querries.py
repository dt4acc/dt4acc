# import os
#
# import pymongo

# from dt4acc import mongodb_
#
# client = pymongo.MongoClient(mongodb_)
# DB_NAME = os.environ.get("MONGODB_DB", "bessyii")
# db = client[DB_NAME]
# collection = db['accelerator.setup']
# TODO
# this is a temporary solution to avoid the MongoDB dependency
# rework this to use the file repository along with mongodb

import json
from pathlib import Path
from typing import Iterable, List, Dict, Any

# -----------------------------------------------------------------
# locate and load the data file once; keep it cached in _DATA
# -----------------------------------------------------------------

# _DATA_FILE = Path.home() / "Documents" / "dt4acc_soleil_twin_data" / "accelerator_setup.json"
_DATA_FILE = (
        Path(__file__)
        .resolve()  # .../src/dt4acc/custom_epics/queries_json.py
        .parent  # .../src/dt4acc/custom_epics/data
        / "standard"
        / "accelerator_setup.json"
)

with _DATA_FILE.open() as fp:
    _DATA: List[Dict[str, Any]] = json.load(fp)


# -----------------------------------------------------------------
# helper: Mongo-style $in filtering for the tiny use-cases we need
# -----------------------------------------------------------------
def _match(doc: Dict[str, Any], field: str, allowed: Iterable[str]) -> bool:
    return doc.get(field) in allowed


# -----------------------------------------------------------------
# public API
# -----------------------------------------------------------------
def get_controlled_elements():
    """Return all controlled magnetic elements as an iterator."""
    wanted = {"Quadrupole", "Sextupole", "Steerer"}
    return (d for d in _DATA if _match(d, "type", wanted))


def get_elements_per_power_converter(pc: str) -> List[Dict[str, Any]]:
    """Return all controlled elements driven by the given power-converter name."""
    return [d for d in _DATA if d.get("pc") == pc]


def get_unique_magnet_power_converters() -> List[str]:
    """Distinct list of power-converter names for Quad/Sext/Steerer magnets."""
    wanted = {"Quadrupole", "Sextupole", "Steerer"}
    return sorted({d["pc"] for d in _DATA if _match(d, "type", wanted)})


def get_unique_power_converters_for_types(type_list: Iterable[str]) -> List[str]:
    """Distinct list of power-converter names for the supplied magnet types."""
    wanted = set(type_list)
    return sorted({d["pc"] for d in _DATA if _match(d, "type", wanted)})


# Backward-compatible aliases for older call sites.
def get_magnets():
    return get_controlled_elements()


def get_magnets_per_power_converters(pc: str) -> List[Dict[str, Any]]:
    return get_elements_per_power_converter(pc)


def get_unique_power_converters() -> List[str]:
    return get_unique_magnet_power_converters()


def get_unique_power_converters_type_specified(type_list: Iterable[str]) -> List[str]:
    return get_unique_power_converters_for_types(type_list)

#
# def get_magnets():
#     return collection.find({"type": {"$in": ["Quadrupole", "Sextupole", "Steerer"]}})
#
#
# def get_magnets_per_power_converters(pc):
#     return list(collection.find({"pc": pc}))
#
#
# def get_unique_power_converters():
#     """Fetch unique power converter names from magnets in the DB."""
#     return collection.distinct("pc", {"type": {"$in": ["Quadrupole", "Sextupole", "Steerer"]}})
#
#
# def get_unique_power_converters_type_specified(type_list):
#     """Fetch unique power converter names from magnets in the DB."""
#     return collection.distinct("pc", {"type": {"$in": type_list}})
