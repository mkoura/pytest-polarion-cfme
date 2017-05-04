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

    config.pluginmanager.register(PolarionCFMEPlugin(config), '_polarion_cfme')


def create_db_connection(db_file):
    """Creates a database connection."""
    try:
        conn = sqlite3.connect(os.path.expanduser(db_file))
        return conn
    except Error as err:
        pytest.fail("{}".format(err))


class PolarionCFMEPlugin(object):
    """Gets Test Cases info and record test results in database."""

    SEARCHES = [
        'Skipping due to these blockers',
        'BZ ?[0-9]+',
        'GH ?#?[0-9]+',
        'GH#ManageIQ',
    ]
    TESTCASE_ID_BASE = 'cfme.tests'

    def __init__(self, config):
        self.config = config
        self.conn = create_db_connection(config.getoption('db'))
        self.valid_skips = '(' + ')|('.join(self.SEARCHES) + ')'

    @staticmethod
    def _cache_test_case_ids(cache, test_cases):
        """Extends Test Case ids cache."""
        for test_case in test_cases:
            work_item_id, title, test_case_id = test_case
            unique_id = test_case_id
            param_index = title.rfind('[')
            if param_index > 0:
                unique_id += title[param_index:]
            cache[unique_id] = work_item_id

    def guess_polarion_id(self, item):
        """Guess how the test's 'Node ID' corresponds to Work Item 'Test Case ID' in Polarion."""
        unique_id = (item.nodeid.
                     replace('/', '.').
                     replace('::()', '').
                     replace('::', '.').
                     replace('.py', ''))
        start = unique_id.find(self.TESTCASE_ID_BASE)
        if start > 0:
            unique_id = unique_id[start:]
        polarion_test_case_id = unique_id
        param_index = polarion_test_case_id.rfind('[')
        if param_index > 0:
            polarion_test_case_id = polarion_test_case_id[:param_index]

        return unique_id

    def polarion_collect_test_cases(self, items):
        """Finds corresponding Polarion work item ID for each test."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, title, testcaseid FROM testcases WHERE verdict is null or verdict = ''")
        test_cases_list = cur.fetchall()
        cached_ids = {}
        self._cache_test_case_ids(cached_ids, test_cases_list)

        found = []
        for test_case in items:
            unique_id = self.guess_polarion_id(test_case)
            work_item_id = cached_ids.get(unique_id)
            if work_item_id:
                test_case.polarion_work_item_id = work_item_id
                found.append(test_case)

        return found

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        """Deselects tests that are not in the database."""
        remaining = self.polarion_collect_test_cases(items)

        deselect = set(items) - set(remaining)
        if deselect:
            self.config.hook.pytest_deselected(items=deselect)
            items[:] = remaining

        print("Deselected {} tests using database, will continue with {} tests".format(
            len(deselect), len(items)))

    def testcase_set_record(self, work_item_id, **kwargs):
        """Updates Test Case record in database."""
        sets = ', '.join(["{} = '{}'".format(k, v) for k, v in kwargs.iteritems() if v])
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE testcases SET {sets} WHERE id = '{wid}'".format(sets=sets, wid=work_item_id))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item):
        """Checks test result and update Test Case record in database."""
        outcome = yield

        report = outcome.get_result()
        result = None
        comment = None

        if report.when == 'call' and report.passed:
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

            # found reason to mark test as 'blocked' in Polarion
            if comment:
                result = 'skipped'

        testrun_record = dict(
            verdict=result,
            comment=comment,
            last_status=report.outcome,
            time=str(report.duration))
        self.testcase_set_record(item.polarion_work_item_id, **testrun_record)

    def pytest_unconfigure(self):
        """Closes database connection."""
        self.conn.commit()
        self.conn.close()
