"""Name-based direction classification for SOLEIL correctors."""

from typing import Literal, Optional


CorrectorDirection = Literal["horizontal", "vertical"]


def corrector_direction(
    name: str,
    family_name: str = "",
    subtype: str = "",
) -> Optional[CorrectorDirection]:
    """Return the physical corrector direction encoded by a control-system name."""
    if subtype == "H":
        return "horizontal"
    if subtype == "V":
        return "vertical"

    if family_name.endswith("_HCOR"):
        return "horizontal"
    if family_name.endswith("_VCOR"):
        return "vertical"

    if any(
        marker in name
        for marker in (
            "CDLH", "CDRH", "CRFCX", "CRCOX", "EM-COR/CH", "EI-COR/CH", "-CHE", "-CHS",
        )
    ):
        return "horizontal"
    if any(
        marker in name
        for marker in (
            "CDLV", "CDRV", "CRFCY", "CRCOY", "EM-COR/CV", "EI-COR/CV", "-CVE", "-CVS",
        )
    ):
        return "vertical"
    return None


def corrector_lattice_property(
    name: str,
    family_name: str = "",
    subtype: str = "",
) -> Optional[str]:
    """Return the multipole coefficient used by a recognised corrector."""
    direction = corrector_direction(name, family_name, subtype)
    if direction == "horizontal":
        return "B1"
    if direction == "vertical":
        return "A1"
    return None
