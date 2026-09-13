---
name: bec-new-device
description: Integrate a new hardware or virtual device into BEC as an ophyd class built on the ophyd_devices base classes - PSIDeviceBase on_* hooks (on_init/on_connected/on_stage/on_pre_scan/on_trigger/on_kickoff/on_complete/on_unstage/on_stop/on_destroy), PSI status objects (CompareStatus, TransitionStatus, SubscriptionStatus, TaskHandler), BEC signals for async/preview/progress/file data, positioner bases, scan_info usage, the matching device-config YAML entry and tests with patched_device. Use whenever the user wants to add support for a detector, motor, DAQ, camera, pseudo-motor or any EPICS/socket device to BEC or a beamline plugin repo, port an old CustomDetectorMixin/PSIDetectorBase device, or asks how a device should react to stage/trigger/kickoff.
metadata:
  author: bec-project
  version: "0.1"
---

# New BEC device (ophyd_devices)

The device server is the only process that instantiates your class. It calls the ophyd verbs
(`stage`, `trigger`, `kickoff`, `complete`, `unstage`, `stop`, `read`, `set`) and expects status
objects back; `PSIDeviceBase` translates those verbs into `on_*` hooks and adds the plumbing
(`scan_info`, `task_handler`, `file_utils`, stop propagation, `wait_for_condition`). Your job is to
implement hooks that return quickly or return a status, never to block the device server thread.
The old `PSIDetectorBase` / `CustomDetectorMixin` / `CustomPrepare` / `wait_for_signals` API is
gone - port it with the table in [references/hooks-and-statuses.md](references/hooks-and-statuses.md).

Reference implementations: `ophyd_devices/sim/sim_camera.py` (detector with preview, file
event, task handler), `sim_positioner.py`, `sim_monitor.py` (`SimMonitorAsync`), and in plugin
repos `debye_bec/devices/nidaq/nidaq.py` (DAQ with status-object handshakes) and
`debye_bec/devices/falcon/falcon.py` (spectrometer pushing `AsyncSignal` data).

## 1. Choose the base and the shape

| device kind | base | notes |
|---|---|---|
| detector / DAQ / anything with stage-trigger-complete | `class X(PSIDeviceBase, XControl)` where `XControl(Device)` holds the `Cpt(Epics...)` signals | two-layer pattern: signals in a plain ophyd `Device`, behaviour in the PSI subclass |
| EPICS motor record | `ophyd_devices.EpicsMotor` / `EpicsMotorEC` directly via YAML - no class needed | |
| custom positioner (PVs for setpoint/readback/stop) | `PSISimplePositionerBase` (required `user_readback`, `user_setpoint`; optional `velocity`, `motor_stop`, `motor_done_move`) or `PSIPositionerBase` for the full motor-record-like set | `override_suffixes={"user_setpoint": ":SP"}` remaps PV suffixes |
| pseudo motor combining real devices | `PSIPseudoMotorBase` (`forward_calculation`, `inverse_calculation`, `motors_are_moving`) | needs `device_mapping` + `device_access` in YAML |
| pure signal | `ophyd.EpicsSignal(RO)`, `EpicsSignalWithRBV` via YAML | |
| simulation twin for tests/GUI | `ophyd_devices.Sim*` or a `sim/` subclass of your class with `SetableSignal`/`ReadOnlySignal` | keep the same signal names |

Import base classes and statuses from `ophyd_devices` (`from ophyd_devices import PSIDeviceBase,
CompareStatus, DeviceStatus, StatusBase, AsyncSignal, ...`), not from `ophyd`, where
`ophyd_devices` re-exports them - the PSI versions carry descriptions and timeout diagnostics.

## 2. Constructor contract

```python
class MyDetector(PSIDeviceBase, MyDetectorControl):
    USER_ACCESS = ["set_config", "arm"]        # methods callable as dev.mydet.set_config(...)

    def __init__(self, prefix: str = "", *, name: str, scan_info: ScanInfo | None = None,
                 device_manager: DeviceManagerBase | None = None, timeout: float = 5.0, **kwargs):
        super().__init__(prefix=prefix, name=name, scan_info=scan_info, device_manager=device_manager, **kwargs)
```

- The device server passes only `deviceConfig` keys that match named parameters and injects
  `name`; it injects `device_manager` and `scan_info` **only if they are explicit parameters**
  (hidden in `**kwargs` they are not passed). `PSIDeviceBase.__init__` also inherits them from
  a parent device and calls `on_init()` at the end - before any signal is connected.
- Defaults that need PVs go in `on_connected()`, not `__init__`/`on_init`.
- Leftover `deviceConfig` keys are applied by the server after connection as attribute/signal
  writes, so expose tunables either as parameters or as signals.
- Never open sockets, threads or files in `__init__`; the class must be constructible offline
  (`ophyd_test --config` instantiates it).

## 3. Implement the hooks

