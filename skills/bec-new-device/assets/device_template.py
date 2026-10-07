"""<Vendor/model> detector integration. prefix: 'X99XA-ES-MYDET:'

Two layers, following ophyd_devices/AGENTS.md:

- ``MyDetectorControl`` (plain ``ophyd.Device``) is the reusable control layer: PV definitions and
  small command methods. For hardware used at more than one beamline it lives in ophyd_devices.
- ``MyDetector`` (``PSIDeviceBase``) adds the business logic in the ``on_*`` hooks. Generic
  lifecycle behaviour can live next to the control class; beamline-specific behaviour belongs in
  a subclass in the beamline plugin repository (see SKILL.md, "Beamline subclass").
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from bec_lib.logger import bec_logger
from ophyd import Component as Cpt
from ophyd import Device, EpicsSignal, EpicsSignalRO

from ophyd_devices.interfaces.base_classes.psi_device_base import PSIDeviceBase
from ophyd_devices.utils.bec_signals import (
    AsyncSignal,
    FileEventSignal,
    PreviewSignal,
    ProgressSignal,
)
from ophyd_devices.utils.psi_device_base_utils import (
    AndStatus,
    CompareStatus,
    DeviceStatus,
    StatusBase,
    TransitionStatus,
)

if TYPE_CHECKING:  # pragma: no cover
    from bec_lib.devicemanager import DeviceManagerBase, ScanInfo

logger = bec_logger.logger


class DetectorState(int, enum.Enum):
    """States of the IOC state machine (keep enums next to the device)."""

    IDLE = 0
    ARMED = 1
    ACQUIRING = 2
    ERROR = 3


class TriggerMode(int, enum.Enum):
    """Trigger sources supported by the IOC."""

    INTERNAL = 0
    EXTERNAL = 1


class MyDetectorControl(Device):
    """<Vendor/model> detector control interface: IOC PVs and acquisition commands.

    Settings are written with ``set()`` and the statuses are returned, so the hooks can wait for
    them without blocking. Commands (arm, start, stop) are plain ``put()`` calls: the hooks confirm
    their effect with a status on the state PV. Whether a write may go unconfirmed is device
    specific - check the IOC before turning a ``set()`` into a ``put()``.
    """

    state = Cpt(EpicsSignalRO, "STATE", auto_monitor=True, kind="omitted")
    acquire = Cpt(EpicsSignal, "ACQUIRE", kind="omitted")
    arm_cmd = Cpt(EpicsSignal, "ARM", kind="omitted")
    exp_time = Cpt(EpicsSignal, "EXPTIME", kind="config")
    num_images = Cpt(EpicsSignal, "NIMAGES", kind="config")
    trigger_mode = Cpt(EpicsSignal, "TRIGMODE", kind="config")
    frame_counter = Cpt(EpicsSignalRO, "FRAMECOUNT", auto_monitor=True, kind="normal")
    spectrum = Cpt(EpicsSignalRO, "SPECTRUM", kind="omitted")

    def configure_acquisition(self, num_images: int, exp_time: float) -> AndStatus:
        """Write the acquisition parameters; the status finishes when the IOC has taken both."""
        return AndStatus(
            self.num_images.set(num_images),
            self.exp_time.set(exp_time),
            description=f"{self.name}: configure acquisition",
        )

    def set_trigger_mode(self, mode: TriggerMode) -> StatusBase:
        """Select the trigger source used by the next acquisition."""
        return self.trigger_mode.set(int(mode))

    def arm(self) -> None:
        """Arm the detector so it accepts triggers."""
        self.arm_cmd.put(1)

    def start_acquisition(self) -> None:
        """Start one acquisition (software trigger) or the hardware-triggered series."""
        self.acquire.put(1)

    def stop_acquisition(self) -> None:
        """Abort the running acquisition; safe to call repeatedly."""
        self.acquire.put(0)


class MyDetector(PSIDeviceBase, MyDetectorControl):
    """<Vendor/model> detector with software and hardware triggering and HDF5 file output."""

    USER_ACCESS = ["set_timeout", "get_timeout"]

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
        scan_info: ScanInfo | None = None,  # explicit -> injected by the device server
        device_manager: DeviceManagerBase | None = None,
        timeout: float = 5.0,  # deviceConfig key
        **kwargs,
    ):
        super().__init__(
            prefix=prefix, name=name, scan_info=scan_info, device_manager=device_manager, **kwargs
        )
        self._timeout = timeout

    ########################################
    #  Beamline Specific Implementations   #
    ########################################

    def on_init(self) -> None:
        """
        Called when the device is initialized.

        No signals are connected at this point. If you like to
        set default values on signals, please use on_connected instead.
        """
        self._expected_frames = 0
        self._file_path: str | None = None

    def on_connected(self) -> None:
        """
        Called after the device is connected and its signals are connected.
        Default values for signals should be set here.
        """
        # One bounded readiness check at connect time; scan hooks return statuses instead.
        status = TransitionStatus(
            self.state, transitions=[DetectorState.IDLE], strict=False, description="IOC idle"
        )
        self.cancel_on_stop(status)
        status.wait(timeout=self._timeout)
        self.frame_counter.subscribe(self._on_new_frame, run=False)

    def on_stage(self) -> DeviceStatus | StatusBase | None:
        """
        Called while staging the device.

        Information about the upcoming scan can be accessed from the scan_info (self.scan_info.msg) object.
        """
        msg = self.scan_info.msg
        self._expected_frames = msg.num_points * msg.scan_parameters.get("frames_per_trigger", 1)
        config = self.configure_acquisition(
            num_images=self._expected_frames, exp_time=msg.scan_parameters.get("exp_time", 0.1)
        )
        self._file_path = self.file_utils.get_full_path(scan_status_msg=msg, name=self.name)
        self.file_event.put(
            file_path=self._file_path,
            done=False,
            successful=False,
            hinted_h5_entries={"data": "/entry/data/data"},
        )
        # If this IOC must have the configuration before arming, arm from config.add_callback(...).
        self.arm()
        armed = CompareStatus(
            self.state,
            DetectorState.ARMED,
            failure_value=DetectorState.ERROR,
            timeout=self._timeout,
            description=f"{self.name}: arming",
        )
        status = armed & config  # PSI status leftmost keeps the PSI AndStatus and its diagnostics
        self.cancel_on_stop(status)
        return status

    def on_unstage(self) -> DeviceStatus | StatusBase | None:
        """Called while unstaging the device."""
        if self._file_path is not None:
            self.file_event.put(file_path=self._file_path, done=True, successful=not self.stopped)
        self.progress.put(value=self._expected_frames, max_value=self._expected_frames, done=True)

    def on_pre_scan(self) -> DeviceStatus | StatusBase | None:
        """Called right before the scan starts on all devices automatically."""
        self.progress.put(value=0, max_value=self._expected_frames, done=False)

    def on_trigger(self) -> DeviceStatus | StatusBase | None:
        """Called when the device is triggered."""
        self.start_acquisition()
        status = CompareStatus(
            self.acquire,
            0,
            timeout=self.exp_time.get() + self._timeout,
            description=f"{self.name}: exposure",
        )
        self.cancel_on_stop(status)
        return status

    def on_complete(self) -> DeviceStatus | StatusBase | None:
        """Called to inquire if a device has completed a scans."""
        status = CompareStatus(
            self.frame_counter,
            self._expected_frames,
            operation_success=">=",
            description=f"{self.name}: waiting for {self._expected_frames} frames",
        )
        self.cancel_on_stop(status)
        return status

    def on_kickoff(self) -> DeviceStatus | StatusBase | None:
        """Called to kickoff a device for a fly scan. Has to be called explicitly."""
        self.start_acquisition()
        status = CompareStatus(
            self.state,
            DetectorState.ACQUIRING,
            failure_value=DetectorState.ERROR,
            timeout=self._timeout,
            description=f"{self.name}: kickoff",
        )
        self.cancel_on_stop(status)
        return status

    def on_stop(self) -> None:
        """Called when the device is stopped."""
        # EPICS device: statuses come from PV subscriptions, no task_handler tasks to kill.
        self.stop_acquisition()

    def on_destroy(self) -> None:
        """Called when the device is destroyed. Cleanup resources here."""
        self.frame_counter.clear_sub(self._on_new_frame)

    ########################################
    #            Helper Methods            #
    ########################################

    def set_timeout(self, timeout: float) -> None:
        """Set the IOC handshake timeout in seconds (RPC: dev.mydet.set_timeout(10))."""
        self._timeout = float(timeout)

    def get_timeout(self) -> float:
        """Return the IOC handshake timeout in seconds."""
        return self._timeout

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
