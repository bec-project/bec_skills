---
name: bec-deep-review
description: Deep code review of a BEC-ecosystem pull request, branch pair or working tree (bec, bec_widgets, ophyd_devices, beamline plugin repos). Reviews the change AND the code it lives in - bugs, bad design, thread/Qt/Redis pitfalls, test gaps - and also flags problems found outside the change. Use whenever the user asks for a thorough / deep / full review, an audit of a PR or branch, or "review this branch against main and tell me everything that is wrong". For a review restricted to what the change itself introduced, use bec-focused-review instead.
metadata:
  author: bec-project
  version: "0.1"
---

# BEC deep review

You are reviewing for **recall across the whole touched area**: catch every real bug and design
problem a senior BEC maintainer would catch in one long sitting, whether or not the change under
review introduced it. The change is the entry point, not the boundary. A finding outside the diff
is still a finding - it just has to be labelled as such so the author knows what they own.

The deliverable is a report in chat (template at the end). Never post to GitHub, never push,
never fix anything unless the user asks afterwards.

## Phase 0 - Establish scope

1. **Resolve the target.** Accepted forms: a PR number or URL, `<base>..<head>` / "branch X against
   Y", a single branch (compare against `main`), or nothing (working tree: `git diff main...HEAD`
   plus `git diff HEAD` for uncommitted work). For a PR: `gh pr view <N> --json title,body,baseRefName,headRefName,commits`
   and `gh pr diff <N>`. Never check the PR branch out over the user's working copy - use a
   worktree (`git worktree add ../<repo>_review-<N> <head>`) or `git fetch origin pull/<N>/head:pr-<N>`.
2. **Save the diff to a file** (`<scratch>/review.diff`) and list changed files. Every finder reads
   this file rather than re-running git.
3. **Map the touched area**, not just the hunks: for each changed file note its module, the
   classes it defines, who imports it (`grep -rn "from <module>" --include=*.py`), and the tests
   that cover it (`tests/unit_tests/**/test_<name>*.py`). This map is what makes the review deep:
   the finders in Phase 1 read whole modules, not hunks.
4. **Read the governing conventions**: the repo's `AGENTS.md` / `CLAUDE.md`, and
   [references/bec-review-checklist.md](references/bec-review-checklist.md) in this skill for the
   BEC-specific failure modes (Qt cleanup, SafeSlot, dispatcher, scan stubs, ophyd hooks, Redis
   endpoints, tests).
5. **Extract the author's claims** from the PR body / commit messages ("fixes X", "no behaviour
   change", "tested with ..."). Each claim is something to verify in Phase 3.

## Phase 1 - Find candidates (9 angles)

Run every angle. If your harness has sub-agents (Claude Code `Agent`, Codex/Gemini sub-tasks), run
the angles in parallel, read-only, each pointed at the diff file, the file map and the checklist;
otherwise do them one after another yourself. Each angle returns **up to 8 candidates** with
`file`, `line`, `summary`, `failure_scenario`, and `origin` = `introduced` | `pre-existing` |
`exposed` (old bug that the change now makes reachable or worse).

**Correctness angles**

- **A. Line-by-line diff scan.** Every hunk, then the enclosing function. What input, state,
  timing or platform makes this line wrong? Inverted conditions, off-by-one, `None` deref,
  falsy-zero, wrong variable after copy-paste, swallowed exceptions, missing `yield from` on a
  scan stub, `str` vs `bytes` on Redis payloads.
- **B. Removed-behaviour audit.** For every deleted or replaced line name the invariant it
  enforced and find where the new code re-establishes it. Dropped guards, narrowed validation,
  deleted tests, removed `cleanup()` / `disconnect_slot` calls.
- **C. Cross-file tracer.** Callers and callees of every changed symbol (grep the whole repo and
  the sibling repos if they are checked out next to it: bec_widgets calls bec_lib, plugins call
  both). New preconditions, changed return shapes, new exceptions, ordering dependencies, RPC
  `USER_ACCESS` surfaces that changed signature.
- **D. Whole-module read (deep-only).** Read each touched module top to bottom as if it were new
  code. Anything wrong in it is a candidate with `origin: pre-existing`. Look especially for the
  checklist items: widgets without `cleanup()`, slots without `@SafeSlot`, threads without a
  join, timers not stopped, scans whose `scan_core` blocks instead of yielding, devices doing
  I/O in `__init__`.
- **E. Concurrency & lifecycle.** Qt main thread vs dispatcher thread vs Redis callbacks; scan
  server generators vs device threads; `QTimer`, `QThread`, `threading.Thread`, `concurrent.futures`
  created in the touched code - is every one stopped, joined and dereferenced on close? Is any
  Qt object touched from a non-GUI thread without a signal?

