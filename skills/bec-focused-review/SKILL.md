---
name: bec-focused-review
description: Focused code review of a BEC-ecosystem pull request, branch pair or working tree (bec, bec_widgets, ophyd_devices, beamline plugin repos) that judges only what the change itself introduces. Pre-existing problems it stumbles on are reported, but in a strictly separate section so the author is never blamed for inherited code. Use whenever the user asks to review a PR / branch / diff, "check my changes", "is this PR good to merge", or wants review comments for a merge request. For a thorough audit of the whole touched area including inherited bugs, use bec-deep-review instead. Supports a prove mode (say "prove" / --prove) that leaves failing regression tests, repro scripts and BEC IPython recipes on a local review/<N>-proof branch in its own worktree (created with agent-worktree-manager when available), and a post mode (say "post" / --post) that publishes the review on the PR as a single COMMENT review rendered from the repo's review template, after the user approves the text.
metadata:
  author: bec-project
  version: "0.1"
---

# BEC focused review

You are reviewing **the delta**: every finding must be traceable to a line the change added,
modified or removed, or to a behaviour the change altered. The bar for a finding is "would a
careful BEC maintainer block or request changes on this PR for this". Problems you notice in
code the PR merely touches or sits next to are worth a sentence in a separate section, never a
finding against the change.

The deliverable is a report in chat (template at the end). Never post to GitHub (outside post
mode), never push, never fix anything unless the user asks afterwards.

## Phase 0 - Gather the diff

1. **Resolve the target.** PR number or URL (`gh pr view <N> --json title,body,baseRefName,headRefName,commits`,
   `gh pr diff <N>`), `<base>..<head>` / "branch X against Y", a single branch (against `main`),
   or nothing (`git diff main...HEAD` plus `git diff HEAD` for uncommitted work - reviews usually
   run before the commit). Never check the PR branch out over the user's working copy - use a
   worktree (`git worktree add ../<repo>_review-<N> <head>`) or `git fetch origin pull/<N>/head:pr-<N>`.
2. **Save the diff** to `<scratch>/review.diff` and list changed files. This file is the review
   scope; finders read it, not `git`.
3. **Read the conventions** that govern the changed files: the repo `AGENTS.md` / `CLAUDE.md`, and
   [references/bec-review-checklist.md](references/bec-review-checklist.md) for BEC-specific
   failure modes (Qt cleanup, SafeSlot, dispatcher, scan stubs, ophyd hooks, Redis endpoints,
   tests). Use the checklist to sharpen the angles below, not as a list of things to grep for
   across the repo.
4. **Note the author's claims** ("fixes #123", "no behaviour change", "tested on the beamline").

## Phase 1 - Find candidates (7 angles, changed code only)

Run every angle. With sub-agents (Claude Code `Agent`, Codex/Gemini sub-tasks) run them in
parallel, read-only, pointed at the diff file and the checklist; otherwise do them sequentially
yourself. Each angle returns **up to 6 candidates** with `file`, `line`, `summary`,
`failure_scenario` and `origin`:

- `introduced` - the defect lives in added/modified lines, or the change removed what prevented it.
- `exposed` - the defect was already in the code but the change makes it reachable, more likely,
  or worse (a new caller, a wider input range, a removed guard elsewhere). Still counts against
  the change - the author has to deal with it - but say so.
- `pre-existing` - noticed while reading, untouched by the change. Goes to the separate section.

**Angles**

- **A. Line-by-line diff scan.** Every hunk, then just enough of the enclosing function to judge
  it. What input, state, timing or platform makes this line wrong? Inverted conditions,
  off-by-one, `None` deref, falsy-zero, wrong variable after copy-paste, swallowed exceptions,
  missing `yield from` on a scan stub, wrong `MessageEndpoints` name, `str` vs `bytes`.
- **B. Removed-behaviour audit.** For every deleted or replaced line name the invariant it
  enforced and find where the new code re-establishes it: dropped guards, narrowed validation,
  deleted tests, removed `cleanup()` / `disconnect_slot` / `timer.stop()` calls.
