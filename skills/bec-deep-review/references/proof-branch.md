# Prove mode - leaving runnable evidence on a proof branch

Prove mode turns the review's findings into artefacts the developer can execute: failing unit
tests written as the future regression tests, standalone scripts for behaviour unit tests
cannot show, and BEC IPython client recipes for problems that only appear against a running
system. Everything lives on a dedicated branch in a dedicated worktree. Nothing is pushed,
nothing is fixed.

## 1. Sandbox: worktree + environment

Never work on the user's checkout. Preference order:

**A. `agent-worktree-manager` (`awm`) is installed and the repo has an `awm.toml` above it.**
It creates the worktree *and* a reproduced Python environment with the worktree editable-installed,
so imports resolve to the proof branch:

```bash
awm --version                                   # present?
awm --root <project-root> list --json           # existing sandboxes; never reuse one that is not yours
awm --root <project-root> create review-<N>-proof --repo <alias> --ref <target-head-sha> --dry-run
awm --root <project-root> create review-<N>-proof --repo <alias> --ref <target-head-sha>
awm --root <project-root> list --json           # take worktrees[].path and environments[].path from here
```

`<alias>` is the repository key in `awm.toml` (e.g. `bec_widgets`); `--ref` pins the sandbox to the
reviewed head instead of the checkout's current HEAD. Wait for status `ready`. Run everything
through awm so the sandbox interpreter is used and its lock is held:

```bash
awm --root <project-root> run --repo <alias> review-<N>-proof -- python -m pytest -q tests/review_proof
```

Inside the worktree create the branch: `git switch -c review/<N>-proof`. Do not delete the
sandbox at the end - the developer needs it; mention `awm delete review-<N>-proof` in the report.
If `awm` reports a busy lock, dependency conflict or failed creation, report it and fall back to B;
do not force, retry with `--force`, or touch other sandboxes.

**B. Plain git worktree** (no awm): 

```bash
git -C <repo> worktree add ../<repo>_review-<N>-proof -b review/<N>-proof <target-head-sha>
python -m venv ../<repo>_review-<N>-proof/.venv && ../<repo>_review-<N>-proof/.venv/bin/pip install -e "../<repo>_review-<N>-proof[dev]"
```

Sibling BEC packages the repo depends on must be installed in that venv too (editable from their
checkouts, or from PyPI) - the proof must import the reviewed code, not the primary checkout.
Verify with `python -c "import <pkg>; print(<pkg>.__file__)"` before writing a single test.

## 2. Branch layout

```
review_proof/
  README.md                      # finding -> proof map (format below)
  scripts/
    repro_<n>_<slug>.py          # standalone reproductions (leaks, races, timing)
  ipython/
    recipe_<n>_<slug>.md         # numbered client recipe, sim config only
    recipe_<n>_<slug>.py         # optional: %run-able companion for the recipe
tests/review_proof/
  __init__.py
  conftest.py                    # re-export the repo's fixtures the proofs need (see below)
  test_review_<n>_<slug>.py      # one file per finding
```

`tests/review_proof/` is deliberately outside the normal test packages so a stray merge cannot
break CI, but `python -m pytest tests/review_proof` still collects it. The `conftest.py` imports
the fixtures the repo's own tests use (bec_widgets: `from tests.unit_tests.conftest import *` and
`from tests.unit_tests.client_mocks import *`; bec_server scans: the `scan_fixtures` plugin;
ophyd_devices: `patched_device`). Never re-implement fixtures.

Commit per finding, message `test(review): proof for finding <n> - <slug>`; a final
`docs(review): add review_proof/README.md`. No other changes on the branch.

## 3. Proof types and when to use which

| finding shows up as | proof | must |
|---|---|---|
| wrong value / exception / missing guard on a reachable code path | **unit test** | fail today with the assert stating the *correct* behaviour, so the fix PR can move it into the real test tree unchanged |
| resource leak, timer/thread left running, growth over iterations | **script** (or a test using the leak fixtures) | print the measurement (`len(...)`, thread count, `tracemalloc` delta) before/after and exit non-zero on the defect |
| race / order dependence | **test with `--random-order-seed`** or a script looping N times | record the seed or iteration count that reproduces |
| only visible against running services (scan queue, Redis streams, file writer, GUI dock) | **IPython recipe** (+ optional `.py`) | target the simulated device config only; state what to observe and what correct behaviour would look like |
| GUI behaviour | script under `QT_QPA_PLATFORM=offscreen` that builds the widget with the mocked client, drives it, and asserts state (or saves a screenshot to `review_proof/artifacts/`) | never require a display |

