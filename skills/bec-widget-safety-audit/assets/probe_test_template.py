"""Lifecycle and teardown probes for one BEC widget.

Copy next to the widget tests: tests/unit_tests/test_<widget>_safety.py in core bec_widgets, or
tests/tests_bec_widgets/test_<widget>_safety.py in a beamline plugin repo. The conftest of that
folder must star-import ``bec_widgets.tests.fixtures`` (bec_widgets >= 3.38). Fill in the block
marked FILL IN, run with ``--random-order``; every failing probe names the leaked resource.

The probes check the state a widget leaves behind, not only which slots ran: a pyqtgraph
``SignalProxy`` or a timer created outside ``qtpy`` escapes the autouse leak check, and a widget
deleted through a plain Qt parent never runs ``cleanup()``. Scenarios that can segfault run in a
child process (``run_isolated``) so a crash fails one test instead of killing pytest. A badly
broken widget can still crash the in-process probes: run this module on its own with
``PYTHONFAULTHANDLER=1``; the trace names the test, then move that scenario into ``run_isolated``.
"""

import os
import subprocess
import sys
import textwrap
import threading
from unittest import mock

import pytest
import shiboken6
from pyqtgraph import SignalProxy
from qtpy.QtCore import QObject
from qtpy.QtWidgets import QApplication, QWidget

from bec_widgets.tests.utils import create_widget, process_all_deferred_deletes
from bec_widgets.utils.rpc_register import RPCRegister

# isort: split
# ---------------------------------------------------------------- FILL IN
# The widget under test (core: bec_widgets.widgets..., plugin: <plugin>.bec_widgets.widgets...),
# the same import as a string for the child-process probes, and constructor kwargs.
from bec_widgets.widgets.plots.waveform.waveform import Waveform as WIDGET_CLS

WIDGET_IMPORT = "from bec_widgets.widgets.plots.waveform.waveform import Waveform as WIDGET_CLS"
WIDGET_KWARGS: dict = {}

# (signal attribute, slot name): signals that queue work (typically into a SignalProxy) and the
# slot that finally runs it. Emitted right before close; the slot must not run afterwards.
PENDING_UPDATES = [("sync_signal_update", "update_sync_curves")]


def exercise(widget) -> None:
    """Drive the widget into a busy state before it is closed (subscribe, start timers, ...)."""


# ---------------------------------------------------------------- helpers


def _timers_and_proxies(widget):
    """Snapshot every QTimer and SignalProxy the widget can reach, as (label, object) pairs.

    Covers QTimer children (parented) and QTimer / SignalProxy attributes of the widget and of its
    Python-side children (unparented ones are the dangerous ones).
    """
    found = {}
    owners = [widget] + [c for c in widget.findChildren(QObject) if hasattr(c, "__dict__")]
    for owner in owners:
        if owner is not widget and owner.inherits("QTimer"):
            found[id(owner)] = (f"child QTimer {owner.objectName() or hex(id(owner))}", owner)
        for name, value in list(vars(owner).items()):
            if isinstance(value, SignalProxy) or (
                isinstance(value, QObject) and shiboken6.isValid(value) and value.inherits("QTimer")
            ):
                found[id(value)] = (f"{type(owner).__name__}.{name}", value)
    return list(found.values())


def _still_running(obj) -> str | None:
    """Return why a timer or proxy is still live, or None."""
    if isinstance(obj, SignalProxy):
        inner = getattr(obj.timer, "timer", obj.timer)  # pyqtgraph ThreadsafeTimer wraps a QTimer
        if shiboken6.isValid(inner) and inner.isActive():
            return "delivery timer still active"
        if obj.args is not None:
            return "queued arguments kept (delivered on the next tick)"
        return None
    if shiboken6.isValid(obj) and obj.isActive():
        return "still active"
    return None


def _owned_slots(dispatcher, widget) -> int:
    # Private bookkeeping of BECDispatcher; adapt if it changes.
    return sum(
        1
        for slot in dispatcher._registered_slots.values()
        if slot.cb_owner is not None and slot.cb_owner() is widget
    )


def _settle(qtbot, ms=300):
    qtbot.wait(ms)
    process_all_deferred_deletes(QApplication.instance())


def run_isolated(body: str, timeout: float = 60) -> subprocess.CompletedProcess:
    """Run a widget scenario in a fresh offscreen interpreter with the mocked BEC client.

    A segfault shows up as a negative return code (-11 SIGSEGV, -10 SIGBUS) instead of killing
    the test session. ``body`` sees ``app``, ``WIDGET_CLS`` and ``flush()``.
    """
    script = "\n".join(
        [
            "import faulthandler, gc, os, sys",
            "faulthandler.enable()",
            "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')",
            "from unittest import mock",
            "from qtpy.QtWidgets import QApplication",
            "app = QApplication(sys.argv)",
            "from bec_widgets.tests.utils import mock_client, process_all_deferred_deletes",
            "from bec_widgets.utils import bec_dispatcher as _bd",
            "_patch = mock.patch.object(_bd, 'BECClient', mock_client)",
            "_patch.start()",
            WIDGET_IMPORT,
            "def flush():",
            "    app.processEvents()",
            "    process_all_deferred_deletes(app)",
            textwrap.dedent(body),
            "flush()",
            # same teardown as the bec_dispatcher fixture, so the process can exit
            "_d = _bd.BECDispatcher()",
            "_d.disconnect_all()",
            "_d.client.shutdown()",
            "_d.stop_cli_server()",
            "_patch.stop()",
            "gc.collect()",
        ]
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONFAULTHANDLER="1")
    return subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=timeout, env=env
    )