- **C. Cross-file tracer.** Callers and callees of every changed symbol (grep this repo and
  the sibling BEC repos if checked out next to it). New preconditions, changed return shapes,
  new exceptions, ordering dependencies, changed `USER_ACCESS` signatures that break the
  generated RPC client.
- **D. Lifecycle & threads in the delta.** Every `QTimer`, `QThread`, `threading.Thread`,
  `submit_task`, dispatcher `connect_slot`, `SafeConnect`, ophyd subscription or status callback
  the diff adds: is it stopped / joined / disconnected on `cleanup()` or `on_destroy`? Is any Qt
  object touched from a non-GUI thread? Any new slot without `@SafeSlot`? Any I/O added to a
  constructor or to the Qt main thread?
- **E. Reuse, simplification, efficiency.** New code re-implementing a helper the repo already
  has (grep `bec_lib/utils`, `bec_widgets/utils`, `ophyd_devices/utils`), derivable state,
  dead code, new repeated I/O or Redis round-trips, per-point Python loops in plot updates,
  closures kept alive by long-lived objects. Name the existing helper or the simpler form.
- **F. Tests & docs for the delta.** Does each new behaviour have a unit test using the repo's
  fixtures? Do new tests leak widgets/timers/threads (the autouse fixtures fail on that - run
  them)? Are they order-independent? Did user-visible changes update docs, docstrings, the
  `bw-generate-cli` client stubs, the demo config?
- **G. Conventions.** Only clear violations where you can quote the rule (`AGENTS.md`/`CLAUDE.md`)
  and the offending added line: qtpy over PySide6, f-strings, black/isort, `ophyd_devices`
  imports over `ophyd`, Conventional Commits in the PR title. No style opinions.

Pass through every candidate with a nameable failure scenario; the verifier decides.

## Phase 2 - Verify

Dedup (same defect, same location, same reason). For each candidate run one verifier (sub-agent
or yourself) with the diff, the relevant files and the candidate. Verdicts:

- **CONFIRMED** - reproduced or shown by a concrete code path. When cheap, reproduce: run the
  affected test, a short Python snippet against the module, or the widget under
  `QT_QPA_PLATFORM=offscreen`.
- **PLAUSIBLE** (default for realistic runtime state) - races, rare error paths, cold caches,
  missing optional config keys, `--random-order` interactions. Do not refute as "speculative".
- **REFUTED** - only with constructible evidence: quote the line, the type/invariant, or the guard
  already in the diff. Also refute (re-tag) `introduced` candidates that on inspection are
  `pre-existing`: `git blame` / `git log -L` the line if unsure.

Keep CONFIRMED and PLAUSIBLE.

## Phase 3 - Run what the change touches

Run the tests the diff adds or modifies plus the test modules of every changed source file, in a
dedicated environment: `python -m pytest --random-order -q <tests>` (bec_widgets: add
`-p no:cacheprovider`, `pyside6-uic` must be on `PATH`). Compare against the author's claims; a
claim without evidence becomes an `unverified-claim` finding. If the change adds or changes a
widget and a live or simulated BEC is available, exercise it once - unit tests alone rarely
catch dispatcher and teardown problems.

## Phase 3b - Prove mode (only when asked)

Activate when the invocation contains `prove` / `--prove` or the user asks for proofs,
reproductions the developer can run, or a branch with failing tests. It roughly doubles the cost
of the review, so it is never on by default. Follow [references/proof-branch.md](references/proof-branch.md)
exactly; the essentials:

1. **Sandbox first.** If `agent-worktree-manager` is installed (`awm --version`) and an `awm.toml`
   governs the repo, create the sandbox with it - worktree plus reproduced environment in one step:
   `awm --root <project> create review-<N>-proof --repo <alias> --ref <head-sha>` (dry-run first),
   then run everything via `awm --root <project> run --repo <alias> review-<N>-proof -- <cmd>`.
   Otherwise `git worktree add ../<repo>_review-<N>-proof -b review/<N>-proof <head-sha>` plus a
   venv with the reviewed code editable-installed. Prove that imports resolve to the worktree
   before writing anything. Never use the user's checkout.
