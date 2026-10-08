---
name: bec-new-scan
description: Write a new BEC scan (step, fly, continuous, time or custom acquisition procedure) using only the v4 ScanBase template - all ten scan hooks, ScanActions/ScanComponents instead of generator stubs, typed ScanArgument parameters, plugin export and v4 tests. Use whenever the user wants to add, implement, port or scaffold a scan for BEC or a beamline plugin repo (debye_bec, csaxs_bec, ...), migrate a legacy generator scan (yield from self.stubs) to v4, or asks how scan_core / prepare_scan / at_each_point should be implemented.
metadata:
  author: bec-project
  version: "0.1"
---

# New BEC scan (v4)

A v4 scan is a plain Python class deriving from `bec_server.scan_server.scans.scan_base.ScanBase`.
A scan implements ten hook methods: the scan server runs eight of them in a fixed order, the
scan calls `at_each_point` itself, and `on_exception` runs on failure. The scan drives devices *directly*
through `self.actions` (`ScanActions`) and reusable building blocks in `self.components`
(`ScanComponents`). There are no generators, no `yield from self.stubs...`, no
`SyncFlyScanBase`/`AsyncFlyScanBase`: that legacy API (`legacy_scans.py`, `ScanStubs`) was removed
in bec 4.0, so a plugin scan still written that way fails to import. If the user hands you a
legacy scan, port it (mapping table in
[references/hooks-and-actions.md](references/hooks-and-actions.md)).

Authoritative in-repo sources when in doubt (the public docs have no scan-authoring page yet):
`bec_server/scan_server/scans/line_scan.py` (step scan), `cont_line_scan.py` (software-managed
continuous), a plugin `HARDWARE_TRIGGERED` scan such as `debye_bec/scans/nidaq_continuous_scan.py`,
and the Jinja template `bec_lib/utils/plugin_manager/create/templates/scan.py.jinja`.

## 1. Decide the shape before writing code

Ask yourself (or the user, if the answer changes the design) three things:

- **Where does it live?** A beamline-specific scan goes into the plugin repo under
  `<plugin>/<plugin>/scans/<scan_name>.py` and must be exported from `scans/__init__.py`
  (`bec.scans` entry point). Only generic scans go into `bec_server/scan_server/scans/`.
- **Who triggers?** `ScanType.SOFTWARE_TRIGGERED` when the scan itself moves, triggers and reads
  at every point (`at_each_point` inside `scan_core`). `ScanType.HARDWARE_TRIGGERED` when a device
  runs the acquisition after `kickoff` and the scan only waits for `complete` while reading
  monitored devices. Devices read `scan_info.scan_type` to decide whether to expect a software
  trigger per point, so this must be honest.
- **What are the inputs?** Fixed parameters become typed `__init__` arguments. Only scans that
  accept a variable number of `(device, start, stop)` bundles use `arg_input` + `arg_bundle_size`
  (see [references/arguments.md](references/arguments.md)).

**Core repo or beamline plugin repo?** Most scan requests come from beamline scientists working in
their plugin repo. Check the repository root first: the core `bec` repo holds `bec_lib/` and
`bec_server/`; a plugin repo has `[project.entry-points."bec.scans"]` in `pyproject.toml` and a
`<plugin>/scans/` package. Then:

- **In a plugin repo, stay there.** Write the scan in `<plugin>/scans/`, import the base classes
  from `bec_server.scan_server.scans...`, never copy a core scan module into the plugin or edit the
  installed `bec_server`.
- **Changing how an existing core scan behaves at one beamline** (an extra detector arm in
  `pre_scan`, a different default `exp_time`) is a `ScanModifier` in the plugin
  (`<plugin>/scans/scan_customization/scan_modifier.py`, entry point `bec.scans.scan_modifier`), not
  a new scan and not a core edit. A plugin scan cannot replace a core scan by reusing its
  `scan_name`: core scans load first and the duplicate is skipped with a `DuplicateScanName` alarm.
  See "Scan modifiers" in [references/hooks-and-actions.md](references/hooks-and-actions.md).
