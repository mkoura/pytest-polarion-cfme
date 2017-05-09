# -*- coding: utf-8 -*-
"""pytest plugin for collecting test cases from and recording test results to database."""

from __future__ import print_function, unicode_literals

import re
import os

import sqlite3
from sqlite3 import Error

import pytest


def pytest_addoption(parser):
    """Adds Polarion specific options to pytest."""
    group = parser.getgroup("Polarion: options related to Polarion CFME plugin")
    group.addoption('--db',
                    default=None,
                    action='store',
                    help="SQLite file with tests results (default: %default)")


def pytest_configure(config):
    """Registers plugin."""
    if config.getoption('db') is None:
        return

    config.pluginmanager.register(PolarionCFMEPlugin(config.getoption('db')), '_polarion_cfme')


def create_db_connection(db_file):
    """Creates a database connection."""
    try:
        conn = sqlite3.connect(os.path.expanduser(db_file))
        return conn
    except Error as err:
        pytest.fail("{}".format(err))


class PolarionCFMEPlugin(object):
    """Gets Test Cases info and record test results in database."""

    # specific to CFME (RHCF3)
    SEARCHES = [
        'Skipping due to these blockers',
        'BZ ?[0-9]+',
        'GH ?#?[0-9]+',
        'GH#ManageIQ',
    ]
    TESTCASE_ID_BASE = 'cfme.tests'

    def __init__(self, db_file):
        self.conn = create_db_connection(db_file)
        self.valid_skips = '(' + ')|('.join(self.SEARCHES) + ')'

    @staticmethod
    def get_polarion_uniq_id(title, testcase_id):
        """Get unique id for Polarion Test Case (Work Item).

        The unique id generated here corresponds to the unique id obtained from pytest item.
        """
        unique_id = testcase_id
        param_index = title.rfind('[')
        if param_index > 0:
            unique_id += title[param_index:]

        return unique_id

    def get_pytest_uniq_id(self, item):
        """Guess how the test's 'Node ID' corresponds to Work Item 'Test Case ID' in Polarion.

        In case of RHCF3 project the Test Case ID
        ``cfme.tests.infrastructure.test_vm_power_control.TestDeleteViaREST.test_delete``
        corresponds to the `cfme/tests/infrastructure/test_vm_power_control.py` file,
        `TestDeleteViaREST` class and `test_delete` test.
        Coupled with test parameter `smartvm` this constructs the unique id
        `cfme.tests.infrastructure.test_vm_power_control.TestDeleteViaREST.test_delete[smartvm]`.

        This way it's possible to match Node ID of pytest item to Polarion Test Case ID + parameter.
        """
        unique_id = (item.nodeid.
                     replace('/', '.').
                     replace('::()', '').
                     replace('::', '.').
                     replace('.py', ''))
        start = unique_id.find(self.TESTCASE_ID_BASE)
        if start > 0:
            unique_id = unique_id[start:]

        return unique_id

    def db_collect_testcases(self, items):
        """Finds corresponding Polarion Work Item ID for collected test cases
        and return list of test cases found in the database."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, title, testcaseid FROM testcases WHERE verdict is null or verdict = ''")
        polarion_testcases = cur.fetchall()

        # cache Work Item ID for each Polarion Test Case
        cached_ids = {}
        for testcase in polarion_testcases:
            work_item_id, title, testcase_id = testcase
            unique_id = self.get_polarion_uniq_id(title, testcase_id)
            cached_ids[unique_id] = work_item_id

        # save Work Item ID to corresponding items collected by pytest
        # and get list of test cases to run
        found = []
        for testcase in items:
            unique_id = self.get_pytest_uniq_id(testcase)
            work_item_id = cached_ids.get(unique_id)
            if work_item_id:
                testcase.polarion_work_item_id = work_item_id
                found.append(testcase)

        return found

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        """Deselects tests that are not in the database."""
        remaining = self.db_collect_testcases(items)

        deselect = set(items) - set(remaining)
        if deselect:
            config.hook.pytest_deselected(items=deselect)
            items[:] = remaining

        print("Deselected {} tests using database, will continue with {} tests".format(
            len(deselect), len(items)))

    def testcase_set_record(self, work_item_id, **kwargs):
        """Updates Test Case record in database."""
        values = []
        keys_bind = []
        for key, value in kwargs.iteritems():
            if value:
                keys_bind.append('{} = ?'.format(key))
                values.append(value)
        if not values:
            return
        values.append(work_item_id)  # for 'WHERE' clause
        cur = self.conn.cursor()
        cur.execute("UPDATE testcases SET {} WHERE id = ?".format(','.join(keys_bind)), values)
        self.conn.commit()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item):
        """Checks test result and update Test Case record in database."""
        outcome = yield

        report = outcome.get_result()
        result = None
        comment = None
        last_status = None

        if report.when == 'call':
            last_status = report.outcome
            if report.passed:
                result = 'passed'
        elif report.when == 'setup' and report.skipped:
            try:
                comment = item.get_marker('skipif').kwargs['reason']
            except AttributeError:
                comment = None
            if not comment and report.longrepr:
                reason = report.longrepr[2]
                if re.match(self.valid_skips, reason):
                    comment = reason

            # found reason to mark test as 'skipped'
            if comment:
                result = 'skipped'

        testrun_record = dict(
            verdict=result,
            comment=comment,
            last_status=last_status,
            time=str(report.duration) if result else None)
        self.testcase_set_record(item.polarion_work_item_id, **testrun_record)

    def pytest_unconfigure(self):
        """Closes database connection."""
        self.conn.commit()
        self.conn.close()