A proof exists only if it was **executed in the sandbox and failed for the stated reason**. Put
the decisive output lines into the README. If you cannot make it fail, the finding is downgraded to
"unverified candidate" in the report and no proof file is committed for it.

## 4. Templates

Unit test (bec_widgets example):

```python
"""Review finding 3: Waveform keeps the old scan's async subscription after a new scan opens.
Expected after the fix: exactly one device_async_signal subscription per curve."""
from bec_lib.endpoints import MessageEndpoints
from bec_widgets.widgets.plots.waveform.waveform import Waveform

from tests.unit_tests.client_mocks import create_dummy_scan_item, mocked_client  # noqa: F401
from tests.unit_tests.conftest import create_widget


def test_review_3_async_subscription_is_swapped_per_scan(qtbot, mocked_client, monkeypatch):
    wf = create_widget(qtbot, Waveform, client=mocked_client)
    wf.plot("async_device")
    scans = {"s1": create_dummy_scan_item(scan_id="s1"), "s2": create_dummy_scan_item(scan_id="s2")}
    monkeypatch.setattr(wf.queue.scan_storage, "find_scan_by_ID", lambda sid: scans[sid])
    wf.on_scan_status({"scan_id": "s1", "status": "open"}, {})
    wf.on_scan_status({"scan_id": "s2", "status": "open"}, {})
    topics = [str(t) for t in wf.bec_dispatcher._connections if "async" in str(t)]
    assert len(topics) == 1, f"stale subscriptions kept: {topics}"   # FAILS on review/<N>-proof
```

Script skeleton:

```python
"""Review finding 5: <one line>. Run: python review_proof/scripts/repro_5_<slug>.py  -> exit 1 on defect."""
import sys, gc, threading
...
before = threading.active_count()
for _ in range(200):
    ...  # create/destroy the object under review
gc.collect()
after = threading.active_count()
print(f"threads before={before} after={after}")
sys.exit(1 if after > before else 0)
```

IPython recipe (`review_proof/ipython/recipe_<n>_<slug>.md`):

```markdown
# Finding <n>: <one line>
Requirements: BEC services running with the demo/sim config (`bec.config.load_demo_config()`), `bec` IPython client.
Do NOT run against beamline hardware.

1. `gui.new("Waveform")` ; `gui.Waveform.plot("bpm4i")`
2. `scans.line_scan(dev.samx, -5, 5, steps=50, exp_time=0.02, relative=False)`
3. While it runs: `scans.line_scan(dev.samx, -5, 5, steps=50, exp_time=0.02, relative=False)` from a second client
Observe: <what the reviewer saw, e.g. curve keeps points of scan 1>. Expected: <correct behaviour>.
Companion: `%run review_proof/ipython/recipe_<n>_<slug>.py` performs steps 1-3 and prints the observed values.
```

## 5. README.md on the branch

```markdown
# Review proofs for <target> (<head sha>)
Sandbox: <worktree path>, env: <env path>  (awm sandbox `review-<N>-proof` | plain venv)
Run all unit proofs: `python -m pytest -q tests/review_proof`   -> expected today: <k> failed, 0 passed

| # | finding (severity, origin) | proof | command | observed on this branch |
|---|---|---|---|---|
| 1 | <one line> (CONFIRMED, introduced) | tests/review_proof/test_review_1_<slug>.py | pytest ... | `AssertionError: ...` |
| 2 | <one line> (PLAUSIBLE, exposed)   | review_proof/scripts/repro_2_<slug>.py | python ... | `threads before=7 after=57` |
| 3 | <one line> (CONFIRMED, introduced) | review_proof/ipython/recipe_3_<slug>.md | manual | screenshot artifacts/finding_3.png |

Findings without proof (unverified): <list or "none">.
After fixing: move `tests/review_proof/test_review_*.py` into the regular test tree (drop the `review_` prefix), delete `review_proof/`.
```

## 6. Report additions

In the chat report add one line per finding: `Proof: <path> - <command> -> <decisive output>`, and a
closing block:

```
### Proof branch
review/<N>-proof in <worktree path> (awm sandbox review-<N>-proof, env <path>) - not pushed.
Fetch: git -C <your checkout> fetch <worktree path> review/<N>-proof
Run:   python -m pytest -q tests/review_proof     (expected: <k> failed)
Clean: awm delete review-<N>-proof   |   git worktree remove <worktree path>
```
