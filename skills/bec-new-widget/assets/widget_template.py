"""<One-line description of the widget - shown as the Qt Designer tooltip.>"""

from __future__ import annotations

from bec_lib.endpoints import MessageEndpoints
from bec_lib.logger import bec_logger
from pydantic import Field
from qtpy.QtCore import QTimer
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget

from bec_widgets.utils.bec_connector import ConnectionConfig
from bec_widgets.utils.bec_widget import BECWidget
from bec_widgets.utils.colors import get_accent_colors
from bec_widgets.utils.error_popups import SafeProperty, SafeSlot

logger = bec_logger.logger


class DeviceReadbackLabelConfig(ConnectionConfig):
    """Persisted configuration of the widget."""

    device: str = Field("samx", description="Device whose readback is displayed.")
    precision: int = Field(3, description="Decimal places.")


class DeviceReadbackLabel(BECWidget, QWidget):
    """Shows the live readback of one device and lets the user move it via RPC."""

    PLUGIN = True
    ICON_NAME = "speed"
    USER_ACCESS = [*BECWidget.USER_ACCESS, "set_device", "move", "precision", "precision.setter"]

    def __init__(
        self,
        parent: QWidget | None = None,
        client=None,
        config: DeviceReadbackLabelConfig | dict | None = None,
        gui_id: str | None = None,
        device: str | None = None,
        **kwargs,
    ):
        if config is None:
            config = DeviceReadbackLabelConfig(widget_class=self.__class__.__name__)
        elif isinstance(config, dict):
            config = DeviceReadbackLabelConfig(**config)
        super().__init__(parent=parent, client=client, config=config, gui_id=gui_id, **kwargs)
        self.config: DeviceReadbackLabelConfig
        self.get_bec_shortcuts()

        self._current_endpoint = None
        # Parented, so Qt deletes it with the widget. A running timer still has to be stopped in
        # cleanup(): close() runs cleanup() and may come long before the actual deletion.
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(5000)
        self._stale_timer.timeout.connect(self._mark_stale)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("-", parent=self)
        layout.addWidget(self.label)

        self.set_device(device or self.config.device)

    # ------------------------------------------------------------------ RPC / public API
    @SafeSlot(str, popup_error=True)
    def set_device(self, device: str) -> None:
        """Switch the displayed device.

        Args:
            device (str): device name known to the BEC device manager.
        """
        if device not in self.dev:
            raise ValueError(f"Device '{device}' is not in the current session.")
        # Disconnect only to re-target; at teardown BECWidget.cleanup() releases every
        # subscription whose owner is this widget (bound methods carry their owner).
        if self._current_endpoint is not None:
            self.bec_dispatcher.disconnect_slot(self.on_readback, self._current_endpoint)
        self.config.device = device
        self._current_endpoint = MessageEndpoints.device_readback(device)
        self.bec_dispatcher.connect_slot(self.on_readback, self._current_endpoint)
        self._stale_timer.start()

    @SafeSlot(float, popup_error=True)
    def move(self, position: float) -> None:
        """Move the device without blocking the GUI thread."""
        self.submit_task(
            self.dev[self.config.device].move, position, on_failed=self._on_move_failed
        )

    @SafeProperty(int, auto_emit=True)
    def precision(self) -> int:
        """Decimal places used for the readback."""
        return self.config.precision

    @precision.setter
    def precision(self, value: int) -> None:
        self.config.precision = max(0, int(value))

    # ------------------------------------------------------------------ slots
    @SafeSlot(dict, dict)
    def on_readback(self, content: dict, metadata: dict) -> None:
        """Dispatcher slot for MessageEndpoints.device_readback(device)."""
        signals = content.get("signals", {})
        value = signals.get(self.config.device, {}).get("value")
        if value is None:
            return
        self.label.setText(f"{value:.{self.config.precision}f}")
        self._stale_timer.start()  # restart the watchdog

    @SafeSlot()
    def _mark_stale(self) -> None:
        self.label.setText(f"{self.label.text()} (stale)")

    @SafeSlot(str)
    def _on_move_failed(self, traceback_text: str) -> None:
        logger.error(f"Move of {self.config.device} failed: {traceback_text}")

    # ------------------------------------------------------------------ theme / lifecycle
    def apply_theme(self, theme: str) -> None:
        colors = get_accent_colors()
        self.label.setStyleSheet(f"color: {colors.default.name()};")

    def cleanup(self) -> None:
        # Only what BECWidget cannot know about. BECWidget.cleanup() already disconnects this
        # widget's dispatcher slots, removes its RPC entry and closes child BECWidgets.
        # Add here: running QTimers, QThreads (quit + wait), ophyd/bec_lib callbacks you subscribed.
        # Without any of those, do not override cleanup() at all.
        self._stale_timer.stop()
        super().cleanup()


if __name__ == "__main__":  # pragma: no cover
    import sys

    from qtpy.QtWidgets import QApplication

    app = QApplication(sys.argv)
    widget = DeviceReadbackLabel(device="samx")
    widget.show()
    sys.exit(app.exec())
