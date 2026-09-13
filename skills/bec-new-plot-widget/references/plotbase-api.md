# PlotBase API (bec_widgets/widgets/plots/plot_base.py)

## Construction

```python
class PlotBase(BECWidget, QWidget):
    PLUGIN = False
    RPC = False
    def __init__(self, parent=None, config: ConnectionConfig | None = None, client=None,
                 gui_id: str | None = None, popups: bool = True, **kwargs)
```

Creates, in order: `layout_manager` (`LayoutManagerWidget`), `state_manager`, `entry_validator`,
`plot_widget = pg.GraphicsLayoutWidget`, `plot_item = pg.PlotItem(viewBox=BECViewBox(...))`,
`side_panel = SidePanel(self, orientation="left", panel_max_width=280)`, legend, `info_label`
(`PlotInfoLabel`), `tick_item`, `arrow_item`, `toolbar = ModularToolBar(...)`, then
`_init_toolbar()`, `_init_ui()`, `_update_theme(None)`. `popups=False` selects `UIMode.SIDE`.

`BECViewBox` emits `sigPaint` (drives the FPS counter) and honours `item.skip_auto_range` so
crosshair labels do not trigger autorange.

## Signals

`property_changed(str, object)`, `crosshair_position_changed/clicked(tuple)`,
`crosshair_coordinates_changed/clicked/pinned(tuple)`, `crosshair_pin_cleared()`.

## USER_ACCESS (BASE_USER_ACCESS, all getters and setters)

`enable_toolbar`, `enable_side_panel`, `enable_fps_monitor`, `show_info_label`, `set`, `title`,
`x_label`, `y_label`, `x_limits`, `y_limits`, `x_grid`, `y_grid`, `inner_axes`, `outer_axes`,
`lock_aspect_ratio`, `auto_range`, `auto_range_x`, `auto_range_y`, `x_log`, `y_log`,
`legend_label_size`, `minimal_crosshair_precision`, `screenshot`; plus `BECWidget.USER_ACCESS`
(`remove`, `attach`, `detach`).

Subclass: `USER_ACCESS = [*PlotBase.USER_ACCESS, "plot", "clear_all", ...]` and run
`bw-generate-cli --target bec_widgets` (or the plugin) afterwards.

## Properties (SafeProperty; * = auto_emit -> property_changed)

`title*`, `x_label*`, `y_label*`, `x_limits`/`y_limits` (`QPointF`; helper tuples `x_lim`, `x_min`,
`x_max`, ...), `x_grid*`, `y_grid*`, `x_log*`, `y_log*`, `inner_axes*`, `outer_axes*`, `invert_x`,
`invert_y`, `lock_aspect_ratio`, `auto_range_x`, `auto_range_y`, `legend_label_size`,
`minimal_crosshair_precision*`, `show_info_label*`, `enable_popups`, `enable_side_panel`,
`enable_toolbar`, `enable_fps_monitor`, `ui_mode` (plain property, `UIMode`).

Axis label composition: `x_label_combined = x_label + x_label_suffix + " [units]"`; use
`set_x_label_suffix(str)`, `x_label_units = "mm"` (same for y) so user labels survive.

## Methods to know

| method | use |
|---|---|
| `apply_theme(theme)` | override; call `super().apply_theme(theme)`; refresh item colours |
| `add_side_menus()` | override; call `super()` (adds `AxisSettings`); add your `SettingWidget`s |
| `hook_crosshair()` / `unhook_crosshair(preserve_pin=True)` | crosshair lifecycle; `MultiWaveform` overrides `hook_crosshair` |
| `hook_fps_monitor()` / `unhook_fps_monitor(delete_label=True)` | FPS overlay |
| `reset()` (`@SafeSlot()`) | clears crosshair markers; call at new scan |
| `auto_range(value=True)` | autorange over `visible_items` |
| `visible_items` | items excluding crosshair parts - use for range computations |
| `remove_info_label_action()` | for widgets without scan info (Image, MotorMap) |
| `set_scan_info(...)`, `update_scan_info_from_source(source)`, `set_info_label_rows(rows)`, `clear_info_label()` | info label |
| `viewbox_state_changed()` | emits `property_changed` for limits; connected to `vb.sigStateChanged` |
| `cleanup_pyqtgraph(item=None)` | closes/deletes `vb.menu` and `ctrlMenu`; called by `cleanup()` |
| `cleanup()` | toolbar → crosshair(pin=False) → fps → tick/arrow → axis dialog → pyqtgraph menus → `round_plot_widget.close()` → `super().cleanup()` |

## Layout

```
QVBoxLayout(self)
 └─ layout_manager
     ├─ toolbar               (top of fps_label)
     ├─ fps_label (hidden)    (top of plot)
     ├─ side_panel            (left of plot)
     └─ round_plot_widget     (RoundedFrame around plot_widget, variant "plot_background")
```

Add extra widgets with `self.layout_manager.add_widget_relative(widget, self.round_plot_widget, "bottom")`
rather than a new layout; `ImageBase` adds its ROI plots this way.

## Item classes to build on

- `bec_widgets/widgets/plots/waveform/curve.py`: `Curve(BECConnector, pg.PlotDataItem)` with
  `CurveConfig` (label, color, symbol, symbol_size, pen_width, pen_style, source, scan_id,
  scan_number, parent_label) and `DeviceSignal`; `setClipToView(True)` by default;
  `set_data`, `clear_data`, `set_color`, `set_symbol`, `set_pen_width`.
- `scatter_waveform/scatter_curve.py`: `ScatterCurve` with a per-colormap `QBrush` pool.
- `image/image_item.py`: `ImageItem(BECConnector, pg.ImageItem)` with `ImageProcessor`
  (fft, log, rotation, transpose), `set_data(data, transform=None)`, `remove(emit=False)`;
  managed by `ImageLayerManager` in `image_base.py`.
- `utils/crosshair.py`: `Crosshair(plot_item, min_precision)`; items tagged `is_crosshair`.
