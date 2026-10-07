# PSIDeviceBase hooks, wrapper semantics, status objects, legacy mapping

Source: `ophyd_devices/ophyd_devices/interfaces/base_classes/psi_device_base.py`,
`ophyd_devices/ophyd_devices/utils/psi_device_base_utils.py`,
`ophyd_devices/ophyd_devices/interfaces/base_classes/psi_positioner_base.py`,
`bec_server/device_server/device_server.py` (`_trigger_device`, `_kickoff_device`,
`_complete_device`, `_stage_device`, `_pre_scan`), `devices/devicemanager.py`
(`construct_device_obj`, `initialize_enabled_device`).

## Hooks (all optional to override; default is no-op)

Base-class order - keep it when you copy the "Beamline Specific Implementations" section:

```python
def on_init(self) -> None                 # end of __init__; NO signals connected yet, no device I/O
def on_connected(self) -> None            # called by the device server after connect; set defaults, subscribe callbacks
def on_stage(self) -> DeviceStatus | StatusBase | None    # scan_info.msg describes the upcoming scan
def on_unstage(self) -> DeviceStatus | StatusBase | None
def on_pre_scan(self) -> DeviceStatus | StatusBase | None  # right before scan_core on all devices
def on_trigger(self) -> DeviceStatus | StatusBase | None   # software trigger per point
def on_complete(self) -> DeviceStatus | StatusBase | None  # "is acquisition finished?"; return a status that finishes when it is
def on_kickoff(self) -> DeviceStatus | StatusBase | None   # hardware-triggered start (called explicitly by the scan)
def on_stop(self) -> None                   # abort the hardware; must be safe to call repeatedly
def on_destroy(self) -> None                # session teardown; release callbacks/threads/sockets
```

`on_connected` is not called by plain instantiation, `patched_device` or `ophyd_test`; call it
explicitly in tests that rely on it.

Wrapper behaviour in `PSIDeviceBase`:

- `stage()`: if already staged returns `super().stage()`; else `stopped = False`, `super().stage()`,
  `on_stage()`; returns the hook's status if any, else ophyd's staged list. The device server
  auto-unstages a device that is still staged from a previous scan (timeout 10 s).
- `unstage()`: `super().unstage()`, `on_unstage()`, then fails all registered stoppable statuses.
- `trigger()`: `super().trigger()` then `on_trigger()`; hook status wins.
- `kickoff()` / `complete()`: hook status, else an already-finished `DeviceStatus`. The device
  server calls `kickoff(metadata=..., **parameters)` only if your `kickoff` signature takes
  arguments; otherwise it calls `configure(parameters)` then `kickoff()`. It warns if `complete`
  does not return a `StatusBase`.
- `pre_scan()` is called only if the object has the attribute; PSIDeviceBase provides it.
- `stop(*, success=False)`: `on_stop()`, `stopped = True`, cancel registered statuses (`DeviceStoppedError`), `super().stop()`.
- `destroy()`: `on_destroy()`, cancel statuses, `task_handler.shutdown()`, `super().destroy()`.
- Properties: `staged`, `stopped` (settable), `destroyed`.

Helpers: `cancel_on_stop(status)`, `wait_for_condition(condition, timeout, check_stopped=False,
interval=0.05) -> bool` (raises `DeviceStoppedError` when stopped and `check_stopped=True`; it
blocks the caller, so only use it in `on_connected` or inside a `task_handler` task, never in the
scan hooks),
`self.task_handler` (`TaskHandler`), `self.file_utils.get_full_path(scan_status_msg, name, create_dir=True)`,
`self.scan_info.msg` (`ScanStatusMessage`: `scan_id`, `scan_name`, `scan_type`, `num_points`,
`scan_parameters` incl. `exp_time`, `frames_per_trigger`, `readout_time`, `positions`, ...).

## Status objects (import from `ophyd_devices.utils.psi_device_base_utils`)

| class | use |
|---|---|
| `DeviceStatus(device, *, timeout=None, settle_time=0, description=None)` | manual: `status.set_finished()` / `set_exception(exc)` from a callback |
| `CompareStatus(signal, value, *, operation_success="==", failure_value=None, operation_failure="==", timeout=None, settle_time=0, description=None)` | finishes when `signal` compares true; fails when it equals `failure_value`; ops `== != < <= > >=` |
| `TransitionStatus(signal, transitions=[...], *, strict=True, failure_states=None, timeout=None, description=None)` | finishes when the signal walks through the states in order (`strict=False` allows skipping) |
| `SubscriptionStatus(obj, callback, event_type=None, timeout=None, settle_time=None, run=True, description=None)` | arbitrary predicate on subscription callbacks |
| `ExceptionStatus(CompareStatus)` | comparison that raises a custom exception |
| `AndStatus(a, b)` / `a & b` | finishes when both finish, fails with the first failure. Keep a PSI status leftmost: `ophyd_status & psi_status` builds ophyd's `AndStatus` without the PSI diagnostics. No OR status exists; use `failure_value` / `failure_states` for alternative outcomes |
| `TaskStatus` (from `task_handler.submit_task(fn, task_args=(), task_kwargs={}, run=True)`) | thread-backed, for work with no PV to subscribe to (socket or vendor-SDK polling), not for EPICS devices; `.state` in `TaskState` (`not_started/running/timeout/error/completed/killed`); `task_handler.kill_task(status)`, `shutdown()`. `destroy()` kills running tasks, `stop()` only if `on_stop()` calls `shutdown()` |
| `MoveStatus`, `Status`, `StatusBase` | re-exports of ophyd with descriptions |

