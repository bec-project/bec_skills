---
name: bec-widget-safety-audit
description: Audit existing BEC widgets for Qt lifecycle and thread safety - cleanup contract, the three destruction paths (close, deleteLater, plain Qt parent), dispatcher subscriptions, deferred callbacks into closed widgets, signal proxies that keep delivering, Qt objects touched from threads, BEC widgets in table cells, singletons, item-model contracts and crashes at exit. Static sweep plus runtime probes built on the packaged bec_widgets test fixtures, crash-prone scenarios in child processes, every finding backed by a failing test. Use whenever the user asks whether a widget, plot or widget folder (bec_widgets or a beamline plugin repo) is safe, leaks, crashes or freezes on close, reports "Internal C++ object already deleted", a segfault, timers or callbacks firing after close, or wants a widget checked before a release. For reviewing a PR diff use bec-focused-review or bec-deep-review instead.
metadata:
  author: bec-project
  version: "0.1"
---

# BEC widget safety audit

Audits code that already exists - one widget, a plot family or a whole widget folder - for the
defects that crash or corrupt a running BEC GUI: resources that outlive the widget, callbacks into
closed or deleted objects, Qt calls from the wrong thread, native crashes. It is not a diff
review: for a PR use `bec-focused-review` or `bec-deep-review`.

The deliverable is a report (template at the end) in which every CONFIRMED finding comes with a
failing test the developer can run. Do not change the widget's source unless the user asks
afterwards; probes and scratch tests live on a separate branch or worktree and are not committed
or pushed without the user's word.

Read [references/lifecycle.md](references/lifecycle.md) first (what `BECWidget` already
releases, the three destruction paths) and keep
[references/defect-classes.md](references/defect-classes.md) open: it lists, per defect class,
where it hides, how to prove it and the fix.

## 0. Target and setup

1. **Pin the target.** List the widget classes in scope with their modules. In core that is
   `bec_widgets/widgets/<domain>/<name>/`; in a beamline plugin repo
   `<plugin>/bec_widgets/widgets/<name>/`. For a plugin widget that subclasses a core widget,
   audit the plugin code, and report defects that sit in the inherited core class separately as
   core issues (with the bec_widgets version they were seen in).
2. **Work outside the user's checkout.** `git worktree add ../<repo>_audit-<name> <ref>` (or the
   harness's worktree tool) on the commit to audit, usually the repository's `main`.
3. **Environment.** The probes need the fixtures shipped with bec_widgets >= 3.38:
   `python -c "import bec_widgets.tests.fixtures"` must succeed (otherwise ask the user to
   upgrade bec_widgets), plus pytest-qt and fakeredis (`pip install "bec_widgets[dev]"`). The
   widget-test folder (`tests/unit_tests/` in core, `tests/tests_bec_widgets/` in a plugin) needs a
   `conftest.py` with:

   ```python
   from bec_widgets.tests.fixtures import *  # noqa: F401,F403
   from bec_widgets.tests.utils import create_widget  # noqa: F401
   ```
4. **Offscreen and mocked only.** Run everything with `QT_QPA_PLATFORM=offscreen` and
   `BEC_WIDGETS_OPENGL=0`, against the mocked client of the fixtures; never against a running BEC,
   Redis on the default port or hardware.

## 1. Static sweep - inventory per widget class

For each class read `__init__`, every method it connects to a signal, and `cleanup()`. Write down
a small inventory and match each entry to its release:

| created in the widget | released where? | class |
|---|---|---|
| `QTimer`, `QThread`, own `QThreadPool`, `threading.Thread` | `cleanup()` stops / joins | C1 |
| `pg.SignalProxy` / `BECSignalProxy` | `cleanup()`: disconnect + stop delivery timer + drop args | C5 |
| `QTimer.singleShot`, queued invokes, retry loops | guarded against close / deletion | C4 |
| dispatcher `connect_slot` (lambda/partial? scan-scoped?) | `owner=self`, swapped per scan | C6 |
| ophyd / bec_lib callbacks, application-wide signals, event filters, override cursor | `cleanup()` | C1, C10 |
| work in `submit_task` / threads / ophyd callbacks that touches Qt | must not | C7 |
| BEC widgets in table/tree/list cells | rows removed before `super().cleanup()` | C8 |
| singletons, module globals, references to other widgets | lifetime handled | C9, C12 |
| item models | begin/end protocol, flat-model `rowCount` | C11 |

Useful starting points (read every hit, do not report grep matches as findings):

```bash
grep -rnE "QTimer\(|singleShot|QThread|QThreadPool\(|threading\.Thread|SignalProxy|connect_slot\(|subscribe\(|callbacks\.register|installEventFilter|setOverrideCursor|UniqueConnection|setCellWidget|setItemWidget|setIndexWidget|sender\(\)|_instance\b" <widget package>
```

