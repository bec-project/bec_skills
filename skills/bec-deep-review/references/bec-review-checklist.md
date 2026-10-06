# BEC review checklist - failure modes worth hunting for

Use this to sharpen the finder angles; do not turn it into a grep list across the repo. Every
line names a concrete defect class, where it hides, and how to confirm it.

## bec_widgets (Qt / PySide6 via qtpy)

- **Cleanup contract**: subclass `cleanup()` must end with `super().cleanup()`; every `QTimer`,
  `QThread`, `pg.SignalProxy`, `BECSignalProxy`, dialog, event filter and ophyd/bec_lib callback
  created by the widget must be stopped/disconnected there. Confirm by grepping the class for
  `QTimer(`, `QThread`, `SignalProxy`, `subscribe(`, `installEventFilter(` and matching them to
  `cleanup()`. A missing stop shows up in tests as `Failed to stop all timers` / `threads_check`.
- **MRO / ctor**: `class X(BECWidget, QWidget)`; `parent` is the first parameter and passed as
  `parent=parent` in one `super().__init__` call; `theme_update`/`parent_dock` kwargs no longer exist.
- **Slots**: any method connected to a signal or registered with the dispatcher without
  `@SafeSlot` - an exception there kills the event loop. Dispatcher slots take `(content, metadata)`.
- **Dispatcher ownership**: `connect_slot` with a lambda/partial and no `owner=`; scan-scoped
  endpoints (`device_async_signal(scan_id, ...)`, `dap_response(f"{scan_id}-{gui_id}")`) not
  disconnected when the next scan starts (unbounded subscriptions).
- **Threads**: Qt objects touched from `submit_task` workers or `QThread.run`; `on_failed` connected
  after `submit_task` returned (misses fast failures); `QThread` without `quit()`/`wait()` in cleanup.
- **USER_ACCESS / RPC**: new public method not in `USER_ACCESS`; `USER_ACCESS` replaced instead of
  extended (`[*Base.USER_ACCESS, ...]`) so `remove/attach/detach` vanish; signature change without
  regenerating `bec_widgets/cli/client.py` (`bw-generate-cli --target ...`); hand edits in
  generated files (`client.py`, `designer_plugins.py`, `*_plugin.py`).
- **Toolbar**: `MaterialIconAction(...)` without `parent=`; `QToolBar.addAction` bypassing
  `ToolbarComponents`; `bundle.bundle_actions` weakrefs dereferenced without a `None` check;
  `WidgetAction` widgets not closed by the owner.
- **pyqtgraph**: `plot_item.clear()` (destroys crosshair items); items removed without
  `rpc_register.remove_rpc(item)`; `ImageItem` dropped without `removeItem → remove(emit=False) → deleteLater()`;
  per-update `addItem`/`removeItem` instead of `setData`; per-point `pg.mkBrush`/Python loops on
  live data; dispatcher slot doing the redraw directly instead of `signal → SignalProxy(rateLimit)`.
- **Theme**: overriding `_update_theme` instead of `apply_theme`; hard-coded colours instead of
  `get_accent_colors()`; connecting to theme signals manually (base already does via `SafeConnect`).
- **Config models**: `ConnectionConfig` subclass fields without defaults; mutating `self.config`
  before `super().__init__`.
- **Imports**: `from PySide6...` (CI fails) - only `PySide6.QtDesigner`/`scripts` are exempt.
- **Tests**: widgets created without `create_widget`/`qtbot.addWidget`; dialogs opened and not
  closed; order-dependent fixtures (`--random-order` is how CI runs); assertions on pixels
  instead of `setData` spies; missing lifecycle test for new cleanup logic; fixtures copied or
  imported from test modules (`tests.unit_tests...`, `.conftest`) instead of the packaged
  `bec_widgets.tests` ones; a new shared fixture added to a conftest instead of
  `bec_widgets/tests/fixtures.py` (and to its `__all__`, or the conftest star import skips it).
  In a beamline plugin repo: widget tests that stub the widget to avoid the BEC client, or a
  `tests/tests_bec_widgets/` without the conftest star import of `bec_widgets.tests.fixtures`.

## bec_lib / bec_server (client, scan server, device server, file writer)

- **Scan API version**: new scans must use v4 `ScanBase` from `scans/scan_base.py` (ten
  `@scan_hook` methods, `self.actions`/`self.components`); `yield from self.stubs...`,
  `required_kwargs`, `pre_move`, `ScanArgType` are legacy and must not appear in new code.
