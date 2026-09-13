"""Tests for MyDetector - tests/tests_devices/test_mydet.py"""

from unittest import mock

import numpy as np
import pytest
from ophyd_devices import CompareStatus
from ophyd_devices.interfaces.base_classes.psi_device_base import DeviceStoppedError
from ophyd_devices.tests.utils import get_mock_scan_info, patched_device

from mybeamline_bec.devices.mydet.mydet import DetectorState, MyDetector


@pytest.fixture
def det():
    with patched_device(MyDetector, name="mydet", prefix="SIM:MYDET:") as device:
        device.scan_info = get_mock_scan_info(device=device)  # num_points, scan_parameters, ...
        device.state._read_pv.mock_data = DetectorState.IDLE
        yield device


def test_constructs_offline():
    with patched_device(MyDetector, name="mydet", prefix="SIM:MYDET:", timeout=2.0) as device:
        assert device._timeout == 2.0


def test_on_stage_configures_ioc_and_returns_status(det):
    msg = det.scan_info.msg
    status = det.on_stage()
    assert det.num_images.get() == msg.num_points * msg.scan_parameters["frames_per_trigger"]
    assert det.exp_time.get() == msg.scan_parameters["exp_time"]
    assert det.arm.get() == 1
    assert isinstance(status, CompareStatus) and not status.done
    det.state._read_pv.mock_data = DetectorState.ARMED  # setter fires the subscription callbacks
    status.wait(timeout=1)
    assert status.done and status.success


def test_on_trigger_finishes_when_acquire_returns_to_zero(det):
    status = det.on_trigger()
    assert det.acquire.get() == 1
    det.acquire._read_pv.mock_data = 0
    status.wait(timeout=1)
    assert status.success


def test_stop_fails_pending_status(det):
    status = det.on_stage()
    det.stop()
    assert det.stopped is True
    with pytest.raises(DeviceStoppedError):
        status.wait(timeout=1)
    det.stop()  # idempotent


def test_new_frame_publishes_preview_and_async_data(det):
    det._expected_frames = 3
    det.spectrum._read_pv.mock_data = np.arange(4096)
    with mock.patch.object(det.preview, "put") as preview_put, mock.patch.object(
        det.data, "put"
    ) as data_put, mock.patch.object(det.progress, "put") as progress_put:
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
