# ModularToolBar, bundles, actions, connections, settings widgets

Files: `bec_widgets/utils/toolbars/{toolbar,bundles,actions,connections,performance}.py`,
`bec_widgets/widgets/plots/toolbar_components/*.py`, `bec_widgets/utils/settings_dialog.py`,
`bec_widgets/utils/side_panel.py`, `bec_widgets/widgets/plots/setting_menus/axis_settings.py`.

## Registry model

- `toolbar.components: ToolbarComponents` - name → `ToolBarAction`. `add(name, action)` raises on
  duplicates, `add_safe(name, action)` logs and skips (use it: widgets get re-created). `exists`,
  `get_action(name)`, `remove_action(name)` (also calls the action's `cleanup()` and refreshes).
- `ToolbarBundle(name, components)` - ordered group; `add_action(name)` (must exist in
  components), `remove_action`, `add_separator()`, `add_splitter(...)`, `add_connection`.
  `bundle.bundle_actions` holds **weakrefs**: iterate `for name, ref in ...: action = ref()`.
- `toolbar.add_bundle(bundle)`, `get_bundle(name)`, `remove_bundle(name)`, `new_bundle(name)`.
- `toolbar.show_bundles([...names])` **rebuilds** the toolbar in that order (separators added);
  `toolbar.shown_bundles` is the current order. `toolbar.add_action(name, action)` is the shortcut
  for a one-action bundle. `toggle_action_visibility(name, visible)`, `hide_action`, `show_action`.
- `toolbar.connect_bundle(connection_name, BundleConnection)` / `disconnect_bundle(...)`.
- `toolbar.cleanup()` disconnects bundles, cleans components, clears bundles (called by PlotBase).

## Actions

```python
MaterialIconAction(icon_name, tooltip, *, checkable=False, filled=False, color=None,
                   label_text=None, text_position=None, parent=None)   # always pass parent
SwitchableToolBarAction(actions: dict[str, IconAction], initial_action=None, tooltip=None,
                        checkable=True, default_state_checked=False, exclusive=True, parent=None)
WidgetAction(*, widget: QWidget, label=None, adjust_size=True, parent=None)  # widget owned by YOU
DeviceComboBoxAction(...), ExpandableMenuAction(...), SeparatorAction(), SplitterAction(...)
```

`action.action` is the `QAction` (or the container widget for `WidgetAction`). Connect with
`self.toolbar.components.get_action("name").action.triggered.connect(slot)` /
`.toggled.connect(slot)`.

## Bundle factory + connection pattern (copy from performance.py)

```python
def my_bundle(components: ToolbarComponents) -> ToolbarBundle:
    components.add_safe("my_toggle", MaterialIconAction(icon_name="tune", tooltip="My toggle",
                                                        checkable=True, parent=components.toolbar))
    bundle = ToolbarBundle("my_bundle", components)
    bundle.add_action("my_toggle")
    return bundle

class MyConnection(BundleConnection):
    def __init__(self, components, target_widget):
        super().__init__()
        self.bundle_name = "my_bundle"
        self.components, self.target_widget = components, target_widget
        if not hasattr(target_widget, "my_option"):
            raise AttributeError("Target widget must implement 'my_option'.")
    def connect(self):
        self.components.get_action("my_toggle").action.toggled.connect(self._on_toggled)
        self.register_checked_action_sync("my_option", self.components.get_action("my_toggle"))
        self.connect_property_sync(self.target_widget)
    def disconnect(self):
        self.components.get_action("my_toggle").action.toggled.disconnect(self._on_toggled)
        self.disconnect_property_sync(self.target_widget)
    def _on_toggled(self, checked): self.target_widget.my_option = checked
```

Then in the widget: `self.toolbar.add_bundle(my_bundle(self.toolbar.components))`,
`self.toolbar.connect_bundle("my_bundle", MyConnection(self.toolbar.components, self))`.
Because `my_option` is a `SafeProperty(bool, auto_emit=True)`, RPC calls and the toolbar stay in
sync through `property_changed`.

## Base bundles you can extend

`performance` (`fps_monitor`, hidden by default), `plot_export` (`save`, `matplotlib`),
`mouse_interaction` (`drag_mode`, `rectangle_mode`, `auto_range`), `roi` (`crosshair`,
`reset_legend`), `axis_popup` (`axis`, `plot_info_label`). Images add `image_roi`, `image_autorange`,
`image_colorbar`, `image_processing`, `image_crosshair`; device-driven widgets add
`device_selection` / `motor_selection` / `monitor_selection` bundles from `toolbar_components/`.

## Side panel

`self.side_panel.add_menu(widget, action_id=None, icon_name=None, tooltip=None, title=None) -> int`
adds a stacked page and, if `action_id/icon_name` are given, a toggle on the side panel's own
toolbar. Do it inside `add_side_menus()` after `super().add_side_menus()`.

## Popup settings

```python
@SafeSlot(popup_error=True)
def show_settings(self):
    if self.settings_dialog is None or not self.settings_dialog.isVisible():
        widget = MySettings(parent=self, target_widget=self, popup=True)
        self.settings_dialog = SettingsDialog(self, settings_widget=widget, window_title="My settings", modal=False)
        self.settings_dialog.finished.connect(self._settings_closed)
        self.settings_dialog.show()
        self.toolbar.components.get_action("my_settings").action.setChecked(True)
    else:
        self.settings_dialog.raise_(); self.settings_dialog.activateWindow()

@SafeSlot(int)
def _settings_closed(self, result):
    self.settings_dialog.close(); self.settings_dialog.deleteLater(); self.settings_dialog = None
    self.toolbar.components.get_action("my_settings").action.setChecked(False)
```

`SettingWidget` API: `set_target_widget(w)`, `accept_changes()`, `display_current_settings(config_dict)`,
`cleanup()`; set `self.setProperty("skip_settings", True)` to keep it out of state export. Bind
controls to properties by giving them `objectName == property name` and using
`WidgetIO.connect_widget_change_signal`; in side-panel mode listen to `target_widget.property_changed`.
`AxisSettings` is the template.