- **Statuses**: `self.actions.*(wait=False)` results never `.wait()`-ed/`.done`-checked;
  `close_scan` without `check_for_unchecked_statuses()`; `self.actions.*` called in `__init__`
  (raises `@requires_scan_is_running` / blocked RPC) instead of `prepare_scan`.
- **Positions/metadata**: `positions` not `(num_points, num_motors)`; `num_monitored_readouts`
  not multiplied by `burst_at_each_point`; step-scanned motors not elevated with
  `set_device_readout_priority(..., "monitored")`; `scan_type` lying about who triggers.
- **Abortability**: `time.sleep(total_duration)` in `scan_core` instead of polling `status.done`;
  `on_exception` that can raise; relative scans not moving back in `post_scan`/`on_exception`.
- **Arguments**: untyped `__init__` params (no `Annotated[..., ScanArgument]`/`DefaultArgType`);
  `gui_config` listing names that are not parameters; docstring without `Examples:`; `scan_name`
  not an identifier or duplicated; class not exported from `scans/__init__.py`.
- **Messaging**: wrong `MessageEndpoints.*` factory or operation (`send` vs `set_and_publish`
  vs `xadd`); message models mutated after sending; `str`/`bytes` confusion on Redis keys;
  missing `expire` on per-scan keys; blocking Redis calls on callback threads.
- **Device server**: exceptions in device callbacks not converted to alarms; `onFailure`
  semantics bypassed; `construct_device_obj` signature rules (only named params get
  `deviceConfig` keys; `device_manager`/`scan_info` must be explicit).
- **Config**: `!include` used outside the wrapper-key/list form; duplicate device names across
  included files (last-wins silently); unknown schema keys (`connector`, `deviceType`).
- **Tests**: scan tests not using `v4_scan_assembler` + `scan_hook_tests`; hand-rolled device
  mocks where `DMMock`/`_MockDevice` exist; e2e behaviour asserted in unit tests.

## ophyd_devices / beamline device classes

- **Base class**: `PSIDetectorBase`, `CustomDetectorMixin`, `CustomPrepare`, `wait_for_signals`,
  `wait_with_status`, `on_check_scan_id`, `BecScaninfoMixin` - removed API; new devices derive
  from `PSIDeviceBase` (+ a plain control `Device`) and use `on_*` hooks.
- **Hooks**: blocking `time.sleep`/busy loops inside hooks instead of returning a status;
  statuses not registered with `cancel_on_stop` (stop leaves the scan hanging); `on_stop` not
  idempotent; `on_connected` logic in `on_init`/`__init__` (signals not connected yet); I/O in
  `__init__` (breaks `ophyd_test` and session rollback).
- **Constructor**: `device_manager`/`scan_info` hidden in `**kwargs`; `deviceConfig` keys that
  match neither a parameter nor an attribute (raise `DeviceConfigError` at load).
- **Data publishing**: manual `connector.xadd`/`_run_subs` instead of `Cpt(AsyncSignal|PreviewSignal|ProgressSignal|FileEventSignal)`;
  `AsyncMultiSignal` updates missing sub-signals; `max_shape` inconsistent with the data; async
  data expected outside an open scan.
- **Imports**: `from ophyd import DeviceStatus/StatusBase` where `ophyd_devices` re-exports the
  PSI versions with descriptions/timeout diagnostics.
- **Status objects**: `CompareStatus` on a signal without `auto_monitor` (never fires);
  `TransitionStatus(strict=True)` on a state machine that skips states; missing `description`.
- **Tests**: devices instantiated without `patched_device`/`patch_dual_pvs`; `scan_info` not
  faked (`get_mock_scan_info`); hook tests that never poke the mock PV to finish the status.

## Cross-cutting

- Conventional Commits title/type; black 100 cols + isort profile black; f-strings only; `pathlib`
  over string paths; docstrings on public API; Python 3.11+ syntax only where the repo allows it.
- Docs: user-visible behaviour changed without a `bec_docs` page/how-to update or a CHANGELOG
  entry where the repo keeps one; `USER_ACCESS` changes without regenerated client stubs.
- Memory: grow-only dicts keyed by `scan_id`/`request_id` in long-lived services or widgets;
  closures capturing large arrays kept alive by signals/timers.
