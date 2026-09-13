---
name: bec-device-config
description: Write or restructure BEC device configuration YAML - single device entries (deviceClass, deviceConfig, readoutPriority, onFailure, deviceTags, ...), composite configs where a main file pulls in frontend/optics/detector files with !include, validation with ophyd_test, and loading into a session with bec.config. Use whenever the user wants to add a device to BEC, create or split a beamline config, ask which readoutPriority/onFailure to pick, fix a config validation error, or generate YAML for an EPICS motor, signal, camera or custom ophyd class.
metadata:
  author: bec-project
  version: "0.1"
---

# BEC device config YAML

A BEC session is defined by one *effective* YAML mapping `device_name -> entry`. The mapping may
be assembled from several files with `!include`, is validated by the pydantic model
`_DeviceModelCore` (`bec_lib/atlas_models.py`), and is turned into live ophyd objects by the
device server. Every key you write therefore has a precise consumer; unknown keys fail loudly.
Schema details, key-by-key: [references/schema.md](references/schema.md).

## 1. One device entry

```yaml
samx:                                   # valid identifier, no leading "_", unique in the effective config
  deviceClass: ophyd_devices.SimPositioner   # importable dotted path; the device server imports it
  deviceConfig:                          # kwargs for __init__ + extra attributes/signals (see rule below)
    limits: [-50, 50]
    tolerance: 0.01
  readoutPriority: baseline              # monitored | baseline | async | on_request | continuous
  enabled: true
  description: Sample stage X
  deviceTags: [sample_stage, motor]      # free-form; used for grouping/splitting and GUI filters
  onFailure: retry                       # buffer | retry | raise   (default retry)
  readOnly: false
  softwareTrigger: false                 # true only for detectors triggered by the scan server
  connectionTimeout: 5.0
  needs: []                              # names of devices that must be created first
  userParameter: {}
```

Required: `deviceClass`, `enabled`, `readoutPriority`. Everything else has a default. Fields not
in the model (for example `connector`, `deviceType`, `status`) are rejected.

**`deviceConfig` rule**: the device server passes every key that matches a parameter of the
class' `__init__` (or of its ophyd bases) as a kwarg and always injects `name`. Keys that are left
over are applied *after* connection: `limits` → `low/high_limit_travel` signals, `labels` →
ophyd labels, any other key must be an existing attribute - a `Signal` gets `.set(value)`, a
callable is called, a plain attribute is set - otherwise `DeviceConfigError("Unknown config
parameter ...")`. `device_access: true` injects the device manager into classes that accept
`device_manager`. So: read the class signature before inventing keys.

**readoutPriority** decides when the device is read: `monitored` at every scan point (scan
motors and fast detectors), `baseline` once at scan start (slow/slit/temperature values),
`async` for devices that push their own data stream during the scan (cameras, DAQs), `on_request`
never automatically, `continuous` for free-running monitors. Scan motors are elevated to
`monitored` by the scan itself; do not set every motor to `monitored`.

**onFailure** on read errors: `retry` reads once more then raises, `buffer` returns the last Redis
value (use for flaky beamline diagnostics you do not want to abort scans), `raise` aborts
immediately (use for sample-safety relevant devices).

Per-class `deviceConfig` fields for the common ophyd classes (`EpicsMotor`, `EpicsMotorEC`,
`EpicsSignal`, `EpicsSignalRO`, `EpicsSignalWithRBV`, sim devices):
[references/class-templates.md](references/class-templates.md).

## 2. Composite configs with `!include`

BEC's YAML loader (`bec_lib/bec_yaml_loader.py`) understands a scalar `!include <path>` tag.
Convention used by every beamline plugin: the main file contains one wrapper key per subsystem
whose value is a one-element list with the include; the wrapper key is dropped and the included
devices are merged at top level. Relative paths resolve against the including file, `~` works,
includes nest.

