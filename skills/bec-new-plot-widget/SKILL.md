---
name: bec-new-plot-widget
description: Create a new BEC plotting widget on top of PlotBase (pyqtgraph) in bec_widgets or a beamline plugin - respecting the layout, properties, USER_ACCESS and cleanup contract PlotBase imposes, adding ModularToolBar bundles/actions and side-panel or popup settings, subscribing to scan/device data through BECDispatcher with SignalProxy throttling, and keeping updates fast (setData, clipToView, downsampling, no per-point Python loops). Use whenever the user wants a new plot, chart, waveform/scatter/image/heatmap-style visualisation, live data view or any pyqtgraph-based widget for BEC, or asks how Waveform/Image/MotorMap are built. For non-plot widgets use bec-new-widget.
metadata:
  author: bec-project
  version: "0.1"
---

# New BEC plot widget (PlotBase)

`PlotBase(BECWidget, QWidget)` in `bec_widgets/widgets/plots/plot_base.py` is the base of
`Waveform`, `ScatterWaveform`, `MultiWaveform`, `Image`, `Heatmap` and `MotorMap`. It owns the
pyqtgraph `PlotItem` (inside a `BECViewBox`), the `ModularToolBar`, the side panel, the
crosshair, the FPS monitor, the axis/legend/title properties and their RPC surface. A subclass
adds *data items* and *domain actions*; it does not rebuild any of that. The general widget rules
(MRO, `SafeSlot`, dispatcher ownership, cleanup paths, tests) from `bec-new-widget` apply
unchanged - this skill covers what PlotBase adds on top. Read an existing subclass of the same
family before writing yours: `waveform/waveform.py` (curves + async data + DAP),
`image/image_base.py` (2D items, ROI plots), `motor_map/motor_map.py` (device readback driven).

## 0. Core or beamline plugin repo?

A plot for one beamline (its detector, its scan, its layout) belongs in that beamline's plugin
repo under `<plugin>/bec_widgets/widgets/<snake_name>/`, subclassing `PlotBase` (or `Waveform`,
`Image`, ...) imported from `bec_widgets` - never a copy of a core plot module. Only
beamline-agnostic plots go into `bec_widgets/widgets/plots/`. Check which repository you are in and
ask when the request does not fit it: [references/repo-context.md](references/repo-context.md).

## 1. Skeleton and what PlotBase already provides

```python
class MyPlot(PlotBase):
    PLUGIN = True
    RPC = True
    ICON_NAME = "show_chart"
    USER_ACCESS = [*PlotBase.USER_ACCESS, "plot", "clear_all", "my_option", "my_option.setter"]

    def __init__(self, parent=None, config=None, client=None, gui_id=None, popups=True, **kwargs):
        super().__init__(parent=parent, config=config, client=client, gui_id=gui_id, popups=popups, **kwargs)
        self._items: list[pg.PlotDataItem] = []
        self.sync_signal_update = Signal()             # declare at class level in real code
        self.proxy_update = pg.SignalProxy(self.sync_signal_update, rateLimit=25, slot=self.update_plot)
        self._init_toolbar_my_plot()
        self.bec_dispatcher.connect_slot(self.on_scan_status, MessageEndpoints.scan_status())
        self.bec_dispatcher.connect_slot(self.on_scan_progress, MessageEndpoints.scan_progress())
```

Provided and **not** to be re-implemented: `self.plot_item`, `self.plot_widget`, `self.toolbar`,
`self.side_panel`, `self.crosshair` (via `hook_crosshair`), `self.fps_monitor`, `self.info_label`,
properties `title`, `x_label`, `y_label`, `x_limits`, `y_limits`, `x_grid`, `y_grid`, `x_log`,
`y_log`, `inner_axes`, `outer_axes`, `lock_aspect_ratio`, `auto_range_x/y`, `legend_label_size`,
`minimal_crosshair_precision`, `enable_toolbar`, `enable_side_panel`, `enable_fps_monitor`,
`show_info_label`, `ui_mode` (`UIMode.NONE|POPUP|SIDE`), and the `property_changed(str, object)`
signal that `SafeProperty(auto_emit=True)` setters emit. `PlotBase` has no abstract methods; what
you override: `apply_theme` (call `super()`), `add_side_menus` (call `super()`), `reset`,
`cleanup` (call `super()` last), optionally `hook_crosshair`. Both `apply_theme` and
`add_side_menus` run **inside `PlotBase.__init__`**, before your own `__init__` body - read
subclass attributes defensively there (`getattr(self, "_curves", {})`) or set them before
calling `super().__init__`. Axis units: use
`set_x_label_suffix` / `x_label_units` rather than overwriting `x_label`. Widgets that never show
scan info call `self.remove_info_label_action()`. Full API: [references/plotbase-api.md](references/plotbase-api.md).

