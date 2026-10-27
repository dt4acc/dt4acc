Prerequisites
-------------

* Description of a lattice
* conversion between the different `views`


Handling the lattice file
-------------------------

Currently only pyat is used as back engine. This lattice file needs to be
loaded. Some simple files can be read by `at.load_m`; Its safer to load them
from json.

If you have the file only in matlab ".m" format, it is typically safer to
export it to json. pyat can only read an accelerator toolbox if stored in a
very specific manner.

As of the date of this writing the author could not instantiate such an lattice
using the tools provided by pyat. Please drop a line if that can be done

In the mean time use  what :mod:`lat2db.tools.factories` provides to instaniate
the lattice.


Requirements to lattice elements
--------------------------------

`dt4acc` is build on the concept of identifiers:

* identifiers for each `lattice element` dt4acc must handle
* identifiers for each `device` dt4acc must handle

Furthermore each property that needs to be changed (be it a device or
a lattice element) must be unique.

Many lattices out there use the tuple `(family_name, sector, child)` as
identifier. Such an identifier is available as
:class:`MMLStyleDeviceIdentifier`. This could be added to each pyat element.

:class:`NameAugmenter` supports creating these names using such
code as

.. code-block:: python
   :linenos:
    def add_uid(elem):
        # This lattice marks each sector with a marker with this Family name
        if elem.FamName.startswith("SECT"):
            nm.new_sector(elem.FamName)
        sector, child = nm.sector_child_for_family_name(elem.FamName)
        elem.UUID = f"{elem.FamName}-sec_{sector}-child_{child}"

    [add_uuid(elem) for elem in elements]

You could also use:

.. code-block:: python
    elem.UUID = MMLStyleDeviceIdentifier(elem.Famname, sector, child)


.. todo::
    Describe what accelerator toolbox has in store for exporting
    data

    Proper reference to the `MMLStyleDeviceIdentifier` and `NameAugmenter`


Preparing device (nomen clature)
--------------------------------

`Lattice elements` are the idealistic components and accelerator lattice is
built of. `Devices` are the real world devices that are built to implement
the desired functionality of the individual lattice elements. Furthermore, these
devices require supplies: e.g. electromagnets need power converters that drive
them. These power converters are then integrated to the control system.

Dt4acc builds a view of the twin presenting the devices themselfes or the
devices that drive the -- i.e. what is exposed to the network. While devices as
magnets typically can be derived from their equivalent elements,this is
typically not so straight forward for e.g. power converters.

Every lab has its own naming convention. Get help from colleagues to get the
correct naming of the devices. (This information is necessary to build the input
for the `liaison manager` and the `translation service`.


Preparing conversion
--------------------

You need to know how the different value map from
element parameters to the device parameters.
`dt4acc-lib` provides you with different objects for typical usage:

* linear conversion which can be dependent on the energy or not
* linear interpolation between points

You are free to roll your own. They only need to adhere to the
specified interfaces.

* :class:`dt4acc_lib.interfaces.utils.liaison_manager.LiaisonManagerBase`
* :class:`dt4acc_lib.interfaces.utils.translator_service.TranslatorServiceBase`

The concept of Liaison managment and Translator Service is explained
at ...

.. todo::

    add ALS style magnet conversion

    explain Liaison manager and translator service