- **In the core repo, keep it generic.** A scan that names a beamline device, an EPICS prefix or a
  beamline workflow belongs in that beamline's plugin repo; core scans live in
  `bec_server/bec_server/scan_server/scans/` and need no export.
- **Ask one short question and wait** when the repository is unknown (no repo, a workspace holding
  several repos, or a plugin and core checkout side by side and the request names neither), when
  you are in core and the request is beamline-specific, or when you are in a plugin and the request
  changes a core scan for everybody. Offer the options (plugin scan, plugin `ScanModifier`, core
  change as a separate bec PR); the user decides. When the repo and the request agree, state the
  choice in one line and continue.

## 2. Scaffold

In a plugin repo prefer the official generator, which renders the scan template, appends the
export to `scans/__init__.py`, wires the plugin's `ScanComponents` subclass if one exists, and
formats:

```bash
bec-plugin-manager create scan <scan_name>
```

It is interactive (name, description, scan type, built-in args, custom args). It does not look at
the current directory: it writes into the one BEC plugin that is installed in editable mode in the
active Python environment (`<repo>/<repo name>/scans/`) and fails if none or several are installed.
Check the target first with
`python -c "from bec_lib.plugin_helper import plugin_repo_path; print(plugin_repo_path())"`; if it
is not the repo you are working in, do not run it. If it cannot run (no TTY, no or the wrong
editable plugin, core repo), copy [assets/v4_scan_template.py](assets/v4_scan_template.py)
and adapt it; it is the rendered template with a complete software-triggered step scan and a
hardware-triggered variant in [assets/hardware_triggered_example.py](assets/hardware_triggered_example.py).

## 3. Implement all ten hooks

The server runs `prepare_scan, open_scan, stage, pre_scan, scan_core, post_scan, unstage,
close_scan` in this order (`SCAN_SEQUENCE` in `direct_scan_worker.py`). `at_each_point` is not in
that sequence: `scan_core` calls it (directly or through `components.step_scan`). `on_exception(exc)`
runs when a hook raises, but only if the queue item still allows cleanup: a halt sets
`run_on_exception_hook` to False and skips it, and so does a worker shutdown or a queue that was
already stopped; otherwise the worker clears the abort event and calls it once. Every hook is `@abstractmethod` on `ScanBase`, so all ten must
exist, each decorated with `@scan_hook` (this is what lets a beamline `ScanModifier` plugin run
code before/after/instead of your hook). Responsibilities:

| hook | must do | typical body |
|---|---|---|
| `__init__` | `super().__init__(**kwargs)`, store args, `self.update_scan_info(...)` with exp_time/relative/..., set `scan_report_devices`, elevate step-scanned motors: `self.actions.set_device_readout_priority(self.motors, priority="monitored")` | no device I/O here - RPC calls are blocked during construction |
| `prepare_scan` | compute `self.positions` (`position_generators.*`), apply `relative` via `self.components.get_start_positions`, `self.components.check_limits`, `update_scan_info(positions=, num_points=, num_monitored_readouts=)`, `add_scan_report_instruction_scan_progress`, start pre-move and baseline read with `wait=False` and keep the statuses | everything that can fail should fail here, before the scan opens |
| `open_scan` | `self.actions.open_scan()` | mandatory, nothing else |
| `stage` | `self.actions.stage_all_devices()` | device-side logic belongs in the device |
| `pre_scan` | `self._premove_motor_status.wait()`, `self.actions.pre_scan_all_devices()` | last chance before time-critical devices start |
| `scan_core` | step: `self.components.step_scan(self.motors, self.positions, at_each_point=self.at_each_point, last_positions=self.positions[0])`; hardware: `if not kickoff(wait=False).wait(timeout=..): raise ScanAbortion(...)`, then loop `while not complete_status.done: self.at_each_point()` | never `time.sleep` for the whole duration - poll `.done` so abort works |
| `at_each_point` | step: `self.components.step_scan_at_each_point(motors, positions, last_positions=...)`; hardware: `self.actions.read_monitored_devices()` | keep it a hook so modifiers can extend it |
| `post_scan` | `status = self.actions.complete_all_devices(wait=False)`, move back if `relative`, `status.wait()` | |
| `unstage` | `self.actions.unstage_all_devices()` | |
| `close_scan` | wait for the baseline status, `self.actions.close_scan()`, `self.actions.check_for_unchecked_statuses()` | the last call turns forgotten statuses into a WARNING alarm instead of silent data loss |
| `on_exception` | return motors to start, stop kicked-off devices, release locks | must not raise |

