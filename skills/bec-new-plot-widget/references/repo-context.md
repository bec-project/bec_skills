# Core repo or beamline plugin repo?

Most people who ask for a widget or a plot are beamline scientists working in their beamline's
plugin repository, not core developers. Decide which kind of repository the task
belongs to **before** writing code, because it changes where files go, how they are tested and
what you may touch.

## Recognise the repository you are in

Look at the repository root of the current working directory (`git rev-parse --show-toplevel`):

| signal | repository |
|---|---|
| `pyproject.toml` has `name = "bec_widgets"` | core `bec_widgets` |
| `pyproject.toml` has `name = "bec_server"` / `"bec_lib"`, or the root holds `bec_lib/` and `bec_server/` | core `bec` |
| `pyproject.toml` has `name = "ophyd_devices"` | core `ophyd_devices` |
| `.copier-answers.yml` with `_src_path: ...plugin_copier_template...`, and/or `pyproject.toml` with `[project.entry-points."bec"] plugin_bec = "<pkg>"` | beamline plugin repo `<pkg>` (`csaxs_bec`, `debye_bec`, ...) |
| none of the above (home directory, a workspace holding several repos, a loose script) | unknown - ask |

A plugin repo has the template layout: `<pkg>/bec_widgets/widgets/`, `<pkg>/scans/`,
`<pkg>/devices/`, `<pkg>/device_configs/`, and `tests/tests_bec_widgets/`, `tests/tests_scans/`,
`tests/tests_devices/`. `.copier-answers.yml` also records the template version (`_commit`).

## Decide where the work goes

- **In a plugin repo, stay in the plugin repo.** Put the new code in the plugin package and import
  core classes from their public modules (`bec_widgets.utils.bec_widget`,
  `bec_widgets.widgets.plots.plot_base`, `bec_server.scan_server.scans...`,
  `ophyd_devices...`). Extend core behaviour by subclassing or composing, never by copying a core
  module into the plugin or editing the installed `bec_widgets` / `bec_lib` / `ophyd_devices`
  package (site-packages or an editable checkout the user did not point you at).
- **In a core repo, keep it generic.** Anything that names a beamline, a specific EPICS prefix or a
  beamline workflow belongs in that beamline's plugin repo; propose that instead of adding it to
  core.

## Ask instead of guessing

Ask one short question (and wait) when:

- the repository is unknown (table above), or several candidate repos are checked out next to each
  other and the request does not name one;
- you are in a core repo but the request is beamline-specific ("a panel for the Debye mono", "our
  X-ray eye"): offer to put it in the plugin repo;
- you are in a plugin repo but the request changes core behaviour ("make Waveform also do X",
  "fix the scan queue widget"): offer a plugin subclass/composition now, or a core change (separate
  repo and PR) - the user decides;
- the plugin repo's installed `bec_widgets` is too old for what the skill relies on (see the
  version check in the skill's testing section).

Do not ask when the signals agree with the request; state the choice in one line and continue.

## What differs between the two

| | core `bec_widgets` | plugin repo `<pkg>` |
|---|---|---|
| widget package | `bec_widgets/widgets/<domain>/<name>/` | `<pkg>/bec_widgets/widgets/<name>/` |
| scaffold | by hand | `bec-plugin-manager create widget <name>` (copier) |
| RPC client | `bw-generate-cli --target bec_widgets` | `bw-generate-cli --target <pkg>` |
| widget tests | `tests/unit_tests/test_<name>.py` | `tests/tests_bec_widgets/test_<name>.py` |
| test fixtures | `tests/unit_tests/conftest.py` star-imports `bec_widgets.tests.fixtures` | the same star import in `tests/tests_bec_widgets/conftest.py` |
| run tests | `python -m pytest --random-order tests/unit_tests/test_<name>.py` | `python -m pytest --random-order tests/tests_bec_widgets/test_<name>.py` |
| scans | `bec_server/scan_server/scans/` | `<pkg>/scans/` + export in `scans/__init__.py` |
| devices | reusable control classes: `ophyd_devices/devices/` or `ophyd_devices/sim/` | beamline subclasses and beamline-only hardware: `<pkg>/devices/`; a control class reusable by other beamlines goes to `ophyd_devices` in a separate PR - ask first |
