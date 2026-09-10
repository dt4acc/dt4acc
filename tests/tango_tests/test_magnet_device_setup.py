import pytest


pytest.importorskip("transitions")

from dt4acc.custom_tango.ioc.devices.tango_device_setup import _magnet_device_spec


@pytest.mark.parametrize(
    ("magnet", "expected"),
    [
        (
            {
                "name": "AN06-AR/EM-COR/CH.01",
                "type": "Multipole",
                "FamName": "COR_006",
            },
            ("HorizontalSteererDevice", "B1"),
        ),
        (
            {
                "name": "AN06-AR/EM-COR/CV.01",
                "type": "Steerer",
                "FamName": "COR_006",
            },
            ("VerticalSteererDevice", "A1"),
        ),
        (
            {
                "name": "AN06-AR/EM-DIP/B.01",
                "type": "Bend",
                "FamName": "B_011",
            },
            ("MultipoleDevice", "main_strength"),
        ),
    ],
)
def test_magnet_device_spec_matches_fodo_physical_type(magnet, expected):
    assert _magnet_device_spec(magnet) == expected