Also check the class against the base contract: `class X(BECWidget, <one Qt class>)`, every
connected method decorated with `@SafeSlot`, `cleanup()` ending with `super().cleanup()`, and
no teardown in `closeEvent`/`__del__` (C2). Each mismatch is a candidate with a concrete failure
scenario ("closing the dock while a scan streams data leaves `proxy_update` ticking").

## 2. Runtime probes

Copy [assets/probe_test_template.py](assets/probe_test_template.py) next to the widget tests as
`test_<widget>_safety.py`, one copy per widget class, and fill in the marked block: the widget
import (also as a string for the child-process probes), constructor kwargs, every
`(signal, slot)` pair that feeds a signal proxy or deferred update, and `exercise()` - what makes
the widget busy before it is closed (subscribe to a device, feed a dispatcher slot with a
hand-built message, start a scan with `create_dummy_scan_item`). The probes:

| probe | catches |
|---|---|
| `test_close_stops_timers_and_signal_proxies` | timers and proxy delivery timers still running, queued proxy args kept (C1, C5) |
| `test_no_queued_update_runs_after_close` | slots fed by proxies or deferred calls running after close (C4, C5) |
| `test_close_releases_dispatcher_slots_and_rpc_entry` | subscriptions and RPC entries left after close (C6) |
| `test_cleanup_runs_exactly_once` | cleanup skipped or repeated across close / close / deleteLater (C2) |
| `test_delete_through_plain_qt_parent` | timers and top-level windows left when no `cleanup()` runs (C3) |
| `test_create_close_cycle_returns_to_baseline` | growth of subscriptions, RPC entries, threads over 10 cycles (C1, C6) |
| `test_teardown_and_exit_do_not_crash` | native crashes at teardown and interpreter exit, in a child process (C8, C13) |

Run the module on its own first, so a native crash cannot hide behind other tests:

```bash
QT_QPA_PLATFORM=offscreen BEC_WIDGETS_OPENGL=0 PYTHONFAULTHANDLER=1 \
  python -m pytest -p no:cacheprovider --random-order -q tests/<folder>/test_<widget>_safety.py
```

If pytest itself dies (`Fatal Python error: Segmentation fault`), the faulthandler trace names the
test: move that scenario into a `run_isolated(...)` probe so it fails with `rc=-11` instead of
killing the session. Add targeted probes for what the template cannot do generically: two scans
through scan-scoped slots (C6), a deleted target under an open editor (C12), a failing singleton
`__init__` (C9), `QAbstractItemModelTester` on a mutating model (C11), a filled item view whose
owner is closed (C8, in `run_isolated`). Run every probe at least twice with `--random-order`;
crashes that depend on GC order (C13) need several runs.

## 3. Verify and classify

- **CONFIRMED**: a probe fails for the stated reason - read the assertion or traceback, do not
  accept any failure. A probe that passes refutes the candidate unless it could not reach the
  path; then say why.
- **PLAUSIBLE**: static evidence and a realistic trigger, but no deterministic probe (thread
  races, C7). Keep it, with the trigger spelled out.
- **REFUTED**: the guard exists (quote the line) or the probe passes on the path.
- Check each CONFIRMED finding against the repository's current `main`: if it is already fixed
  there, say so instead of reporting it as open. Check open issues and PRs for the same defect
  and link them.
- Severity: crash > callback into a closed or deleted widget > leak > wrong behaviour.
  A defect that needs an unusual destruction path (C3) is still real; say how the widget is used
  in practice (docked, embedded in a plugin container, created by RPC) so the reader can rank it.

## 4. Report

```
## Widget safety audit: <widgets> @ <repo> <commit> - <verdict: safe / safe with fixes / unsafe>
Scope: <classes and files>. Environment: bec_widgets <version>, PySide6 <version>, offscreen.
Probes: <test files> -> <passed/failed/crashed counts>, <n> runs with --random-order.

### Findings (most severe first)
#### 1. [<class C1-C13>] <one-line defect> - <file>:<line> (<CONFIRMED|PLAUSIBLE>)
Trigger and impact in 2-4 sentences (what the user does, what breaks).
Proof: <test id> -> <decisive assertion / rc=-11 / traceback line>.
Fix: <specific change, see defect-classes.md>.

### In inherited core code (plugin audits only)
- <core file>:<line> - <defect>, seen with bec_widgets <version>; report upstream.

### Checked and found sound
- <resource or path checked> - <evidence>.
```

The probe files go to the user as they are (they are the reproducers). Unless asked, do not open
issues, PRs or comments, and do not commit the probes to the audited branch.
