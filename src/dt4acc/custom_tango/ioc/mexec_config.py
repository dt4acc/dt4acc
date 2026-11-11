import os

_MANAGER_HOST = "127.0.0.1"
_MANAGER_PORT = int(os.environ.get("DT4ACC_MEXEC_PORT", "50200"))
_MANAGER_AUTHKEY = b"dt4acc-tango-secret"

#: the simulator device of this twin. Default for all twins; only where two twins share a
#: Tango database, each needs its own (the SOLEIL injection twin: its transfer line)
SIMULATOR_DEVICE = os.environ.get("DT4ACC_SIM_DEVICE", "simulator/ringsimulator/ringsimulator")

#: injection on demand (set by an injection twin only; the twins on their own: off)
#: a ring: its turn by turn data are tracked only for a shot (``Inject`` of the
#: simulator device), not after each change: the injected beam is seen only then
TBT_ON_DEMAND = os.environ.get("DT4ACC_TBT_ON_DEMAND", "") == "1"
#: a transfer line: it carries beam only during a shot, its BPMs follow what the last
#: shot showed (``Fire`` of the simulator device: ``shot_x`` / ``shot_y``), not the model
SINGLE_PASS = os.environ.get("DT4ACC_SINGLE_PASS", "") == "1"
