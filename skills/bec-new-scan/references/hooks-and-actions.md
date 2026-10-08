# v4 hooks, ScanActions, ScanComponents, statuses - and the legacy mapping

Source files (bec repo): `bec_server/bec_server/scan_server/scans/scan_base.py`,
`scan_actions.py`, `scan_components.py`, `scan_modifier.py`, `position_generators.py`,
`scan_status.py` (`ScanStatus`), `bec_server/bec_server/scan_server/direct_scan_worker.py`.

## Execution order (DirectScanWorker)

```python
SCAN_SEQUENCE = ["prepare_scan", "open_scan", "stage", "pre_scan",
                 "scan_core", "post_scan", "unstage", "close_scan"]
# on any exception: scan.on_exception(exc) if the queue allows the hook
```

`at_each_point` is not in the sequence; call it from `scan_core` so `ScanModifier` plugins can
hook it. A missing hook raises `ScanAbortion("Scan is missing required method: ...")`.

## ScanBase essentials

```python
class ScanBase(ABC):
    scan_type = ScanType.SOFTWARE_TRIGGERED      # or ScanType.HARDWARE_TRIGGERED
    scan_name = "base_scan"
    arg_input = {}                               # only for *args bundle scans
    arg_bundle_size = {"bundle": len(arg_input), "min": None, "max": None}
    is_scan = True
    is_internal = False                          # True hides it from the client
```

Instance attributes: `self.dev` (device container), `self.actions`, `self.components`,
`self.scan_info` (pydantic `ScanInfo`), `self.positions` (`np.ndarray`), `self.start_positions`,
`self.device_manager`, `self.redis_connector`.

`update_scan_info(num_points=, num_monitored_readouts=, positions=, exp_time=, frames_per_trigger=,
settling_time=, settling_time_after_trigger=, burst_at_each_point=, relative=,
run_on_exception_hook=, scan_report_devices=, monitored=, on_request=, **kwargs)` - unknown
kwargs go to `scan_info.additional_scan_parameters` and end up in the file metadata.

## ScanActions (`self.actions`) - plain calls, mostly returning `ScanStatus`

The device actions (stage, pre_scan, set, kickoff, complete, trigger, read, unstage) take
`wait=True` by default and return a `ScanStatus`; pass `wait=False` to get one you resolve later.
Exceptions: `read_manually(wait=True)` returns the readings (the status only with `wait=False`),
`rpc_call` returns the method's result (a status only when the device method returns one), and the
bookkeeping helpers (`open_scan`, `close_scan`, `add_scan_report_instruction_*`,
`set_device_readout_priority`, `check_for_unchecked_statuses`, the lock and `send_client_info`
helpers) take no `wait` and return no status.

| method | notes |
|---|---|
| `open_scan()` / `close_scan()` | mandatory in the hooks of the same name; `close_scan` records `num_monitored_readouts` and sends the closed status |
| `stage_all_devices(wait=True, exclude=None)` / `stage(device, wait=True)` | |
| `pre_scan_all_devices(wait=True, exclude=None)` / `pre_scan(device, wait=True)` | |
| `set(device | [devices], value | [values], wait=True)` | move positioners; list form moves several at once |
| `kickoff(device, parameters: dict | None = None, wait=True)` | hardware-triggered acquisition start |
| `complete(device, wait=True)` / `complete_all_devices(wait=True, exclude=None)` | |
| `trigger_all_devices(min_wait: float | None = None, wait=True)` | software trigger; `min_wait` = exposure x frames |
| `read_monitored_devices(wait=True)` | the normal readout; increments the point counter |
| `read_baseline_devices(wait=True)` | once per scan, in `prepare_scan` with `wait=False` |
| `read_manually(devices, wait=True)` / `publish_manual_read(readings, wait=True)` | rarely right; use monitored readouts |
| `unstage(device, wait=True)` / `unstage_all_devices(wait=True, exclude=None)` | |
| `add_scan_report_instruction_scan_progress(points=0, show_table=True)` | progress bar/table in the client |
| `add_scan_report_instruction_readback(devices, start, stop)` / `add_scan_report_instruction_device_progress(device)` | alternatives for fly scans |
| `set_device_readout_priority(devices, priority="monitored"|"baseline"|"on_request"|"async")` | allowed in `__init__`; use for step-scanned motors |
| `check_for_unchecked_statuses()` | call last in `close_scan`; raises a WARNING alarm for forgotten statuses and waits for them |
| `rpc_call(device, func_name, *args, **kwargs)` / `rpc_call_no_wait(...)` | arbitrary device method; blocked during `__init__` |
| `acquire_device_lock(device)` / `release_device_lock()` | exclusive device use across queues |
| `send_client_info(message)` | one-line message in the client console |

