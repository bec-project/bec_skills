"""
Hardware-triggered acquisition: a DAQ/detector device runs the acquisition after kickoff and the
scan reads monitored devices until the device reports completion.

Scan procedure: prepare_scan, open_scan, stage, pre_scan, scan_core (at_each_point), post_scan,
unstage, close_scan; on_exception on error.
"""

from __future__ import annotations

import time
from typing import Annotated

from bec_lib.device import DeviceBase
from bec_lib.scan_args import ScanArgument, Units
from bec_server.scan_server.errors import ScanAbortion
from bec_server.scan_server.scans.scan_base import ScanBase, ScanType
from bec_server.scan_server.scans.scan_modifier import scan_hook


class MyDaqScan(ScanBase):
    scan_type = ScanType.HARDWARE_TRIGGERED
    scan_name = "my_daq_scan"
    gui_config = {"Acquisition Parameters": ["daq", "scan_duration", "readout_cycle"]}

    def __init__(
        self,
        # fmt: off
        daq: Annotated[DeviceBase, ScanArgument(display_name="DAQ", description="Device implementing kickoff/complete.")],
        scan_duration: Annotated[float, ScanArgument(display_name="Duration", description="Acquisition duration.", units=Units.s, gt=0)],
        *,
        readout_cycle: Annotated[float, ScanArgument(display_name="Monitored readout cycle", description="Period of the monitored readouts.", units=Units.s, gt=0)] = 0.5,
        # fmt: on
        **kwargs,
    ):
        """
        Kick off `daq` for `scan_duration` seconds and read monitored devices every `readout_cycle`.

        Args:
            daq (DeviceBase): device implementing kickoff/complete
            scan_duration (float): acquisition duration in seconds
            readout_cycle (float): period of the monitored readouts in seconds. Default is 0.5.

        Returns:
            ScanReport
        """
        super().__init__(**kwargs)
        self.daq = daq
        self.scan_duration = scan_duration
        self.readout_cycle = readout_cycle
        self._baseline_readout_status = None
        # Tell the device (and the file writer) how long / how many readouts to expect.
        self.update_scan_info(
            num_points=int(scan_duration / readout_cycle),
            num_monitored_readouts=int(scan_duration / readout_cycle),
            scan_duration=scan_duration,  # unknown kwargs -> additional_scan_parameters
        )

    @scan_hook
    def prepare_scan(self):
        self.actions.add_scan_report_instruction_device_progress(self.daq)
        self._baseline_readout_status = self.actions.read_baseline_devices(wait=False)

    @scan_hook
    def open_scan(self):
        self.actions.open_scan()

    @scan_hook
    def stage(self):
        self.actions.stage_all_devices()

    @scan_hook
    def pre_scan(self):
        self.actions.pre_scan_all_devices()

    @scan_hook
    def scan_core(self):
        # Parameters are delivered to the device's kickoff(); keep them JSON-serialisable.
        kickoff_status = self.actions.kickoff(
            device=self.daq, parameters={"duration": self.scan_duration}, wait=False
        )
        if not kickoff_status.wait(timeout=5):
            raise ScanAbortion(f"Kickoff of {self.daq} did not finish within 5 s.")
        complete_status = self.actions.complete(device=self.daq, wait=False)
        # Poll instead of sleeping the full duration so abort/halt stay responsive.
        while not complete_status.done:
            self.at_each_point()
            time.sleep(self.readout_cycle)

    @scan_hook
    def at_each_point(self):
        self.actions.read_monitored_devices()

    @scan_hook
    def post_scan(self):
        self.actions.complete_all_devices()

    @scan_hook
    def unstage(self):
        self.actions.unstage_all_devices()

    @scan_hook
    def close_scan(self):
        if self._baseline_readout_status is not None:
            self._baseline_readout_status.wait()
        self.actions.close_scan()
        self.actions.check_for_unchecked_statuses()

    @scan_hook
    def on_exception(self, exception: Exception):
        # Stop the acquisition; the device's stop() must be idempotent.
        self.actions.rpc_call(self.daq, "stop")
