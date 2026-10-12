---
name: bec-new-device
description: Integrate a new hardware or virtual device into BEC as an ophyd class built on the ophyd_devices base classes - reusable control class vs beamline business logic, PSIDeviceBase on_* hooks (on_init/on_connected/on_stage/on_unstage/on_pre_scan/on_trigger/on_complete/on_kickoff/on_stop/on_destroy), PSI status objects (CompareStatus, TransitionStatus, SubscriptionStatus, TaskHandler), BEC signals for async/preview/progress/file data, positioner bases, scan_info usage, the example device-config YAML and tests with patched_device. Use whenever the user wants to add support for a detector, motor, DAQ, camera, pseudo-motor or any EPICS/socket device to BEC, ophyd_devices or a beamline plugin repo, port an old CustomDetectorMixin/PSIDetectorBase device, or asks how a device should react to stage/trigger/kickoff.
metadata:
  author: bec-project
  version: "0.2"
---

# New BEC device (ophyd_devices)

This skill follows the device rules in `ophyd_devices/AGENTS.md`. If the target repository has
its own `AGENTS.md`, read it first; it wins wherever the two differ.

The device server is the only process that instantiates your class. It calls the ophyd verbs
(`stage`, `trigger`, `kickoff`, `complete`, `unstage`, `stop`, `read`, `set`) and expects status
objects back; `PSIDeviceBase` translates those verbs into `on_*` hooks and adds the plumbing
(`scan_info`, `task_handler`, `file_utils`, stop propagation). Your job is to implement hooks that
return promptly and represent unfinished work with a status - never to block the device server.
The old `PSIDetectorBase` / `CustomDetectorMixin` / `CustomPrepare` / `wait_for_signals` API is
gone - port it with the table in [references/hooks-and-statuses.md](references/hooks-and-statuses.md).

Reference implementations: `ophyd_devices/sim/sim_camera.py` (detector with preview, file
event, task handler), `sim_positioner.py`, `sim_monitor.py` (`SimMonitorAsync`), and in plugin
repos `debye_bec/devices/nidaq/nidaq.py` (DAQ with status-object handshakes) and
`debye_bec/devices/falcon/falcon.py` (spectrometer pushing `AsyncSignal` data).

## 1. Split control from business logic, then pick the repo

- **Control layer** - a plain `ophyd.Device` with the signal definitions, commands, protocol
  handling and device state (`configure_acquisition()`, `arm()`, `start_acquisition()`, ...).
  It is reusable across beamlines and belongs in **ophyd_devices**.
- **Business logic** - the `on_*` hooks: how a beamline uses that control interface during a
  scan (which trigger mode, which acquisition settings). Hooks call the control methods; they
  never duplicate PV definitions or communication code. Generic lifecycle behaviour can sit next
  to the control class; bespoke behaviour goes into a subclass in the **beamline plugin repo**.
- A device that only exposes a collection of signals needs no business-logic layer: plain
  `ophyd.Device` is enough (e.g. `SLSOperatorMessages` in `ophyd_devices/devices/sls_devices.py`).
  The need for business logic decides the base class, not the transport (EPICS, socket, ...).

| device kind | base | notes |
|---|---|---|
| detector / DAQ / anything with stage-trigger-complete | `class X(PSIDeviceBase, XControl)` where `XControl(Device)` holds the `Cpt(Epics...)` signals and command methods | two-layer pattern above |
| signal collection without lifecycle logic | plain `ophyd.Device` | no `PSIDeviceBase` just to group signals |
| EPICS motor record | `ophyd_devices.EpicsMotor` / `EpicsMotorEC` directly via YAML - no class needed | |
| custom positioner (PVs for setpoint/readback/stop) | `PSISimplePositionerBase` (required `user_readback`, `user_setpoint`; optional `velocity`, `motor_stop`, `motor_done_move`) or `PSIPositionerBase` for the full motor-record-like set | `override_suffixes={"user_setpoint": ":SP"}` remaps PV suffixes |
| pseudo motor combining real devices | `PSIPseudoMotorBase` (`forward_calculation`, `inverse_calculation`, `motors_are_moving`) | needs `device_mapping` + `device_access` in YAML |
| pure signal | `ophyd.EpicsSignal(RO)`, `EpicsSignalWithRBV` via YAML | |
| simulation twin for tests/GUI | `ophyd_devices.Sim*` or a `sim/` subclass of your class with `SetableSignal`/`ReadOnlySignal` | keep the same signal names |

