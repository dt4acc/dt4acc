import functools
import logging
from collections import defaultdict
from importlib.resources import files
from pathlib import Path
from typing import Tuple

import jsons
import yaml
from pydantic import TypeAdapter

from dt4acc.core.model.view import ProcessVariableCollection
from dt4acc_lib.bl.liaison_manager import LiaisonManager
from dt4acc_lib.bl.translator_service import TranslatorService
from dt4acc_lib.bl.unit_conversion import LinearUnitConversion, EnergyDependentLinearUnitConversion
from dt4acc_lib.bl.yellow_pages import YellowPages
from dt4acc_lib.interfaces.utils.liaison_manager import LiaisonManagerBase
from dt4acc_lib.interfaces.utils.translator_service import TranslatorServiceBase
from dt4acc_lib.interfaces.utils.yellow_pages import YellowPagesBase
from dt4acc_lib.model.utils.identifiers import LatticeElementPropertyID, DevicePropertyID, ConversionID
from dt4acc_lib.model.utils.liaison_manager_lookup_table import LiaisonManagerInverseLookupTable, LiaisonManagerForwardLookupTable
from dt4acc_lib.model.utils.translator_manager_lookup_table import TranslatorLookupTable

logger = logging.getLogger("dt4acc")


@functools.lru_cache(maxsize=1)
def load_managers() -> (YellowPagesBase, LiaisonManagerBase, TranslatorServiceBase, ProcessVariableCollection):
    """

    Todo:
        appropriate to separate caching from loading?
    """
    return build_managers(("custom_facility", "bessyii", "resources", "storage_ring", "created"))


def build_managers(config_dir: Tuple[str]):
    obj = load_file(config_dir + ("bessyii_yellow_pages_lookup_table.yml",))
    yp_lut = jsons.load(obj)
    yp = YellowPages(yp_lut)

    obj = load_file(config_dir + ("bessyii_liaison_manager_forward_lookup_table.yml",))
    lm_fwd = jsons.load(obj, LiaisonManagerForwardLookupTable)
    obj = load_file(config_dir + ("bessyii_liaison_manager_inverse_lookup_table.yml",))
    lm_inv = jsons.load(obj, LiaisonManagerInverseLookupTable)
    lm = LiaisonManager(forward_lut=lm_fwd, inverse_lut=lm_inv)

    obj = load_file(config_dir + ("bessyii_translation_service_lookup_table.yml",))
    ts_lut = jsons.load(obj, TranslatorLookupTable)
    #: Todo: use correct brho!
    ts = TranslatorService(lut=ts_lut, brho=5.4)

    obj = load_file(config_dir + ("bessyii_process_variables.yml",))
    pv_col = TypeAdapter(ProcessVariableCollection).validate_python(obj)

    return yp, lm, ts, pv_col

def load_file(config_dir: Tuple[str]):
    t_file = files("dt4acc").joinpath(*(config_dir))
    with open(t_file, "rt") as fp:
        obj = yaml.load(fp, yaml.Loader)
    return obj



if __name__ == "__main__":
    yp, lm, tm = build_managers("custom/accml_lib/config_data")
    # lat_prop_id = LatticeElementPropertyID(element_name="QF1C01A", property="set_current")
    # r, = lm.forward(lat_prop_id)
    # dev_prop_id = DevicePropertyID(device_name="PC_QF1C01A", property="set_current")
    # r, = lm.inverse(dev_prop_id)
    # to = tm.get(ConversionID(lattice_property_id=r, device_property_id=dev_prop_id))  # pprint.pprint(to)
