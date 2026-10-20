"""
device_values.py
================
A device's value from the lattice, through the liaison manager and the
translation service (device view).

A device drives several lattice element properties (a combined-function
supply: every slice's dipole, quadrupole and sextupole share). Each of them,
translated forward with that device's own conversion, gives a value for the
device; where the lattice was written through the liaison they all agree.
The lattice file the twin starts from need not lie in that image (e.g. no
dipole share on combined-function quadrupole slices), so the device value is the
median of them: the outliers drop out, no rule on property names needed.
"""
from statistics import median
from typing import Callable, Optional, Sequence

from dt4acc_lib.model.utils.identifiers import (
    ConversionID,
    DevicePropertyID,
    LatticeElementPropertyID,
)


def lattice_ids(lm, device_id: str, prop: str) -> Sequence[LatticeElementPropertyID]:
    """The lattice element properties a device property drives (empty if none)."""
    return lm.inverse_lut.get(DevicePropertyID(device_name=device_id, property=prop)) or []


def device_value_from(lm, ts, values, device_id: str, prop: str) -> Optional[float]:
    """values: {LatticeElementPropertyID: present lattice value}; None if no
    lattice property of the device could be translated."""
    dev = DevicePropertyID(device_name=device_id, property=prop)
    out = []
    for lat in lattice_ids(lm, device_id, prop):
        if lat not in values or values[lat] is None:
            continue
        try:
            conversion = ts.get(ConversionID(lattice_property_id=lat, device_property_id=dev))
            out.append(float(conversion.forward(float(values[lat]))))
        except Exception:
            continue
    return median(out) if out else None


def device_value(lm, ts, read: Callable[[str, str], float], device_id: str, prop: str) -> Optional[float]:
    """As device_value_from, reading each lattice property with read(element, property)."""
    values = {}
    for lat in lattice_ids(lm, device_id, prop):
        try:
            values[lat] = read(lat.element_name, lat.property)
        except Exception:
            continue
    return device_value_from(lm, ts, values, device_id, prop)


def supply_names(lm, prop: str = "set_current") -> Sequence[str]:
    """Every device with a current setpoint in the liaison manager."""
    return [e.dev_id.device_name for e in lm.inverse_lut.lut if e.dev_id.property == prop]