Most are decorated `@requires_scan_is_running` and raise `RuntimeError` when called before the
worker starts the scan - i.e. from `__init__`.

## ScanComponents (`self.components`) - building blocks

- `move_and_wait(motors, positions, last_positions=None)` - moves only motors whose position
  changed, waits for all.
- `trigger_and_read()` - settle, `trigger_all_devices(min_wait=exp_time*frames_per_trigger)`,
  settle after trigger, `read_monitored_devices()`.
- `step_scan(motors, positions, at_each_point=None, last_positions=None)` - loops points x
  `burst_at_each_point`, calling `at_each_point(motors, pos, last_positions=...)`.
- `step_scan_at_each_point(motors, pos, last_positions=None)` = `move_and_wait` + `trigger_and_read`.
- `get_start_positions(motors) -> list[float]` - current readbacks for `relative=True`.
- `optimize_trajectory(positions, optimization_type="corridor"|"shell"|"nearest", ...)`.
- `check_limits(motors, positions)` - raises `LimitError`.

Beamline plugins may subclass `ScanComponents` (`<plugin>/scans/scan_customization/`); the
generator wires `self.components = <PluginComponents>(self)` automatically. `ScanBase` itself
always creates a plain `ScanComponents`, so a hand-written plugin scan that needs the plugin's
components sets `self.components = <PluginComponents>(self)` right after `super().__init__()`.

## Position generators (`bec_server.scan_server.scans.position_generators`)

`line_scan_positions(axes, steps, endpoint=True)` with `axes` a list of `(start, stop)` pairs,
`nd_grid_positions(...)`, `fermat_spiral_pos(...)`, `spiral_positions(...)`,
`log_scan_positions(...)`, `round_scan_positions(...)`, `get_round_roi_scan_positions(...)`,
`hex_grid_2d(...)`, `multi_region_line_positions(...)`, `multi_region_grid_positions(...)`,
`Direction` enum. These return `np.ndarray` shaped `(num_points, num_motors)`. The exception is
`oscillating_positions(values, repeat_turning_points=False)`: an endless iterator of scalars going
back and forth over `values`, for open-ended scans that stop on a condition, not a position
matrix.

## ScanStatus

`bec_server/scan_server/scans/scan_status.py` (called `ScanStubStatus` in `scan_stubs.py` before bec 4).

`.wait(min_wait=None, timeout=np.inf)` raises `DeviceInstructionError` when the device call
failed. On timeout it raises `TimeoutError` up to bec 4.1.4; bec#1118 changes it to return `False`
(and `True` on success). Code that must stop on a timeout works with both:

```python
if not status.wait(timeout=5):          # bec#1118: False on timeout
    raise ScanAbortion("kickoff of the DAQ timed out")   # bec_server.scan_server.errors
```

With bec#1118, `False` also means "an abort was requested": `wait()` then returns `False` at once,
without blocking, on every call. The check above still does the right thing (the scan aborts),
but a polling loop must end on `.done`, which is `True` after an abort:

```python
while not complete_status.done:                   # not: while not complete_status.wait(timeout=0.5)
    self.actions.read_monitored_devices()
    time.sleep(0.1)                               # not wait(timeout=...): it raises before bec#1118
```

`.done` (property; reading it marks the status as checked; `True` once an abort was requested),
`.result`. Container statuses aggregate sub-statuses (e.g. `stage_all_devices`). A status that is
never waited on or checked is reported by `check_for_unchecked_statuses()`.

