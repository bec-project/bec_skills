# PSIDeviceBase hooks, wrapper semantics, status objects, legacy mapping

Source: `ophyd_devices/ophyd_devices/interfaces/base_classes/psi_device_base.py`,
`ophyd_devices/ophyd_devices/utils/psi_device_base_utils.py`,
`ophyd_devices/ophyd_devices/interfaces/base_classes/psi_positioner_base.py`,
`bec_server/device_server/device_server.py` (`_trigger_device`, `_kickoff_device`,
`_complete_device`, `_stage_device`, `_pre_scan`), `devices/devicemanager.py`
(`construct_device_obj`, `initialize_enabled_device`).

## Hooks (all optional to override; default is no-op)

```python
def on_init(self) -> None                 # end of __init__; NO signals connected yet
def on_connected(self) -> None            # after connect; set signal defaults, subscribe callbacks
def on_stage(self) -> StatusBase | None   # scan_info.msg describes the upcoming scan
def on_unstage(self) -> StatusBase | None
def on_pre_scan(self) -> StatusBase | None  # right before scan_core on all devices
def on_trigger(self) -> StatusBase | None   # software trigger per point
def on_kickoff(self) -> StatusBase | None   # hardware-triggered start (called explicitly by the scan)
def on_complete(self) -> StatusBase | None  # "is acquisition finished?"; return a status that finishes when it is
def on_stop(self) -> None                   # abort; must be idempotent and fast
def on_destroy(self) -> None                # session teardown; release callbacks/sockets
```

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
interval=0.05) -> bool` (raises `DeviceStoppedError` when stopped and `check_stopped=True`),
`self.task_handler` (`TaskHandler`), `self.file_utils.get_full_path(scan_status_msg, name, create_dir=True)`,
`self.scan_info.msg` (`ScanStatusMessage`: `scan_id`, `scan_name`, `scan_type`, `num_points`,
`scan_parameters` incl. `exp_time`, `frames_per_trigger`, `readout_time`, `positions`, ...).

## Status objects (ophyd_devices.utils.psi_device_base_utils)

| class | use |
|---|---|
| `DeviceStatus(device, *, timeout=None, settle_time=0, description=None)` | manual: `status.set_finished()` / `set_exception(exc)` from a callback |
| `CompareStatus(signal, value, *, operation_success="==", failure_value=None, operation_failure="==", timeout=None, settle_time=0, description=None)` | finishes when `signal` compares true; fails when it equals `failure_value`; ops `== != < <= > >=` |
| `TransitionStatus(signal, transitions=[...], *, strict=True, failure_states=None, timeout=None, description=None)` | finishes when the signal walks through the states in order (`strict=False` allows skipping) |
| `SubscriptionStatus(obj, callback, event_type=None, timeout=None, settle_time=None, run=True, description=None)` | arbitrary predicate on subscription callbacks |
| `ExceptionStatus(CompareStatus)` | comparison that raises a custom exception |
| `AndStatus(a, b)` | both |
| `TaskStatus` (from `task_handler.submit_task(fn, task_args=(), task_kwargs={}, run=True)`) | thread-backed; `.state` in `TaskState` (`not_started/running/timeout/error/completed/killed`); `task_handler.kill_task(status)`, `shutdown()` |
| `MoveStatus`, `Status`, `StatusBase` | re-exports of ophyd with descriptions |

All PSI statuses accept `description=`; a timeout reports it together with the line where the
status was created (`StatusTimeoutErrorWithErrorInfo`), which is what the operator sees in the
alarm - write descriptions like `"waiting for Eiger to arm"`.

Pattern with retry (from a real DAQ device):

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
| `CustomDetectorMixin.on_stage/on_trigger/...` | same names on the device class |
| `custom_prepare.wait_for_signals(signal_conditions, timeout, check_stopped, all_signals)` | `wait_for_condition(lambda: ..., timeout, check_stopped=True)` or a `CompareStatus`/`TransitionStatus` returned from the hook |
| `wait_with_status(...)` | return the status from the hook; register with `cancel_on_stop` |
| `on_check_scan_id` | not needed; `scan_info.msg.scan_id` is current at `on_stage` |
| `BecScaninfoMixin` / `scaninfo.scan_msg` | `self.scan_info.msg` (injected `ScanInfo` dataclass) |
| `self._run_subs(sub_type=self.SUB_DEVICE_MONITOR_2D, value=img)` | `self.preview.put(img)` on a `Cpt(PreviewSignal, ndim=2)` |
| `self._run_subs(sub_type="progress", value=, max_value=, done=)` | `self.progress.put(value=, max_value=, done=)` on a `Cpt(ProgressSignal)` |
| `self._run_subs(sub_type="file_event", ...)` / `FileEventMessage` by hand | `self.file_event.put(file_path=, done=, successful=, hinted_h5_entries=)` |
| `DeviceMessage` + `connector.xadd(device_async_readback(...))` with `async_update` metadata | `Cpt(AsyncSignal, ndim=, max_size=, async_update={...})` + `.put(array)` |
| `SUB_DEVICE_MONITOR_1D/2D` subscriptions | `PreviewSignal(ndim=1|2)` |
| `USER_ACCESS` | unchanged: list of method names exposed via RPC |
