# Widget lifecycle, leaks and segfaults

Sources: `bec_widgets/utils/bec_widget.py`, `bec_widgets/utils/bec_connector.py`,
`bec_widgets/utils/bec_dispatcher.py`, `bec_widgets/utils/error_popups.py`,
`bec_widgets/CLEANUP_AUDIT.MD`, `tests/unit_tests/test_bec_widget_lifecycle.py`.

## What BECWidget gives you

`BECConnector.__init__` creates `self.client`, `self.bec_dispatcher` (singleton), `self.rpc_register`,
`self.config` (`ConnectionConfig`), `self.gui_id`, `self.object_name`, `self.error_utility`,
`self._thread_pool = QThreadPool.globalInstance()`, `self._workers`. `BECWidget.__init__` adds the
busy overlay, connects the theme signal through a weak `SafeConnect`, and hooks
`self.destroyed` to a registry purge keyed by `gui_id`.

Constructor kwargs: `client`, `config`, `gui_id`, `object_name` (sanitised, unique among siblings),
`root_widget` (top-level in the RPC namespace), `rpc_exposed` (False keeps it out of the registry),
`rpc_passthrough_children`, `start_busy`. `parent` is popped and passed to Qt.
The old `theme_update` / `parent_dock` kwargs no longer exist.

## The three destruction paths

```python
def closeEvent(self, event):          # user closes / dock closes / qtbot.addWidget teardown
    if not self._destroyed: self._destroyed = True; self.cleanup()
    super().closeEvent(event)

def deleteLater(self):                # programmatic deletion without a close event
    if not self._destroyed: self._destroyed = True; self.cleanup()
    super().deleteLater()

self.destroyed.connect(partial(_forget_destroyed_widget, self.gui_id))   # parent destroyed
```

The third path cannot call `cleanup()` (the Python wrapper is already gone); it only removes the
RPC entry and prunes dead dispatcher slots. Consequences: put teardown in `cleanup()`, not in
`closeEvent`/`__del__`; make `cleanup()` idempotent; give widgets a `BECWidget` parent or close them
explicitly.

`BECWidget.cleanup()` does, inside `RPCRegister.delayed_broadcast()`:
1. `self.bec_dispatcher.disconnect_owner(self)` - all subscriptions whose owner is this widget.
2. `self.rpc_register.remove_rpc(self)`.
3. `close()` + `deleteLater()` on every child `BECWidget` still valid (`shiboken6.isValid`).
4. Busy-overlay teardown.

## What you own (and must release in cleanup)

| resource | release |
|---|---|
| `QTimer` you created | `.stop()`; `.timeout.disconnect(...)` if connected to a lambda; `.deleteLater()` |
| `QThread` / `QObject` moved to a thread | disconnect signals, `worker.deleteLater()`, `thread.quit()`, `thread.wait(3000)` with an error log on timeout |
| `submit_task` workers | nothing - the base keeps `self._workers` and detaches on completion; just never touch widgets inside the task |
| `pg.SignalProxy`, `BECSignalProxy` | `.cleanup()` / `.disconnect()` |
| ophyd / bec_lib callbacks (`device.readback.subscribe`, `client.callbacks.register`) | `unsubscribe(id)` / `remove(id)` |
| dispatcher slots registered with a lambda/partial | pass `owner=self` at `connect_slot` time; then the base releases them |
| dialogs, popups, context menus you created | `.close()`, `.deleteLater()`, set attribute to `None` |
| event filters on the `QApplication` or another widget | `removeEventFilter(self)` |
| module-level singletons referencing the widget | never do this; use `weakref` if unavoidable |

Reference override (`stop_button.py`):

```python
def cleanup(self):
    self._reset_timer.stop()
    self._reset_timer.timeout.disconnect(self._deactivate_emergency_stop)
    self._reset_timer.deleteLater()
    super().cleanup()
```

## Dispatcher rules

`connect_slot(slot, topics, cb_info=None, owner=None, **kwargs)`; `disconnect_slot(slot, topics, cb_info=None)`;
`disconnect_owner(owner)`; `cleanup_dead_slots()`. Topics accept `EndpointInfo` or lists. Slots run
on the Qt thread (the dispatcher bridges Redis callbacks with a signal), but they run *often*:
throttle heavy redraws with `pg.SignalProxy(signal, rateLimit=25, slot=...)` or a coalescing
`QTimer`. When a subscription is scan-scoped (`device_async_signal(scan_id, ...)`) disconnect
the previous scan's endpoint when the next scan starts, not only in `cleanup()`.

## Threads

- Only the GUI thread touches `QWidget`s, `QGraphicsItem`s and pyqtgraph items. Workers return
  plain data; the completion slot applies it.
- `submit_task(fn, *args, on_complete=slot, on_failed=slot, **kwargs)`: the worker starts before
  the method returns, so late `signals.failed.connect(...)` misses fast failures.
- `QThread` subclasses that reimplement `run()` and touch widgets are a segfault waiting to
  happen; prefer worker `QObject` + `moveToThread` + queued signals, and stop the thread in
  `cleanup()`. The unit-test conftest fails tests on leaked Python threads.

## SafeSlot / SafeProperty / SafeConnect

- `@SafeSlot(*types, popup_error=False, verify_sender=False, raise_error=False)`: wraps `@Slot`,
  logs `SafeSlot error in slot ...`, optionally shows a popup. Stack two decorators for
  overloads (`@SafeSlot(str)` + `@SafeSlot()`).
- `@SafeProperty(type, default=None, auto_emit=False, popup_error=False)`: crash-proof
  `Qt Property`; with `auto_emit=True` the setter emits `property_changed(name, value)` if the
  widget defines that signal; getters tagged for `export_settings()`.
- `SafeConnect(instance, signal, slot)`: weak connection that self-disconnects when the instance
  is gone - use it for long-lived application signals.

## Segfault patterns seen in this codebase

1. A widget deleted by Qt while a Python-side callback (dispatcher, ophyd, timer) still calls
   into it. Guard with `verify_sender=True` slots, `shiboken6.isValid(obj)` before use, and
   release callbacks in `cleanup()`.
2. Overriding `event()` to intercept `DeferredDelete` - every event gets wrapped by shiboken and
   stale pointer-cache entries raise inside the binding. Override `deleteLater()`/`closeEvent`
   as the base does instead.
3. Notification/broker singletons that own a `QObject` parented to a window that gets closed.
4. `WidgetAction`s in toolbars: the injected widget must be owned and closed by the parent widget.
5. pyqtgraph `PlotItem` menus (`vb.menu`, `ctrlMenu`) not closed before the item dies.
6. Application-wide override cursors or event filters left installed after the widget closed.
7. Holding `QPixmap`/`QImage` created before the `QApplication` exists.

## Theme

`BECWidget` connects `qapp.theme.theme_changed` for you. Override `apply_theme(self, theme: str)`
(the argument is `"light"` or `"dark"`) and pull palette colours from
`bec_widgets.utils.colors.get_accent_colors()`; never override `_update_theme`. Tests force the
light theme before each test.
