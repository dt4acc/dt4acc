"""The stops' record: names checked against the lattice before they are set"""
from types import SimpleNamespace

# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.custom_epics.ioc.stops import stops_record


def test_stops_record():
    made, stops = {}, []

    class Builder:
        def longStringOut(self, name, **kwargs):
            made[name] = kwargs

    # the last uid: the optics' end point, no element of its own
    backend = SimpleNamespace(acc=SimpleNamespace(acc=["A", "B"]), get_element_uids=lambda: ["A", "B", "B:exit"])
    stops_record("TBT:stops", backend, stops.append, builder=Builder())
    record = made["TBT:stops"]
    assert record["validate"](None, "A, B") and record["validate"](None, "")
    assert not record["validate"](None, "A, NOPE") and not record["validate"](None, "B:exit")
    record["on_update"]("A, B")
    record["on_update"]("")
    assert stops == [["A", "B"], []]
