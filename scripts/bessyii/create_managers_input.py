"""Managers input for BESSY II

"""
import functools
import logging
import datetime
import pprint
from collections import defaultdict
from dataclasses import asdict
from importlib.resources import files
from typing import Dict, Sequence, Tuple, List, Union

import jsons
import yaml
from pydantic import TypeAdapter

from dt4acc.core.model.view import Monitor, Setpoint, ProcessVariableCollection
from dt4acc.custom_facility.model.config.magnet import MagneticObject
from dt4acc.custom_facility.model.config.power_converter import PowerConverter
from dt4acc_lib.bl.yellow_pages import YellowPages
from dt4acc_lib.interfaces.utils.yellow_pages import YellowPagesBase
from dt4acc_lib.model.utils.command import ReadCommand
from dt4acc_lib.model.utils.identifiers import (
    DevicePropertyID,
    LatticeElementPropertyID,
    ConversionID,
)
from dt4acc_lib.model.utils.liaison_manager_lookup_table import (
    LiaisonManagerInverseLookupElement,
    LiaisonManagerInverseLookupTable,
    LiaisonManagerForwardLookupElement,
    LiaisonManagerForwardLookupTable,
)
from dt4acc_lib.model.utils.translator_manager_lookup_table import (
    TranslatorLookupTable,
    TranslatorLookupTableElement,
    PolynomCoefficients,
    TuneConversionCoefficients,
    IdentityMapper,
)


logger = logging.getLogger("dt4acc")


