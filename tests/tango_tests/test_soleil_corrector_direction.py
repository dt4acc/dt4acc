from dt4acc.custom_facility.soleil.corrector_direction import (
    corrector_direction,
    corrector_lattice_property,
)


def test_soleil_corrector_name_conventions_map_to_expected_coefficients():
    cases = {
        "AN01-AR/EM-COR/SHF.01-CDLH.01": "B1",
        "AN01-SD/EM-COR/CDRH.02": "B1",
        "AN01-AR/EM-COR/CRFCX.01": "B1",
        "AN03-SD/EI-COR/CHE": "B1",
        "AN16-SD/EI-COR/CPMU18.1-CHE": "B1",
        "AN01-AR/EM-COR/SHF.01-CDLV.01": "A1",
        "AN01-SD/EM-COR/CDRV.02": "A1",
        "AN01-AR/EM-COR/CRFCY.01": "A1",
        "AN03-SD/EI-COR/CVE": "A1",
        "AN03-SD/EI-COR/CVS": "A1",
        "AN16-SD/EI-COR/CPMU18.1-CVS": "A1",
        "AN01-AR/EM-COR/CH.01": "B1",
        "AN01-AR/EM-COR/CV.01": "A1",
    }

    for name, property_name in cases.items():
        assert corrector_lattice_property(name) == property_name


def test_corrector_family_and_subtype_are_supported():
    assert corrector_direction("unclassified", "Q_HCOR") == "horizontal"
    assert corrector_direction("unclassified", "Q_VCOR") == "vertical"
    assert corrector_lattice_property("unclassified", subtype="H") == "B1"
    assert corrector_lattice_property("unclassified", subtype="V") == "A1"


def test_unrelated_magnet_is_not_classified_as_a_corrector():
    assert corrector_direction("AN01-AR/EM-QP/QF.01") is None
    assert corrector_lattice_property("AN01-AR/EM-QP/QF.01") is None
