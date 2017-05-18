====================
pytest-polarion-cfme
====================

NOTE: pytest-polarion-cfme is no longer using pylarion as pylarion is being
deprecated. As a consequence command line options changed too.

pytest-polarion-cfme is a pytest plugin for collecting test cases and recording
test results to database.

From set of test cases specified on command line the plugin selects such test
cases that are present in the database and have no reportable result yet.

After executing a test case the plugin records its result in the database. By
default results for passed and blocked (test cases with blocker or 'skipif')
test cases are recorded.

It is tailored to work with test case ids and blockers used by CFME QE team.


Usage
-----
Generate sqlite3 file out of the CSV file exported from Polarion®. Use the
``csv2sqlite.py`` from dump2polarion_ for this.

From test cases available to pytest (you can limit these using standard pytest
features like ``-k`` or specifying file/directory path) select and run those
that are present in the database and have no reportable result. Record results
for test cases that passed or that are blocked::

    $ py.test --db <db_file.sqlite3>

To exclude tests that were already executed but haven't passed, add
``--skip-executed`` command line option (i.e. failing/skipped tests are not
re-run and it saves time)::

    $ py.test --db <db_file.sqlite3> --skip-executed

Submit results to Polarion® xunit importer using ``dump2polarion.py`` from dump2polarion_.

.. _dump2polarion: https://github.com/mkoura/dump2polarion


Install
-------
For CFME QE specific instructions see https://mojo.redhat.com/docs/DOC-1098563
(accessible only from internal network).

Install this plugin::

    $ pip install .