All PSI statuses accept `description=`; a timeout reports it together with the line where the
status was created (`StatusTimeoutErrorWithErrorInfo`), which is what the operator sees in the
alarm - write descriptions like `"waiting for Eiger to arm"`.

Composing writes and readiness in a scan hook (EPICS: the subscriptions complete the statuses,
no task handler, nothing blocks):

```python
config = AndStatus(self.num_images.set(n_frames), self.exp_time.set(exp_time))  # set(), not put()
self.arm_cmd.put(1)                       # command; its effect is confirmed by the state below
status = CompareStatus(self.state, DetectorState.ARMED, failure_value=DetectorState.ERROR,
                       timeout=self._timeout, description=f"{self.name}: arming") & config
self.cancel_on_stop(status)
return status
```

Pattern with retry in `on_connected` (from a real DAQ device; blocking is acceptable there,
not in the scan hooks):

```python
status = TransitionStatus(self.heartbeat, transitions=[0, 1], strict=False)
self.cancel_on_stop(status)
try:
    status.wait(timeout=self._timeout)
except WaitTimeoutError:
    self.power.put(1)
    status = TransitionStatus(self.heartbeat, transitions=[0, 1], strict=False)
    self.cancel_on_stop(status)
    status.wait(timeout=self._timeout)
```

## Positioners

`PSISimplePositionerBase(ABC, PSIDeviceBase, PositionerBase)`: declare `user_readback = Cpt(EpicsSignalRO, ...)`,
`user_setpoint = Cpt(EpicsSignal, ...)`; optional `velocity`, `motor_stop`, `motor_done_move`;
class knobs `stop_value = 1`, `done_value = 1`, `use_put_complete = False`; ctor
`(prefix="", *, name, limits=None, deadband=None, override_suffixes={}, **kwargs)`. Implements
`move(position, wait=True, timeout=None, moved_cb=None)`, `check_value`, `moving`, `limits`,
`egu`, `stop`. `PSIPositionerBase` adds the motor-record signal set (`user_offset`, `acceleration`,
`motor_egu`, `high/low_limit_switch`, `high/low_limit_travel`, homing, ...) and propagates `limits`.
`PSIPseudoMotorBase(ABC, PSIDeviceBase, PositionerBase)`: implement `forward_calculation(*args) -> float`,
`inverse_calculation(position, **positioner_objects) -> dict[str, float]`, `motors_are_moving(*args) -> int`;
real devices are handed in through `device_mapping` (YAML) and `set_positioner_objects`.

Protocol checklists: `ophyd_devices/interfaces/protocols/bec_protocols.py`
(`BECDeviceProtocol`, `BECPositionerProtocol`, `BECFlyerProtocol`, `BECSignalProtocol`).

## Legacy → current

| legacy | current |
|---|---|
| `PSIDetectorBase` + `custom_prepare_cls = MyPrepare(CustomDetectorMixin)` | `class My(PSIDeviceBase, MyControl)` with `on_*` hooks on the class itself |
| `CustomDetectorMixin.on_stage/on_trigger/...` | same names on the device class, inside the copied "Beamline Specific Implementations" section |
| `custom_prepare.wait_for_signals(signal_conditions, timeout, check_stopped, all_signals)` | in scan hooks: a `CompareStatus`/`TransitionStatus` returned from the hook; in `on_connected` or a task: `wait_for_condition(lambda: ..., timeout, check_stopped=True)` |
| `wait_with_status(...)` | return the status from the hook; register with `cancel_on_stop` |
| `on_check_scan_id` | not needed; `scan_info.msg.scan_id` is current at `on_stage` |
| `BecScaninfoMixin` / `scaninfo.scan_msg` | `self.scan_info.msg` (injected `ScanInfo` dataclass) |
| `self._run_subs(sub_type=self.SUB_DEVICE_MONITOR_2D, value=img)` | `self.preview.put(img)` on a `Cpt(PreviewSignal, ndim=2)` |
| `self._run_subs(sub_type="progress", value=, max_value=, done=)` | `self.progress.put(value=, max_value=, done=)` on a `Cpt(ProgressSignal)` |
| `self._run_subs(sub_type="file_event", ...)` / `FileEventMessage` by hand | `self.file_event.put(file_path=, done=, successful=, hinted_h5_entries=)` |
| `DeviceMessage` + `connector.xadd(device_async_readback(...))` with `async_update` metadata | `Cpt(AsyncSignal, ndim=, max_size=, async_update={...})` + `.put(array)` |
| `SUB_DEVICE_MONITOR_1D/2D` subscriptions | `PreviewSignal(ndim=1|2)` |
| `USER_ACCESS` | unchanged: list of method names exposed via RPC |