Rules that follow from how the server works:

- **Every `ScanStatus` must be resolved** with `.wait()` or by checking `.done`. Statuses from
  `wait=False` calls are the only way to overlap work (pre-move during baseline read, complete
  during move-back); never drop them.
- **`self.actions.*` guarded by `@requires_scan_is_running` raise outside a running scan.** Setup
  belongs in `prepare_scan`, not `__init__`; construction-time RPC is blocked by the assembler.
- **Positions are `np.ndarray` of shape `(num_points, len(motors))`**, even for one motor
  (`[:, np.newaxis]`). `num_monitored_readouts` = points x `burst_at_each_point`.
- **Abort-friendliness:** the worker checks for an abort between hooks, and inside a hook only
  when the scan calls `self.actions` (every device instruction checks first); once an abort is
  requested, `status.done` returns `True` and `status.wait()` returns early. So long loops call
  actions or poll statuses and sleep in short slices; a hook that only sleeps or computes cannot
  be aborted.
- **Do not rely on `status.wait(timeout=...)` raising.** It raises `TimeoutError` up to bec 4.1.4;
  bec#1118 makes it return `False` instead. Write `if not status.wait(timeout=t): raise
  ScanAbortion(...)` (`bec_server.scan_server.errors`), which is correct with both.
- **Poll on `.done`, never `while not status.wait(timeout=t)`.** With bec#1118, `wait()` returns
  `False` immediately on every call once an abort was requested, so that loop spins at full CPU
  and never ends unless its body calls `self.actions`. `while not status.done:` with a short
  `time.sleep` inside ends on abort and works with every bec version.
- `scan_name` must be a valid identifier and unique across core + plugin scans (duplicates are
  skipped with an alarm). Keep the module docstring listing the hook order - the template does.

## 4. Arguments, GUI and docs

Type every argument with `Annotated[T, ScanArgument(display_name=..., description=...,
gt/ge/lt/le=..., units=..., reference_units="device")]` or the shared aliases `DefaultArgType.Relative`, `.ExposureTime`,
`.FramesPerTrigger`, `.SettlingTime`, `.SettlingTimeAfterTrigger`, `.ReadoutTime`,
`.BurstAtEachPoint`, `.Snaked`, `.OptimizeTrajectory`. A required argument is one without a
default; it can be positional (`device, start, stop, steps` in the template) or keyword-only after
`*` (`*, relative: DefaultArgType.Relative`), which forces callers to name it.
`ScanInputValidator` enforces these
on client and server, and the ScanControl widget builds its form from them. `gui_config`
groups (`{"Movement Parameters": [...], "Acquisition Parameters": [...]}`) must list every keyword
argument a GUI user has to set: ScanControl shows only the listed ones, and nothing checks the
names, so a misspelt or forgotten entry silently drops that field from the form. Wrap the
parameter list in `# fmt: off` / `# fmt: on` (after `self`, before `**kwargs`) with one argument
per line, as the templates do, so black does not explode the `Annotated[...]` types.

