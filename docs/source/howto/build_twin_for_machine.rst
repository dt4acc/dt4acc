Building a twin for a machine
=============================

.. toctree::
   :maxdepth: 3
   :caption: Contents:

   twin_info_prerequisites
   twin_info_mml

--------------------

Liaison management
~~~~~~~~~~~~~~~~~~

Or: whom do I have to talk to

Translation service
~~~~~~~~~~~~~~~~~~~

Or: how do I convert my value


Setting up the view: the control system interface to the devices
----------------------------------------------------------------

Currently 2 control systems are supported
* EPICS
* TANGO

Devices are set up:by dedicated view components (e.g. for orbit,
Twiss parameters or Tune).

EPICS Interface
~~~~~~~~~~~~~~~
Functionality is provided to instantiate many EPCIS process variables using
the `Monitor` or `Setpoint` data model.

So all to do for that is build the Monitor and setpoint variables

.. todo::
    Proper references for `Monitor` and `Setpoint`

