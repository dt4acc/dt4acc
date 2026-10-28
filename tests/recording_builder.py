"""A stand in for softioc's builder that records the PV names it is asked for

The twins' PV setup takes the builder as an argument: with this one, a test
sees the PVs a twin would serve without starting an IOC.
"""
from typing import Dict, List


class Record:
    def __init__(self, name: str, kind: str, initial_value=None):
        self.name, self.kind, self.value = name, kind, initial_value

    def set(self, value, *args, **kwargs):
        self.value = value

    def get(self):
        return self.value


class RecordingBuilder:
    """``SetDeviceName`` sets the prefix, any record type records the full name"""

    def __init__(self):
        self.prefix = ""
        self.records: Dict[str, Record] = {}

    def SetDeviceName(self, prefix: str):
        self.prefix = prefix

    def __getattr__(self, kind: str):
        if kind.startswith("_"):
            raise AttributeError(kind)

        def make(name, *args, initial_value=None, **kwargs):
            full = f"{self.prefix}:{name}" if self.prefix else name
            assert full not in self.records, f"PV {full} created twice"
            self.records[full] = Record(full, kind, initial_value)
            return self.records[full]

        return make

    def names(self, prefix: str) -> List[str]:
        """names below ``prefix``, without it"""
        return sorted(n[len(prefix) + 1:] for n in self.records if n.startswith(prefix + ":"))