def build_liaison_manager_lut(
    data_path: Tuple[str], *, yp: YellowPagesBase
) -> Tuple[
    Sequence[LiaisonManagerForwardLookupElement],
    Sequence[LiaisonManagerInverseLookupElement],
    ProcessVariableCollection,
]:
    """A first poor mans implementation of liaison manager BessyII

    Todo:
        Which info is already in database and better obtained from database?
    """
    magnet_info = get_magnet_info(data_path=data_path)

    magnet_types = set([info.type for info in magnet_info])
    # Make sure that names are unique ... everything down the list depends on it
    magnet_names = set([info.elem_id for info in magnet_info])
    assert len(magnet_names) == len(
        magnet_info
    ), "Magnet names seem not to be unique, but is assumption of all further processing"

    power_converter_names = set([info.dev_id for info in magnet_info])
    power_converter_feeds = {
        pc_name: [info.elem_id for info in magnet_info if info.dev_id == pc_name]
        for pc_name in power_converter_names
    }

    pc_magnet_is_connected_to = {
        entry.elem_id: entry.power_converter_id for entry in magnet_info
    }

    # magnet_lut = {info.name: info for info in magnet_info}
    # todo: check if property must be different for the different magnets ...

    # These contain a one to one mapping (for quadrupoles and sextupoles)
    # therefore I need to group them as they belong together

    process_variable_views: List[Union[Monitor, Setpoint]] = []

    inv_d = defaultdict(list)
    fwd_d = defaultdict(list)
    for family_name, lattice_property, at_property in (
        # fmt:off
        ( "quadrupoles" , "main_strength", "K" ),
        ( "sextupoles"  , "main_strength", "H" ),
        # fmt:on
    ):
        for entry in magnet_info:
            if entry.elem_id in yp.get(family_name):
                dev_name = str(pc_magnet_is_connected_to[entry.elem_id])
                lat_p = LatticeElementPropertyID(
                    element_name=str(entry.elem_id), property=lattice_property
                )
                pc_dev_p = DevicePropertyID(
                    device_name=dev_name, property="set_current"
                )
                mag_dev_p = DevicePropertyID(
                    device_name=str(entry.dev_id), property="main_strength"
                )
                fwd_d[lat_p].append(pc_dev_p)
                inv_d[pc_dev_p].append(lat_p)
                inv_d[mag_dev_p].append(lat_p)
                # Readback current only needs to go one way
                inv_d[
                    DevicePropertyID(device_name=dev_name, property="rdbk_current")
                ].append(lat_p)
                # Todo: review naming of the properties
                inv_d[
                    DevicePropertyID(
                        device_name=entry.dev_id, property="main_strength_rdbk"
                    )
                ].append(lat_p)

                # view for the magnet
                monitor = Monitor(
                    pv_name=f"{mag_dev_p.device_name}:main_strength",
                    rcmd=ReadCommand(mag_dev_p.device_name, mag_dev_p.property),
                    prec=3,
                    record_type="ai",
                    treat_returned_data="average",
                )
                process_variable_views.append(monitor)

    # iterate over the actually used devices
    for pc_dev_p, assocated_lattice_elements in inv_d.items():
        if pc_dev_p.property != "set_current":
            continue
        # view for the power converter
        monitor = Monitor(
            pv_name=f"{pc_dev_p.device_name}:rdbk",
            rcmd=ReadCommand(pc_dev_p.device_name, "rdbk_current"),
            prec=3,
            record_type="ai",
            treat_returned_data="average",
        )
        setp = Setpoint(
            pv_name=f"{pc_dev_p.device_name}:set",
            rcmd=ReadCommand(pc_dev_p.device_name, pc_dev_p.property),
            prec=3,
            record_type="ao",
            # When a power converter changes all the magnets on
            # this string need to change too.
            # I use here that for BESSY II device names and lattice names are
            # so close to each other ...
            # So I rely on here that names match
            reads=[monitor.rcmd]
            + [
                ReadCommand(lat_p.element_name, lat_p.property)
                for lat_p in assocated_lattice_elements
            ],
            treat_returned_data="average",
        )
        process_variable_views.extend([monitor, setp])

    # special treatment for horizontal and vertical steerers as these are cowound ..
    # so the magnet name is the sextupole but the
    # power converter
    lut_fwd = []
    lut_inv = []

    for family_name, lattice_property, co_wound_prefix in (
        # fmt:off
        ( "horizontal_steerers" , "x_kick", "H"),
        ( "vertical_steerers"   , "y_kick", "V"),
        # fmt:on
    ):
        names_in_family = yp.get(family_name)
        for entry in magnet_info:
            if entry.elem_id in names_in_family:
                dev_name = str(pc_magnet_is_connected_to[entry.elem_id])
                magnet_name = str(entry.elem_id)
                assert magnet_name[0] == co_wound_prefix
                host_magnet_name = magnet_name[1:]
                if co_wound_prefix == "H":
                    assert host_magnet_name in yp.get("horizontal_steerers_host")
                elif co_wound_prefix == "V":
                    assert host_magnet_name in yp.get("vertical_steerers_host")
                else:
                    raise AssertionError("Should not end up here")
                lat_p = LatticeElementPropertyID(
                    element_name=host_magnet_name, property=lattice_property
                )
                pc_dev_p = DevicePropertyID(
                    device_name=dev_name, property="set_current"
                )
                mag_dev_p = DevicePropertyID(
                    device_name=str(entry.dev_id), property="main_strength"
                )
                fwd_d[lat_p].append(pc_dev_p)
                inv_d[pc_dev_p].append(lat_p)
                inv_d[mag_dev_p].append(lat_p)

                # Readback current only needs to go one way
                inv_d[
                    DevicePropertyID(device_name=dev_name, property="rdbk_current")
                ].append(lat_p)

                # view for the power converter ... for the steerers
                # these should be one to one.
                # not checking, only assuming
                monitor = Monitor(
                    pv_name=f"{pc_dev_p.device_name}:rdbk",
                    rcmd=ReadCommand(pc_dev_p.device_name, "rdbk_current"),
                    prec=3,
                    record_type="ai",
                    treat_returned_data="single",
                )
                monitor_mag = Monitor(
                    pv_name=f"{mag_dev_p.device_name}:rdbk",
                    rcmd=ReadCommand(mag_dev_p.device_name, "main_strength"),
                    prec=3,
                    record_type="ai",
                    treat_returned_data="single",
                )
                setp = Setpoint(
                    pv_name=f"{pc_dev_p.device_name}:set",
                    rcmd=ReadCommand(pc_dev_p.device_name, pc_dev_p.property),
                    prec=3,
                    record_type="ao",
                    # Power converter changes, magnet setting should change too
                    reads=[monitor.rcmd, monitor_mag.rcmd],
                    treat_returned_data="single",
                )
                process_variable_views.extend([monitor, setp, monitor_mag])

    lut_fwd += [
        LiaisonManagerForwardLookupElement(lat_id=k, dev_ids=v)
        for k, v in fwd_d.items()
    ]
    lut_inv += [
        LiaisonManagerInverseLookupElement(dev_id=k, lat_ids=v)
        for k, v in inv_d.items()
    ]
    del fwd_d, inv_d

    for family, same_property, pv_suffix in [
        # fmt:off
        ( "quadrupoles" , "dx" , "dx" ),
        ( "sextupoles"  , "dx" , "dx" ),
        ( "quadrupoles" , "dy" , "dy" ),
        ( "sextupoles"  , "dy" , "dy" ),
        # fmt:on
        ("cavities", "frequency", "freq")
    ]:
        for entry in magnet_info:
            if entry.elem_id in yp.get(family):
                lut_inv += [
                    LiaisonManagerInverseLookupElement(
                        dev_id=DevicePropertyID(
                            device_name=entry.dev_id, property=same_property
                        ),
                        lat_ids=[
                            LatticeElementPropertyID(
                                element_name=entry.elem_id, property=same_property
                            )
                        ],
                    ),
                    # Different command required for read back: view will send it to controller
                    # receive answer back, needs to distinquish it
                    LiaisonManagerInverseLookupElement(
                        dev_id=DevicePropertyID(
                            device_name=entry.dev_id, property=f"{same_property}_rdbk"
                        ),
                        lat_ids=[
                            LatticeElementPropertyID(
                                element_name=entry.elem_id, property=same_property
                            )
                        ],
                    ),
                ]
                lut_fwd += [
                    LiaisonManagerForwardLookupElement(
                        lat_id=LatticeElementPropertyID(
                            element_name=entry.elem_id, property=same_property
                        ),
                        dev_ids=[
                            DevicePropertyID(
                                device_name=entry.dev_id,
                                property=f"{same_property}_rdbk",
                            )
                        ],
                    )
                ]
                monitor = Monitor(
                    pv_name=f"{entry.dev_id}:{pv_suffix}:rdbk",
                    rcmd=ReadCommand(entry.dev_id, f"{same_property}_rdbk"),
                    prec=3,
                    record_type="ai",
                    treat_returned_data="average",
                )
                setp = Setpoint(
                    pv_name=f"{entry.dev_id}:{pv_suffix}:set",
                    rcmd=ReadCommand(entry.dev_id, same_property),
                    prec=3,
                    record_type="ao",
                    reads=[monitor.rcmd],
                    treat_returned_data="average",
                )
                process_variable_views.extend([monitor, setp])
                pass

    lut_inv += [
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(
                device_name="master_clock", property="reference_frequency"
            ),
            lat_ids=[
                LatticeElementPropertyID(element_name=cavity_name, property="frequency")
                for cavity_name in yp.get("cavities")
            ],
        ),
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name="master_clock", property="frequency"),
            lat_ids=[
                LatticeElementPropertyID(element_name=cavity_name, property="frequency")
                for cavity_name in yp.get("cavities")
            ],
        ),
    ]
    lut_inv += [
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name=cavity_name, property="frequency"),
            lat_ids=[
                LatticeElementPropertyID(element_name=cavity_name, property="frequency")
            ],
        )
        for cavity_name in yp.get("cavities")
    ]
    lut_fwd += [
        LiaisonManagerForwardLookupElement(
            lat_id=LatticeElementPropertyID(
                element_name=cavity_name, property="frequency"
            ),
            dev_ids=[
                DevicePropertyID(device_name="master_clock", property="frequency")
            ],
        )
        for cavity_name in yp.get("cavities")
    ]
    cavity_monitors = [
        Monitor(
            pv_name=f"{cavity_name}:freq:rdbk",
            rcmd=ReadCommand(cavity_name, "frequency"),
            prec=9,
            record_type="ai",
            treat_returned_data="single",
        )
        for cavity_name in yp.get("cavities")
    ]

    master_clock_monitor = Monitor(
        pv_name="MCLKHX251C:freq:rdbk",
        rcmd=ReadCommand("master_clock", "frequency"),
        prec=9,
        record_type="ai",
        treat_returned_data="average",
    )
    setp = Setpoint(
        pv_name="MCLKHX251C:freq",
        rcmd=ReadCommand("master_clock", "reference_frequency"),
        prec=9,
        record_type="ao",
        reads=[master_clock_monitor.rcmd] + [cav_m.rcmd for cav_m in cavity_monitors],
        treat_returned_data="average",
    )
    process_variable_views.extend(cavity_monitors + [master_clock_monitor, setp])

    # Dedicate elements that represent calculation results
    lut_fwd += [
        LiaisonManagerForwardLookupElement(
            lat_id=LatticeElementPropertyID(
                element_name="tune", property="transversal"
            ),
            dev_ids=[
                DevicePropertyID(device_name="tune", property=prop)
                for prop in (
                    "x",
                    "y",
                    "flq_x",
                    "flq_y",
                    "transversal",
                    "transversal_frequency",
                )
            ],
        )
    ]
    lut_inv += [
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name="tune", property=prop),
            lat_ids=[
                LatticeElementPropertyID(element_name="tune", property="transversal")
            ],
        )
        for prop in ("x", "y", "flq_x", "flq_y", "transversal", "transversal_frequency")
    ]

    lut_inv += [
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name="orbit", property="pos"),
            lat_ids=[LatticeElementPropertyID(element_name="orbit", property="pos")],
        )
    ]
    lut_inv += [
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name="twiss", property="parameters"),
            lat_ids=[
                LatticeElementPropertyID(element_name="twiss", property="parameters")
            ],
        ),
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name="track", property="pos"),
            lat_ids=[LatticeElementPropertyID(element_name="track", property="pos")],
        ),
        LiaisonManagerInverseLookupElement(
            dev_id=DevicePropertyID(device_name="survey", property="s"),
            lat_ids=[LatticeElementPropertyID(element_name="survey", property="s")],
        ),
    ]
    lut_fwd += [
        LiaisonManagerForwardLookupElement(
            lat_id=LatticeElementPropertyID(
                element_name="twiss", property="parameters"
            ),
            dev_ids=[DevicePropertyID(device_name="twiss", property="parameters")],
        ),
        LiaisonManagerForwardLookupElement(
            lat_id=LatticeElementPropertyID(element_name="track", property="pos"),
            dev_ids=[DevicePropertyID(device_name="track", property="pos")],
        ),
        LiaisonManagerForwardLookupElement(
            lat_id=LatticeElementPropertyID(element_name="survey", property="s"),
            dev_ids=[DevicePropertyID(device_name="survey", property="s")],
        ),
    ]

    return lut_fwd, lut_inv, ProcessVariableCollection(vars=process_variable_views)


