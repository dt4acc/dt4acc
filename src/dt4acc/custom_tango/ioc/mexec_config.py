import os

_MANAGER_HOST = "127.0.0.1"
_MANAGER_PORT = int(os.environ.get("DT4ACC_MEXEC_PORT", "50200"))
_MANAGER_AUTHKEY = b"dt4acc-tango-secret"

#: the simulator device of this twin. Default for all twins; only where two twins share a
#: Tango database, each needs its own (the SOLEIL injection twin: its transfer line)
SIMULATOR_DEVICE = os.environ.get("DT4ACC_SIM_DEVICE", "simulator/ringsimulator/ringsimulator")
