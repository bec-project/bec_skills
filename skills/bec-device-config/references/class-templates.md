# deviceConfig by class

Machine-readable source: `ophyd_devices/interfaces/device_config_templates/ophyd_templates.py`;
docs: `bec_docs/docs/references/ophyd-devices/device-config-templates.md`,
`how-to/devices/add-an-epics-motor.md`, `add-an-epics-signal.md`, `add-a-pseudo-motor.md`.
For any other class: `python -c "import inspect, <module>; print(inspect.signature(<module>.<Class>))"`.

## EPICS motor

```yaml
samx:
  deviceClass: ophyd_devices.EpicsMotor          # ophyd_devices.EpicsMotorEC for the PSI EC motor record
  deviceConfig:
    prefix: "X12SA-ES1-MOT:SAMX"                 # required; full record name incl. trailing separator if the class expects it
    limits: [-50, 50]                            # optional soft limits, written to low/high_limit_travel
  readoutPriority: baseline
  enabled: true
  description: Sample X
  deviceTags: [sample_stage]
  onFailure: retry
```

## EPICS signal

```yaml
curr:
  deviceClass: ophyd.EpicsSignalRO               # read-only; ophyd.EpicsSignal for read/write
  deviceConfig:
    read_pv: ARIDI-PCT:CURRENT
    auto_monitor: true                           # subscribe instead of polling
  readoutPriority: baseline
  onFailure: buffer                              # machine diagnostics must not abort scans
  readOnly: true
  enabled: true
  softwareTrigger: false

shutter_cmd:
  deviceClass: ophyd.EpicsSignal
  deviceConfig:
    read_pv: X12SA-FE-SH1:STATUS
    write_pv: X12SA-FE-SH1:CMD
    put_complete: true
  readoutPriority: on_request
  enabled: true

with_rbv:
  deviceClass: ophyd_devices.EpicsSignalWithRBV  # write_pv = prefix, read_pv = prefix + "_RBV"
  deviceConfig:
    prefix: X12SA-ES1-CAM:AcquireTime
```

## Detector / async device (custom PSIDeviceBase subclass)

```yaml
eiger:
  deviceClass: csaxs_bec.devices.eiger.Eiger9M
  deviceConfig:
    prefix: "X12SA-ES-EIGER9M:"
    device_access: true                          # only if the class takes device_manager
  readoutPriority: async                         # pushes AsyncSignal / FileEventSignal data itself
  softwareTrigger: true                          # scan server sends trigger()
  onFailure: raise
  enabled: true
  deviceTags: [detector]
```

## Simulation (bec_lib/configs/demo_config.yaml conventions)

```yaml
samx:
  deviceClass: ophyd_devices.SimPositioner
  deviceConfig: {delay: 1, limits: [-50, 50], tolerance: 0.01, update_frequency: 400}
  readoutPriority: baseline
  enabled: true
bpm4i:
  deviceClass: ophyd_devices.SimMonitor
  readoutPriority: monitored
  enabled: true
  softwareTrigger: false
eiger:
  deviceClass: ophyd_devices.SimCamera
  deviceConfig: {device_access: true}
  readoutPriority: async
  softwareTrigger: true
  enabled: true
  deviceTags: [detector]
waveform:
  deviceClass: ophyd_devices.SimWaveform
  readoutPriority: async
  enabled: true
```

`SimPositioner.__init__` kwargs: `delay`, `update_frequency`, `precision`, `limits`, `tolerance`,
`sim_init`; `SimCamera`/`SimMonitor` accept `device_access`, `sim_init`. Other sim classes:
`SimMonitorAsync`, `SimLinearTrajectoryPositioner`, `SimFlyer`, `SimWaveform`, proxies in
`ophyd_devices/sim/sim_frameworks/` (`SlitProxy`, `H5ImageReplayProxy`, `StageCameraProxy`) that
need `device_mapping` and `device_access`.

## Pseudo motor

```yaml
energy:
  deviceClass: mybeamline_bec.devices.mono.Energy
  deviceConfig:
    prefix: ""
    device_mapping: {bragg: mo1_bragg, gap: id_gap}   # names of real devices; device_access implied
  needs: [mo1_bragg, id_gap]                          # created after its constituents
  readoutPriority: baseline
  enabled: true
```