def build_translator_manager_lut(
    data_path: Tuple[str],
    *,
    yp: YellowPagesBase,
    lm_inv: LiaisonManagerInverseLookupTable,
) -> Sequence[TranslatorLookupTableElement]:
    """A first poor mans implementation of liaison manager BessyII"""
    # start to build it for the magnets ... power converter feed

    magnet_infos = get_magnet_info(data_path=data_path)
    pc_infos = get_pc_info(data_path=data_path)

    lut: List[TranslatorLookupTableElement] = []

    # lets make the easy ones our selves first
    for cavity_name in yp.get("cavities"):
        # BESSY II displays master clock frequency in kHz
        lut.extend(
            [
                TranslatorLookupTableElement(
                    ConversionID(
                        lattice_property_id=LatticeElementPropertyID(
                            element_name=cavity_name, property="frequency"
                        ),
                        device_property_id=DevicePropertyID(
                            device_name="master_clock", property="reference_frequency"
                        ),
                    ),
                    PolynomCoefficients([0.0, 1.0 / 1000.0], energy_dependent=False),
                ),
                TranslatorLookupTableElement(
                    ConversionID(
                        lattice_property_id=LatticeElementPropertyID(
                            element_name=cavity_name, property="frequency"
                        ),
                        device_property_id=DevicePropertyID(
                            device_name="master_clock", property="frequency"
                        ),
                    ),
                    PolynomCoefficients([0.0, 1.0 / 1000.0], energy_dependent=False),
                ),
            ]
        )

    all_keys = [key for key in lm_inv.keys()]

    # Find out which power converter feeds what
    pc_feeds = defaultdict(list)
    for mag_info in magnet_infos:
        pc_feeds[mag_info.power_converter_id].append(mag_info.elem_id)

    # Simplify look up by magnet name
    mag_info_lut = {mag_info.elem_id: mag_info for mag_info in magnet_infos}

    unhandled = []

    # Need to address conversion: seems I have to invert the used
    # slope: but do it step by step: lets work on steerers power converters first
    for dev_p in all_keys:
        # Todo: seems I need to invert slope for correct translation
        #       lets do it step by step
        if not dev_p.device_name[0] in ["H", "V"]:
            # Not a steerer power converter, go ahead
            unhandled.append(dev_p)
            continue

        (lat_p,) = lm_inv.get(dev_p)
        if lat_p.element_name in yp.get("horizontal_steerers_host"):
            magnet_name = "H" + lat_p.element_name
            assert magnet_name in yp.get("horizontal_steerers")
        elif lat_p.element_name in yp.get("vertical_steerers_host"):
            magnet_name = "V" + lat_p.element_name
            assert magnet_name in yp.get("vertical_steerers")
        else:
            raise AssertionError(f"{lat_p} neither horizontal nor vertical steerer")
        conv = mag_info_lut[magnet_name].conversion
        assert conv.conversion_type == "linear"
        intercept, slope = conv.intercept, conv.slope
        assert intercept == 0.0
        if dev_p.property == "main_strength":
            # Todo: need to find out how to convert x_kick / y_kick to magnet
            #       strength
            #       something with length?
            slope = 1.0
        else:
            slope = 1.0 / slope
        lut.append(
            TranslatorLookupTableElement(
                ConversionID(lat_p, dev_p),
                PolynomCoefficients(
                    [intercept, slope],
                    # is it also energy dependent for the kick ?
                    energy_dependent=True,
                ),
            )
        )

    all_keys, unhandled = unhandled, []

    for dev_p in all_keys:
        feed_by_pc = pc_feeds.get(dev_p.device_name)
        if not feed_by_pc:
            unhandled.append(dev_p)
            continue
        lat_ps = lm_inv.get(dev_p)
        for lat_p in lat_ps:
            conv = mag_info_lut[lat_p.element_name].conversion
            assert conv.conversion_type == "linear"
            lut.append(
                TranslatorLookupTableElement(
                    ConversionID(lat_p, dev_p),
                    PolynomCoefficients(
                        [conv.intercept, 1.0 / conv.slope], energy_dependent=True
                    ),
                )
            )

    all_keys, unhandled = unhandled, []
    for dev_p in all_keys:
        if dev_p.property not in ["dx", "dy", "dx_rdbk", "dy_rdbk"]:
            unhandled.append(dev_p)
            continue
        (lat_p,) = lm_inv.get(dev_p)

        if lat_p.element_name not in yp.get(
            "quadrupoles"
        ) and lat_p.element_name not in yp.get("sextupoles"):
            unhandled.append(dev_p)
            continue

        lut.append(
            TranslatorLookupTableElement(
                ConversionID(lat_p, dev_p),
                PolynomCoefficients([0.0, 1.0], energy_dependent=False),
            )
        )

    # handle corrector main strength
    all_keys, unhandled = unhandled, []
    for dev_p in all_keys:
        if dev_p.device_name not in yp.get("steerers"):
            unhandled.append(dev_p)
            continue
        # assuming that there is only one for the steerer main strength
        (lat_p,) = lm_inv.get(dev_p)
        if lat_p.element_name == dev_p.device_name:
            # Todo: translation of kick to magnet: how to calculate the
            #       associated dipole strength.
            #       For the time being do just a linear mapping
            assert lat_p.property in ["x_kick", "y_kick"]
            assert dev_p.property == "main_strength"
            lut.append(
                TranslatorLookupTableElement(
                    ConversionID(lat_p, dev_p),
                    PolynomCoefficients([0.0, 1.0], energy_dependent=False),
                )
            )
        else:
            pass
        # Todo: find out the coefficient for magnet to steerer power converter

    all_keys, unhandled = unhandled, []
    dev_names = list(yp.get("quadrupoles")) + list(yp.get("sextupoles"))
    for dev_p in all_keys:
        if dev_p.property == "main_strength" and dev_p.device_name in dev_names:
            (lat_p,) = lm_inv.get(dev_p)
            lut.append(
                TranslatorLookupTableElement(
                    ConversionID(lat_p, dev_p),
                    PolynomCoefficients([0.0, 1.0], energy_dependent=False),
                )
            )
        elif dev_p.property == "main_strength_rdbk" and dev_p.device_name in dev_names:
            (lat_p,) = lm_inv.get(dev_p)
            lut.append(
                TranslatorLookupTableElement(
                    ConversionID(lat_p, dev_p),
                    PolynomCoefficients([0.0, 1.0], energy_dependent=False),
                )
            )
        else:
            unhandled.append(dev_p)

    lat_p = LatticeElementPropertyID(element_name="tune", property="transversal")
    lut.extend(
        [
            TranslatorLookupTableElement(
                ConversionID(
                    lat_p, DevicePropertyID(device_name="tune", property=prop)
                ),
                IdentityMapper(),
            )
            for prop in ("flq_x", "flq_y", "transversal")
        ]
    )

    # These are just a hack ... here we have interdependence of different
    #                           values
    #     to calculate it one would also need the reference frequency
    # Warning: Frequency needs to be read from master clock or similar
    # Todo:    investigate if already there
    floquet_to_frequency = 500e3 / 400.0
    lut.extend(
        [
            TranslatorLookupTableElement(
                ConversionID(
                    lat_p, DevicePropertyID(device_name="tune", property=prop)
                ),
                TuneConversionCoefficients(
                    PolynomCoefficients(
                        [0.0, floquet_to_frequency], energy_dependent=False
                    )
                ),
            )
            for prop in ("x", "y", "transversal_frequency")
        ]
    )

    lut.extend(
        [
            TranslatorLookupTableElement(
                ConversionID(
                    LatticeElementPropertyID(
                        element_name="twiss", property="parameters"
                    ),
                    DevicePropertyID(device_name="twiss", property="parameters"),
                ),
                IdentityMapper(),
            ),
            TranslatorLookupTableElement(
                ConversionID(
                    LatticeElementPropertyID(element_name="track", property="pos"),
                    DevicePropertyID(device_name="track", property="pos"),
                ),
                IdentityMapper(),
            ),
            TranslatorLookupTableElement(
                ConversionID(
                    LatticeElementPropertyID(element_name="survey", property="s"),
                    DevicePropertyID(device_name="survey", property="s"),
                ),
                IdentityMapper(),
            ),
        ]
    )

    print("No translation objects for")
    pprint.pprint(unhandled)
    return lut