Order during a scan: `stage → pre_scan → (trigger per point | kickoff … complete) → unstage`;
`stop` may interrupt anywhere; `destroy` on session teardown. Each hook may return `None` or a
`StatusBase`; if it returns a status the server waits on it (with the scan's timeout), so
**return a status for anything longer than a few milliseconds instead of sleeping**.

```python
def on_connected(self):
    status = TransitionStatus(self.state, transitions=[IDLE], strict=False)   # wait for IOC ready
    self.cancel_on_stop(status); status.wait(timeout=self._pv_timeout)
    self.frame_counter.subscribe(self._on_new_frame, run=False)

def on_stage(self) -> StatusBase | None:
    msg = self.scan_info.msg                              # ScanStatusMessage of the upcoming scan
    self.num_images.set(msg.num_points * msg.scan_parameters["frames_per_trigger"]).wait(timeout=2)
    self.exp_time.set(msg.scan_parameters["exp_time"]).wait(timeout=2)
    self.file_path = self.file_utils.get_full_path(scan_status_msg=msg, name=self.name)
    self.file_event.put(file_path=self.file_path, done=False, successful=False,
                        hinted_h5_entries={"data": "/entry/data/data"})
    if msg.scan_type == "software_triggered":            # decide per scan type
        self.trigger_mode.set(TriggerMode.SOFTWARE).wait(timeout=2)
    return CompareStatus(self.state, DetectorState.ARMED, timeout=10, description="arming")

def on_trigger(self) -> StatusBase:
    self.acquire.put(1)
    return CompareStatus(self.acquire, 0, timeout=self.exp_time.get() + 5, description="exposure")

def on_kickoff(self) -> StatusBase:                      # hardware-triggered scans
    self.start.put(1)
    return CompareStatus(self.state, DetectorState.ACQUIRING, timeout=5)

def on_complete(self) -> StatusBase:
    return self.task_handler.submit_task(self._wait_for_all_frames)   # or a CompareStatus on a counter

def on_unstage(self):  self.file_event.put(file_path=self.file_path, done=True, successful=True)
def on_stop(self):     self.acquire.put(0); self.task_handler.shutdown()
def on_destroy(self):  self.frame_counter.clear_sub(self._on_new_frame)
```

Every status you hand out should be registered with `self.cancel_on_stop(status)` so `stop()`
fails it with `DeviceStoppedError` instead of leaving the scan hanging. Use
`self.wait_for_condition(callable, timeout, check_stopped=True)` for short polls. Long-running
work (frame counting, socket reads) goes through `self.task_handler.submit_task(fn)` which
returns a `TaskStatus` and is killed by `on_stop`/`destroy`. Status-object catalogue and the
legacy mapping: [references/hooks-and-statuses.md](references/hooks-and-statuses.md).

## 4. Publishing data to BEC

Declare BEC signals as components; the device server subscribes to them automatically and routes
each to the right Redis endpoint. Do not hand-roll `connector.xadd`.

```python
preview    = Cpt(PreviewSignal, name="preview", ndim=2)                       # live image, not saved
progress   = Cpt(ProgressSignal, name="progress")                             # progress bar in client
file_event = Cpt(FileEventSignal, name="file_event")                          # file references in the master HDF5
data       = Cpt(AsyncSignal, name="data", ndim=1, max_size=1000,             # saved to HDF5 per scan
                 async_update={"type": "add", "max_shape": [None, 4096]})
means      = Cpt(DynamicSignal, name="means", ndim=1, max_size=1000, signals=["ch1", "ch2"],
                 async_update={"type": "add", "max_shape": [None]})
```

`async_update["type"]`: `add` appends along axis 0, `add_slice` needs `index`, `replace`
overwrites. `AsyncMultiSignal` requires every sub-signal per update, `DynamicSignal` allows
partial updates. Async updates are dropped unless a scan is open, so buffer or skip data that
arrives before `stage`/after `unstage`. `readoutPriority: async` in the YAML tells the scan
server not to read the device per point. Catalogue: [references/bec-signals.md](references/bec-signals.md).

## 5. YAML entry, install, verify

```yaml
mydet:
  deviceClass: mybeamline_bec.devices.mydet.mydet.MyDetector
  deviceConfig: {prefix: "X99XA-ES-MYDET:", timeout: 10}
  readoutPriority: async          # monitored for point detectors that are read per point
  softwareTrigger: true           # scan server calls trigger()
  onFailure: raise
  enabled: true
  deviceTags: [detectors]
```

1. Put the class in `<plugin>/<plugin>/devices/<mydet>/mydet.py` (+ `<mydet>_enums.py` for PV
   state constants); import it in `devices/__init__.py` if the plugin re-exports devices.
2. `ophyd_test --config <config>.yaml` must instantiate it offline; with hardware,
   `ophyd_test --connect`.
3. Load with `bec.config.add_to_session(...)`, then in the client: `dev.mydet.summary()`,
   `dev.mydet.read()`, `scans.line_scan(dev.samx, -1, 1, steps=3, exp_time=0.1, relative=False)`
   with `mydet` monitored/async, and check `bec.queue`/alarms for `DeviceStoppedError` or
   status timeouts (they name the status `description` and creation line).

## 6. Tests

`ophyd_devices.tests.utils.patched_device(cls, *args, **kwargs)` gives a connected instance with
mock PVs (`MockPV`); `get_mock_scan_info(device)` / `fake_scan_status_msg(device)` fill
`scan_info` so `on_stage` can read `num_points` and `scan_parameters`. Test each hook: PV writes
performed (`device.exp_time.get()`), returned status type and completion when the mock PV is
poked, `stop()` failing registered statuses, `on_stop` idempotent, BEC signal `put` calls
(`device.data.put` with a spy), and constructor without hardware. Template:
[assets/test_template.py](assets/test_template.py). Run
`python -m pytest --random-order -q tests/tests_devices/test_mydet.py`.

## Deliverable checklist

- [ ] `class X(PSIDeviceBase, XControl)`; signals in the control class; imports from `ophyd_devices`
- [ ] `name`, `scan_info`, `device_manager` explicit keyword parameters; no I/O in `__init__`/`on_init`
- [ ] hooks return statuses for anything slow; all statuses `cancel_on_stop`; `on_stop` idempotent
- [ ] `scan_info.msg` used for exposure/points/type instead of duplicated scan kwargs
- [ ] BEC signals declared as `Cpt(...)`; no manual Redis writes; `readoutPriority` consistent
- [ ] `USER_ACCESS` lists user-callable methods; docstrings on hooks and public methods
- [ ] YAML entry provided and `ophyd_test` passes; tests with `patched_device` pass in random order
