# Qt / BEC widget defect classes

Every class below was found in bec_widgets in 2026 and reproduced on PySide6 6.11. Each entry says
where the defect hides (what to grep or read), how to prove it (which probe in
[../assets/probe_test_template.py](../assets/probe_test_template.py), or what to add), and the fix
that works on current bec_widgets without unreleased helpers. Destruction paths and what
`BECWidget.cleanup()` already does are in [lifecycle.md](lifecycle.md).

Severity guide: **crash** (SIGSEGV/SIGBUS, abort) > **callback into a dead or closed widget**
(`RuntimeError: Internal C++ object ... already deleted`, slots running after close) > **leak**
(timers ticking, subscriptions, threads, top-level windows left behind) > **wrong behaviour**.

## C1. Owned resource not released in `cleanup()`

- **Where**: `QTimer(`, `QThread`, `QThreadPool(`, `threading.Thread`, `.subscribe(`,
  `callbacks.register(`, `installEventFilter(`, `setOverrideCursor(`, `QApplication.instance().`
  signal connections. Match each to a release in `cleanup()`; `cleanup()` must end with
  `super().cleanup()`.
- **Prove**: `test_close_stops_timers_and_signal_proxies`, the autouse leak check
  (`Failed to stop all timers`, `threads_check`), `test_create_close_cycle_returns_to_baseline`.
  For ophyd/bec_lib callbacks, assert the subscription count on the fake device after close.
- **Fix**: release exactly what the widget created. A widget-owned `QThreadPool` waits for running
  tasks in its destructor and freezes the GUI on close: clear the queue and stop feeding it in
  `cleanup()`, or use `self.submit_task`, which runs on the global pool.

## C2. Teardown that runs on the wrong path or twice

- **Where**: teardown code in `closeEvent`, `__del__`, `hideEvent` or a `destroyed` handler instead
  of `cleanup()`; `cleanup()` without `super().cleanup()`; `cleanup()` that raises when called on a
  half-built widget (constructor failed half-way) or a second time.
- **Prove**: `test_cleanup_runs_exactly_once`; construct with a failing dependency
  (monkeypatch) and close.
- **Fix**: all teardown in `cleanup()`, guarded so it is idempotent (`if self._timer is not None`).

## C3. Deleted through a plain Qt parent - `cleanup()` never runs

- **Where**: BEC widgets placed in a plain `QWidget`/`QFrame`/`QSplitter` container that is later
  deleted (`deleteLater()` on the container, C++ parent destruction). Only the `destroyed` hook
  runs: RPC entry and dead dispatcher slots are purged, nothing else.
- **Prove**: `test_delete_through_plain_qt_parent` - it reports running timers and top-level
  windows (menus, popups) that only `cleanup()` would have closed. pyqtgraph-based widgets leave
  their `ViewBoxMenu`/`QMenu` windows behind on main.
- **Fix**: give BEC widgets a `BECWidget` parent (its `cleanup()` closes child BEC widgets), or
  close them explicitly before deleting the container. Resources that must die with the widget
  even on this path need a Qt parent (`QTimer(self)`), not just a Python attribute.

## C4. Deferred calls into closed or deleted widgets

- **Where**: `QTimer.singleShot(ms, callable)` with a lambda, a partial or a bound method;
  `QMetaObject.invokeMethod(..., Qt.QueuedConnection)`; queued signal connections to objects that
  can die first; retry loops that re-arm themselves (`singleShot(0, self.apply)` while a splitter
  has no size spins the GUI thread).
- **Prove**: close (or delete the target, e.g. remove a dock) right after the call is scheduled,
  wait longer than the delay, and assert the callback did not run / no `already deleted` error.
  `SafeSlot` swallows the exception, so assert on a recorded call or on logged errors.
- **Fix**: `QTimer.singleShot(ms, self, callback)` drops the call when `self` is *deleted*, but a
  closed widget is not deleted yet: either check `self._destroyed` first thing in the callback, or
  use a single-shot `QTimer(self)` stored on the widget and stopped in `cleanup()`. For objects you
  do not own (a splitter, a dock), check `shiboken6.isValid(obj)` before touching them. Bound
  retry loops with a counter.

## C5. Signal proxies keep delivering after close

- **Where**: `pg.SignalProxy` / `BECSignalProxy` attributes. `SignalProxy.disconnect()` only sets
  `blockSignal`; with an emission queued, its delivery timer keeps ticking (`flush()` returns early
  and never stops it) and the queued `args` survive. `BECSignalProxy.cleanup()` stops only its own
  watchdog timer. pyqtgraph creates its timers outside `qtpy`, so the autouse timer check cannot
  see them.
- **Prove**: `test_close_stops_timers_and_signal_proxies` (state left behind) and
  `test_no_queued_update_runs_after_close` (slot ran after close) - list every signal that feeds a
  proxy in `PENDING_UPDATES`.
- **Fix** in `cleanup()`, for each proxy: `proxy.disconnect()`, `proxy.timer.stop()`,
  `proxy.args = None` (plus `proxy.cleanup()` for a `BECSignalProxy`), before
  `super().cleanup()`.

## C6. Dispatcher subscriptions

