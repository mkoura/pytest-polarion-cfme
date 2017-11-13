# -*- coding: utf-8 -*-
"""pytest plugin for collecting test cases from and recording test results to database."""

from __future__ import print_function, unicode_literals

import datetime
import re
import sqlite3

import pytest


def pytest_addoption(parser):
    """Adds Polarion specific options to pytest."""
    group = parser.getgroup("Polarion: options related to Polarion CFME plugin")
    group.addoption('--db',
                    default=None,
                    action='store',
                    help="SQLite file with tests results (default: %default)")
    group.addoption('--skip-executed',
                    default=False,
                    action='store_true',
                    help="Run only tests that were not executed yet (default: %default)")


def pytest_configure(config):
    """Registers plugin."""
    db_file = config.getoption('db')
    if db_file is None:
        return

    with open(db_file):
        # test that file can be accessed
        pass
    conn = sqlite3.connect(db_file, detect_types=sqlite3.PARSE_DECLTYPES)

    # check that all required columns are there
    cur = conn.cursor()
    cur.execute("SELECT * FROM testcases")
    columns = [description[0] for description in cur.description]
    required_columns = (
        'id', 'title', 'verdict', 'comment', 'last_status', 'time', 'sqltime')
    missing_columns = [k for k in required_columns if k not in columns]
    if missing_columns:
        pytest.fail(
            "The database `{}` is missing following columns: {}".format(
                db_file, ', '.join(missing_columns)))

    config.pluginmanager.register(PolarionCFMEPlugin(conn), '_polarion_cfme')


class PolarionCFMEPlugin(object):
    """Gets Test Cases info and record test results in database."""

    # specific to CFME (RHCF3)
    SEARCHES = [
        'Skipping due to these blockers',
        'SKIPME:',
        'BZ ?[0-9]+',
        'GH ?#?[0-9]+',
        'GH#ManageIQ',
    ]

    def __init__(self, conn):
        self.conn = conn
        self.valid_skips = re.compile('(' + ')|('.join(self.SEARCHES) + ')')

    @staticmethod
    def get_testcase_name(item):
        """Gets Polarion test case name out of the Node ID."""
        return (item.nodeid[item.nodeid.find('::') + 2:]
                .replace('::()', '')
                .replace('::', '.'))

    def db_collect_testcases(self, items, skip_executed=False):
        """Finds corresponding Polarion Work Item ID for collected test cases.

        Returns list of test cases found in the database.
        """
        select = ("SELECT id, title FROM testcases "
                  "WHERE (verdict IS NULL OR verdict = '')",
                  "AND (last_status IS NULL or last_status = '' or last_status = 'skipped')")
        select = ' '.join(select) if skip_executed else select[0]
        cur = self.conn.cursor()
        cur.execute(select)
        polarion_testcases = cur.fetchall()

        # cache Work Item ID of every Polarion Test Case
        cached_ids = {}
        for testcase in polarion_testcases:
            work_item_id, title = testcase
            if title in cached_ids:
                print('{} is not unique, skipping'.format(title))
                del cached_ids[title]
                continue
            cached_ids[title] = work_item_id

        # save Work Item ID to corresponding items collected by pytest
        # and get list of test cases to run
        found = []
        for testcase in items:
            unique_id = self.get_testcase_name(testcase)
            work_item_id = cached_ids.get(unique_id)
            if work_item_id:
                testcase.polarion_work_item_id = work_item_id
                found.append(testcase)

        return found

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        """Deselects tests that are not in the database."""
        remaining = self.db_collect_testcases(items, config.getoption('skip_executed'))

        deselect = set(items) - set(remaining)
        if deselect:
            config.hook.pytest_deselected(items=deselect)
            items[:] = remaining

        print("Deselected {} tests using database, will continue with {} tests".format(
            len(deselect), len(items)))

    def testcase_set_record(self, work_item_id, **kwargs):
        """Updates Test Case record in database."""
        cur = self.conn.cursor()

        cur.execute("SELECT verdict FROM testcases WHERE id = ?", (work_item_id, ))
        verdict, = cur.fetchone()
        # don't override existing verdict
        if verdict:
            kwargs.pop('verdict', None)

        values = []
        keys_bind = []
        for key, value in kwargs.items():
            if value:
                keys_bind.append('{} = ?'.format(key))
                values.append(value)
        if not values:
            return
        values.append(work_item_id)  # for 'WHERE' clause

        cur.execute("UPDATE testcases SET {} WHERE id = ?".format(','.join(keys_bind)), values)
        try:
            self.conn.commit()
        # pylint: disable=broad-except
        except Exception:
            # will succeed next time hopefully
            pass

    def get_skip_reason(self, report):
        """Check if there's a reason to mark test as 'skipped'."""
        if report.longrepr:
            reason = report.longrepr[2]
            if self.valid_skips.search(reason):
                return reason
        return

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item):
        """Checks test result and update Test Case record in database."""
        outcome = yield

        report = outcome.get_result()
        result = None
        comment = None
        last_status = None
        time = None

        if report.when == 'call':
            last_status = report.outcome
            time = str(report.duration)
            if report.passed:
                result = 'passed'
            elif report.skipped:
                comment = self.get_skip_reason(report)
                if comment:
                    result = 'skipped'
        elif report.when == 'setup' and not report.passed:
            last_status = 'error' if report.failed else report.outcome
            if report.skipped:
                try:
                    comment = item.get_marker('skipif').kwargs['reason']
                except AttributeError:
                    comment = None

                if not comment:
                    comment = self.get_skip_reason(report)
                if comment:
                    result = 'skipped'

        if last_status:
            testrun_record = dict(
                verdict=result,
                comment=comment,
                last_status=last_status,
                time=time,
                sqltime=datetime.datetime.utcnow())
            self.testcase_set_record(item.polarion_work_item_id, **testrun_record)

    def pytest_unconfigure(self):
        """Closes database connection."""
        self.conn.commit()
        self.conn.close()
