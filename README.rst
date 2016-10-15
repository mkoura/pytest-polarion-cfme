====================
pytest-polarion-cfme
====================
pytest-polarion-cfme is a pytest plugin for collecting test cases and reporting results to Polarion.
It is tailored to work with test case ids used by CFME QE team.

Needs 'pylarion' library that is not public at the moment.
Based on https://github.com/avi3tal/pytest-polarion


Commands
--------
Trigger tests from TestRun::

    $ py.test --polarion-run <run name> <tests>

See complete help::

    $ py.test --help
