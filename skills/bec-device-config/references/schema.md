# Device config schema

Source of truth: `bec_lib/bec_lib/atlas_models.py::_DeviceModelCore` and `Device`,
`bec_lib/bec_lib/device.py::ReadoutPriority/OnFailure`, `bec_lib/bec_lib/config_helper.py`
(`_ConfigConstants`, exported header), `bec_server/device_server/devices/devicemanager.py`
(`construct_device_obj`, `update_config`, `resolve_device_dependencies`).

```python
class _DeviceModelCore(BaseModel):
    enabled: bool
    deviceClass: str
    readoutPriority: Literal["monitored", "baseline", "async", "on_request", "continuous"]
    deviceConfig: dict | None = None
    connectionTimeout: float = 5.0
    description: str = ""            # None -> ""
    deviceTags: set[str] = set()
    needs: list[str] = []
    onFailure: Literal["buffer", "retry", "raise"] = "retry"
    readOnly: bool = False
    softwareTrigger: bool = False
    userParameter: dict = {}
```

`Device(_DeviceModelCore)` adds `name`: must not start with `_`, must be a valid non-keyword
identifier, must not collide with `DeviceContainer` attribute names.

| key | consumer | notes |
|---|---|---|
| `deviceClass` | `DeviceManagerDS._get_device_class` imports the dotted path | not updatable at runtime (only `name` and `deviceClass` are frozen) |
| `deviceConfig` | `construct_device_obj`: signature-matching keys → `__init__` kwargs; `name` injected; `device_manager`/`scan_info` injected when they are explicit parameters; `device_access: true` forces `device_manager` | leftovers → `update_config`: `limits` → travel-limit signals `.set().wait(timeout=2)`, `labels` → `_ophyd_labels_`, other keys must be attributes (Signal → `.set`, callable → call, else `setattr`), else `DeviceConfigError` |
| `readoutPriority` | scan server groups devices into readout groups; device server `_subscribe_to_auto_monitors` | `async` devices must publish their own data (`AsyncSignal` etc.) |
| `enabled` | disabled devices are created as proxies but never connected | flipping it is a runtime update |
| `onFailure` | `device_server._retry_obj_method` on `read()`/`read_configuration()` errors | WARNING alarm in all cases; `buffer` falls back to `MessageEndpoints.device_read` cache |
| `readOnly` | client refuses `set`/`move` | still readable |
| `softwareTrigger` | scan server sends `trigger` only to devices with `softwareTrigger: true` | detectors in software-triggered scans |
| `connectionTimeout` | `connect_device(..., timeout=...)` | seconds; raise for slow IOCs |
| `deviceTags` | grouping (`save_current_session(split_by_tag=True)`), GUI filters, `bec.device_manager.devices.get_devices_with_tags` | set semantics |
| `needs` | `resolve_device_dependencies` (Kahn sort) creates dependencies first | unknown or cyclic → `DeviceConfigError`; disabled dependency → WARNING |
| `userParameter` | free-form, exposed to users on the device object | e.g. `in: 5.0`, `out: 30.0` positions |
| `description` | shown in GUIs and `dev.<name>` repr | keep it human |

Runtime-updatable keys (`bec.config.send_config_request(action="update", config={name: {...}})`):
`description`, `deviceConfig`, `deviceTags`, `enabled`, `onFailure`, `readOnly`,
`readoutPriority`, `softwareTrigger`, `userParameter`.

## Validation flow

`ConfigHelper._load_config_from_file` (only `.yaml`/`.yml`, `!include` resolved) →
`_get_config_conflicts(validate=True)` → per device `_DeviceModelCore(**entry)`; a
`ValidationError` is re-raised with `exc.context = "the provided device config for device '<name>'"`.
Server side, SciHub validates again (`DevicePartial` for updates) and the device server
instantiates; instantiation failures roll back the new session (`_rollback_added_devices`).

## Message contract

`DeviceConfigMessage(action: "add"|"set"|"update"|"reload"|"remove"|"reset"|"cancel", config: dict)`;
`add`/`set`/`update` require a non-empty `config`.
