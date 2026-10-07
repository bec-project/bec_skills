---
name: bec-new-widget
description: Create a new BEC GUI widget (PySide6/qtpy) for bec_widgets or a beamline plugin repo - BECWidget + Qt base class, BECDispatcher subscriptions, @SafeSlot slots, cleanup() that stops timers/threads, USER_ACCESS + bw-generate-cli RPC client, Qt Designer plugin files, and tests with the shared qtbot/mocked_client fixtures that fail on leaked widgets, timers and threads. Use whenever the user asks to add, build, scaffold or port a widget, control panel, dock content, status display or any Qt UI element for BEC, even if they only say "make a GUI for X". For plots based on PlotBase use bec-new-plot-widget instead.
metadata:
  author: bec-project
  version: "0.1"
---

# New BEC widget

BEC widgets are PySide6 (through `qtpy`) widgets that mix in `BECWidget` to get a BEC client, the
Redis-backed `BECDispatcher`, an RPC identity, theme handling and a guaranteed `cleanup()`.
Getting the lifecycle right is what separates a widget that works in a demo from one that survives
a beamline shift: every leaked timer, thread or dispatcher subscription is a crash or a memory
leak in a GUI that runs for days. Read [references/lifecycle.md](references/lifecycle.md)
before writing `cleanup()` and [references/testing.md](references/testing.md) before writing tests.

## 1. Where does it go?

Decide first whether this is a core `bec_widgets` task or a beamline plugin repo task - most
users are scientists working in their beamline's plugin repo. Check the repository you are in and
ask when it is unclear or the request does not fit it; the detection table and the "ask instead of
guessing" rules are in [references/repo-context.md](references/repo-context.md).

- **Core (`bec_widgets`)** only for beamline-agnostic widgets:
  `bec_widgets/widgets/<domain>/<snake_name>/` with `domain` in `control`, `plots`, `services`,
  `utility`, `editors`, `progress`, `containers`, `dap`. Regenerate the client with
  `bw-generate-cli --target bec_widgets`.
- **Beamline plugin repo** (`debye_bec`, `csaxs_bec`, ...) for anything site-specific:
  `<plugin>/<plugin>/bec_widgets/widgets/<snake_name>/`. Discovery is through the
  `bec.widgets.user_widgets` entry point (`plugin_widgets = "<plugin>.bec_widgets.widgets"` in
  `pyproject.toml`); the generated client lands in `<plugin>/bec_widgets/widgets/client.py` via
  `bw-generate-cli --target <plugin>`. Scaffold with `bec-plugin-manager create widget <snake_name>`
  (copier template, optional `.ui` file, commits the scaffold) when it can run interactively;
  otherwise create the directory by hand from [assets/widget_template.py](assets/widget_template.py).
  Import core classes from `bec_widgets`; never copy or edit core modules from a plugin task.
  Details: [references/plugin-repo.md](references/plugin-repo.md).

Check first whether a widget with the same purpose already exists (`bec_widgets/widgets/**`,
`bec_widgets/cli/client.py`) - extending or composing beats duplicating.

## 2. Class skeleton rules

Start from [assets/widget_template.py](assets/widget_template.py): a complete widget with a
dispatcher subscription that can be re-targeted, a `submit_task` move, a `SafeProperty`, a timer
and the minimal `cleanup()`. Its test counterpart is [assets/test_template.py](assets/test_template.py).

```python
from qtpy.QtWidgets import QWidget
from bec_lib.endpoints import MessageEndpoints
from bec_widgets.utils.bec_widget import BECWidget
from bec_widgets.utils.error_popups import SafeSlot, SafeProperty

class MyWidget(BECWidget, QWidget):          # BECWidget FIRST, then exactly one Qt class
    """One-line purpose (becomes the Designer tooltip)."""
    PLUGIN = True                            # expose in Qt Designer / bec-designer
    ICON_NAME = "widgets"                    # Material Symbols name (fonts.google.com/icons)
    USER_ACCESS = [*BECWidget.USER_ACCESS, "set_device"]   # RPC + generated CLI surface

    def __init__(self, parent=None, client=None, config=None, gui_id=None, device: str = "samx", **kwargs):
        super().__init__(parent=parent, client=client, config=config, gui_id=gui_id, **kwargs)
        self.get_bec_shortcuts()             # self.dev, self.scans, self.queue, self.scan_storage, self.dap
        ...
```

