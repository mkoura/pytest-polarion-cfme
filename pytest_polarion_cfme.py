# -*- coding: utf-8 -*-
"""pytest plugin for collecting test cases based on Polarion Test Run
and for recording test results in Polarion."""

from __future__ import print_function, unicode_literals

import datetime
import time
import pytest

from pylarion.test_run import TestRun
from pylarion.work_item import TestCase
from pylarion.exceptions import PylarionLibException
from suds import WebFault


def pytest_addoption(parser):
    """Add Polarion specific options to pytest."""

    group = parser.getgroup("Polarion: options related to Polarion CFME plugin:")
    group.addoption('--polarion-run',
                    default=None,
                    action='store',
                    help="Polarion Test Run name (default: %default)")
    group.addoption('--polarion-project',
                    default=None,
                    action='store',
                    help="Polarion project name (default taken from pylarion config file)")
    group.addoption('--polarion-assignee',
                    default=None,
                    action='store',
                    help="Select only tests assigned to specified id (default: %default)")
    group.addoption('--polarion-collect-blocked',
                    default=False,
                    action='store_true',
                    help="Collect also blocked tests, not only tests without record "
                         "(default: %default)")
    group.addoption('--polarion-collect-failed',
                    default=False,
                    action='store_true',
                    help="Collect also failed tests, not only tests without record "
                         "(default: %default)")
    group.addoption('--polarion-dont-record-blocked',
                    default=False,
                    action='store_true',
                    help="Don't record blocked tests, record only passed tests "
                         "(default: %default)")
    group.addoption('--polarion-dont-record',
                    default=False,
                    action='store_true',
                    help="Don't record any test outcome (default: %default)")
    group.addoption('--polarion-prefetch-level',
                    action='store',
                    type=int,
                    default=-1,
                    help="Data prefetching aggressivity (0-2; default: no prefetching)")


def pytest_configure(config):
    """Register plugin."""

    if config.getoption('polarion_run') is None:
        return
    if config.getoption('polarion_project') is None:
        config.option.polarion_project = TestRun.default_project
    if config.getoption('polarion_project') is None:
        pytest.fail("Polarion project name is not set.")

    config.pluginmanager.register(PolarionCFMEPlugin(config), '_polarion_cfme')


def retry_query(fun, *args, **kwargs):
    """Re-try query when webservice call failed."""

    # Sometimes query fails with "WebFault: Server raised fault: 'Not authorized.'".
    # When re-tried, the same query often succeed.
    for retry in range(5):
        if retry != 0:
            time.sleep(0.3)  # sleep and try again
        try:
            return fun(*args, **kwargs)
        except WebFault as detail:
            pass

    # all retries failed, bailing out
    pytest.fail("Failed to query Polarion: {}".format(detail))


def guess_polarion_id(item):
    """Guess how the test's 'Node ID' corresponds to Work Item 'Test Case ID' in Polarion."""

    unique_id = item.nodeid.replace('/', '.').replace('::()', '') \
        .replace('::', '.').replace('.py', '')
    polarion_test_case_id = unique_id
    param_index = polarion_test_case_id.rfind('[')
    if param_index > 0:
        polarion_test_case_id = polarion_test_case_id[:param_index]

    return (unique_id, polarion_test_case_id)


def polarion_set_record(testrun, testrun_record):
    """Do the updating of Test Run record in Polarion."""

    try:
        testrun.add_test_record_by_object(testrun_record)
    except PylarionLibException:
        testrun.reload()
        testrun.update_test_record_by_object(testrun_record.test_case_id, testrun_record)


def polarion_set_record_retry(testrun, testrun_record):
    """Re-try to update Polarion in case of failure."""

    for retry in range(3):
        if retry != 0:
            time.sleep(0.5)  # sleep and try again
        try:
            if retry == 1:
                testrun.reload()
            return polarion_set_record(testrun, testrun_record)
        # we really don't want to fail here
        # pylint: disable=broad-except
        except (WebFault, Exception):
            pass

    print("  {}: failed to write result to Polarion!".format(testrun_record.test_case_id), end='')