Import statuses from `ophyd_devices.utils.psi_device_base_utils` (`DeviceStatus`, `MoveStatus`,
`StatusBase`, `CompareStatus`, `TransitionStatus`, ...) and BEC signals from
`ophyd_devices.utils.bec_signals` - not from `ophyd`. The PSI versions carry descriptions,
timeout diagnostics and status composition. Prefer a repository helper whenever a BEC-aware
counterpart exists.

## 2. Constructor contract

```python
class MyDetector(PSIDeviceBase, MyDetectorControl):
    """<Vendor/model> detector with software and hardware triggering and HDF5 file output."""

    USER_ACCESS = ["set_timeout", "get_timeout"]   # methods callable as dev.mydet.set_timeout(...)

    def __init__(self, prefix: str = "", *, name: str, scan_info: ScanInfo | None = None,
                 device_manager: DeviceManagerBase | None = None, timeout: float = 5.0, **kwargs):
        super().__init__(prefix=prefix, name=name, scan_info=scan_info, device_manager=device_manager, **kwargs)
```

- The device server passes only `deviceConfig` keys that match named parameters and injects
  `name`; it injects `device_manager` and `scan_info` **only if they are explicit parameters**
  (hidden in `**kwargs` they are not passed). `PSIDeviceBase.__init__` also inherits them from
  a parent device and calls `on_init()` at the end - before any signal is connected.
- Constructors and `on_init()` must not communicate with devices: no PV reads or writes, no
  sockets, threads or files. The class must be constructible offline (`ophyd_test --config`
  instantiates it).
- Leftover `deviceConfig` keys are applied by the server after connection as attribute/signal
  writes, so expose tunables either as parameters or as signals.
- Give the class a docstring whose first line describes the device: CI collects it into
  `ophyd_devices/devices/device_list.md` (generated - never edit that file by hand).
- `USER_ACCESS`: expose methods, not properties, with verb names (`set_velocity()`,
  `get_velocity()`, not `velocity()`).

## 3. Implement the hooks

### Layout - same section and comment style as the base class

Copy the entire "Beamline Specific Implementations" section from
`ophyd_devices/interfaces/base_classes/psi_device_base.py`: its separator, all ten hooks with
their signatures and docstrings, in the base-class order, including hooks you do not use. Put
your implementation below each copied docstring. Helper methods, `USER_ACCESS` methods and
callbacks go after it under a separate separator:

```python
    ########################################
    #  Beamline Specific Implementations   #
    ########################################

    def on_init(self) -> None:
        """
        Called when the device is initialized.

        No signals are connected at this point. If you like to
        set default values on signals, please use on_connected instead.
        """

    def on_connected(self) -> None: ...
    def on_stage(self) -> DeviceStatus | StatusBase | None: ...
    def on_unstage(self) -> DeviceStatus | StatusBase | None: ...
    def on_pre_scan(self) -> DeviceStatus | StatusBase | None: ...
    def on_trigger(self) -> DeviceStatus | StatusBase | None: ...
    def on_complete(self) -> DeviceStatus | StatusBase | None: ...
    def on_kickoff(self) -> DeviceStatus | StatusBase | None: ...
    def on_stop(self) -> None: ...
    def on_destroy(self) -> None: ...

    ########################################
    #            Helper Methods            #
    ########################################
```

(The `...` bodies above are shorthand - copy the real docstrings.) The full worked example is
[assets/device_template.py](assets/device_template.py).

### Beamline subclass

When subclassing a device that already implements hooks (a plugin subclass of a reusable
ophyd_devices device), copy the same section, but preserve the parent behaviour: a copied stub
must not silently disable an inherited implementation. Delegate unused hooks and extend used ones:

```python
class MyBeamlineDetector(MyDetector):
    """MyDetector configured for <beamline>: hardware triggering on the X99 timing card."""

    ########################################
    #  Beamline Specific Implementations   #
    ########################################

    def on_stage(self) -> DeviceStatus | StatusBase | None:
        """<copied base docstring>"""
        self.set_trigger_mode(TriggerMode.EXTERNAL)   # beamline choice, via the control layer
        return super().on_stage()

    def on_trigger(self) -> DeviceStatus | StatusBase | None:
        """<copied base docstring>"""
        return super().on_trigger()
    # ... the remaining hooks likewise
```

### Semantics

Order during a scan: `stage → pre_scan → (trigger per point | kickoff … complete) → unstage`;
`stop` may interrupt anywhere; `destroy` on session teardown.

- **Return promptly.** Staging, triggering, kickoff, completion and movement must not wait,
  sleep or poll on the calling thread. Write PVs with `put()` (or keep the `set()` status) and
  return a status for anything that is not finished yet. Use `task_handler.submit_task(fn)` for
  long-running work; it returns a `TaskStatus` and is killed by `stop`/`destroy`.
- **Return values.** `on_stage()`, `on_complete()` and friends may return a status or `None`.
  Return `None` only when there is no outstanding work: `complete()` and `kickoff()` turn `None`
  into an already-finished status, so return a pending status while acquisition or file writing
  continues. Read the wrapper semantics in
  [references/hooks-and-statuses.md](references/hooks-and-statuses.md); the protocol signatures
  alone do not describe them.
- **`on_connected()`** is the first hook allowed to talk to the hardware (set defaults, subscribe
  callbacks, one bounded readiness check). The device server calls it once an enabled device has
  connected; plain instantiation, `patched_device` and `ophyd_test` do not, so call it explicitly
  in tests that rely on it. It is not a per-scan hook: scan-specific settings belong in the scan
  hooks, read from `self.scan_info.msg` (`num_points`, `scan_type`, `scan_parameters`).
- **Interruption.** Register every status that must fail on stop with
  `self.cancel_on_stop(status)`; `stop()` then fails it with `DeviceStoppedError`. Cancelling a
  status does not stop hardware or a background task - implement that in `on_stop()`, and make
  repeated calls safe.
- **Teardown.** Preserve base-class stop and destroy behaviour. Release subscriptions, threads,
  sockets and other owned resources in `on_destroy()`; worker code must be able to exit on
  interruption.
- `wait_for_condition(condition, timeout, check_stopped=True)` blocks the caller: use it only
  where blocking is acceptable (`on_connected`, inside a `task_handler` task), never in the scan
  hooks.

Status catalogue and the legacy mapping:
[references/hooks-and-statuses.md](references/hooks-and-statuses.md).

## 4. Signals and publishing data to BEC

Set each signal's `kind` deliberately: `normal` and `hinted` appear in `read()` (`hinted` also
selects the default BEC scan readouts), `config` appears in `read_configuration()`, `omitted` in
neither. Renaming a signal or changing its kind changes the data interface.

Declare BEC signals as components; the device server subscribes to them automatically and routes
each to the right Redis endpoint. Reuse their message formats - do not publish custom Redis
messages or hand-roll `connector.xadd`.

```python
preview    = Cpt(PreviewSignal, name="preview", ndim=2)                       # live image, not saved
progress   = Cpt(ProgressSignal, name="progress")                             # progress bar in client
file_event = Cpt(FileEventSignal, name="file_event")                          # file references in the master HDF5
data       = Cpt(AsyncSignal, name="data", ndim=1, max_size=1000,             # saved to HDF5 per scan
                 async_update={"type": "add", "max_shape": [None, 4096]})
means      = Cpt(DynamicSignal, name="means", ndim=1, max_size=1000, signals=["ch1", "ch2"],
                 async_update={"type": "add", "max_shape": [None]})
```

`async_update["type"]`: `add` appends along axis 0, `add_slice` needs `index`, `replace`
overwrites. `AsyncMultiSignal` requires every sub-signal per update, `DynamicSignal` allows
partial updates. Async updates are dropped unless a scan is open, so buffer or skip data that
arrives before `stage`/after `unstage`. `readoutPriority: async` in the YAML tells the scan
server not to read the device per point. Catalogue: [references/bec-signals.md](references/bec-signals.md).