2. **Branch `review/<N>-proof` from the reviewed head.** Only proof artefacts go on it: failing
   unit tests under `tests/review_proof/` written as the regression tests the fix should make
   pass, scripts under `review_proof/scripts/` for leaks/races/timing, BEC IPython recipes under
   `review_proof/ipython/` for problems only visible against running services (simulated config
   only, never hardware), and `review_proof/README.md` mapping finding -> proof -> command ->
   observed output. Commit per finding (`test(review): proof for finding <n> - <slug>`). Do not
   push. Do not fix anything on this branch.
3. **Scope: CONFIRMED and PLAUSIBLE correctness and lifecycle findings only.** Cleanup, design and
   convention findings get no proof.
4. **A proof counts only if you ran it in the sandbox and it failed for the stated reason.** A
   finding whose proof cannot be made to fail is downgraded to "unverified candidate"; its
   half-finished proof is not committed. Prove mode must raise confidence, not volume.
5. Leave the sandbox in place for the developer and end the report with the "Proof branch" block
   (branch, worktree/env paths, fetch command, run command, cleanup command).

## Phase 4 - Post mode (only when asked)

Activate when the invocation contains `post` / `--post` or the user asks to post, publish or
submit the review on the PR - including after the chat report was delivered. PR targets only.
Follow [references/post-review.md](references/post-review.md) exactly; the essentials:

1. **Render, don't rewrite.** Map the finished chat report onto the target repository's
   `.github/pull_request_review_template.md` (fallback: `assets/pull_request_review_template.md`):
   visible verdict, reviewer, full model designation and reviewed commit; everything else in the
   collapsed details. Permalinks at the head SHA, no local paths.
2. **One review per model designation.** Edit your own earlier COMMENT review with the same
   `**Model:**` line in place instead of adding a second one.
3. **COMMENT only.** The verdict is text; never submit a formal APPROVE or REQUEST_CHANGES - an
   agent approval would count towards required reviews and cannot be amended later.
4. **Head unchanged, user agreed.** Re-check the head SHA, show the complete body, and post only
   after an explicit yes. Report the review URL.

## Output

At most 10 findings against the change, most severe first: correctness, then lifecycle, then
design/cleanup, then conventions. `introduced` outranks `exposed` at equal severity.

If your harness has a `ReportFindings` tool, call it once with the findings (`category`,
`verdict`, `file`, `line`, `summary`, `failure_scenario`; prefix `summary` with the origin tag)
and do **not** include pre-existing problems in it. Then, and in every other harness, write the
report in chat:

```
## Focused review: <target> - <verdict: approve / approve with fixes / request changes>
Scope: <n> files, +<a>/-<d> lines. Tests run: <cmd> -> <result>.
Author's claims: <claim> - <verified / unverified (why)>.

### Findings introduced or exposed by this change (most severe first)
#### 1. [introduced|exposed] <one-line defect> - <file>:<line>  (<CONFIRMED|PLAUSIBLE>)
What is wrong and why it matters (2-4 sentences, concrete failure scenario).
Evidence: <test output / code path / repro snippet>.
Proof (prove mode): <path> - <command> -> <decisive output>.
Suggested fix: <one or two sentences; name the helper / hook / base-class method>.

### Cleanup in the change (reuse / simplification / conventions)
- <one line each; quote the rule for conventions>

### Pre-existing problems noticed (NOT caused by this change - follow-up material)
- <file>:<line> - <one line>. Not blocking.

### What was checked and found fine
- <one line per author claim or risky area that held up>
```

The last section matters: a focused review that lists only problems reads as hostile and hides
what the reviewer actually verified. Do not create artifacts, files or GitHub comments for the
report unless asked; post mode is the only way this skill writes to GitHub. If the user later asks you to fix findings and a `ReportFindings` tool
exists, re-report each with an `outcome`.
