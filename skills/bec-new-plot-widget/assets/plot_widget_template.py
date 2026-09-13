"""<One-line description of the plot widget.>"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from bec_lib.endpoints import MessageEndpoints
from bec_lib.logger import bec_logger
from qtpy.QtCore import QTimer, Signal
from qtpy.QtWidgets import QWidget

from bec_widgets.utils.colors import Colors
from bec_widgets.utils.error_popups import SafeProperty, SafeSlot
from bec_widgets.utils.toolbars.actions import MaterialIconAction
from bec_widgets.utils.toolbars.bundles import ToolbarBundle
from bec_widgets.widgets.plots.plot_base import PlotBase
from bec_widgets.widgets.plots.waveform.curve import Curve, CurveConfig

logger = bec_logger.logger


class DeviceVsIndexPlot(PlotBase):
    """Plots one monitored signal of the running scan against the point index."""

    PLUGIN = True
    RPC = True
    ICON_NAME = "show_chart"
    USER_ACCESS = [*PlotBase.USER_ACCESS, "plot", "clear_all", "normalize", "normalize.setter"]

    sync_signal_update = Signal()

    def __init__(
        self, parent: QWidget | None = None, config=None, client=None, gui_id=None, popups=True, **kwargs
    ):
        super().__init__(
            parent=parent, config=config, client=client, gui_id=gui_id, popups=popups, **kwargs
        )
        self._curves: dict[str, Curve] = {}
        self._normalize = False
        self.scan_item = None
        self.scan_id: str | None = None

        # dispatcher slot -> signal -> throttled update (25 Hz)
        self.proxy_update = pg.SignalProxy(
            self.sync_signal_update, rateLimit=25, slot=self.update_plot
        )
        self.bec_dispatcher.connect_slot(self.on_scan_status, MessageEndpoints.scan_status())
        self.bec_dispatcher.connect_slot(self.on_scan_progress, MessageEndpoints.scan_progress())

        self._init_toolbar_device_vs_index()
        self.x_label = "point index"

    # ------------------------------------------------------------------ toolbar
    def _init_toolbar_device_vs_index(self) -> None:
        self.toolbar.components.add_safe(
            "normalize",
            MaterialIconAction(
                icon_name="percent", tooltip="Normalize to maximum", checkable=True, parent=self
            ),
        )
        bundle = ToolbarBundle("device_vs_index", self.toolbar.components)
        bundle.add_action("normalize")
        self.toolbar.add_bundle(bundle)
        self.toolbar.components.get_action("normalize").action.toggled.connect(self._set_normalize)
        shown = list(self.toolbar.shown_bundles)
        shown.insert(shown.index("axis_popup"), "device_vs_index")
        self.toolbar.show_bundles(shown)

    # ------------------------------------------------------------------ public API
    @SafeSlot(str, popup_error=True)
    def plot(self, device: str) -> Curve:
        """Add a curve for the monitored device.

        Args:
            device (str): device name; its default signal is used.
        """
        if device in self._curves:
            return self._curves[device]
        # Curves need an explicit colour; pick the next one from a palette like Waveform does.
        palette = Colors.golden_angle_color(
            colormap="plasma", num=max(10, len(self._curves) + 1), format="HEX"
        )
        config = CurveConfig(
            widget_class="Curve", label=device, source="device", color=palette[len(self._curves)]
        )
        curve = Curve(config=config, name=device, parent_item=self)
        self.plot_item.addItem(curve)
        self._curves[device] = curve
        self.sync_signal_update.emit()
        QTimer.singleShot(150, self.auto_range)  # autorange once the item is painted
        return curve

    @SafeSlot()
    def clear_all(self) -> None:
        """Remove every curve."""
        for curve in list(self._curves.values()):
            self.plot_item.removeItem(curve)
            curve.rpc_register.remove_rpc(curve)
        self._curves.clear()

    @SafeProperty(bool, auto_emit=True)
    def normalize(self) -> bool:
        """Divide every curve by its maximum."""
        return self._normalize

    @normalize.setter
    def normalize(self, value: bool) -> None:
        self._normalize = bool(value)
        self.sync_signal_update.emit()

    # ------------------------------------------------------------------ slots
    @SafeSlot(bool)
    def _set_normalize(self, checked: bool) -> None:
        self.normalize = checked

    @SafeSlot(dict, dict)
    def on_scan_status(self, msg: dict, meta: dict) -> None:
        scan_id = msg.get("scan_id")
        if scan_id is None or scan_id == self.scan_id:
            return
        self.scan_id = scan_id
        self.scan_item = self.queue.scan_storage.find_scan_by_ID(scan_id)
        self.reset()  # crosshair markers
        self.update_scan_info_from_source(self.scan_item)
        for curve in self._curves.values():
            curve.clear_data()

    @SafeSlot(dict, dict)
    def on_scan_progress(self, msg: dict, meta: dict) -> None:
        self.sync_signal_update.emit()
        if msg.get("done"):
            QTimer.singleShot(100, self.update_plot)
            QTimer.singleShot(300, self.update_plot)

    @SafeSlot()
    def update_plot(self) -> None:
        """Pull live data for every curve and push it with setData (no item churn)."""
        if self.scan_item is None:
            return
        live = getattr(self.scan_item, "live_data", None)
        if live is None:
            return
        for device, curve in self._curves.items():
            try:
                y = np.asarray(live[device][device].val, dtype=float)
            except (KeyError, AttributeError):
                continue
            if y.size == 0:
                continue
            if self._normalize and np.nanmax(np.abs(y)) > 0:
                y = y / np.nanmax(np.abs(y))
            curve.setData(np.arange(y.size), y)

    # ------------------------------------------------------------------ theme / lifecycle
    def apply_theme(self, theme: str) -> None:
        # Called once from PlotBase.__init__ BEFORE this subclass' __init__ body ran, so every
        # subclass attribute used here must be read defensively.
        super().apply_theme(theme)
        for curve in getattr(self, "_curves", {}).values():
            curve.set_color(curve.config.color)  # re-resolve palette-dependent colours

    def cleanup(self) -> None:
        self.proxy_update.disconnect()
        self.clear_all()
        super().cleanup()


if __name__ == "__main__":  # pragma: no cover
    import sys

    from qtpy.QtWidgets import QApplication

    app = QApplication(sys.argv)
    w = DeviceVsIndexPlot()
    w.plot("bpm4i")
    w.show()
    sys.exit(app.exec())
