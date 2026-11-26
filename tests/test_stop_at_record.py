"""The stop's record: the name checked against the lattice before it is set"""
from types import SimpleNamespace

# loads the EPICS record types, before any module that imports softioc's records
from softioc import builder as _softioc_builder  # noqa: F401

from dt4acc.custom_epics.ioc.stop_at import stop_at_record


def test_stop_at_record():
    made, stops = {}, []

    class Builder:
        def stringOut(self, name, **kwargs):
            made[name] = kwargs

    # the last uid: the optics' end point, no element of its own; "D": twice
    backend = SimpleNamespace(acc=SimpleNamespace(acc=["A", "D", "D"]), get_element_uids=lambda: ["A", "D", "D", "D:exit"])
    stop_at_record("TBT:stop_at", backend, stops.append, builder=Builder())
    record = made["TBT:stop_at"]
    assert record["validate"](None, "A") and record["validate"](None, " A ") and record["validate"](None, "")
    for rejected in ("NOPE", "D", "D:exit", "A, D"):
        assert not record["validate"](None, rejected), rejected
    record["on_update"]("A")
    record["on_update"]("")
    assert stops == ["A", None]
