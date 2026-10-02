"""Tests for MyDetector: tests/test_mydet.py (ophyd_devices) or tests/tests_devices/ (plugin)."""

from unittest import mock

import numpy as np
import pytest
from ophyd.utils import WaitTimeoutError

from ophyd_devices.interfaces.base_classes.psi_device_base import DeviceStoppedError
from ophyd_devices.interfaces.protocols.bec_protocols import BECDeviceProtocol, BECFlyerProtocol
from ophyd_devices.tests.utils import get_mock_scan_info, patched_device
from ophyd_devices.utils.psi_device_base_utils import CompareStatus

from mybeamline_bec.devices.mydet.mydet import DetectorState, MyDetector


@pytest.fixture
def det():
    with patched_device(MyDetector, name="mydet", prefix="SIM:MYDET:") as device:
        device.scan_info = get_mock_scan_info(device=device)  # num_points, scan_parameters, ...
        device.state._read_pv.mock_data = DetectorState.IDLE
        yield device
        device.destroy()


def test_constructs_offline():
    with patched_device(MyDetector, name="mydet", prefix="SIM:MYDET:", timeout=2.0) as device:
        assert device.get_timeout() == 2.0
        device.destroy()


def test_implements_bec_protocols(det):
    assert isinstance(det, BECDeviceProtocol)
    assert isinstance(det, BECFlyerProtocol)


def test_on_connected_subscribes_to_frame_counter(det):
    det.on_connected()  # patched_device and ophyd_test do not call it; the device server does
    det.spectrum._read_pv.mock_data = np.arange(4096)
    with mock.patch.object(det.preview, "put") as preview_put:
        det.frame_counter._read_pv.mock_data = 1
    preview_put.assert_called_once()


def test_on_stage_configures_ioc_and_returns_status(det):
    msg = det.scan_info.msg
    status = det.stage()
    assert det.num_images.get() == msg.num_points * msg.scan_parameters["frames_per_trigger"]
    assert det.exp_time.get() == msg.scan_parameters["exp_time"]
    assert det.arm_cmd.get() == 1
    assert isinstance(status, CompareStatus) and not status.done
    det.state._read_pv.mock_data = DetectorState.ARMED  # setter fires the subscription callbacks
    status.wait(timeout=1)
    assert status.done and status.success


def test_on_stage_fails_when_ioc_reports_error(det):
    status = det.stage()
    det.state._read_pv.mock_data = DetectorState.ERROR
    with pytest.raises(Exception):
        status.wait(timeout=1)
    assert status.done and not status.success


def test_on_trigger_finishes_when_acquire_returns_to_zero(det):
    status = det.trigger()
    assert det.acquire.get() == 1
    det.acquire._read_pv.mock_data = 0
    status.wait(timeout=1)
    assert status.success


def test_complete_waits_for_all_frames(det):
    det.stage()
    status = det.complete()
    det.frame_counter._read_pv.mock_data = det._expected_frames - 1
    with pytest.raises(WaitTimeoutError):
        status.wait(timeout=0.2)
    det.frame_counter._read_pv.mock_data = det._expected_frames
    status.wait(timeout=1)
    assert status.success


def test_stop_fails_pending_status_and_is_repeatable(det):
    status = det.stage()
    det.stop()
    assert det.stopped is True
    assert det.acquire.get() == 0
    with pytest.raises(DeviceStoppedError):
        status.wait(timeout=1)
    det.stop()  # repeated stop must be safe


def test_new_frame_publishes_preview_and_async_data(det):
    det._expected_frames = 3
    det.spectrum._read_pv.mock_data = np.arange(4096)
    with (
        mock.patch.object(det.preview, "put") as preview_put,
        mock.patch.object(det.data, "put") as data_put,
        mock.patch.object(det.progress, "put") as progress_put,
    ):
        det._on_new_frame(value=1, old_value=0)
    preview_put.assert_called_once()
    data_put.assert_called_once()
    progress_put.assert_called_once_with(value=1, max_value=3, done=False)


def test_on_unstage_closes_file_event(det):
    det._file_path = "/tmp/x.h5"
    det._expected_frames = 2
    with mock.patch.object(det.file_event, "put") as fe_put:
        det.on_unstage()
    fe_put.assert_called_once_with(file_path="/tmp/x.h5", done=True, successful=True)