**Design angles**

- **F. Design & altitude.** Is the change at the right layer? Special-casing in shared
  infrastructure, a plugin working around a core limitation instead of fixing the core, a
  widget reaching into another widget's internals, a scan re-implementing what a `ScanStub` or
  base-class hook already does, an ophyd device bypassing `on_*` hooks. Name the better shape.
- **G. Reuse, simplification, efficiency.** Re-implemented helpers (grep `bec_lib/utils`,
  `bec_widgets/utils`, `ophyd_devices/utils`), derivable state, dead code, repeated I/O or
  Redis round-trips in hot paths, per-point Python loops where numpy/`setData` would do,
  closures kept alive by long-lived objects.
- **H. Tests & docs.** Is every new behaviour covered by a unit test using the repo's fixtures
  (see checklist)? Do tests leak widgets/threads (autouse leak fixtures will catch it - run
  them)? Are tests order-independent (`--random-order`)? Do user-facing changes update docs /
  docstrings / `USER_ACCESS` CLI stubs (`bw-generate-cli`)?
- **I. Conventions.** Quote the exact rule from `AGENTS.md`/`CLAUDE.md` and the exact line that
  breaks it (qtpy over PySide6, f-strings, Conventional Commits, Black/isort line length, no
  `ophyd` import where `ophyd_devices` re-exports). No taste-based nits.

Pass every candidate that has a nameable failure scenario through. Finders that silently drop
"probably fine" candidates are the dominant cause of misses; the verifier exists to drop them.

## Phase 2 - Verify

Dedup (same defect, same location, same reason). For each remaining candidate run one verifier
(sub-agent or yourself) with the diff, the relevant files and the candidate. It returns exactly
one of **CONFIRMED / PLAUSIBLE / REFUTED** with one sentence of evidence:

- **CONFIRMED**: reproduced or shown by a concrete code path. Where it is cheap, *do* reproduce:
  run the specific test, a 10-line Python snippet against the module, or a widget in
  `QT_QPA_PLATFORM=offscreen` mode.
- **PLAUSIBLE** (default): realistic runtime state makes it fail - races, rare error paths,
  cold caches, missing optional config keys, `--random-order` interactions. Do not refute for
  "speculative".
- **REFUTED** only with constructible evidence: quote the line that makes it impossible, the type
  or invariant, or the guard already present in the diff.

Keep CONFIRMED and PLAUSIBLE.

## Phase 3 - Check the author's claims

For each claim from Phase 0.5, find the evidence: the test that proves the fix, the code path
that shows "no behaviour change" is true, the CLI/CI run that shows it was tested. Run the tests
the diff touches in a dedicated environment (`python -m pytest --random-order -q <touched tests>`;
for bec_widgets add `-p no:cacheprovider` and make sure `pyside6-uic` is on `PATH`). An
unproven claim becomes a finding of category `unverified-claim`.

## Output

Rank most-severe first, cap at 15 (correctness before design before cleanup; `introduced` before
`exposed` before `pre-existing` at equal severity). Every finding carries its `origin` tag - that
is the one rule that makes this a deep review rather than an unfair one: the author must be able
to see at a glance what they broke versus what they inherited.

If your harness has a `ReportFindings` tool, call it once with the findings (`category`,
`verdict`, `file`, `line`, `summary`, `failure_scenario`; put the origin tag at the start of
`summary`). Then, and in every other harness, write the report in chat:

```
## Deep review: <target> - <verdict: mergeable / mergeable with fixes / not mergeable>
Scope: <n> files changed, <m> modules read in full, tests run: <cmd> -> <result>.
Author's claims: <claim> - <verified / unverified (why)>.

### Findings (most severe first)
#### 1. [introduced|exposed|pre-existing] <one-line defect> - <file>:<line>  (<CONFIRMED|PLAUSIBLE>)
What is wrong and why it matters (2-4 sentences, concrete failure scenario).
Evidence: <test output / code path / repro snippet>.
Suggested fix: <one or two sentences, name the helper/hook/base-class method to use>.

### Design notes (no single failing line)
- <architecture / altitude observations with the better shape named>

### Pre-existing problems outside the change (for a follow-up, not blocking this PR)
- <file>:<line> - <one line>

### Cleanup (reuse / simplification / conventions)
- <one line each, rule quoted for conventions>
```

Do not create artifacts, files or GitHub comments for the report unless asked. If the user later
asks you to fix findings and a `ReportFindings` tool exists, re-report each with an `outcome`.