## 2. Toolbar

PlotBase registers the bundles `performance`, `plot_export`, `mouse_interaction`, `roi`,
`axis_popup` and shows them in that order. Add yours through the component registry, never by
calling `QToolBar.addAction` directly:

```python
def _init_toolbar_my_plot(self):
    self.toolbar.components.add_safe(
        "my_settings",
        MaterialIconAction(icon_name="tune", tooltip="Show settings", checkable=True, parent=self),
    )
    bundle = ToolbarBundle("my_plot", self.toolbar.components)
    bundle.add_action("my_settings")
    self.toolbar.add_bundle(bundle)
    self.toolbar.components.get_action("my_settings").action.triggered.connect(self.show_settings)
    shown = list(self.toolbar.shown_bundles)
    shown.insert(shown.index("axis_popup"), "my_plot")
    self.toolbar.show_bundles(shown)
```

- `MaterialIconAction(..., parent=self)` - a missing parent leaks and warns.
- Put an action into an existing bundle with `self.toolbar.get_bundle("roi").add_action(name)`;
  hide a base action with `self.toolbar.toggle_action_visibility("reset_legend", False)`; remove
  one with `components.remove_action(name)` after disconnecting its handler.
- Property/toolbar state sync goes through a `BundleConnection` subclass (see
  `utils/toolbars/performance.py`) registered with `self.toolbar.connect_bundle(name, conn)`, so a
  checked state follows the property and RPC calls. Bundle actions are held as weakrefs
  (`bundle.bundle_actions[name]()`).
- Widgets embedded in the toolbar (`WidgetAction`, `DeviceComboBoxAction`) are life-cycled by the
  plot widget, not by the toolbar.
Details and the settings-dialog pattern: [references/toolbar-and-settings.md](references/toolbar-and-settings.md).

## 3. Data flow

- Dispatcher slots only *emit* a plain signal; the throttled proxy calls the real update
  (`pg.SignalProxy(..., rateLimit=25)`; 5 for expensive 2D work; `BECSignalProxy` when the update
  triggers a slow request such as DAP). On `scan_progress` `done`, schedule two late updates
  (`QTimer.singleShot(100, ...)`, `QTimer.singleShot(300, ...)`) to catch trailing data.
- Scan data: `self.scan_item = self.queue.scan_storage.find_scan_by_ID(scan_id)`; read
  `scan_item.live_data[device][signal].val`. Async devices: subscribe to
  `MessageEndpoints.device_async_signal(scan_id, device, signal)` with `from_start=True`,
  `cb_info={"scan_id": ...}`, read it back in the slot as `metadata["cb_info"]["scan_id"]` and drop
  messages whose scan ID is not `self.scan_id`; disconnect the previous scan's endpoint when a new
  scan opens.
  Device readbacks: `device_readback(name)` / `device_limits(name)`; 1D monitors:
  `device_monitor_1d(name)`; previews: `device_preview(device, signal)`.
- History mode: accept a `ScanDataContainer` too (`update_scan_info_from_source`), because users
  replay scans from the history browser.
- Items are `BECConnector` + pyqtgraph classes (`Curve(BECConnector, pg.PlotDataItem)`,
  `ImageItem(BECConnector, pg.ImageItem)`) with a pydantic config so they are RPC-addressable
  and serialisable; add with `self.plot_item.addItem(item)`, remove with
  `self.plot_item.removeItem(item)` followed by `item.rpc_register.remove_rpc(item)`. A
  `CurveConfig` needs an explicit `color` (`Colors.golden_angle_color(colormap, num, format="HEX")`
  as `Waveform` does) - a `None` colour raises inside pyqtgraph, and because `plot()` is a
  `SafeSlot` the error is only logged, so check the log when an item silently does not appear.

## 4. Performance rules

- Update with `item.setData(x, y)` / `image.set_data(arr)`; never remove and re-add items per update.
- Keep arrays as numpy; append with `np.hstack`, truncate to `min(len(x), len(y))`, vectorise
  colour lookups (256-entry brush pool, see `scatter_curve.py`) - no per-point `pg.mkBrush`.
- `setClipToView(True)` on curves (the base `Curve` does it) and, above ~1000 points, drop symbols,
  cap pen width and enable `setDownsampling(auto=True, method="peak")` as
  `Waveform._auto_adjust_async_curve_settings` does. Rebind "View All" if you use clipToView.
- Heavy computation (interpolation, FFT) goes to a worker `QObject` in a `QThread` with a
  `data_version`/`scan_id` stamp so stale results are discarded; stop the thread in `cleanup()`.
