# -*- coding: utf-8 -*-
"""pytest plugin for collecting test cases based on Polarion TestRun
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

    group = parser.getgroup('Polarion')
    group.addoption('--polarion-run',
                    default=None,
                    action='store',
                    help="Polarion TestRun name (default: %default)")
    group.addoption('--polarion-project',
                    default=None,
                    action='store',
                    help="Polarion project name (default taken from pylarion config file)")
    group.addoption('--polarion-assignee',
                    default=None,
                    action='store',
                    help="Select only tests assigned to specified id (default: %default)")
    group.addoption('--polarion-collect-skipped',
                    default=False,
                    action='store_true',
                    help="Collect also skipped tests, not only tests without record " \
                         "(default: %default)")
    group.addoption('--polarion-collect-failed',
                    default=False,
                    action='store_true',
                    help="Collect also failed tests, not only tests without record " \
                         "(default: %default)")
    group.addoption('--polarion-record-skipped',
                    default=False,
                    action='store_true',
                    help="Record also skipped tests in addition to passed tests " \
                         "(default: %default)")
    group.addoption('--polarion-record-all',
                    default=False,
                    action='store_true',
                    help="Record all tests, not only those that passed (default: %default)")
    group.addoption('--polarion-record-none',
                    default=False,
                    action='store_true',
                    help="Never record any test outcome (default: %default)")
    group.addoption('--polarion-caching-level',
                    action='store',
                    type=int,
                    default=0,
                    help="Data caching aggressivity (default: %default)")


def pytest_configure(config):
    """Make sure Polarion project name is set."""

    if config.getoption('polarion_run') is None:
        return
    if config.getoption('polarion_project') is None:
        config.option.polarion_project = TestRun.default_project
    if config.getoption('polarion_project') is None:
        pytest.fail('Polarion project name is not set.')


def retry_query(fun, *args, **kwargs):
    """Re-try query when webservice call failed."""

    # Sometimes query fails with "WebFault: Server raised fault: 'Not authorized.'".
    # When re-tried, the same query often succeed.
    for retry in range(5):
        if retry != 0:
            time.sleep(0.3) # sleep and try again
        try:
            return fun(*args, **kwargs)
        except WebFault as detail:
            pass

    # all retries failed, bailing out
    pytest.fail('Failed to query Polarion: {}'.format(detail))


def guess_polarion_id(item):
    """Guess how the test's 'Node ID' corresponds to Work Item 'Test Case ID' in Polarion."""

    unique_id = item.nodeid.replace('/', '.').replace('::()', '') \
                           .replace('::', '.').replace('.py', '')
    polarion_test_case_id = unique_id
    param_index = polarion_test_case_id.rfind('[')
    if param_index > 0:
        polarion_test_case_id = polarion_test_case_id[:param_index]
    return (unique_id, polarion_test_case_id)


def compile_test_case_query(test_case_id, level=0):
    """Compile query string for matching Test Cases."""

    if level <= 0:
        return test_case_id

    components = test_case_id.split('.')
    new_len = len(components) - level
    if new_len < 2:
        new_len = 2
    return ".".join(components[:new_len]) + '.*'


def compile_full_query(test_case_query, config):
    """Compile query for Test Case search."""

    polarion_run = config.getoption('polarion_run')
    polarion_project = config.getoption('polarion_project')
    assignee_id = config.getoption('polarion_assignee')

    assignee_str = 'assignee.id:{} AND '.format(assignee_id) if assignee_id else ''
    test_records_tmplt = 'TEST_RECORDS:("{}/{}",'.format(polarion_project, polarion_run)
    test_records_str = '{}@null)'.format(test_records_tmplt)
    if config.getoption('polarion_collect_skipped'):
        test_records_str += ' OR {}"blocked")'.format(test_records_tmplt)
    if config.getoption('polarion_collect_failed'):
        test_records_str += ' OR {}"failed")'.format(test_records_tmplt)

    full_query = '{assignee}NOT status:inactive AND caseautomation.KEY:automated ' \
                 'AND (({test_records}) AND {query})' \
                 .format(assignee=assignee_str, test_records=test_records_str,
                         query=test_case_query)
    return full_query


def cache_test_case_ids(cache, test_cases):
    """Extend Test Case ids cache."""

    for test_case in test_cases:
        unique_id = test_case.test_case_id
        param_index = test_case.title.rfind('[')
        if param_index > 0:
            unique_id += test_case.title[param_index:]
        cache[unique_id] = test_case.work_item_id