`scans.<name>.__doc__` is rebuilt from the signature rather than copied: when your docstring has
an `Args:` section, the text before it plus its `Returns:` / `Raises:` sections are kept, the
`Args:` lines come from each `ScanArgument.description`, and `Examples:` is generated (a
hand-written one there is dropped). So give every `ScanArgument` a `description` and leave out a
hand-written `Examples:` block; the exact rules and exceptions are in the reference. Details and the `*args` bundle
mechanism: [references/arguments.md](references/arguments.md).

## 5. Tests

Use the shared scan fixtures and hook assertions from `bec_server` (a `dev` extra of every plugin
repo), never hand-rolled device mocks:

```python
from bec_server.scan_server.tests.scan_fixtures import nth_done_status_mock, readout_priority, scan_assembler
from bec_server.scan_server.tests.scan_hook_tests import DEFAULT_HOOK_TESTS, PREMOVE_HOOK_TESTS, STANDARD_STEP_SCAN_TESTS, run_scan_tests
```

The fixture was renamed in bec 4.0: `v4_scan_assembler` still works but emits a
`DeprecationWarning` on every use, so new tests use `scan_assembler` (and existing plugin tests
can switch). The other fixtures it needs (`device_manager`, `session_from_test_config`) come from
the `bec_lib` pytest plugin automatically.

`scan_assembler("<scan_name>", *args, **kwargs)` builds the scan through the real
`ScanAssembler` with mocked devices (limits -10..10) and marks the scan as running so
`self.actions` calls work. Cover: (a) the default hook contracts via
`run_scan_tests(scan, [...])` - pick `DEFAULT_HOOK_TESTS` for every scan, `PREMOVE_HOOK_TESTS`
when you pre-move, `STANDARD_STEP_SCAN_TESTS` for step scans; (b) `prepare_scan` positions,
`num_points`, `scan_report_instructions`, limit errors; (c) `scan_core` for hardware-triggered
scans with `scan.actions.kickoff/complete` mocked and `nth_done_status_mock(resolve_after=N)`;
(d) `on_exception` restores state. Template: [assets/test_template.py](assets/test_template.py).
Run with `python -m pytest --random-order -q tests/tests_scans/test_<scan_name>.py` in a plugin
repo. In core the tests go to `bec_server/tests/tests_scan_server/scans/test_<scan_name>.py`, where
the conftest already registers the fixtures (drop the fixture import).

## 6. Wire it up and verify live

1. Plugin repo: export `from .<scan_name> import <ScanName>` in `scans/__init__.py` (the entry
   point `bec.scans` must point at that package in `pyproject.toml`); plugin discovery only sees
   classes importable from that package. Core repo: no export - the scan server imports every
   module in `bec_server/scan_server/scans/` itself.
2. Reload a running scan server without restart: from the client
   `bec.connector.send(MessageEndpoints.service_request(), messages.ServiceRequestMessage(action="reload_scans"))`,
   or restart `bec-scan-server`. The scan then appears as `scans.<scan_name>` with signature and
   docstring; check `scans.<scan_name>?` in the IPython client.
3. If simulated devices are available, run it once end to end and inspect `bec.queue` / the scan
   report; a scan that opens but never closes usually means an unresolved status.
4. Format: `black --line-length=100 --skip-magic-trailing-comma` and `isort --profile=black`.

## Deliverable checklist

- [ ] `ScanBase` from `scans.scan_base`, `scan_type` honest, `scan_name` unique identifier
- [ ] ten `@scan_hook` methods, `open_scan`/`close_scan` call the actions of the same name,
      `check_for_unchecked_statuses()` last
- [ ] no `yield`, no `self.stubs`, no legacy attributes (`required_kwargs`, `pre_move`,
      `return_to_start_after_abort`, `scan_report_hint`, `ScanArgType`)
- [ ] every `wait=False` status awaited; motors elevated to `monitored` if step-scanned
- [ ] typed arguments with `description`s inside `# fmt: off`/`on` + `gui_config` + summary docstring
- [ ] right repo (plugin scan, plugin `ScanModifier` or core), asked when unclear
- [ ] plugin: exported in `scans/__init__.py`; tests with `scan_assembler` pass in random order