- No global `pg.setConfigOptions` / `useOpenGL` from inside a widget.
- Turn on the FPS monitor (`enable_fps_monitor = True`) while developing and check the plot
  stays responsive during a 200-point `line_scan` with `exp_time=0.02`.
Reference: [references/performance-and-cleanup.md](references/performance-and-cleanup.md).

## 5. Settings UI

Offer the same settings widget both as a side-panel menu (`self.side_panel.add_menu(widget, action_id=, icon_name=, tooltip=, title=)`
inside `add_side_menus`) and as a popup (`SettingsDialog(parent=self, settings_widget=..., modal=False)`),
branching on `self.ui_mode == UIMode.POPUP`. Settings widgets derive from `SettingWidget`, set
`self.setProperty("skip_settings", True)`, bind controls by `objectName == property name` and listen
to `target_widget.property_changed`. Keep a single dialog instance; on `finished` close, `deleteLater`,
set the attribute to `None` and uncheck the toolbar action.

## 6. Cleanup order

```python
def cleanup(self):
    self.proxy_update.disconnect()                 # or .cleanup() for BECSignalProxy
    self._finish_worker_thread()                   # quit() + wait(3000)
    for dlg in (self.settings_dialog,): dlg and dlg.reject()
    self.clear_all()                               # removeItem + remove_rpc for every item
    super().cleanup()                              # toolbar, crosshair, fps, menus, dispatcher, RPC
```

pyqtgraph specifics: never `plot_item.clear()` (kills crosshair/indicator items - filter by
`is_crosshair`); the base closes `vb.menu`/`ctrlMenu` for you; undo anything you attached to
`plot_item.scene()`; `ImageItem` needs `removeItem` → `item.remove(emit=False)` → `deleteLater()`.

## 7. Tests

Tests use the shared fixtures shipped in `bec_widgets.tests` (bec_widgets >= 3.38), wired through
the widget-test conftest exactly as in `bec-new-widget`: `tests/unit_tests/conftest.py` in core,
`tests/tests_bec_widgets/conftest.py` in a plugin repo (create it), containing
`from bec_widgets.tests.fixtures import *` and `from bec_widgets.tests.utils import create_widget`.
Plugin prerequisites:

- Version check: `python -c "import bec_widgets.tests.fixtures"`; an `ImportError` means
  bec_widgets < 3.38 - ask the user to upgrade it instead of copying fixtures into the plugin.
- The fixtures need pytest-qt and fakeredis: `pip install "bec_widgets[dev]"`, or add both to the
  plugin's `[dev]` extra (the copier template does not list them).
- Importing the fixtures patches `QTimer` only for modules imported afterwards, so keep widget
  imports out of the plugin's top-level `tests/conftest.py` and out of non-widget test folders.

Follow `tests/unit_tests/test_plot_base_next_gen.py` and `test_waveform.py` in the bec_widgets repo:
`create_widget(qtbot, MyPlot, client=mocked_client)` (`create_widget` from
`bec_widgets.tests.utils`, `mocked_client` as a fixture argument),
trigger toolbar actions via `w.toolbar.components.get_action(name).action.trigger()` and assert the
property changed, verify data updates by monkeypatching `item.setData` and calling the slot, drive
scan flow with `create_dummy_scan_item()` (`from bec_widgets.tests.client_mocks import create_dummy_scan_item`)
+ `monkeypatch.setattr(w.queue.scan_storage, "find_scan_by_ID", ...)`, use `scan_history_factory`
for history-driven plots, call dispatcher slots with raw dicts, close every dialog you open, and add
your class to the parametrised "subclass" tests in `test_plot_base_next_gen.py` if it lives in core.
The autouse fixtures fail on leaked timers/widgets/threads. Reference images are not used any more.

## Deliverable checklist

- [ ] repo decided (core vs plugin, asked if unclear); plugin subclasses core plots, never copies them
- [ ] `class X(PlotBase)`, same ctor signature incl. `popups`, `USER_ACCESS = [*PlotBase.USER_ACCESS, ...]`
- [ ] toolbar via `components.add_safe` + bundles, actions parented, `show_bundles` order set
- [ ] dispatcher slot → signal → `SignalProxy` → update; scan-scoped endpoints swapped per scan
- [ ] `setData`-based updates, numpy only, clipToView/downsampling for large data
- [ ] settings in side panel and popup; `apply_theme` and `add_side_menus` call `super()`
- [ ] `cleanup()` stops proxies/threads/dialogs, clears items, ends with `super().cleanup()`
- [ ] `bw-generate-cli --target ...` regenerated; tests use the shared `bec_widgets.tests` fixtures and cover toolbar, data update, scan flow, lifecycle
