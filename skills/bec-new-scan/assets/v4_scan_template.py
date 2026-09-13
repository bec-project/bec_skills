"""
<One-line description of the scan.>

Scan procedure:
    - prepare_scan
    - open_scan
    - stage
    - pre_scan
    - scan_core
        - at_each_point (optionally called by scan_core)
    - post_scan
    - unstage
    - close_scan
    - on_exception (called if any exception is raised during the scan)
"""

from __future__ import annotations

from typing import Annotated

import numpy as np
from bec_lib.device import DeviceBase
from bec_lib.logger import bec_logger
from bec_lib.scan_args import DefaultArgType, ScanArgument
from bec_server.scan_server.scans import position_generators
from bec_server.scan_server.scans.scan_base import ScanBase, ScanType
from bec_server.scan_server.scans.scan_modifier import scan_hook

logger = bec_logger.logger


class MyStepScan(ScanBase):
    # SOFTWARE_TRIGGERED: this scan moves, triggers and reads at every point itself.
    # Use HARDWARE_TRIGGERED when a kicked-off device runs the acquisition (see the other asset).
    scan_type = ScanType.SOFTWARE_TRIGGERED
    # Valid Python identifier, unique across core and plugin scans; this is `scans.<scan_name>`.
    scan_name = "my_step_scan"

    gui_config = {
        "Movement Parameters": ["device", "start", "stop", "steps", "relative"],
        "Acquisition Parameters": [
            "exp_time",
            "frames_per_trigger",
            "settling_time",
            "settling_time_after_trigger",
            "readout_time",
            "burst_at_each_point",
        ],
    }

    def __init__(
        self,
        device: DeviceBase,
        start: Annotated[
            float, ScanArgument(display_name="Start Position", reference_units="device")
        ],
        stop: Annotated[float, ScanArgument(display_name="Stop Position", reference_units="device")],
        steps: Annotated[int, ScanArgument(display_name="Number of Steps", gt=0)],
        *,
        relative: DefaultArgType.Relative,
        exp_time: DefaultArgType.ExposureTime = 0,
        frames_per_trigger: DefaultArgType.FramesPerTrigger = 1,
        settling_time: DefaultArgType.SettlingTime = 0,
        settling_time_after_trigger: DefaultArgType.SettlingTimeAfterTrigger = 0,
        readout_time: DefaultArgType.ReadoutTime = 0,
        burst_at_each_point: DefaultArgType.BurstAtEachPoint = 1,
        **kwargs,
    ):
        """
        <Summary sentence shown in the client as scans.my_step_scan.__doc__.>

        Args:
            device (DeviceBase): motor to scan
            start (float): start position
            stop (float): stop position
            steps (int): number of points
            relative (bool): interpret start/stop relative to the current position
            exp_time (float): exposure time in seconds. Default is 0.
            frames_per_trigger (int): frames acquired per trigger. Default is 1.
            settling_time (float): settling time before the trigger. Default is 0.
            settling_time_after_trigger (float): settling time after the trigger. Default is 0.
            readout_time (float): readout time in seconds. Default is 0.
            burst_at_each_point (int): exposures per point. Default is 1.

        Returns:
            ScanReport

        Examples:
            >>> scans.my_step_scan(dev.samx, -5, 5, 11, relative=False, exp_time=0.1)
        """
        super().__init__(**kwargs)
        self.device = device
        self.motors = [device]
        self.start = start
        self.stop = stop
        self.steps = steps
        self.relative = relative
        self.burst_at_each_point = burst_at_each_point
        self._premove_motor_status = None
        self._baseline_readout_status = None

        self.update_scan_info(
            exp_time=exp_time,
            frames_per_trigger=frames_per_trigger,
            settling_time=settling_time,
            settling_time_after_trigger=settling_time_after_trigger,
            readout_time=readout_time,
            relative=relative,
            burst_at_each_point=burst_at_each_point,
            scan_report_devices=self.motors,
        )
        # Step-scanned motors must be part of every monitored readout.
        self.actions.set_device_readout_priority(self.motors, priority="monitored")

    @scan_hook
    def prepare_scan(self):
        """Compute positions, validate them, prepare metadata and start non-blocking work."""
        self.positions = position_generators.line_scan_positions(
            [(self.start, self.stop)], steps=self.steps
        )
        if self.relative:
            self.start_positions = self.components.get_start_positions(self.motors)
            self.positions += self.start_positions
        self.components.check_limits(self.motors, self.positions)

        self.update_scan_info(
            positions=self.positions,
            num_points=len(self.positions),
            num_monitored_readouts=len(self.positions) * self.burst_at_each_point,
        )
        self.actions.add_scan_report_instruction_scan_progress(
            points=self.scan_info.num_monitored_readouts, show_table=True
        )
        # Overlap the pre-move with the baseline readout; both are awaited later.
        self._premove_motor_status = self.actions.set(self.motors, self.positions[0], wait=False)
        self._baseline_readout_status = self.actions.read_baseline_devices(wait=False)

    @scan_hook
    def open_scan(self):
        """Open the scan. Must call self.actions.open_scan()."""
        self.actions.open_scan()

    @scan_hook
    def stage(self):
        """Stage all devices; device-specific logic lives in the devices' stage()."""
        self.actions.stage_all_devices()

    @scan_hook
    def pre_scan(self):
        """Last preparation before time-critical devices start."""
        self._premove_motor_status.wait()
        self.actions.pre_scan_all_devices()

    @scan_hook
    def scan_core(self):
        """Step through all positions, delegating each point to at_each_point."""
        self.components.step_scan(
            self.motors,
            self.positions,
            at_each_point=self.at_each_point,
            last_positions=self.positions[0],
        )

    @scan_hook
    def at_each_point(
        self,
        motors: list[str | DeviceBase],
        positions: np.ndarray,
        last_positions: np.ndarray | None,
    ):
        """Move, settle, trigger, settle, read - kept as a hook so modifiers can extend it."""
        self.components.step_scan_at_each_point(motors, positions, last_positions=last_positions)

    @scan_hook
    def post_scan(self):
        """Complete devices; move back to the start for relative scans."""
        status = self.actions.complete_all_devices(wait=False)
        if self.relative:
            self.components.move_and_wait(self.motors, self.start_positions)
        status.wait()

    @scan_hook
    def unstage(self):
        """Unstage all devices."""
        self.actions.unstage_all_devices()

    @scan_hook
    def close_scan(self):
        """Wait for the baseline readout, close the scan, report forgotten statuses."""
        if self._baseline_readout_status is not None:
            self._baseline_readout_status.wait()
        self.actions.close_scan()
        self.actions.check_for_unchecked_statuses()

    @scan_hook
    def on_exception(self, exception: Exception):
        """Bring the beamline back to a safe state. Must not raise."""
        logger.warning(f"{self.scan_name} aborted: {exception}")
        if self.relative and getattr(self, "start_positions", None) is not None:
            self.components.move_and_wait(self.motors, self.start_positions)
