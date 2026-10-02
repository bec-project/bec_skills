# Testing BEC widgets

Sources: `tests/conftest.py`, `tests/unit_tests/conftest.py`, `tests/unit_tests/client_mocks.py`,
`bec_widgets/tests/utils.py`, `tests/unit_tests/test_bec_widget_lifecycle.py`.

## Fixtures you get for free (autouse unless noted)

- `qapplication` - before each test: flush deferred deletes, force light theme. After: stop the
  ophyd dummy dispatcher, flush deletes, then **fail** if a `QTimer` is still active
  (`TestableQTimer.check_all_stopped`, prints the creation traceback) or if
  `QApplication.topLevelWidgets()` is not empty (`TimeoutError("Failed to close all widgets: ...")`).
  A failed test skips these checks so the real assertion error is reported.
- `bec_dispatcher` - fresh `BECDispatcher` bound to a fakeredis `mock_client()`; torn down with
  `disconnect_all()`, client shutdown, singleton reset. Depends on `threads_check` from
  `pytest-bec-e2e`, which fails on leaked Python threads.
- `rpc_register` - resets the `RPCRegister` singleton.
- `clean_singleton` - resets the `ErrorPopupUtility` singleton.
- `suppress_message_box` - `QMessageBox.exec_` returns `Ok`.
- `testable_qtimer_class` (not autouse) - the tracking `QTimer` class if you need it.

## Fixtures and helpers you import

```python
from .client_mocks import mocked_client, mocked_client_with_dap   # per-test client (fakeredis)
from .conftest import create_widget                                # widget(*a, **k); qtbot.addWidget; waitExposed
from bec_widgets.tests.utils import FakeDevice, FakePositioner, DMMock, DEVICES
```

`mocked_client.device_manager.devices` contains `samx`, `samy`, `samz`, `aptrx`, `aptry`,
`gauss_bpm`, `bpm4i`, `eiger` (async), `async_device`, ... via `DMMock`. Add more with
`DMMock.add_devices([...])`. Scan items: `create_dummy_scan_item(...)` in `client_mocks.py`;
scan history: `scan_history_factory`, `grid_scan_history_msg`, `create_history_file` in the
unit conftest. Plugin repos import the same helpers from `bec_widgets.tests.utils` and define
their own `mocked_client` by copying the fixture from `client_mocks.py`.

## Feeding dispatcher slots

Call the slot directly with the dict shape the endpoint delivers; you do not need Redis:

```python
w.on_readback({"signals": {"samx": {"value": 1.5, "timestamp": 0.0}}}, {"device": "samx"})
w.on_scan_status({"scan_id": "abc", "status": "open"}, {})
```

For message classes use `bec_lib.messages` (`ScanStatusMessage(...)`) and pass `.content`, `.metadata`.
A slot that reads subscription context gets it the way the dispatcher delivers it, inside
`metadata` - do not patch `widget.sender`:

```python
w.on_async_readback(msg.content, {**msg.metadata, "cb_info": {"scan_id": w.scan_id}})
```

## SafeSlot swallows exceptions

A method decorated with `@SafeSlot` catches every exception, logs it (and pops up a dialog when
`popup_error=True`, suppressed in tests). `pytest.raises` around a slot call therefore never
fires. To test the error path either assert on the *state* (nothing changed) or force the raise
for that single call:

```python
with pytest.raises(ValueError):
    widget.set_device("nope", _override_slot_params={"raise_error": True})
```

## Lifecycle test template

```python
def test_close_runs_cleanup_once_and_unregisters(qtbot, mocked_client):
    w = MyWidget(client=mocked_client)
    gui_id = w.gui_id
    assert RPCRegister().get_rpc_by_id(gui_id) is w
    w.close()
    assert w._destroyed is True
    assert RPCRegister().get_rpc_by_id(gui_id) is None
    w.close()                     # idempotent
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
```

Count `cleanup()` calls with a subclass that increments a counter, or `monkeypatch` a spy.

## Headless and random order

```bash
export QT_QPA_PLATFORM=offscreen
python -m pytest --random-order -q -p no:cacheprovider tests/unit_tests/test_my_widget.py
```

`--random-order` is how CI runs; a test that depends on another test's leftover state (theme,
singleton, device list) will flake there. `pyside6-uic` must be on `PATH` for suites that load
`.ui` files.

## Common failures and what they mean

| message | cause |
|---|---|
| `Failed to stop all timers` + traceback line | a `QTimer` started in `__init__` or a slot and not stopped in `cleanup()` |
| `Failed to close all widgets: [<...>]` | a dialog/popup/child window created without being closed; or a widget created without `create_widget`/`qtbot.addWidget` |
| threads_check failure | `QThread`/`threading.Thread` not joined; a `submit_task` worker still running at teardown (wait for it with `qtbot.waitUntil`) |
| `RuntimeError: Internal C++ object already deleted` | a callback ran after the widget died - release ophyd/bec_lib callbacks and timers in `cleanup()`, register lambda/partial dispatcher slots with `owner=self` |
| `TypeError: QtCore.Slot() got an unexpected keyword argument 'verify_sender'` at import | `@SafeSlot(..., verify_sender=True)` on a bec_widgets with #1289 - drop the keyword, read `metadata["cb_info"]` instead of `self.sender()` |
| `Lambda ... without owner` warning | `connect_slot` with a lambda/partial and no `owner=self` |