## Scan modifiers

`@scan_hook` wraps each hook so the single `ScanModifier` plugin of the beamline
(entry point `bec.scans.scan_modifier`, usually
`<plugin>/scans/scan_customization/scan_modifier.py`) can register
`@scan_hook_impl("<hook>", "before"|"after"|"replace", scan_names=[...])` methods; `scan_names`
(shell-style patterns such as `"*_line_scan"`) limits a method to some scans, default is every
scan, core and plugin. Inside a modifier, `self.scan`, `self.dev`, `self.actions`,
`self.components` and `self.scan_info` are the running scan's; `self.call_original("<hook>", ...)`
runs the scan's own hook from a `"replace"`; `self.device_is_available(...)` guards beamline
devices. `scan_signature_overrides(scan_name, arguments, defaults)` changes defaults or adds
arguments (extra ones land in `additional_scan_parameters`). This is the plugin-side way to change
a core scan for one beamline.

Keep your hooks small and delegate to helpers so a modifier can replace one hook without
re-implementing your whole scan.

## Porting a legacy generator scan

| legacy (`legacy_scans.py` / `ScanStubs`, removed in bec 4) | v4 |
|---|---|
| `class X(ScanBase)` from `legacy_scans` / `SyncFlyScanBase` / `AsyncFlyScanBase` | `class X(ScanBase)` from `scans.scan_base`; `scan_type` by who triggers, not by "fly" |
| `scan_type = "step"` / `"fly"` | `SOFTWARE_TRIGGERED` when the scan triggers/reads each point (also software-managed fly scans such as core `ContLineScan`); `HARDWARE_TRIGGERED` when a kicked-off device runs the acquisition |
| `required_kwargs`, `ScanArgType.*` in `arg_input` | params without default (positional or keyword-only); real types / `Annotated[..., ScanArgument]` |
| `pre_move`, `return_to_start_after_abort`, `use_scan_progress_report`, `scan_report_hint` | explicit code: pre-move `set(wait=False)` in `prepare_scan`; move back in `post_scan`/`on_exception`; `add_scan_report_instruction_*` |
| `initialize`, `read_scan_motors`, `_set_position_offset`, `prepare_positions`, `_calculate_positions`, `_check_limits`, `_optimize_trajectory` | all inside `prepare_scan` using `position_generators`, `components.get_start_positions`, `components.check_limits`, `components.optimize_trajectory` |
| `run_baseline_reading` | `self.actions.read_baseline_devices(wait=False)` in `prepare_scan`, waited in `close_scan` |
| `finalize`, `cleanup` | `post_scan`, `close_scan` |
| `yield from self.stubs.open_scan()` etc. | `self.actions.open_scan()` etc. |
| `yield from self.stubs.set(device=, value=, wait_group=)` + `wait(wait_type="move")` | `status = self.actions.set(dev, val, wait=False)`; `status.wait()` |
| `yield from self.stubs.trigger(group="trigger", point_id=self.point_id)` | `self.actions.trigger_all_devices(min_wait=...)` |
| `yield from self.stubs.read(group="monitored", point_id=...)` | `self.actions.read_monitored_devices()` |
| `yield from self.stubs.kickoff(device=)` / `complete(device=)` | `self.actions.kickoff(device=, wait=False)` / `.complete(device=, wait=False)` and poll `.done` |
| `yield from self.stubs.send_rpc_and_wait(device, method, ...)` | `self.actions.rpc_call(device, method, ...)` |
| `self.stubs.scan_report_instruction({...})` | `self.actions.add_scan_report_instruction_*` |
| `self.metadata[...]`, `self.num_pos`, `self.exp_time` class attrs | `self.update_scan_info(...)` / `self.scan_info.*` |
| `ScanStubStatus` (`scan_stubs.py`) | `ScanStatus` (`scans/scan_status.py`) |
| `v4_scan_assembler` test fixture (deprecated alias since bec 4.0) | `scan_assembler` |
