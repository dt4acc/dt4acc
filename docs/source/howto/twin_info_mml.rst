Building a twin from existing matlab middle layer
=================================================

Disclaimer
----------

This conversion will not be so straight forward. While all information
is provided in your particular version of matlab middle layer, some
info is provided by *flexible* matlab structures that can be changed.

Furthermore, many critical information, e.g. conversion functions or
coefficients can be stored or hard coded within the conversion functions
used by the matlab middle layer be it `k2amp` or `amp2k`.

Still quite some information is stored in `AO` or `AD` object, but
there will be significant extra work required.


Extracting information from the `AO` object: matlab side
--------------------------------------------------------

These objects can be accessed using `getao` and `getad`. Then
store them in a file using matlabs `save` function.


Reading `AO` object into pydantic data model
--------------------------------------------
The `AO object can be read-in using:

.. code::
   :linenos:
   import scipy.io
   from bact_mml_json_importer.data_model.mml_ao import load, convert
   from bact_mml_json_importer.data_model.mml_ao import FamilyInfoCollection

   data_from_mat = scipy.io.loadmat(filename, simplify_cells=True)
   tmp = convert(data_from_mat["AO"])
   model = load(tmp)


Now all data available within AO should be contained in the object model.
This object consists of a dictonary. Each entry corresponds to a family.
The info for one family is stored in a :class:`FamilyInfoCollection`.

Typically other data is used too and needs to be exported separately.
Some examples can be seen for ALS.

.. todo::
    Missing data models: AD, LOCO Data

    reference functions properly as soon as these are
    in the appropriate repository


.. todo::
    how to deal with structures that are similar to Monitor or
    setpoint


Implementing and verifying the conversion
-----------------------------------------

As many functionality is stored within `amp2k.m` or `k2amp.m` functions
or similar conversion is not that straight forward (yet).

To verify that the conversion is at least of acceptable qualtiy, the
conversion can be tested using data exported using matlab with the
appropriate middle layer installed.

The following tools are provided:

* matlab scripts

  * `produce_test_data.m` samples a provided matlab middle layer
    function
  * `export_test_data_for_dt4acc.m` runs produce_test_data for
    different functions and families. It was written to export
    test data for the ALS Storage ring.

* python tests are based on pytest. Have a look at `test_amp2k_conversion.py`
  and `test_bpm_conversion.py` how such tests look like.