def crash_report(result: subprocess.CompletedProcess) -> str:
    """Return code plus the Python frames faulthandler printed (the native frames are noise)."""
    lines = result.stderr.splitlines()
    keep = [l for l in lines if l.startswith(("Fatal Python error", "  File ", "Traceback"))]
    return f"rc={result.returncode}\n" + "\n".join(keep or lines[-40:])


# ---------------------------------------------------------------- probes


@pytest.fixture
def widget(qtbot, mocked_client):
    w = create_widget(qtbot, WIDGET_CLS, client=mocked_client, **WIDGET_KWARGS)
    exercise(w)
    return w


def test_close_stops_timers_and_signal_proxies(widget, qtbot):
    for signal_name, _ in PENDING_UPDATES:
        getattr(widget, signal_name).emit()  # leave an emission queued at close time
    snapshot = _timers_and_proxies(widget)
    widget.close()
    _settle(qtbot, 100)
    live = [f"{label}: {why}" for label, obj in snapshot if (why := _still_running(obj))]
    assert not live, "after close():\n" + "\n".join(live)


@pytest.mark.parametrize("signal_name, slot_name", PENDING_UPDATES)
def test_no_queued_update_runs_after_close(qtbot, mocked_client, signal_name, slot_name):
    calls = []

    def record(self, *args, **kwargs):  # records only; the real slot is not needed here
        calls.append(args)

    # Patch the class before construction: connections made in __init__ bind the method then.
    with mock.patch.object(WIDGET_CLS, slot_name, record):
        w = create_widget(qtbot, WIDGET_CLS, client=mocked_client, **WIDGET_KWARGS)
        exercise(w)
        _settle(qtbot)  # drain construction-time emissions
        calls.clear()
        getattr(w, signal_name).emit()
        w.close()
        _settle(qtbot, 500)
    assert not calls, f"{slot_name} ran {len(calls)}x after close()"


def test_close_releases_dispatcher_slots_and_rpc_entry(widget, qtbot, bec_dispatcher):
    gui_id = widget.gui_id
    widget.close()
    _settle(qtbot)
    assert _owned_slots(bec_dispatcher, widget) == 0
    assert gui_id not in RPCRegister().list_all_connections()


def test_cleanup_runs_exactly_once(qtbot, mocked_client):
    # Not registered with qtbot: the widget is deleted here, so pytest-qt must not close it again.
    w = WIDGET_CLS(client=mocked_client, **WIDGET_KWARGS)
    exercise(w)
    with mock.patch.object(
        WIDGET_CLS, "cleanup", autospec=True, side_effect=WIDGET_CLS.cleanup
    ) as spy:
        w.close()
        w.close()
        w.deleteLater()
        _settle(qtbot)
    assert spy.call_count == 1


def test_delete_through_plain_qt_parent(qtbot, mocked_client, bec_dispatcher):
    """The third destruction path: no closeEvent, no Python deleteLater, so no cleanup()."""
    app = QApplication.instance()
    before = set(app.topLevelWidgets())
    parent = QWidget()
    w = WIDGET_CLS(parent=parent, client=mocked_client, **WIDGET_KWARGS)
    exercise(w)
    gui_id = w.gui_id
    snapshot = _timers_and_proxies(w)
    parent.deleteLater()  # plain QWidget: deletes its children in C++
    _settle(qtbot)
    bec_dispatcher.cleanup_dead_slots()
    # Top-level windows the widget created (menus, popups, dialogs) that only cleanup() closes.
    # Close them here so the leftovers do not fail every later test.
    leftovers = [t for t in app.topLevelWidgets() if t not in before]
    names = [type(t).__name__ for t in leftovers]
    for t in leftovers:
        t.close()
        t.deleteLater()
    _settle(qtbot)
    live = [f"{label}: {why}" for label, obj in snapshot if (why := _still_running(obj))]
    assert not live, "after the parent was deleted:\n" + "\n".join(live)
    assert not names, f"top-level widgets left behind: {names}"
    assert gui_id not in RPCRegister().list_all_connections()


def test_create_close_cycle_returns_to_baseline(qtbot, mocked_client, bec_dispatcher):
    def counts():
        return (
            len(bec_dispatcher._registered_slots),
            len(RPCRegister().list_all_connections()),
            threading.active_count(),
        )

    w = create_widget(qtbot, WIDGET_CLS, client=mocked_client, **WIDGET_KWARGS)
    w.close()
    _settle(qtbot)
    baseline = counts()
    for _ in range(10):
        w = create_widget(qtbot, WIDGET_CLS, client=mocked_client, **WIDGET_KWARGS)
        exercise(w)
        w.close()
        _settle(qtbot, 50)
    _settle(qtbot)
    assert counts() == baseline, "(dispatcher slots, RPC entries, threads) grew"


def test_teardown_and_exit_do_not_crash():
    result = run_isolated("""
        w = WIDGET_CLS()
        w.show()
        flush()
        w.close()
        w.deleteLater()
        """)
    assert result.returncode == 0, crash_report(result)