- `parent` must be the first parameter and the first argument of the single cooperative
  `super().__init__(parent=parent, ...)` call - the Designer plugin generator regex-checks this
  and `BECConnector` pops `parent` to hand it to the Qt base.
- Import Qt from `qtpy` only; CI rejects `from PySide6.` (Designer modules excepted).
- `USER_ACCESS` in a subclass *replaces* the base list, so splat the base if `remove/attach/detach`
  should stay. Property setters are listed as `"name.setter"`. `RPC = False` keeps a purely
  visual helper out of the RPC namespace and the generated client.
- Widget-specific config goes in a `ConnectionConfig` subclass (pydantic) passed as `config`.
- Persisted Designer properties use `@SafeProperty(type, auto_emit=True)`; theme reactions go in
  `apply_theme(self, theme: str)` (already wired; do not connect to theme signals yourself).

## 3. Data in, actions out

- Subscribe with bound methods: `self.bec_dispatcher.connect_slot(self.on_readback, MessageEndpoints.device_readback(name))`.
  Lambdas/partials must pass `owner=self` or they outlive the widget. Every dispatcher slot is
  `@SafeSlot(dict, dict)` and receives `(content, metadata)`. Per-subscription context goes in
  `connect_slot(..., cb_info={"scan_id": ...})` and arrives as `metadata["cb_info"]` (key absent
  when no `cb_info` was given); never call `self.sender()` in a dispatcher slot.
- Re-subscribing to a different device/scan: `disconnect_slot` the old endpoint first; keep the
  current endpoint in an attribute so `cleanup()` and re-targeting share one code path.
- Decorate every slot with `@SafeSlot(...)` (`popup_error=True` for user-triggered actions).
  Unhandled exceptions in a plain `@Slot` kill the event loop. The dispatcher drops deliveries to
  disconnected slots and to owners that were cleaned up or deleted, so slots need no sender check.
- Never block the GUI thread: device moves and RPC calls go through `self.submit_task(fn, *args, on_complete=..., on_failed=...)`
  (global `QThreadPool`); pass `on_failed` in the call, not afterwards. Never touch widgets from the
  worker - deliver results via the completion slot.
- Deferred work that touches the widget: `self._call_later(msec, callback)` (bec_widgets >= 3.39.1),
  which is skipped once the widget is closed; never a bare `QTimer.singleShot` (it still fires
  into a closed widget). On older versions use a single-shot `QTimer(self)` stopped in `cleanup()`.
- Device access: `self.dev[name]`, `self.dev[name].limits`, `self.scans.<scan>(...)`, `self.queue`.

## 4. Cleanup - the part reviewers look at first

`BECWidget.cleanup()` already disconnects all dispatcher subscriptions owned by the widget,
removes the RPC registration and closes child `BECWidget`s. A widget with no timers, threads or
external callbacks needs no `cleanup()` override. Otherwise override it only for what you own, and
always end with `super().cleanup()`:

```python
def cleanup(self):
    self._poll_timer.stop()                  # every running QTimer (parented ones die with the widget)
    self._worker_thread.quit(); self._worker_thread.wait(3000)   # every QThread
    self.dev[self.device].readback.unsubscribe(self._sub_id)     # ophyd/bec_lib callbacks
    super().cleanup()
```

`cleanup()` runs from `closeEvent`, from `deleteLater()` and only once (`_destroyed` flag). It
does **not** run when a plain Qt parent is destroyed; the base class still purges the RPC
registry via the `destroyed` signal, so keep anything that must run on teardown inside
`cleanup()` and prefer `BECWidget` parents. Segfault sources to avoid: touching Qt objects from
threads, keeping C++-owned objects in Python containers past their deletion (check
`shiboken6.isValid`), overriding `event()` to catch `DeferredDelete`, module-level singletons
holding widgets. Full list with reasons: [references/lifecycle.md](references/lifecycle.md).

## 5. RPC client, Designer files, docs

