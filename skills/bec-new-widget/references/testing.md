# Testing BEC widgets

Sources (bec_widgets >= 3.38): `bec_widgets/tests/fixtures.py` (all fixtures),
`bec_widgets/tests/utils.py` (`create_widget`, `mock_client`, `create_history_file`),
`bec_widgets/tests/client_mocks.py` (`mocked_client`, `create_dummy_scan_item`,
`inject_scan_history`), `bec_widgets/tests/fake_devices.py` (`FakeDevice`, `FakePositioner`,
`DMMock`, `DEVICES`), `bec_widgets/tests/testable_qtimer.py`, and as a usage example
`tests/unit_tests/test_bec_widget_lifecycle.py` in the bec_widgets repo.

## Wiring: one conftest, same in core and plugin repos

The fixtures ship inside the `bec_widgets` package so beamline plugin repos get the identical test
bed. They are deliberately not a pytest plugin: they apply only below the conftest that imports
them, so a plugin's device and scan tests are not affected.

```python
# core:   tests/unit_tests/conftest.py        (already exists - do not add fixtures here,
#                                               add shared ones to bec_widgets/tests/fixtures.py)
# plugin: tests/tests_bec_widgets/conftest.py (create it; the copier template does not ship one)
from bec_widgets.tests.fixtures import *  # noqa: F401,F403
from bec_widgets.tests.utils import create_widget  # noqa: F401
```

In test modules import helpers by absolute name (`from bec_widgets.tests.utils import create_widget`,
`from bec_widgets.tests.client_mocks import create_dummy_scan_item`), never `from .conftest` or
`from .client_mocks`. Fixtures (`qtbot`, `mocked_client`, `scan_history_factory`, ...) are requested
as test arguments.

**Plugin repo prerequisites.**

- Version check: `python -c "import bec_widgets.tests.fixtures"`. An `ImportError` means
  bec_widgets < 3.38 - ask the user to upgrade bec_widgets rather than copying fixtures into the
  plugin.
- Dev dependencies: the fixtures need pytest-qt and fakeredis, which come with
  `bec_widgets[dev]`; the copier template's `[dev]` extra does not list them (its CI installs
  `bec_widgets[dev]`, a local env may not). `pip install "bec_widgets[dev]"` locally, or add
  `pytest-qt` and `fakeredis` to the plugin's `[dev]` extra.
- `threads_check` comes from bec_lib's pytest plugin (`bec_lib.tests.fixtures`, registered through
  the `pytest11` entry point), so it is available wherever bec_lib is installed.
- Import order: importing `bec_widgets.tests.fixtures` replaces `qtpy.QtCore.QTimer` with
  `TestableQTimer`, which only affects modules imported afterwards. Keep widget imports out of the
  plugin's top-level `tests/conftest.py` and out of non-widget test folders, otherwise a module
  bound to the real `QTimer` escapes the leak check.

## Fixtures you get for free (autouse unless noted)

- `qapplication` - before each test: flush deferred deletes, force light theme. After: stop the
  ophyd dummy dispatcher, flush deletes, then **fail** if a `QTimer` is still active
  (`TestableQTimer.check_all_stopped`, prints the creation traceback) or if
  `QApplication.topLevelWidgets()` is not empty (`TimeoutError("Failed to close all widgets: ...")`).
  A failed test skips these checks so the real assertion error is reported. A timer parented to a
  widget that was closed dies with it; the check catches unparented or externally held timers.
- `bec_dispatcher` - fresh `BECDispatcher` bound to a fakeredis `mock_client()` that knows the
  fake `DEVICES`; torn down with `disconnect_all()`, client shutdown, singleton reset. Depends on
  `threads_check` (bec_lib), which fails on leaked Python threads.
- `rpc_register` - resets the `RPCRegister` singleton.
- `clean_singleton` - resets the `ErrorPopupUtility` singleton.
- `suppress_message_box` - `QMessageBox.exec_` returns `Ok`.
- `testable_qtimer_class` (not autouse) - the tracking `QTimer` class if you need it.

## Fixtures and helpers on request

- `mocked_client`, `mocked_client_with_dap`, `dap_plugin_message` - per-test client on fakeredis.
- `scan_history_factory`, `grid_scan_history_msg` - `ScanHistoryMessage`s backed by a real HDF5
  file in `tmpdir`; `inject_scan_history(widget, scan_history_factory, ...)` in `client_mocks`.
- `create_dummy_scan_item(...)` (`client_mocks`) - a scan item for scan-driven widgets.

`mocked_client.device_manager.devices` contains `samx`, `samy`, `samz`, `aptrx`, `aptry`,
`gauss_bpm`, `bpm4i`, `eiger` (async), `async_device`, ... (`DEVICES` in `fake_devices.py`). Add
more with `mocked_client.device_manager.add_devices([FakeDevice(name="my_det"), ...])`; a plugin
that needs its own device names adds them this way in a fixture instead of replacing the client.

## Feeding dispatcher slots

Call the slot directly with the dict shape the endpoint delivers; you do not need Redis:

```python
w.on_readback({"signals": {"samx": {"value": 1.5, "timestamp": 0.0}}}, {"device": "samx"})
w.on_scan_status({"scan_id": "abc", "status": "open"}, {})
```

For message classes use `bec_lib.messages` (`ScanStatusMessage(...)`) and pass `.content`, `.metadata`.
A slot that reads subscription context gets it the way the dispatcher delivers it, inside
`metadata`:

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
python -m pytest --random-order -q -p no:cacheprovider tests/unit_tests/test_my_widget.py         # core
python -m pytest --random-order -q -p no:cacheprovider tests/tests_bec_widgets/test_my_widget.py  # plugin
```

`--random-order` is how CI runs; a test that depends on another test's leftover state (theme,
singleton, device list) will flake there. `pyside6-uic` must be on `PATH` for suites that load
`.ui` files.

## Common failures and what they mean

| message | cause |
|---|---|
| `Failed to stop all timers` + traceback line | a `QTimer` started in `__init__` or a slot and not stopped in `cleanup()`; in 3.38.0 a leaked timer is not cleared, so every later test errors too - fix the first one |
| `RuntimeError: libshiboken: Internal C++ object (TestableQTimer) already deleted` at teardown | same cause: in 3.38.0 the timer report trips over an already-deleted timer of another widget and hides the message above; look for your unstopped timer |
| `Failed to close all widgets: [<...>]` | a dialog/popup/child window created without being closed; or a widget created without `create_widget`/`qtbot.addWidget` |
| `fixture 'mocked_client' not found` / `'threads_check' not found` | the conftest star import is missing, or bec_lib is not installed in the env |
| `ModuleNotFoundError: bec_widgets.tests.fixtures` | bec_widgets < 3.38 - upgrade it |
| threads_check failure | `QThread`/`threading.Thread` not joined; a `submit_task` worker still running at teardown (wait for it with `qtbot.waitUntil`) |
| `RuntimeError: Internal C++ object already deleted` | a callback ran after the widget died - release ophyd/bec_lib callbacks and timers in `cleanup()`, register lambda/partial dispatcher slots with `owner=self` |
| `Lambda ... without owner` warning | `connect_slot` with a lambda/partial and no `owner=self` |