## 5. Configuration and validation

```yaml
mydet:
  deviceClass: ophyd_devices.devices.mydet.MyDetector   # or <plugin>.devices.mydet.mydet.MyBeamlineDetector
  deviceConfig: {prefix: "X99XA-ES-MYDET:", timeout: 10}
  readoutPriority: async          # monitored for point detectors that are read per point
  softwareTrigger: true           # scan server calls trigger()
  onFailure: raise
  enabled: true
  deviceTags: [detectors]
```

1. **Where the code goes.** Reusable control class (and generic lifecycle) in
   `ophyd_devices/devices/`; a new reusable device family also gets an example configuration
   under `ophyd_devices/configs/`. Beamline-specific subclasses in
   `<plugin>/<plugin>/devices/<mydet>/mydet.py` (+ `<mydet>_enums.py` for PV state constants).
2. **Offline check.** `ophyd_test --config <changed-config>.yaml` must instantiate it; reports go
   to `./device_test_reports`. Use `--connect` only when the user explicitly asks for hardware
   validation and the target is reachable.
3. **Live session - only when requested.** Starting services (`bec-server start`, `bec`) and
   loading the device (`bec.config.add_to_session(...)`, then `dev.mydet.summary()`,
   `dev.mydet.read()` and a short scan) is part of validation only when the user asks for it.
   Restart the device server after changing code it has already loaded.
4. **Report** whether validation used mocks, simulation or real hardware; include the model and
   firmware when known.

## 6. Tests

Use mocked EPICS and sockets. `ophyd_devices.tests.utils.patched_device(cls, *args, **kwargs)`
gives an instance with mock PVs (`MockPV`); `get_mock_scan_info(device)` fills `scan_info` so
`on_stage` can read `num_points` and `scan_parameters`. Use simulation devices when a working
device is needed. Keep tests independent of execution order.

New device tests must cover instantiation, the relevant protocol
(`isinstance(dev, BECDeviceProtocol)`, `BECFlyerProtocol`, `BECPositionerProtocol` from
`ophyd_devices.interfaces.protocols.bec_protocols`) and safe `stop()` behaviour. For asynchronous
work also exercise completion, failure (e.g. the IOC reporting an error state) and interruption
while a status is pending. Bug fixes get a regression test. Template:
[assets/test_template.py](assets/test_template.py).

Run the smallest target first:
`python -m pytest --random-order tests/test_mydet.py` (ophyd_devices) or
`python -m pytest --random-order tests/tests_devices/test_mydet.py` (plugin).

## Style

Python 3.11-compatible syntax, f-strings, `pathlib`, type annotations and docstrings on public
methods, Black and isort with the repository's `pyproject.toml` (line length 100). Follow the
existing local patterns before introducing a new abstraction.

## Deliverable checklist

- [ ] Reusable control class (plain `Device`, signals + command methods) separated from the hooks; placed in the right repo
- [ ] `PSIDeviceBase` only where lifecycle/business logic is needed
- [ ] "Beamline Specific Implementations" section copied: all ten hooks, base-class order, docstrings; helpers under "Helper Methods"
- [ ] Subclass hooks preserve parent behaviour with `super()`
- [ ] `name`, `scan_info`, `device_manager` explicit keyword parameters; no I/O in `__init__`/`on_init`
- [ ] Scan hooks return promptly with statuses; all statuses `cancel_on_stop`; `on_stop` stops the hardware and is repeatable
- [ ] `scan_info.msg` used for exposure/points/type instead of duplicated scan kwargs
- [ ] Signal kinds chosen deliberately; BEC signals declared as `Cpt(...)`; no manual Redis writes; `readoutPriority` consistent
- [ ] Class docstring with a useful first line; `USER_ACCESS` lists verb-named methods
- [ ] Example config under `ophyd_devices/configs/` for a new reusable family; `ophyd_test --config` passes
- [ ] Tests with `patched_device` cover instantiation, protocol, stop, completion/failure/interruption and pass with `--random-order`