class PolarionCFMEPlugin(object):
    """Get Test Cases and Test Run info and record test results in Polarion."""

    def __init__(self, config):
        self.config = config
        self.polarion_testrun_records = None
        self.polarion_testrun_obj = None

    @staticmethod
    def compile_test_case_query(test_case_id, level):
        """Compile query string for matching Test Cases."""

        if level <= 0:
            return test_case_id

        components = test_case_id.split('.')
        new_len = len(components) - level
        if new_len < 2:
            new_len = 2

        return ".".join(components[:new_len]) + '.*'

    def compile_full_query(self, test_case_query):
        """Compile query for Test Case search."""

        assignee_id = self.config.getoption('polarion_assignee')
        polarion_run = self.config.getoption('polarion_run')
        polarion_project = self.config.getoption('polarion_project')

        assignee_str = 'assignee.id:{} AND '.format(assignee_id) if assignee_id else ''
        test_records_tmplt = 'TEST_RECORDS:("{}/{}",' \
                             .format(polarion_project, polarion_run)
        test_records_str = '{}@null)'.format(test_records_tmplt)
        if self.config.getoption('polarion_collect_blocked'):
            test_records_str += ' OR {}"blocked")'.format(test_records_tmplt)
        if self.config.getoption('polarion_collect_failed'):
            test_records_str += ' OR {}"failed")'.format(test_records_tmplt)

        full_query = '{assignee}NOT status:inactive AND caseautomation.KEY:automated ' \
                     'AND (({test_records}) AND {query})' \
                     .format(assignee=assignee_str, test_records=test_records_str,
                             query=test_case_query)
        return full_query

    @staticmethod
    def cache_test_case_ids(cache, test_cases):
        """Extend Test Case ids cache."""

        for test_case in test_cases:
            unique_id = test_case.test_case_id
            param_index = test_case.title.rfind('[')
            if param_index > 0:
                unique_id += test_case.title[param_index:]
            cache[unique_id] = test_case.work_item_id

    def get_prefetch_level(self, num_items):
        """Data prefetching aggressivity - for how many test cases to ask in single query."""

        level = self.config.getoption('polarion_prefetch_level')

        if level == -1:
            if self.config.getoption('polarion_assignee'):
                # total number of test cases is limited by specifying assignee
                # so we can set prefetching level higher
                if num_items > 10:
                    level = 2
                elif num_items > 5:
                    level = 1
            else:
                if num_items > 10:
                    level = 1

        return level

    def polarion_collect_test_cases(self, items):
        """Find corresponding Polarion work item ID for each test."""

        prefetch_level = self.get_prefetch_level(len(items))
        cached_ids = {}
        cached_queries = set()
        start_time = time.time()

        for test_case in items:
            unique_id, test_case_id = guess_polarion_id(test_case)
            if unique_id not in cached_ids:
                test_case_query = self.compile_test_case_query(test_case_id, prefetch_level)
                if test_case_query in cached_queries:
                    # we've already tried this query, no need to repeat
                    test_case.polarion_work_item_id = None
                    continue
                cached_queries.add(test_case_query)
                full_query = self.compile_full_query(test_case_query)
                test_cases_list = retry_query(TestCase.query, query=full_query,
                                              project_id=self.config.getoption('polarion_project'),
                                              fields=['title', 'work_item_id', 'test_case_id'])
                self.cache_test_case_ids(cached_ids, test_cases_list)

            if unique_id in cached_ids:
                test_case.polarion_work_item_id = cached_ids[unique_id]
            else:
                # test case was not found
                test_case.polarion_work_item_id = None

        print("Fetched {} Polarion item(s) in {}s".format(
            len(cached_ids), round(time.time() - start_time, 2)))

    def polarion_collect_testrun(self):
        """Collect all work item IDs in specified testrun."""

        polarion_run = self.config.getoption('polarion_run')
        polarion_project = self.config.getoption('polarion_project')

        testrun = retry_query(TestRun, project_id=polarion_project, test_run_id=polarion_run)
        if not testrun:
            pytest.fail("Failed to collect Test Run '{}' from polarion.".format(polarion_run))

        self.polarion_testrun_records = {rec.test_case_id: rec for rec in testrun.records}
        self.polarion_testrun_obj = testrun

    def pytest_collection_modifyitems(self, items):
        """Deselect tests that are not present in testrun."""

        self.polarion_collect_testrun()
        self.polarion_collect_test_cases(items)

        remaining = [test_case for test_case in items if test_case.polarion_work_item_id
                     and test_case.polarion_work_item_id in self.polarion_testrun_records]

        deselect = set(items) - set(remaining)
        if deselect:
            self.config.hook.pytest_deselected(items=deselect)
            items[:] = remaining

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item):
        """Check test result and update Test Run record in Polarion."""

        outcome = yield

        if self.config.getoption('polarion_dont_record'):
            return

        report = outcome.get_result()
        result = None

        if report.when == 'call' and report.passed:
            comment = "Test Result: passed"
            result = 'passed'
        elif report.when == 'setup' and report.skipped:
            if self.config.getoption('polarion_dont_record_blocked'):
                return

            try:
                comment = item.get_marker('skipif').kwargs['reason']
            except AttributeError:
                comment = None
            if not comment and report.longrepr \
                    and "Skipping due to these blockers" in report.longrepr[2]:
                comment = report.longrepr[2]

            # found reason to mark test as 'blocked' in Polarion
            if comment:
                result = 'blocked'

        if result:
            testrun_record = self.polarion_testrun_records[item.polarion_work_item_id]
            testrun_record.result = result
            testrun_record.comment = comment
            testrun_record.duration = report.duration
            testrun_record.executed = datetime.datetime.now()
            testrun_record.executed_by = testrun_record.logged_in_user_id
            polarion_set_record_retry(self.polarion_testrun_obj, testrun_record)
