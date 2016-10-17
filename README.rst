====================
pytest-polarion-cfme
====================
pytest-polarion-cfme is a pytest plugin for collecting test cases based on
Polarion TestRun and for recording test results in Polarion.

From set of tests specified on command line the plugin is able to select such
tests that have no result (i.e. were not executed) in the specified Polarion
TestRun (but are present there) and that are assigned to person with specified
'id'.

After executing test the plugin can record their results in Polarion. By
default only passed tests are recorded.

It is tailored to work with test case ids used by CFME QE team.

Requires 'pylarion' library that is not public at the moment.

Inspired by https://github.com/avi3tal/pytest-polarion


Example commands
----------------
From '<tests>' select and run such tests that have no result in Polarion TestRun
'<run name>'. Record tests that passed::

    $ py.test --polarion-run='<run name>' <tests>

From tests located in 'dir/with/tests/' select and run such tests that have no
result in Polarion TestRun '<run name>', are assigned to person with '<id>' and
their names contain 'string expression'. Record all results::

    $ py.test --polarion-run='<run name>' --polarion-assignee='<id>' --polarion-always-record -k 'string expression' dir/with/tests/

See complete help::

    $ py.test --help


Install
-------
Install pylarion first::

    $ cd pylarion_repo
    $ pip install .

Create and edit pylarion config file ~/.pylarion according to Pylarion install instructions.

Install this plugin (it's not in pypi yet)::

    $ cd pytest-polarion-cfme_repo
    $ pip install .
