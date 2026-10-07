# Scan arguments: typing, validation, GUI grouping, *args bundles

Source: `bec_lib/bec_lib/scan_args.py` (`ScanArgument`, `DefaultArgType`, `Units`),
`bec_lib/bec_lib/scan_input_validator.py`, `bec_server/scan_server/scan_manager.py` (`available_scans`).

## Typed parameters

```python
from typing import Annotated
from bec_lib.device import DeviceBase
from bec_lib.scan_args import DefaultArgType, ScanArgument, Units

def __init__(
    self,
    # fmt: off
    device: Annotated[DeviceBase, ScanArgument(display_name="Motor", description="Motor to scan.")],
    start: Annotated[float, ScanArgument(display_name="Start Position", description="Start position.", reference_units="device")],
    stop: Annotated[float, ScanArgument(display_name="Stop Position", description="Stop position.", reference_units="device")],
    steps: Annotated[int, ScanArgument(display_name="Number of Steps", description="Number of points.", gt=0)],
    *,
    relative: DefaultArgType.Relative,                 # required keyword-only: no default
    exp_time: DefaultArgType.ExposureTime = 0,
    frames_per_trigger: DefaultArgType.FramesPerTrigger = 1,
    settling_time: DefaultArgType.SettlingTime = 0,
    settling_time_after_trigger: DefaultArgType.SettlingTimeAfterTrigger = 0,
    readout_time: DefaultArgType.ReadoutTime = 0,
    burst_at_each_point: DefaultArgType.BurstAtEachPoint = 1,
    duration: Annotated[float, ScanArgument(display_name="Duration", description="Acquisition duration.", units=Units.s, gt=0)] = 1.0,
    # fmt: on
    **kwargs,
):
```

Wrap the parameter list in `# fmt: off` / `# fmt: on` (after `self`, before `**kwargs`) and keep
one argument per line, however long: black would otherwise split every `Annotated[...]` over
several lines and make the signature unreadable. Beamline plugin scans do the same (e.g.
`debye_bec/scans/xas_simple_scan.py`, `csaxs_bec/scans/flomni_fermat_scan.py`).

`ScanArgument` fields: `display_name`, `description`, `tooltip`, `expert`, `hidden`, `example`,
`units` (pint unit or string), `reference_units` (name of the argument whose units apply, e.g.
the motor), `gt/ge/lt/le`, `reference_limits` (argument whose limits apply, e.g. a motor's soft
limits), `precision`, `alternative_group` (mutually exclusive parameterisations such as `steps`
vs `step_size`).

`DefaultArgType` aliases carry the standard display names and constraints for the common
acquisition parameters; use them instead of re-declaring `exp_time` etc. The `ScanInfo` model
fields with the same names are filled via `self.update_scan_info(...)`.

Validation runs twice: client-side in `Scans.prepare_scan_request` (immediate feedback in the
IPython client) and server-side in `ScanAssembler.assemble_scan`. The validator checks types
and constraints and resolves device names to device objects; it does not fill in defaults. The
assembler does that separately (`apply_scan_argument_defaults`, including defaults a
`ScanModifier` overrides) before it constructs the scan, so `__init__` always receives a value for
a defaulted argument. Nothing sets `self.exp_time` for you: store what you need yourself or read
it back from `self.scan_info` after `update_scan_info(...)`, as the template does.

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
    self.motors = list(self.motor_input_bundles.keys())        # device objects (resolved by the validator)
    # values are [start, stop] lists -> position_generators.line_scan_positions(list(values), steps=steps)
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

Group label -> list of argument names. The scan manager publishes it as `gui_visibility` in
`available_scans` (a `gui_visibility` class attribute takes precedence over `gui_config`). Since
bec 4.0 nothing validates it (the `GUIConfig` models in `scan_gui_models.py` were removed), so
check the names yourself.

The ScanControl widget (bec_widgets 3.x, `scan_info_adapter.py`) builds its keyword-argument form
only from these groups, in this order:

- a keyword argument that is not listed does not appear in the form at all;
- a listed name that is not a parameter of `__init__` (a typo) is skipped without a warning;
- `arg_input` names are skipped here; the bundles are rendered separately as repeatable rows, so
  list only keyword arguments;
- `ScanArgument(hidden=True)` arguments are skipped even when listed.

So list every keyword argument a GUI user must be able to set, and check the result in
ScanControl. ScanControl matches the group names against the published signature, which already
includes arguments a `ScanModifier` adds through `scan_signature_overrides()`; such an argument
shows up only if its name is in the scan's own `gui_config`. `ScanModifier.gui_config_overrides()`
exists, but bec up to 4.1.4 never applies it to the published groups, so a modifier cannot add a
field to a scan whose `gui_config` does not already name it.

## Client-side surface

`scan_name` -> `scans.<scan_name>(*args, **kwargs, callback=None, async_callback=None,
hide_report=False, metadata=None, monitored=None, on_request=None, file_suffix=None,
file_directory=None, scan_queue=None)` returning a `ScanReport`.

The scan manager generates `scans.<scan_name>.__doc__` and `__signature__` from the signature
(`scan_doc_with_modifiers()` in `scan_server/scans/scan_argument_modifier.py`), after any
`ScanModifier` overrides. It starts from the class docstring when the class has its own, otherwise
the `__init__` one, and:

- if that docstring contains `Args:`, keeps the text before it and the `Returns:` / `Raises:`
  sections, drops the rest of `Args:` and any `Examples:` section, and inserts a rebuilt `Args:`;
- if it contains no `Args:`, keeps the whole docstring unchanged (a hand-written example in it
  survives) and still appends the rebuilt `Args:` and `Examples:`;
- rebuilt argument lines read `name (type [units]): <ScanArgument.description>. Default: <value>`;
  without a `description` the argument name with spaces is used (`steps (int): steps.`), so give
  every `ScanArgument` a `description` - the `DefaultArgType` aliases already have one. `arg_input`
  bundles get one summary line (`*args (device: DeviceBase, start: float, stop: float): repeated
  scan argument bundles.`), not a line per bundle entry, so describe them in the summary;
- `Examples:` is generated as a `Minimum:` call (required arguments only) and a `Full:` call. Each
  value is the argument's default when it has one; only arguments without a default use
  `ScanArgument.example`, or a placeholder (`dev.<name>`, `1.0`, `10` for steps) when no example
  is set.

So keep the `__init__` docstring to a summary sentence, `Args:` for readers of the code, and
`Returns: ScanReport`, as the generator template does. Check the result with
`scans.<scan_name>?` in the IPython client.
