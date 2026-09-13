# Scan arguments: typing, validation, GUI grouping, *args bundles

Source: `bec_lib/bec_lib/scan_args.py` (`ScanArgument`, `DefaultArgType`, `Units`),
`bec_lib/bec_lib/scan_input_validator.py`, `bec_server/scan_server/scan_gui_models.py`.

## Typed parameters

```python
from typing import Annotated
from bec_lib.device import DeviceBase
from bec_lib.scan_args import DefaultArgType, ScanArgument, Units

def __init__(
    self,
    device: DeviceBase,
    start: Annotated[float, ScanArgument(display_name="Start Position", reference_units="device")],
    stop: Annotated[float, ScanArgument(display_name="Stop Position", reference_units="device")],
    steps: Annotated[int, ScanArgument(display_name="Number of Steps", gt=0)],
    *,
    relative: DefaultArgType.Relative,                 # required keyword-only: no default
    exp_time: DefaultArgType.ExposureTime = 0,
    frames_per_trigger: DefaultArgType.FramesPerTrigger = 1,
    settling_time: DefaultArgType.SettlingTime = 0,
    settling_time_after_trigger: DefaultArgType.SettlingTimeAfterTrigger = 0,
    readout_time: DefaultArgType.ReadoutTime = 0,
    burst_at_each_point: DefaultArgType.BurstAtEachPoint = 1,
    duration: Annotated[float, ScanArgument(display_name="Duration", units=Units.s, gt=0)] = 1.0,
    **kwargs,
):
```

`ScanArgument` fields: `display_name`, `description`, `tooltip`, `expert`, `hidden`, `example`,
`units` (pint unit or string), `reference_units` (name of the argument whose units apply, e.g.
the motor), `gt/ge/lt/le`, `reference_limits` (argument whose limits apply, e.g. a motor's soft
limits), `precision`, `alternative_group` (mutually exclusive parameterisations such as `steps`
vs `step_size`).

`DefaultArgType` aliases carry the standard display names and constraints for the common
acquisition parameters; use them instead of re-declaring `exp_time` etc. The `ScanInfo` model
fields with the same names are filled via `self.update_scan_info(...)`.

Validation runs twice: client-side in `Scans.prepare_scan_request` (immediate feedback in the
IPython client) and server-side in `ScanAssembler.assemble_direct_scan`. The validator also
applies defaults, so `self.exp_time` is never `None` when a default exists.

## Variable-length device bundles (`*args`)

Only for scans that take an arbitrary number of `(device, start, stop)`-style groups:

```python
arg_input = {
    "device": DeviceBase,
    "start": Annotated[float, ScanArgument(display_name="Start Position", reference_units="device")],
    "stop": Annotated[float, ScanArgument(display_name="Stop Position", reference_units="device")],
}
arg_bundle_size = {"bundle": len(arg_input), "min": 1, "max": None}

def __init__(self, *args, steps: ..., **kwargs):
    super().__init__(**kwargs)
    self.motor_input_bundles = bundle_args(args, bundle_size=self.arg_bundle_size["bundle"])
    self.motors = list(self.motor_input_bundles.keys())        # device names
    # values are (start, stop) tuples -> position_generators.line_scan_positions(list(values), steps=steps)
```

`bundle_args` comes from `scans.scan_base`. The client bundles positional arguments with
`toolz.partition`; `min`/`max` bound the number of bundles.

## gui_config

```python
gui_config = {
    "Movement Parameters": ["steps", "relative"],
    "Acquisition Parameters": ["exp_time", "frames_per_trigger", "settling_time",
                               "settling_time_after_trigger", "readout_time", "burst_at_each_point"],
}
```

Group label -> list of argument names. Validated by `GUIConfig.from_dict`; every listed name must
be a parameter. The ScanControl widget renders groups in this order; arguments not listed still
appear but ungrouped. `arg_input` bundles are rendered separately as repeatable rows.

## Client-side surface

`scan_name` -> `scans.<scan_name>(*args, **kwargs, callback=None, async_callback=None,
hide_report=False, metadata=None, monitored=None, on_request=None, file_suffix=None,
file_directory=None, scan_queue=None)` returning a `ScanReport`. `__doc__` and `__signature__`
come from your `__init__`, so the docstring must describe every argument and include an
`Examples:` block:

```python
"""
One-line summary.

Args:
    device (DeviceBase): motor to move
    ...

Returns:
    ScanReport

Examples:
    >>> scans.my_scan(dev.samx, -5, 5, steps=10, exp_time=0.1, relative=False)
"""
```