```yaml
# device_configs/<beamline>_standard_config.yaml  (the file users load)
machine:
  - !include ./<beamline>_machine.yaml        # ring current, shutters
frontend:
  - !include ./<beamline>_frontend.yaml       # FE slits, absorbers
optics:
  - !include ./<beamline>_optics.yaml         # mono, mirrors, optics-hutch diagnostics
sample_environment:
  - !include ./<beamline>_experimental_hutch.yaml
detectors:
  - !include ./<beamline>_detectors.yaml
# toggle a subsystem by commenting the include:
# xrd:
#   - !include ./<beamline>_xrd.yaml

# beamline-specific one-offs can stay inline
mo1_bragg:
  deviceClass: debye_bec.devices.mo1_bragg.mo1_bragg.Mo1Bragg
  deviceConfig: {prefix: "X01DA-OP-MO1:BRAGG:"}
  readoutPriority: baseline
  enabled: true
```

Rules that keep composite configs sane:

- **One device, one file.** A duplicate name across files is *not* an error - the loader prints
  a warning and the last definition wins. Grep for the name before adding it
  (`grep -rn "^<name>:" device_configs/`).
- Name files by subsystem/hutch, not by device class; keep the wrapper keys stable so people can
  comment subsystems in and out. Put a heading comment block above each device group.
- A sub-file is a plain device mapping (no wrapper keys, no `!include` of its own unless it
  represents a sub-subsystem).
- `deviceTags` should mirror the file: every device in `<beamline>_frontend.yaml` carries
  `frontend`. `bec.config.save_current_session(path, split_by_tag=True)` regenerates exactly
  this layout (`<stem>/main.yaml` + one file per tag), which is the canonical way to split an
  existing monolithic config.
- Sim variants live in a parallel file (`<beamline>_sim.yaml`) that redefines the same names with
  `ophyd_devices.Sim*` classes, so scans and GUIs run unchanged.
Worked layout: [assets/composite_config](assets/composite_config).

## 3. Validate before loading

```bash
ophyd_test --config device_configs/<beamline>_standard_config.yaml            # schema + class import
ophyd_test --config ... --connect --timeout-per-device 10                      # also connect signals
```

Reports go to `./device_test_reports/<file>.txt`. The static pass resolves `!include`s, checks
each entry against the model, imports `deviceClass` and instantiates it; `--connect` talks to
the hardware. Fix in this order: YAML syntax → unknown key → class import → `deviceConfig` kwarg
mismatch (compare with the `__init__` signature) → connection.

## 4. Load into a running BEC

From the IPython client (`bec.config` is `ConfigHelper`):

```python
bec.config.update_session_with_file("device_configs/<beamline>_standard_config.yaml")   # replaces the session; writes a recovery file
bec.config.add_to_session("device_configs/new_detector.yaml")                          # adds devices
bec.config.save_current_session("backup.yaml", split_by_tag=True)                       # export
bec.config.load_demo_config()                                                          # bec_lib/configs/demo_config.yaml
```

Conflicts (device exists with different config) prompt interactively unless `force=True`. A
device whose `__init__` fails flushes the whole new session; a device that fails to *connect* is
disabled individually with an alarm - so test classes with `ophyd_test` first. Service config
(`bec-server start --config`) is a different file (Redis, file writer paths) - do not mix them.
Full API and message flow: [references/loading.md](references/loading.md).

## 5. Checklist for the deliverable

- [ ] every entry has `deviceClass`, `enabled`, `readoutPriority`; names are identifiers
- [ ] `deviceConfig` keys exist in the class signature or as attributes (checked, not guessed)
- [ ] `readoutPriority`/`onFailure` chosen with a one-line justification in `description` or comment
- [ ] composite: wrapper key + `- !include ./relative.yaml`, no duplicate names, tags mirror files
- [ ] `ophyd_test --config <main>` passes; `--connect` run if hardware reachable
- [ ] loading command given to the user; recovery file location mentioned
