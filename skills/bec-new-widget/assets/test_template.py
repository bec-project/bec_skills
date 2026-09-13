"""Unit tests for DeviceReadbackLabel - place in tests/unit_tests/test_device_readback_label.py."""

import pytest
from qtpy.QtCore import QEvent
from qtpy.QtWidgets import QApplication

from bec_widgets.utils.rpc_register import RPCRegister
from bec_widgets.widgets.utility.device_readback_label.device_readback_label import (
    DeviceReadbackLabel,
)

from .client_mocks import mocked_client  # noqa: F401  (fixture)
from .conftest import create_widget


@pytest.fixture
def widget(qtbot, mocked_client):
    return create_widget(qtbot, DeviceReadbackLabel, client=mocked_client, device="samx")


def test_readback_updates_label(widget):
    widget.on_readback({"signals": {"samx": {"value": 1.23456}}}, {"device": "samx"})
    assert widget.label.text() == "1.235"


def test_precision_property_is_applied(widget):
    widget.precision = 1
    widget.on_readback({"signals": {"samx": {"value": 1.23456}}}, {})
    assert widget.label.text() == "1.2"


def test_set_device_swaps_subscription(widget, monkeypatch):
    calls = []
    monkeypatch.setattr(
        widget.bec_dispatcher, "disconnect_slot", lambda slot, topics, cb_info=None: calls.append(topics)
    )
    widget.set_device("samy")
    assert widget.config.device == "samy"
    assert calls and calls[0].endpoint.endswith("samx")


def test_set_device_rejects_unknown_device(widget):
    # SafeSlot swallows exceptions (logs / popup) unless told to raise for this call.
    with pytest.raises(ValueError):
        widget.set_device("does_not_exist", _override_slot_params={"raise_error": True})
    assert widget.config.device == "samx"


def test_move_runs_off_thread(widget, qtbot, monkeypatch):
    moved = []
    monkeypatch.setattr(widget.dev["samx"], "move", lambda pos: moved.append(pos))
    widget.move(2.0)
    qtbot.waitUntil(lambda: moved == [2.0], timeout=2000)


def test_close_runs_cleanup_once_and_unregisters(qtbot, mocked_client):
    w = DeviceReadbackLabel(client=mocked_client, device="samx")
    gui_id = w.gui_id
    assert RPCRegister().get_rpc_by_id(gui_id) is w
    assert w._stale_timer.isActive()

    w.close()
    assert w._destroyed is True
    assert not w._stale_timer.isActive()
    assert RPCRegister().get_rpc_by_id(gui_id) is None

    w.close()  # idempotent
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
