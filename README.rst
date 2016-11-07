====================
pytest-polarion-cfme
====================
pytest-polarion-cfme is a pytest plugin for collecting test cases based on
Polarion Test Run and for recording test results in Polarion.

From set of tests specified on command line the plugin is able to select such
tests that have no result (i.e. were not executed) in the specified Polarion
Test Run (but are present there) and that are assigned to person with specified
'id'.

After executing test the plugin can record their results in Polarion. By
default passed and blocked (tests with blocker or 'skipif') tests are recorded.

It is tailored to work with test case ids used by CFME QE team.

Requires 'pylarion' library that is not public at the moment.

Inspired by https://github.com/avi3tal/pytest-polarion


Example commands
----------------
From '<tests>' select and run such tests that have no result in Polarion Test Run
'<run name>'. Record tests that passed or that are blocked::

    $ py.test --polarion-run <run_name> <tests>

From tests located in 'dir/with/tests/' select and run such tests that have no
result in Polarion Test Run '<run name>', are assigned to person with '<id>' and
their names contain 'string expression'::

    $ py.test --polarion-run <run_name> --polarion-assignee <id> -k 'string expression' dir/with/tests/

See complete help::

    $ py.test --help


Install
-------
For CFME QE specific install instructions see https://mojo.redhat.com/docs/DOC-1098563 (accessible only from internal network).

Install pylarion first::

    $ cd pylarion_repo
    $ pip install .

Create and edit pylarion config file ~/.pylarion according to Pylarion install instructions.

Install this plugin::

    $ cd pytest-polarion-cfme_repo
    $ pip install .

or without cloning the repo::

   $ pip install https://github.com/mkoura/pytest-polarion-cfme/archive/master.tar.gz