- **Where**: `connect_slot` with a lambda/partial and no `owner=` (logs "the callable has no
  owner"); scan-scoped endpoints (`device_async_signal(scan_id, ...)`, DAP responses) not swapped
  when the next scan starts; `self.sender()` inside a dispatcher slot; dispatcher slots without
  `@SafeSlot(dict, dict)`.
- **Prove**: `test_close_releases_dispatcher_slots_and_rpc_entry`; for scan-scoped endpoints, run
  two scans through the slots (`create_dummy_scan_item`) and count the owned subscriptions.
- **Fix**: bound methods or `owner=self`; keep the current endpoint in an attribute and
  `disconnect_slot` it when re-targeting; per-subscription context via `cb_info`.

## C7. Qt objects touched from another thread

- **Where**: widget, item or pyqtgraph calls inside `submit_task` functions, `QThread.run`,
  `threading.Thread` targets, ophyd/bec_lib callbacks (they run on client threads, not the GUI
  thread); `on_failed`/`on_complete` connected after `submit_task` returned.
- **Prove**: hard to make deterministic; assert `QThread.currentThread() is app.thread()` inside the
  touched method under a test that drives the callback from its real thread, and run the scenario
  in `run_isolated` with faulthandler.
- **Fix**: workers return plain data; apply it in a slot on the GUI thread (signal, or
  `submit_task(..., on_complete=slot)`); pass callbacks in the `submit_task` call itself.

## C8. BEC widgets inside item-view cells

- **Where**: `setCellWidget`, `setItemWidget`, `setIndexWidget` with a BEC widget (buttons in
  queue/history tables). The parent's `BECWidget.cleanup()` closes and deletes every child BEC
  widget, but the view keeps raw pointers to its cell widgets; the next layout pass segfaults in
  `QAbstractItemView::updateEditorGeometries`.
- **Prove**: in `run_isolated`: fill the view, `close()` the owner, flush deferred deletes, call
  `view.updateEditorGeometries()` (or resize the window) - main returns `rc=-11` for such widgets.
- **Fix**: in the owner's `cleanup()`, remove the rows or cell widgets
  (`table.setRowCount(0)`, `removeCellWidget`) before `super().cleanup()`.

## C9. Singletons and module-level state

- **Where**: module globals or class attributes holding widgets or `QObject`s; singletons parented
  to the first window (they die with it and later windows reuse a deleted object); singletons whose
  `__init__` can fail half-way (a Redis subscription) and leave an instance that refuses to
  initialise again.
- **Prove**: create window A, close and delete it, create window B, use the singleton; for the
  half-init case make the failing call raise once (monkeypatch) and construct twice.
- **Fix**: parent singletons to `QApplication.instance()` or nothing; on a failing `__init__`
  reset the singleton before re-raising; never keep widgets in module state (use `weakref`).

## C10. Signal connections Qt silently ignores

- **Where**: `connect(callable, Qt.ConnectionType.UniqueConnection)` with a plain Python function,
  lambda or partial - PySide6 returns an invalid connection, logs "unique connections require a
  pointer to member function of a QObject subclass", and the slot never runs (e.g. an
  `aboutToQuit` cleanup that never happens). Connections to application-wide signals that are never
  disconnected keep the widget's method alive after close.
- **Prove**: assert `signal.receivers(...)`/the side effect after emitting; `app.aboutToQuit.emit()`
  in a test.
- **Fix**: UniqueConnection only with a bound slot of a `QObject`; otherwise a normal connection
  plus a Python-side guard. Long-lived application signals through `SafeConnect` or an explicit
  disconnect in `cleanup()`.

## C11. Item models that break Qt's model contract

- **Where**: `QAbstractItemModel` / `QAbstractTableModel` subclasses that mutate their backing
  data without `beginInsertRows`/`endInsertRows` (remove/reset likewise), table models whose
  `rowCount(parent)` is non-zero for a valid parent; row lookups through `self.sender()` or a
  stored row index that is stale after a removal (acting on the wrong row).
- **Prove**: `QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Fatal)`
  from `qtpy.QtTest` while the test mutates the model; for row lookups, remove a row above and act
  on the one below.
- **Fix**: wrap every mutation in the begin/end pair; return 0 rows/columns for a valid parent in
  flat models; find the row from the item or a persistent index at click time.

## C12. Lifetime of objects the widget points at

- **Where**: editors, inspectors and delegates holding a reference to another widget or device
  object that can be deleted first (property editors, settings panels bound to a plot item).
- **Prove**: delete the target while the editor is open, then interact with the editor.
- **Fix**: connect `target.destroyed` to a slot that disables the editor and drops the reference;
  check `shiboken6.isValid(target)` before use.

## C13. Crashes at interpreter exit

- **Where**: Python subclasses of `QIconEngine` and other Qt value objects ending up in cyclic
  garbage; `QPixmap`/`QImage`/`QIcon` created before the `QApplication` exists or after it is gone;
  global Qt objects destroyed after `QApplication`.
- **Prove**: `test_teardown_and_exit_do_not_crash` (show, close, delete, `gc.collect()`, normal
  interpreter exit in a child process). Run it several times: the crash depends on GC order.
- **Fix**: break reference cycles that hold Qt value objects (icons, pixmaps, icon engines),
  create them after the `QApplication`, and keep no module-level Python references to them. When
  the crash sits in a library (an icon engine from the theme package), report it there.
