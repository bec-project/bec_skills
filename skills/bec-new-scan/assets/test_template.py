"""Tests for my_step_scan. Place under tests/tests_scans/ in the plugin repo (or
bec_server/tests/tests_scan_server/scans_v4/ in core). `bec_server` must be installed ([dev])."""

from unittest import mock

import numpy as np
import pytest
from bec_server.scan_server.errors import LimitError
from bec_server.scan_server.tests.scan_fixtures import (  # noqa: F401  (fixtures)
    nth_done_status_mock,
    readout_priority,
    v4_scan_assembler,
)
from bec_server.scan_server.tests.scan_hook_tests import (
    DEFAULT_HOOK_TESTS,
    PREMOVE_HOOK_TESTS,
    STANDARD_STEP_SCAN_TESTS,
    run_scan_tests,
)

SCAN = "my_step_scan"


@pytest.fixture
def scan(v4_scan_assembler):
    # Mock devices have limits (-10, 10) and read back 0.0.
    return v4_scan_assembler(SCAN, "samx", -1.0, 1.0, 5, relative=False, exp_time=0.1)


@pytest.mark.parametrize(
    ("hook_name", "hook_tests"),
    [*DEFAULT_HOOK_TESTS, *PREMOVE_HOOK_TESTS, *STANDARD_STEP_SCAN_TESTS],
)
def test_default_hook_contracts(scan, nth_done_status_mock, hook_name, hook_tests):
    run_scan_tests(scan, [(hook_name, hook_tests)], nth_done_status_mock=nth_done_status_mock)


def test_prepare_scan_positions_and_metadata(scan):
    scan.prepare_scan()
    np.testing.assert_allclose(scan.positions[:, 0], np.linspace(-1.0, 1.0, 5))
    assert scan.scan_info.num_points == 5
    assert scan.scan_info.num_monitored_readouts == 5
    assert scan.scan_info.scan_report_instructions == [
        {"scan_progress": {"points": 5, "show_table": True}}
    ]
    assert scan.scan_info.scan_type == "software_triggered"


def test_prepare_scan_rejects_positions_outside_limits(v4_scan_assembler):
    scan = v4_scan_assembler(SCAN, "samx", -100.0, 100.0, 3, relative=False)
    with pytest.raises(LimitError):
        scan.prepare_scan()


def test_relative_scan_offsets_positions_and_moves_back(v4_scan_assembler, nth_done_status_mock):
    scan = v4_scan_assembler(SCAN, "samx", -1.0, 1.0, 3, relative=True)
    scan.components.get_start_positions = mock.MagicMock(return_value=[2.0])
    scan.prepare_scan()
    np.testing.assert_allclose(scan.positions[:, 0], [1.0, 2.0, 3.0])

    scan.actions.complete_all_devices = mock.MagicMock(return_value=nth_done_status_mock(1))
    scan.components.move_and_wait = mock.MagicMock()
    scan.post_scan()
    scan.components.move_and_wait.assert_called_once_with(scan.motors, [2.0])


def test_on_exception_returns_to_start_for_relative_scans(v4_scan_assembler):
    scan = v4_scan_assembler(SCAN, "samx", -1.0, 1.0, 3, relative=True)
    scan.start_positions = [2.0]
    scan.components.move_and_wait = mock.MagicMock()
    scan.on_exception(RuntimeError("boom"))
    scan.components.move_and_wait.assert_called_once_with(scan.motors, [2.0])