1. `bw-generate-cli --target bec_widgets` (or `--target <plugin>`). It writes the `RPCBase` stub
   into `client.py`, the `designer_plugins.py` registry, and - if missing - the three Designer
   files next to the widget: `<name>.pyproject`, `<name>_plugin.py`, `register_<name>.py`.
   Existing files are not overwritten, so set `group()` in `<name>_plugin.py` (e.g. `"BEC Buttons"`)
   after the first run. Never hand-edit `client.py`/`designer_plugins.py`; regenerate after
   every `USER_ACCESS` or docstring change and commit the result.
2. Verify the stub: `python -c "from bec_widgets.cli.client import MyWidget"` (core) or the
   plugin client module. Check `bec-designer` lists the widget if `PLUGIN = True`.
3. Document user-facing methods with Google-style docstrings; they are copied into the client.

## 6. Tests

Use the shared fixtures shipped in `bec_widgets.tests` (bec_widgets >= 3.38) - they are the leak
detector, and core and plugin repos load them the same way. The widget-test `conftest.py`
(`tests/unit_tests/` in core, already present; `tests/tests_bec_widgets/` in a plugin repo, create
it if missing) contains:

```python
from bec_widgets.tests.fixtures import *  # noqa: F401,F403
from bec_widgets.tests.utils import create_widget  # noqa: F401
```

```python
from bec_widgets.tests.utils import create_widget   # adds to qtbot + waits exposed

def test_readback_updates_label(qtbot, mocked_client):   # mocked_client: fixture from the conftest
    w = create_widget(qtbot, MyWidget, client=mocked_client, device="samx")
    w.on_readback({"signals": {"samx": {"value": 1.5}}}, {})
    assert w.label.text() == "1.500"
```

Never import fixtures from a sibling test module or copy them into the repo; do not replace the
widget with a hand-written stub to avoid the BEC client - `mocked_client` is that client. The
autouse fixtures fail a test when any top-level widget, running `QTimer` (patched to a tracking
class) or Python thread survives, and reset the dispatcher, RPC registry and popup singletons.
Plugin specifics (dev dependencies, version check, import order): [references/testing.md](references/testing.md).

Cover: construction with the mocked client, each `USER_ACCESS` method, each dispatcher
slot fed with a hand-built message dict, re-targeting (old subscription gone), theme change
(`w.apply_theme("dark")`), and a lifecycle test that `close()` runs `cleanup()` exactly once and
removes the RPC entry. Remember that `@SafeSlot` swallows exceptions: to assert an error path
call the slot with `_override_slot_params={"raise_error": True}` or assert on unchanged state. Template: [assets/test_template.py](assets/test_template.py). Run:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest --random-order -q -p no:cacheprovider tests/unit_tests/test_my_widget.py        # core
QT_QPA_PLATFORM=offscreen python -m pytest --random-order -q -p no:cacheprovider tests/tests_bec_widgets/test_my_widget.py # plugin repo
```

Then run the whole unit suite once if you touched shared code, and open the widget in a real
`QApplication` (or `bec-gui-server` + `gui.new("MyWidget")` from the client) to confirm it renders
and closes cleanly - a single run with `PYTHONFAULTHANDLER=1` catches most segfaults.

## Deliverable checklist

- [ ] `class X(BECWidget, QWidget)`, `parent` first, one `super().__init__`, `qtpy` imports only
- [ ] `PLUGIN`, `ICON_NAME`, `USER_ACCESS` (base splatted when needed); `RPC = False` for helpers
- [ ] every slot `@SafeSlot`; dispatcher subscriptions via bound methods or `owner=self`
- [ ] subscription context read from `metadata["cb_info"]`, not `self.sender()`
- [ ] no blocking I/O on the GUI thread; `submit_task` with `on_failed`
- [ ] `cleanup()` stops timers/threads/external callbacks and calls `super().cleanup()`
- [ ] `bw-generate-cli --target ...` run; Designer files present; client import works
- [ ] repo decided (core vs plugin, asked if unclear); plugin code imports core, never copies it
- [ ] tests use the shared `bec_widgets.tests` fixtures via the conftest star import, `create_widget`/`mocked_client`, include a lifecycle test, pass in random order
- [ ] black/isort formatted; docstrings on the class and public methods
- [ ] for a widget that owns timers, threads, proxies or cell widgets: the `bec-widget-safety-audit`
      skill's probes pass (if that skill is installed)