def create_yellow_pages_entries() -> Dict[str, Sequence[str]]:
    # standard quadrupoles
    quadrupoles = [
        f"Q{family}M{child}{sector_type}{sector}R"
        for family in range(1, 6)
        for child in range(1, 3)
        for sector_type in ["D", "T"]
        for sector in range(1, 9)
    ]
    # Emil straight
    quadrupoles += ["QIT6R"]

    sextupoles = [
        f"S{family}M{sector_type}{sector}R"
        for family in range(1, 2)
        for sector_type in ["D", "T"]
        for sector in range(1, 9)
    ]
    sextupoles += [
        f"S{family}M{child}{sector_type}{sector}R"
        for family in range(2, 6)
        for child in range(1, 3)
        for sector_type in ["D", "T"]
        for sector in range(1, 9)
    ]
    horizontal_steerers = [
        f"H{sextupole}" for sextupole in sextupoles if sextupole[1] in ["1", "4"]
    ]
    vertical_steerers = [
        f"V{sextupole}" for sextupole in sextupoles if sextupole[1] in ["2", "3"]
    ]
    d = dict(
        quadrupoles=quadrupoles,
        sextupoles=sextupoles,
        horizontal_steerers=horizontal_steerers,
        vertical_steerers=vertical_steerers,
    )

    return d


