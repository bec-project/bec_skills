"""<Vendor/model> integration for <beamline>. prefix: 'X99XA-ES-MYDET:'"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from bec_lib.logger import bec_logger
from ophyd import Component as Cpt
from ophyd import Device, EpicsSignal, EpicsSignalRO
from ophyd_devices import (
    AsyncSignal,
    CompareStatus,
    FileEventSignal,
    PreviewSignal,
    ProgressSignal,
    StatusBase,
    TransitionStatus,
)
from ophyd_devices.interfaces.base_classes.psi_device_base import PSIDeviceBase

if TYPE_CHECKING:
    from bec_lib.devicemanager import DeviceManagerBase, ScanInfo

logger = bec_logger.logger


class DetectorState(int, enum.Enum):
    """States of the IOC state machine (keep enums next to the device)."""

    IDLE = 0
    ARMED = 1
    ACQUIRING = 2
    ERROR = 3


class MyDetectorControl(Device):
    """Plain ophyd layer: every PV of the IOC, nothing else."""

    state = Cpt(EpicsSignalRO, "STATE", auto_monitor=True)
    acquire = Cpt(EpicsSignal, "ACQUIRE", put_complete=True)
    arm = Cpt(EpicsSignal, "ARM")
    exp_time = Cpt(EpicsSignal, "EXPTIME", kind="config")
    num_images = Cpt(EpicsSignal, "NIMAGES", kind="config")
    frame_counter = Cpt(EpicsSignalRO, "FRAMECOUNT", auto_monitor=True)
    spectrum = Cpt(EpicsSignalRO, "SPECTRUM", kind="omitted")


class MyDetector(PSIDeviceBase, MyDetectorControl):
    """Behaviour layer: reacts to stage/trigger/kickoff/complete and streams data to BEC."""

    USER_ACCESS = ["set_timeout"]

    # BEC signals - the device server subscribes automatically
    progress = Cpt(ProgressSignal, name="progress")
    file_event = Cpt(FileEventSignal, name="file_event")
    preview = Cpt(PreviewSignal, name="preview", ndim=1)
    data = Cpt(
        AsyncSignal,
        name="data",
        ndim=1,
        max_size=1000,
        async_update={"type": "add", "max_shape": [None, 4096]},
        doc="Spectrum per frame.",
    )

    def __init__(
        self,
        prefix: str = "",
        *,
        name: str,
        scan_info: ScanInfo | None = None,           # explicit -> injected by the device server
        device_manager: DeviceManagerBase | None = None,
        timeout: float = 5.0,                        # deviceConfig key
        **kwargs,
    ):
        super().__init__(
            prefix=prefix, name=name, scan_info=scan_info, device_manager=device_manager, **kwargs
        )
        self._timeout = timeout

    # ------------------------------------------------------------------ hooks
    def on_init(self) -> None:
        self._expected_frames = 0
        self._file_path: str | None = None

    def on_connected(self) -> None:
        status = TransitionStatus(
            self.state, transitions=[DetectorState.IDLE], strict=False, description="IOC idle"
        )
        self.cancel_on_stop(status)
        status.wait(timeout=self._timeout)
        self.frame_counter.subscribe(self._on_new_frame, run=False)

    def on_stage(self) -> StatusBase:
        msg = self.scan_info.msg
        self._expected_frames = msg.num_points * msg.scan_parameters.get("frames_per_trigger", 1)
        self.num_images.set(self._expected_frames).wait(timeout=self._timeout)
        self.exp_time.set(msg.scan_parameters.get("exp_time", 0.1)).wait(timeout=self._timeout)
        self._file_path = self.file_utils.get_full_path(scan_status_msg=msg, name=self.name)
        self.file_event.put(
            file_path=self._file_path,
            done=False,
            successful=False,
            hinted_h5_entries={"data": "/entry/data/data"},
        )
        self.arm.put(1)
        status = CompareStatus(
            self.state, DetectorState.ARMED, timeout=self._timeout, description="arming"
        )
        self.cancel_on_stop(status)
        return status

    def on_pre_scan(self) -> None:
        self.progress.put(value=0, max_value=self._expected_frames, done=False)

    def on_trigger(self) -> StatusBase:
        self.acquire.put(1)
        status = CompareStatus(
            self.acquire, 0, timeout=self.exp_time.get() + self._timeout, description="exposure"
        )
        self.cancel_on_stop(status)
        return status

    def on_kickoff(self) -> StatusBase:
        self.acquire.put(1)
        status = CompareStatus(self.state, DetectorState.ACQUIRING, timeout=self._timeout)
        self.cancel_on_stop(status)
        return status

    def on_complete(self) -> StatusBase:
        status = CompareStatus(
            self.frame_counter,
            self._expected_frames,
            operation_success=">=",
            description=f"waiting for {self._expected_frames} frames",
        )
        self.cancel_on_stop(status)
        return status

    def on_unstage(self) -> None:
        if self._file_path is not None:
            self.file_event.put(file_path=self._file_path, done=True, successful=True)
        self.progress.put(value=self._expected_frames, max_value=self._expected_frames, done=True)

    def on_stop(self) -> None:
        self.acquire.put(0)  # idempotent on the IOC side
        self.task_handler.shutdown()

    def on_destroy(self) -> None:
        self.frame_counter.clear_sub(self._on_new_frame)

    # ------------------------------------------------------------------ user API
    def set_timeout(self, timeout: float) -> None:
        """Set the IOC handshake timeout in seconds (RPC: dev.mydet.set_timeout(10))."""
        self._timeout = float(timeout)

    # ------------------------------------------------------------------ callbacks
    def _on_new_frame(self, value: int, old_value: int, **kwargs) -> None:
        if value == old_value or value <= 0:
            return
        try:
            spectrum = self.spectrum.get()
            self.preview.put(spectrum)
            self.data.put(spectrum)  # dropped by BEC when no scan is open - fine
            self.progress.put(value=value, max_value=self._expected_frames, done=False)
        except Exception:  # pylint: disable=broad-except
            logger.exception(f"{self.name}: failed to publish frame {value}")
