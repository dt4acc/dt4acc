"""The command line of the SOLEIL TL2 twin: the SOLEIL ring's, with the line's defaults
(``custom_facility/soleil/utils/command_line_interface``)"""
import os
from pathlib import Path

from dt4acc.config.data.querries import configure_data_file
from dt4acc.custom_facility.soleil.utils import command_line_interface as soleil_cli

# ---------------------------------------------------------------------------
# SOLEIL TL2 defaults
# ---------------------------------------------------------------------------
DATA_DIR = Path.home() / "Documents" / "dt4acc_config_data" / "soleilii-tl"
DEFAULT_LATTICE_FILE = DATA_DIR / "tl2_lattice_uuid.json"
DEFAULT_TWISS_IN_FILE = DATA_DIR / "twiss_in.yaml"
DEFAULT_SETUP_FILE = DATA_DIR / "accelerator_setup.json"

LOAD_MANAGERS = "dt4acc.custom_facility.soleil_tl2.liasion_translator_setup:load_managers"


def build_args_parser():
    parser = soleil_cli.build_args_parser()
    parser.description = "Launch the SOLEIL TL2 digital twin TANGO server"
    parser.add_argument(
        "--twiss-in",
        type=Path,
        default=Path(os.environ.get("DT4ACC_TWISS_IN_FILE", DEFAULT_TWISS_IN_FILE)),
        help=f"The beam entering the line (default: {DEFAULT_TWISS_IN_FILE})",
    )
    parser.set_defaults(lattice=Path(os.environ.get("DT4ACC_LATTICE_FILE", DEFAULT_LATTICE_FILE)))
    return parser


def parse_args():
    return build_args_parser().parse_args()


def setup_environment(args) -> None:
    """The environment of the twin's processes; the device database: DT4ACC_ACCELERATOR_SETUP_FILE, as the ring"""
    setup_file = os.environ.get("DT4ACC_ACCELERATOR_SETUP_FILE", str(DEFAULT_SETUP_FILE))
    os.environ.update(
        TANGO_HOST=args.tango_host,
        DT4ACC_ACCELERATOR_SETUP_FILE=setup_file,
        DT4ACC_LATTICE_FILE=str(args.lattice),
        DT4ACC_TWISS_IN_FILE=str(args.twiss_in),
        DT4ACC_LOAD_MANAGERS=LOAD_MANAGERS,
        DT4ACC_VIEW=args.view,
    )
    configure_data_file(setup_file)


def display_setup_from_args(args):
    soleil_cli.display_setup_from_args(args)
    print(f"  Beam entering    : {args.twiss_in}")
    print(f"  Devices          : {os.environ.get('DT4ACC_ACCELERATOR_SETUP_FILE')}")
