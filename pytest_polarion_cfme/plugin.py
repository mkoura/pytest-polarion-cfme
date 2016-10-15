# -*- coding: utf-8 -*-
"""pytest plugin for recording test results in Polarion."""

from __future__ import print_function, unicode_literals

import datetime
import time
import pytest

from pylarion.test_run import TestRun
from pylarion.work_item import TestCase
from pylarion.exceptions import PylarionLibException

from _pytest.runner import runtestprotocol


def pytest_addoption(parser):
    """Add Polarion specific options to pytest."""

    group = parser.getgroup('Polarion')
    group.addoption('--polarion-run',
                    default=None,
                    action='store',
                    help='Polarion TestRun name (default: %default)')
    group.addoption('--polarion-project',
                    default=None,
                    action='store',
                    help='Polarion project name (default taken from pylarion config file)')
    group.addoption('--polarion-always-report',
                    default=False,
                    action='store_true',
                    help='Report all results, not only passed tests (default: %default)')
    group.addoption('--polarion-caching-level',
                    action='store',
                    type=int,
                    default=0,
                    help='Data caching aggressivity (default: %default)')


def guess_polarion_id(item):
    """Guess how the test's 'Node ID' corresponds to Work Item 'Test Case ID' in Polarion."""

    unique_id = item.nodeid.replace('/', '.').replace('::()', '') \
                           .replace('::', '.').replace('.py', '')
    polarion_test_case_id = unique_id
    param_index = polarion_test_case_id.rfind('[')
    if param_index > 0:
        polarion_test_case_id = polarion_test_case_id[:param_index]
    return (unique_id, polarion_test_case_id)


def compile_query_str(test_case_id, level=0):
    """Compile query string for Test Case search."""

    if level <= 0:
        return test_case_id

    components = test_case_id.split('.')
    new_len = len(components) - level
    if new_len < 2:
        new_len = 2
    return ".".join(components[:new_len]) + '.*'


def polarion_query_test_case(cache, query_str, polarion_project):
    """Query Polarion for matching Test Cases and save their IDs."""

    test_cases = TestCase.query(project_id=polarion_project, query=query_str,
                                fields=["title", "work_item_id", "test_case_id"])
    if not test_cases:
        pytest.fail('Failed to collect items from Polarion using query "{}".'
                    .format(query_str))

    for case in test_cases:
        new_id = case.test_case_id
        param_index = case.title.rfind('[')
        if param_index > 0:
            new_id += case.title[param_index:]
        cache[new_id] = case.work_item_id


def polarion_collect_test_cases(items, config):
    """Find corresponding Polarion work item ID for each test."""

    caching_level = config.getoption('polarion_caching_level')
    polarion_project = config.getoption('polarion_project')
    if not polarion_project:
        polarion_project = TestCase.default_project

    cached_ids = {}
    cached_queries = set()
    start_time = time.time()

    for item in items:
        unique_id, test_case_id = guess_polarion_id(item)
        if unique_id not in cached_ids:
            query_str = compile_query_str(test_case_id, caching_level)
            if query_str in cached_queries:
                # we've already tried this query, no need to repeat
                item.polarion_work_item_id = None
                continue
            cached_queries.add(query_str)
            polarion_query_test_case(cached_ids, query_str, polarion_project)

        if unique_id in cached_ids:
            item.polarion_work_item_id = cached_ids[unique_id]
        else:
            # work item was not found
            item.polarion_work_item_id = None

    print('Cached {} polarion items in {}s'.format(
        len(cached_ids), round(time.time() - start_time, 2)))


def polarion_collect_testrun(config):
    """Collect all work item IDs in specified testrun."""

    polarion_run = config.getoption('polarion_run')
    polarion_project = config.getoption('polarion_project')
    if not polarion_project:
        polarion_project = TestRun.default_project

    testrun = TestRun(project_id=polarion_project, test_run_id=polarion_run)
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

    remaining = [item for item in items
                 if item.polarion_work_item_id in config.polarion_testrun_records]

    deselect = set(items) - set(remaining)
    if deselect:
        config.hook.pytest_deselected(items=deselect)
        items[:] = remaining


def polarion_set_record(testrun, test_case):
    """Do the updating of Test Case record in Polarion."""

    try:
        testrun.add_test_record_by_object(test_case)
    except PylarionLibException:
        testrun.reload()
        testrun.update_test_record_by_object(test_case.test_case_id, test_case)


def pytest_runtest_protocol(item, nextitem):
    """Check test result and update Test Run record in Polarion."""

    if item.config.getoption('polarion_run') is None:
        return

    report_always = item.config.getoption('polarion_always_report')
    reports = runtestprotocol(item, nextitem=nextitem)

    # get polarion objects
    testrun = item.config.polarion_testrun_obj
    testrun_record = item.config.polarion_testrun_records[item.polarion_work_item_id]

    for report in reports:
        if report.when == 'call':
            # build up traceback massage
            trace = ''
            if not report.passed:
                if not report_always:
                    continue
                trace = '{}:{}\n{}'.format(report.location, report.when, report.longrepr)

            testrun_record.result = report.outcome
            testrun_record.executed = datetime.datetime.now()
            testrun_record.executed_by = testrun_record.logged_in_user_id
            testrun_record.duration = report.duration
            testrun_record.comment = trace
            polarion_set_record(testrun, testrun_record)
        elif report.when == 'setup' and report.skipped and report_always:
            testrun_record.result = 'blocked'
            testrun_record.executed_by = testrun_record.logged_in_user_id
            try:
                testrun_record.comment = item.get_marker('skipif').kwargs['reason']
            except AttributeError:
                pass
            polarion_set_record(testrun, testrun_record)

    return True