class CompressedSequenceDumper(yaml.SafeDumper):
    def represent_sequence(self, tag, seq, flow_style=None):
        if len(seq) <= 12:  # threshold
            flow = True
        else:
            flow = False
        return super().represent_sequence(tag, seq, flow_style=flow)


@functools.lru_cache(maxsize=None)
def load_yaml_data_config(data_path: Tuple[str], module="dt4acc_lib"):
    t_file = files("dt4acc").joinpath(*(data_path))
    with open(t_file, "rt") as fp:
        obj = yaml.load(fp, yaml.SafeLoader)
    return obj


@functools.lru_cache(maxsize=None)
def get_magnet_info(
    data_path: Tuple[str], module="dt4acc_lib"
) -> Sequence[MagneticObject]:
    t_path = data_path + ("magnets.yaml",)
    return [MagneticObject(**d) for d in load_yaml_data_config(t_path)]


@functools.lru_cache(maxsize=None)
def get_pc_info(data_path: Tuple[str], module="dt4acc_lib") -> Sequence[PowerConverter]:
    t_path = data_path + ("power_converters.yaml",)
    return [PowerConverter(**d) for d in load_yaml_data_config(t_path)]


def create_yellow_pages_lut_from_config(
    data_path: Tuple[str],
) -> Dict[str, Sequence[str]]:

    magnet_info = get_magnet_info(data_path)

    magnet_types = set([info.type for info in magnet_info])
    # check that standard names are there
    assert "quadrupole" in magnet_types
    assert "sextupole" in magnet_types

    magnet_families = set([tuple(info.family_member) for info in magnet_info])

    # I need this info for a check
    sextupoles = [m.elem_id for m in magnet_info if m.type == "sextupole"]

    # This info should be in the config ... family info
    # furthermore these steerer names should not really exist
    # they are all rather correction coils on sextupoles
    # there are some special ones that are air coils,
    # I do not address them here
    steerers = [m.elem_id for m in magnet_info if m.type == "steerer"]
    # All
    horizontal_steerers = [st for st in steerers if st.startswith("H")]
    vertical_steerers = [st for st in steerers if st.startswith("V")]

    horizontal_steerers_host = [st[1:] for st in horizontal_steerers]
    vertical_steerers_host = [st[1:] for st in vertical_steerers]

    horizontal_steerer_not_co_wound = [
        st for st in horizontal_steerers_host if st not in sextupoles
    ]
    if horizontal_steerer_not_co_wound:
        logger.warning(
            "Following horizontal steerers are not on sextupoles ? %s",
            horizontal_steerer_not_co_wound,
        )
    vertical_steerer_not_co_wound = [
        st for st in vertical_steerers_host if st not in sextupoles
    ]
    if vertical_steerer_not_co_wound:
        logger.warning(
            "Following vertical steerers are not on sextupoles ? %s",
            vertical_steerer_not_co_wound,
        )

    r = dict(
        horizontal_steerers=horizontal_steerers,
        vertical_steerers=vertical_steerers,
        horizontal_steerers_host=horizontal_steerers_host,
        vertical_steerers_host=vertical_steerers_host,
        steerers=steerers,
        quadrupoles=[m.elem_id for m in magnet_info if m.type == "quadrupole"],
        sextupoles=sextupoles,
        cavities=[f"CAVH{cnt:01d}T8R" for cnt in range(1, 4 + 1)],
    )
    return r


