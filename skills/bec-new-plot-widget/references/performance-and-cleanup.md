# Performance patterns and pyqtgraph cleanup

## Throttle everything that redraws

| widget | proxy | rate |
|---|---|---|
| Waveform sync/async | `pg.SignalProxy(self.sync_signal_update, rateLimit=25, slot=self.update_sync_curves)` | 25 Hz |
| Waveform DAP | `BECSignalProxy(self.request_dap_update, rateLimit=25, slot=self.request_dap, timeout=10.0)` | 25 Hz, blocks until `unblock_proxy()` |
| ScatterWaveform, MotorMap | `pg.SignalProxy(..., rateLimit=25)` | 25 Hz |
| Heatmap | `pg.SignalProxy(self.sync_signal_update, rateLimit=5, slot=self.update_plot)` | 5 Hz |
| Crosshair mouse | `pg.SignalProxy(scene().sigMouseMoved, rateLimit=60, ...)` | 60 Hz |

Dispatcher slot bodies stay tiny:

```python
@SafeSlot(dict, dict)
def on_scan_progress(self, msg, meta):
    self.sync_signal_update.emit()
    if msg.get("done"):
        QTimer.singleShot(100, self.update_plot)
        QTimer.singleShot(300, self.update_plot)
```

`BECSignalProxy` (`bec_widgets/utils/bec_signal_proxy.py`): emits once, then blocks and stores
the newest args; `unblock_proxy()` replays only if the args changed; a `timeout` timer unblocks a
lost response. Call its `cleanup()` first in the widget `cleanup()`.

## Update in place

- `curve.setData(x, y)`; `Curve.clear_data()` is `setData([], [])`.
- `image_item.set_data(arr, transform=None)` → `setImage(processed, autoLevels=False)`.
- Async streams: `curve.get_data()` + `np.hstack` for `add`, slice assignment for `add_slice`,
  replace for `replace` (see `Waveform.on_async_readback` docstring: "This code needs to be fast").
- Truncate mismatched lengths (`min_len`) rather than raising; live data arrives per device.

## Large data

```python
if data_length > 1000:
    curve.set_symbol(None); curve.set_pen_width(min(curve.config.pen_width, 3))
    curve.setDownsampling(ds=None, auto=True, method="peak"); curve.setClipToView(True)
```

`clipToView` breaks pyqtgraph's "View All"; `Waveform._connect_viewbox_menu_actions` rebinds that
menu entry to `_reset_view` (clip off → `vb.autoRange()` → clip on).

## Colours without per-point objects

`ScatterCurve._brush_pool(colormap)` builds 256 `QBrush` once per colormap; `_make_z_gradient`
normalises z with numpy and indexes the pool. `MotorMap._update_plot` still builds brushes in a
loop bounded by `num_dim_points` - do not copy that into new code.

## Off-thread computation

`Heatmap._StepInterpolationWorker(QObject)` lives in a `QThread` (`moveToThread`, queued
connections); requests carry `data_version` and `scan_id`, results with a stale stamp are dropped
("Discarding outdated interpolation result."). `_finish_interpolation_thread()` disconnects,
`deleteLater()`s the worker, `quit()` + `wait(3000)` and logs on timeout - called before
`super().cleanup()`. Alternative for one-shot work: `self.submit_task(fn, on_complete=..., on_failed=...)`.

## Global config

No `pg.setConfigOptions(...)`, `useOpenGL`, `antialias` changes inside widgets - the application
decides. GPU rendering helps curves, not images, and breaks `grab()` screenshots.

## FPS monitor

`enable_fps_monitor = True` (or the hidden `fps_monitor` toolbar action) shows paint rate from
`BECViewBox.sigPaint`. Use it while tuning: target stable rendering during a 200-point
`line_scan` with `exp_time=0.02` and during a 1 kHz async stream.

## pyqtgraph cleanup checklist

1. `plot_item.removeItem(item)` before dropping the last reference; for BEC items also
   `item.rpc_register.remove_rpc(item)`; for `ImageItem`: `removeItem` → `item.remove(emit=False)` → `deleteLater()`.
2. Never `plot_item.clear()`; filter `plot_item.items` by `isinstance(item, pg.PlotDataItem) and not getattr(item, "is_crosshair", False)`.
3. `vb.menu` and `ctrlMenu` are closed by `PlotBase.cleanup_pyqtgraph()`; call it for any extra
   `PlotItem` you create (`ImageROIPlot` does).
4. Disconnect what you attached to `plot_item.scene()` (event filters, `sigMouseClicked`) and to
   `vb` signals if the receiver outlives the widget.
5. `unhook_crosshair(preserve_pin=False)` in cleanup (base does it); detached pins are separate items.
6. Toolbar `WidgetAction` widgets: close them yourself; `ToolbarComponents.remove_action(name)` for
   actions you remove at runtime (disconnect the handler first).
7. Order: your proxies → your threads → your dialogs → your items → `super().cleanup()`.
