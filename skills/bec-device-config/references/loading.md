# Loading, saving and updating sessions

`bec.config` in the IPython client is `bec_lib.config_helper.ConfigHelper` (user-facing wrapper
`ConfigHelperUser`). Docs: `bec_docs/docs/how-to/devices/load-and-save-a-device-session-from-the-bec-ipython-client.md`,
`learn/devices/device-sessions-in-bec.md`, `learn/devices/error-handling-during-session-updates.md`.

| call | action | effect |
|---|---|---|
| `update_session_with_file(path, save_recovery=True, force=False, validate=True)` | `set` | replaces the session; writes `recovery_config_<timestamp>.yaml` under the log-writer directory of the service config |
| `add_to_session(path, validate=True)` | `add` | adds/updates the listed devices only |
| `save_current_session(path, split_by_tag=False, included_tags=None, excluded_tags=None, remaining_devices_tag="misc")` | - | exports YAML with the schema header; `split_by_tag=True` writes `<stem>/main.yaml` + `<stem>/<tag>.yaml` with `!include` lines |
| `send_config_request(action="update", config={name: {key: value}})` | `update` | runtime change of updatable keys (`enabled`, `readoutPriority`, `deviceConfig`, ...) |
| `reset_config()` | `reset` | empties the session |
| `load_demo_config(force=False)` | `set` | loads `bec_lib/configs/demo_config.yaml` |

Per-device shortcuts also exist: `dev.samx.enabled = False`, `dev.samx.readout_priority = "monitored"`,
`dev.samx.set_device_config({...})`.

## What happens on load

1. Client validates each entry (`_DeviceModelCore`), resolves conflicts with the current session
   (interactive prompt unless `force=True`), writes the recovery file, sends
   `DeviceConfigMessage(action="set", config=...)`.
2. SciHub (`scihub/atlas/config_handler.py`) validates again, stores, forwards.
3. Device server (`device_server/devices/config_update_handler.py`) orders devices by `needs`,
   constructs objects (`construct_device_obj`), connects enabled ones with `connectionTimeout`,
   publishes device info (class, signals, `USER_ACCESS`), calls `on_connected`, applies leftover
   `deviceConfig` keys.
4. Failure semantics: an exception in `__init__` flushes the whole new session (rollback); a
   connection failure disables that device only and raises an alarm; the client receives a
   `RequestResponse` with the error text.

## Validate offline

```bash
ophyd_test --config <main.yaml>                       # schema + import + instantiate
ophyd_test --config <main.yaml> --connect             # plus signal connection
ophyd_test --config <main.yaml> --output ./reports --timeout-per-device 10
```

Implementation: `ophyd_devices/utils/static_device_test.py` (`StaticDeviceTest.validate_schema`
uses the same pydantic model after translating the entry with `name`, coercing `deviceConfig:
None` → `{}` and dropping the legacy `deviceType`).

## Service config is not device config

`bec-server start --config bec-server-config.yaml` points at the *service* configuration (Redis
host, MongoDB/SciBec, `service_config.file_writer.base_path`, log paths). Template:
`bec/bec_config_template.yaml`; beamline example `beamline_plugins/<plugin>/deployment/bec-server-config.yaml`.
The device config is loaded afterwards through `bec.config`.