def main():
    header_fmt = """#
# BESSY II {data_type}: {date}
# WARNING: automatically generated data
#          please check when it is updated if you edit it by hand!
"""
    yp_fname = "bessyii_yellow_pages_lookup_table.yml"
    lm_inv_fname = "bessyii_liaison_manager_inverse_lookup_table.yml"
    lm_fwd_fname = "bessyii_liaison_manager_forward_lookup_table.yml"
    process_variable_fname = "bessyii_process_variables.yml"
    ts_fname = "bessyii_translation_service_lookup_table.yml"
    data_path = ("custom_facility", "bessyii", "resources", "storage_ring", "input")

    yp_lut = create_yellow_pages_lut_from_config(data_path=data_path)
    now = datetime.datetime.now()

    with open(yp_fname, "wt") as fp:
        fp.write(header_fmt.format(**dict(data_type="yellow pages", date=now)))
        yaml.dump(yp_lut, fp, Dumper=CompressedSequenceDumper)
        fp.write("# EOF\n")
    del yp_lut, fp

    with open(yp_fname, "rt") as fp:
        yp_lut = yaml.safe_load(fp)
    del fp
    yp = YellowPages(yp_lut)

    lut_fwd_, lut_inv_, process_variable_view = build_liaison_manager_lut(
        data_path=data_path, yp=yp
    )
    pv_name_clashes = process_variable_view.get_pv_name_clashes()
    if pv_name_clashes:
        print("Pv name clashes detected!")
        pprint.pprint(pv_name_clashes)
        print(" ===========================")

    lut_fwd = LiaisonManagerForwardLookupTable(lut_fwd_)
    lut_inv = LiaisonManagerInverseLookupTable(lut_inv_)
    mismatched = lut_inv.non_unique_entries()
    if mismatched:
        print("Following items look up can be misleading!")
        pprint.pprint(mismatched)
        print(" ===========================================")

    del mismatched

    mismatched = lut_fwd.non_unique_entries()
    if mismatched:
        print("Following items look up can be misleading!")
        pprint.pprint(mismatched)
        print(" ===========================================")

    del mismatched

    with open(lm_inv_fname, "wt") as fp:
        fp.write(header_fmt.format(data_type="Liaison manager inverse table", date=now))
        yaml.dump(asdict(lut_inv), fp, Dumper=CompressedSequenceDumper)
        fp.write("# EOF\n")

    with open(lm_inv_fname, "rt") as fp:
        tmp = yaml.load(fp, Loader=yaml.SafeLoader)

    # verify that it gets reloaded
    lmt_inv = jsons.load(tmp, LiaisonManagerInverseLookupTable)
    lmt_inv.verify()

    with open(lm_fwd_fname, "wt") as fp:
        fp.write(header_fmt.format(data_type="Liaison manager forward table", date=now))
        yaml.dump(asdict(lut_fwd), fp, Dumper=CompressedSequenceDumper)
        fp.write("# EOF\n")
    del yp_lut

    with open(lm_fwd_fname, "rt") as fp:
        tmp = yaml.load(fp, Loader=yaml.SafeLoader)

    # verify that it gets reloaded
    lmt_fwd = jsons.load(tmp, LiaisonManagerForwardLookupTable)
    lmt_fwd.verify()

    with open(process_variable_fname, "wt") as fp:
        fp.write(header_fmt.format(**dict(data_type="process variables", date=now)))
        yaml.dump(
            process_variable_view.model_dump(mode="json"),
            fp,
            Dumper=CompressedSequenceDumper,
            sort_keys=False,
        )
        fp.write("# EOF\n")

    with open(process_variable_fname, "rt") as fp:
        data = yaml.unsafe_load(fp.read())
        pvc_chk = TypeAdapter(ProcessVariableCollection).validate_python(data)

    tlut = TranslatorLookupTable(
        lut=build_translator_manager_lut(data_path=data_path, yp=yp, lm_inv=lmt_inv)
    )

    with open(ts_fname, "wt") as fp:
        fp.write(
            header_fmt.format(**dict(data_type="Translation service table", date=now))
        )
        yaml.dump(asdict(tlut), fp, Dumper=CompressedSequenceDumper)
        fp.write("# EOF\n")

    with open(ts_fname, "rt") as fp:
        tmp = yaml.load(fp, Loader=yaml.SafeLoader)
    tlut_loaded = jsons.load(tmp, TranslatorLookupTable)
    assert tlut == tlut_loaded
    # pprint.pprint(tlut)


if __name__ == "__main__":
    main()
