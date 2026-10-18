import json
from abc import ABCMeta, abstractmethod
from enum import Enum
from typing import Sequence, Union

from dt4acc.config.data.querries import get_data_file
from dt4acc.custom_facility.soleil.corrector_direction import corrector_direction


class FamilyTree(metaclass=ABCMeta):
    """Handling lattice element and their family belonging

    Todo:
        Shall one distinguish that ?

    Two ways to see it:
    * family as seen by a lattice:
        typically some magnets that are split all over the place

    Imagine for some lattice e.g. some quadrupoles could be
    identically as they are produced. But they could still
    belong to different families
    """

    @abstractmethod
    def get(self, family_name: str) -> Sequence[str]:
        """Return a sequence with all identifiers belonging to base class"""
        raise NotImplementedError("use derived class instead")


class FamilyName(Enum):
    quadrupoles = "quadrupoles"
    sextupoles = "sextupoles"
    bends = "bends"
    multipoles = "multipoles"
    horizontal_steerers = "horizontal_steerers"
    vertical_steerers = "vertical_steerers"


class YellowPages(FamilyTree):
    def __init__(self, d: dict):
        self._d = d

    def get(self, family_name: Union[str, FamilyName]) -> Sequence[str]:
        if isinstance(family_name, FamilyName):
            key = family_name.value
        else:
            key = str(family_name)
        return self._d[key]

    def quadrupole_names(self) -> Sequence[str]:
        return self.get("quadrupoles")

    def sextupole_names(self) -> Sequence[str]:
        return self.get("sextupoles")

    def bend_names(self) -> Sequence[str]:
        return self.get("bends")

    def multipole_names(self) -> Sequence[str]:
        return self.get("multipoles")

    def horizontal_steerer_names(self) -> Sequence[str]:
        return self.get("horizontal_steerers")

    def vertical_steerer_names(self) -> Sequence[str]:
        return self.get("vertical_steerers")

    def skew_quadrupole_corrector_names(self) -> Sequence[str]:
        """Return names of all CQLT skew quadrupole correctors on octupoles."""
        return self.get("skew_quadrupole_correctors")

    def quadrupole_corrector_names(self) -> Sequence[str]:
        """Return names of all CQLN skew quadrupole correctors on octupoles."""
        return self.get("quadrupole_correctors")

    def cavity_names(self) -> Sequence[str]:
        return self.get("cavities")

    def octupole_names(self) -> Sequence[str]:
        return self.get("octupoles")


    def skew_quadrupole_corrector_host_id(self, element_name: str) -> str:
        """
        Return the host element ID for a given skew quad corrector name.
        Returns "CQLT:<uuid>" — parsed by accelerator_simulator.get().
        """
        return self._d["skew_quadrupole_corrector_host_ids"][element_name]
    def quadrupole_corrector_host_id(self, element_name: str) -> str:
        """
        Return the host element ID for a given skew quad corrector name.
        Returns "CQLN:<uuid>" — parsed by accelerator_simulator.get().
        """
        return self._d["quadrupole_corrector_host_ids"][element_name]


def soleil_yellow_pages() -> YellowPages:
    """
    Creates a YellowPages instance for SOLEIL using the configured
    accelerator_setup.json.
    """

    elements = json.loads(get_data_file().read_text())

    def is_horizontal(e: dict) -> bool:
        return corrector_direction(e["name"], e.get("FamName", "")) == "horizontal"

    def is_vertical(e: dict) -> bool:
        return corrector_direction(e["name"], e.get("FamName", "")) == "vertical"

    quadrupoles = [e["name"] for e in elements if e["type"] == "Quadrupole"]
    sextupoles = [e["name"] for e in elements if e["type"] == "Sextupole"]
    bends = [e["name"] for e in elements if e["type"] == "Bend"]
    multipoles = [e["name"] for e in elements if e["type"] == "Multipole"]

    # Correctors can be catalogued as Steerer, Corrector or Multipole.
    corrector_types = {"Steerer", "Corrector", "Multipole"}
    horizontal_steerers = [
        e["name"] for e in elements
        if e["type"] in corrector_types and is_horizontal(e)
    ]
    vertical_steerers = [
        e["name"] for e in elements
        if e["type"] in corrector_types and is_vertical(e)
    ]

    # QuadrupoleCorrector: CQLN correctors on octupoles
    # uuid in JSON is "CQLN:<host_uuid>" or "CQLN:<host_uuid>"
    quadrupole_corrector_element = [e for e in elements if e["type"] == "QuadrupoleCorrector"]
    quadrupole_correctors = [e["name"] for e in quadrupole_corrector_element]
    # Map device name → prefixed host id e.g. "CQLN:OH2_QCORROCT_2_001"
    quadrupole_corrector_host_ids = {
        e["name"]: e["uuid"]
        for e in quadrupole_corrector_element
    }


    skew_quadrupole_corrector_elements = [e for e in elements if e["type"] == "SkewQuadrupoleCorrector"]
    skew_quadrupole_correctors = [e["name"] for e in skew_quadrupole_corrector_elements]
    skew_quadrupole_corrector_host_ids = {
        e["name"]: e["uuid"]
        for e in skew_quadrupole_corrector_elements
    }
    cavities = [e["name"] for e in elements if e["type"] == "RFCavity"]
    octupoles = [e["name"] for e in elements if e["type"] == "Octupole"]

    d = dict(
        quadrupoles=quadrupoles,
        sextupoles=sextupoles,
        bends=bends,
        multipoles=multipoles,
        horizontal_steerers=horizontal_steerers,
        vertical_steerers=vertical_steerers,
        quadrupole_correctors=quadrupole_correctors,
        quadrupole_corrector_host_ids=quadrupole_corrector_host_ids,
        skew_quadrupole_correctors=skew_quadrupole_correctors,
        skew_quadrupole_corrector_host_ids=skew_quadrupole_corrector_host_ids,
        cavities=cavities,
        octupoles=octupoles
    )

    return YellowPages(d)