def polarion_collect_test_cases(items, config):
    """Find corresponding Polarion work item ID for each test."""

    # ask for more test cases at once when assignee is specified
    caching_level = config.getoption('polarion_caching_level')
    if config.getoption('polarion_assignee') and caching_level == 0:
        num_items = len(items)
        if num_items > 10:
            caching_level = 2
        elif num_items > 5:
            caching_level = 1

    cached_ids = {}
    cached_queries = set()
    start_time = time.time()

    for test_case in items:
        unique_id, test_case_id = guess_polarion_id(test_case)
        if unique_id not in cached_ids:
            test_case_query = compile_test_case_query(test_case_id, caching_level)
            if test_case_query in cached_queries:
                # we've already tried this query, no need to repeat
                test_case.polarion_work_item_id = None
                continue
            cached_queries.add(test_case_query)
            full_query = compile_full_query(test_case_query, config)
            test_cases_list = retry_query(TestCase.query, query=full_query,
                                          project_id=config.getoption('polarion_project'),
                                          fields=['title', 'work_item_id', 'test_case_id'])
            cache_test_case_ids(cached_ids, test_cases_list)

        if unique_id in cached_ids:
            test_case.polarion_work_item_id = cached_ids[unique_id]
        else:
            # test case was not found
            test_case.polarion_work_item_id = None

    print("Cached {} Polarion item(s) in {}s".format(
        len(cached_ids), round(time.time() - start_time, 2)))


def polarion_collect_testrun(config):
    """Collect all work item IDs in specified testrun."""

    polarion_run = config.getoption('polarion_run')
    polarion_project = config.getoption('polarion_project')

    testrun = retry_query(TestRun, project_id=polarion_project, test_run_id=polarion_run)
    if not testrun:
        pytest.fail("Failed to collect TestRun '{}' from polarion.".format(polarion_run))

    # FIXME: find better way to make this available to other functions
    config.polarion_testrun_records = {rec.test_case_id: rec for rec in testrun.records}
    config.polarion_testrun_obj = testrun


def pytest_collection_modifyitems(items, config):
    """Deselect tests that are not present in testrun."""

    if config.getoption('polarion_run') is None:
        return

    polarion_collect_testrun(config)
    polarion_collect_test_cases(items, config)

    remaining = [test_case for test_case in items if test_case.polarion_work_item_id
                 and test_case.polarion_work_item_id in config.polarion_testrun_records]

    deselect = set(items) - set(remaining)
    if deselect:
        config.hook.pytest_deselected(items=deselect)
        items[:] = remaining


def polarion_set_record(testrun, testrun_record):
    """Do the updating of TestRun record in Polarion."""

    try:
        testrun.add_test_record_by_object(testrun_record)
    except PylarionLibException:
        testrun.reload()
        testrun.update_test_record_by_object(testrun_record.test_case_id, testrun_record)


def polarion_set_record_retry(testrun, testrun_record):
    """Re-try to update Polarion in case of failure."""

    for retry in range(3):
        if retry != 0:
            time.sleep(0.5) # sleep and try again
        try:
            if retry == 1:
                testrun.reload()
            return polarion_set_record(testrun, testrun_record)
        # we really don't want to fail here
        # pylint: disable=broad-except
        except (WebFault, Exception):
            pass

    print("  {}: failed to write result to Polarion!".format(testrun_record.test_case_id), end='')


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item):
    """Check test result and update TestRun record in Polarion."""

    outcome = yield

    if item.config.getoption('polarion_run') is None \
        or item.config.getoption('polarion_record_none'):
        return

    report = outcome.get_result()
    record_always = item.config.getoption('polarion_record_all')
    record_skipped = item.config.getoption('polarion_record_skipped')

    # get polarion objects
    testrun = item.config.polarion_testrun_obj
    testrun_record = item.config.polarion_testrun_records[item.polarion_work_item_id]

    if report.when == 'call':
        # build up traceback massage
        trace = ''
        if not report.passed:
            if not record_always:
                return
            trace = '{}:{}\n{}'.format(report.location, report.when, report.longrepr)

        testrun_record.result = report.outcome
        testrun_record.executed = datetime.datetime.now()
        testrun_record.executed_by = testrun_record.logged_in_user_id
        testrun_record.duration = report.duration
        testrun_record.comment = trace
        polarion_set_record_retry(testrun, testrun_record)
    elif report.when == 'setup' and report.skipped and (record_always or record_skipped):
        testrun_record.result = 'blocked'
        testrun_record.executed_by = testrun_record.logged_in_user_id
        try:
            testrun_record.comment = item.get_marker('skipif').kwargs['reason']
        except AttributeError:
            pass
        polarion_set_record_retry(testrun, testrun_record)
