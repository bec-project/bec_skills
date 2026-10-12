# BEC signals (ophyd_devices/utils/bec_signals.py)

All derive from `BECMessageSignal(Signal)` carrying a `SignalInfo` (`data_type`, `saved`, `ndim`,
`scope`, `role`, `signals`, `signal_metadata`, `acquisition_group`). The device server walks
`device.walk_signals()` at initialisation, subscribes to every `BECMessageSignal`, and
`BECMessageHandler.emit` routes the message. Docs: `bec_docs/docs/learn/devices/bec-signals.md`,
`how-to/devices/add-an-async-signal.md`, `add-an-async-multi-signal.md`, `add-a-preview-signal.md`,
`add-a-file-event-signal.md`, `add-a-progress-signal.md`.

| signal | ctor | put | endpoint | saved |
|---|---|---|---|---|
| `ProgressSignal` | `Cpt(ProgressSignal, name="progress")` | `put(value=, max_value=, done=, metadata=None)` | `device_progress(device)` | no |
| `FileEventSignal` | `Cpt(FileEventSignal, name="file_event")` | `put(file_path=, done=, successful=, file_type="h5", hinted_h5_entries={"data": "/entry/data/data"}, metadata=None)` | `file_event(device)` + `public_file(scan_id, name)` | as file reference in the master file |
| `PreviewSignal` | `Cpt(PreviewSignal, name="preview", ndim=1|2, num_rotation_90=0, transpose=False)` | `put(array)` | `device_preview(device, signal)` stream | no |
| `AsyncSignal` | `Cpt(AsyncSignal, name="data", ndim=0|1|2, max_size=1000, async_update={...}, acquisition_group=None)` | `put(array, timestamp=None, async_update=None)` | `device_async_signal(scan_id, device, signal)` stream + index list | yes |
| `AsyncMultiSignal` | `Cpt(AsyncMultiSignal, name="grp", ndim=, max_size=, signals=["a","b"], async_update=)` | `put({"a": arr, "b": arr})` - all sub-signals required | same | yes |
| `DynamicSignal` | like `AsyncMultiSignal` | partial updates allowed | same | yes |

`async_update`:

```python
{"type": "add",       "max_shape": [None]}             # 1D stream of scalars, append along axis 0
{"type": "add",       "max_shape": [None, 4096]}       # append 1D spectra of 4096 channels
{"type": "add",       "max_shape": [None, 512, 512]}   # append images
{"type": "add_slice", "max_shape": [None, 4096], "index": i}   # write row i
{"type": "replace"}                                    # overwrite the dataset
```

Rules the message handler enforces: async updates are dropped with a warning when no scan is
open or the scan status is `closed/aborted/halted/user_completed`; streams are capped by
`max_size` entries and expire after 10 minutes; each update also records shapes/indices so the
file writer can preallocate. `acquisition_group` (`baseline`, `monitored`, or a tag) controls
grouping in the file. Units/metadata go in `signal_metadata`.

Legacy callbacks (`_obj_callback_device_monitor_1d/2d`, `_obj_callback_progress`,
`_obj_callback_file_event`) still exist for old devices; new code must not use `_run_subs` for
BEC data.
