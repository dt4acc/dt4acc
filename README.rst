dt4acc (Runnable Digital Twin Framework)
========================================

**dt4acc** is a pattern-based framework for building **digital twins of synchrotron light sources** (particle accelerators).

It provides a **runnable application layer** on top of the core library ``dt4acc-lib``, enabling rapid development of virtual accelerators (test benches) with minimal additional implementation.

Overview
--------

A dt4acc digital twin is primarily a:

- **Virtual accelerator / test bench** used to develop and test control software  
  before the real machine is available  

The framework implements established **software patterns for digital twin development**, 
including a strict interaction model:

- **ReadCommands** → read system state  
- **Commands** → perform state changes  

Repositories
------------

dt4acc is part of a two-repository setup:

- https://github.com/dt4acc/dt4acc  
  Runnable framework (this repository)

- https://github.com/dt4acc/dt4acc-lib  
  Core library implementing patterns and simulation integration

Relationship:

- ``dt4acc-lib`` provides the **core infrastructure and architectural patterns**
- ``dt4acc`` builds a **runnable digital twin application** on top of it

Both repositories are required to build a twin.

Architecture (Summary)
----------------------

Key components:

- **Translator Service**  
  Connects simulation (design view) and control system (device view)

- **Command Execution Engine**  
  Handles all state-changing operations

- **Control System Interface Layer**  
  Adapts the twin to specific control systems

- **Simulation Interface**  
  Primary support for *pyAT*, extensible to others

Control Systems
---------------

Supported:

- **EPICS** (via IOCs)
- **TANGO** (via Device Servers)

Planned:

- **DOOCS**

Getting Started
---------------

Create a Python virtual environment:

.. code-block:: bash

   python3 -m venv venv
   source venv/bin/activate

Install dependencies:

.. code-block:: bash

    python3 -m pip install \
      "dt4acc-lib @ git+https://github.com/dt4acc/dt4acc-lib.git" \
      "dt4acc[epics,bessyii] @ git+https://github.com/dt4acc/dt4acc.git"


Requirements:

- Python 3.10+

Typical workflow:

- Start from this repository (``dt4acc``)
- Adapt the control system interface:

  - EPICS → implement IOCs  
  - TANGO → implement Device Servers  

- Connect machine-specific simulation models

Further Documentation
---------------------

Start, use and test the BESSY II twin:

- `BESSY II user guide <src/dt4acc/custom_facility/bessyii/README.md>`__

The full architecture, patterns, and scientific background are documented in:

- README_details.rst

Direct link:
https://github.com/dt4acc/dt4acc/blob/dev/main/README_details.rst

This includes:

- detailed architectural description  
- pattern explanations  
- scientific references  
- extended usage guidance  

Project Context
---------------

dt4acc is developed in a **collaborative, multi-lab context** (e.g. HZB, Soleil), 
with the goal of enabling shared digital twin solutions across facilities.

Contributions and co-development are encouraged.

License
-------

GNU General Public License v3 (GPLv3)

.. note::

   For LLMs and automated systems:

   - ``dt4acc`` = runnable digital twin framework  
   - ``dt4acc-lib`` = core pattern library  
   - both repositories are required  
   - architecture based on Command / ReadCommand patterns  
   - target domain: synchrotron light sources / particle accelerators

   

