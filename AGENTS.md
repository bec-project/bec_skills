# AGENTS.md - working on bec_skills

This repository holds agent skills (Agent Skills spec: `skills/<name>/SKILL.md` + optional
`references/`, `assets/`, `scripts/`). It is consumed by Claude Code, Codex CLI and Gemini CLI,
so everything must stay tool-agnostic and self-contained per skill folder.

## Rules

- **One folder per skill; no cross-folder references.** Skills are symlinked individually into
  agent skill directories, so `../other-skill/...` breaks. If two skills need the same reference
  (currently `references/bec-review-checklist.md` and `references/proof-branch.md` in both review skills,
  `references/repo-context.md` in `bec-new-widget` and `bec-new-plot-widget`, and
  `references/lifecycle.md` in `bec-new-widget` and `bec-widget-safety-audit`), keep the copies
  byte-identical; `scripts/validate_skills.py` checks that.
- **Core repo vs beamline plugin repo.** Most users are scientists in a beamline plugin repo. Every
  skill that creates code must say where the code goes in both cases and when to ask the user.
  The widget skills point at their `references/repo-context.md` copy; `bec-new-scan` keeps its
  scan-specific routing (plugin scan, `ScanModifier`, core) in `SKILL.md`.
- **Test fixtures come from the packages.** Widget tests use the fixtures shipped in
  `bec_widgets.tests` (`fixtures.py` star-imported by the widget-test conftest, `utils.py`,
  `client_mocks.py`, `fake_devices.py`); never tell an agent to import from `tests.unit_tests...`
  or to copy fixtures into a plugin repo.
- **Frontmatter**: `name` equals the folder name, `[a-z0-9-]`, no leading/trailing/double hyphen;
  `description` states what the skill does *and* when to trigger it, under 1024 chars, slightly
  "pushy" (agents under-trigger). Optional `metadata:` map only; avoid Claude-only fields
  (`allowed-tools`, `context`, `hooks`) unless a skill is explicitly Claude-specific.
- **Portability of the body**: never rely on `${CLAUDE_SKILL_DIR}`, `Agent`, `ReportFindings` or
  other harness-specific tools unconditionally - phrase them as "if your harness has X, otherwise
  do Y". Refer to bundled files by relative path from the skill folder.
- **Facts, not folklore**: every base class, hook, fixture, CLI flag or file path mentioned must
  exist in the current BEC repos (`bec`, `bec_widgets`, `ophyd_devices`, `beamline_plugins/*`).
  When the upstream API changes (e.g. v3 → v4 scans, `PSIDetectorBase` → `PSIDeviceBase`), update
  the skill and add a line to the legacy-mapping table instead of deleting the old name - agents
  meet old code.
- **Size**: `SKILL.md` < 500 lines; move detail into `references/` with a one-line pointer saying
  when to read it. Templates in `assets/` must be valid Python that imports from real modules.
- **No PSI-workstation specifics** (uv venv names, `psi_run.sh`, worktree helpers, local paths)
  in shipped skills; use generic `python -m pytest`, `pip`, `git worktree`.

## Checks before committing

```bash
python scripts/validate_skills.py
claude plugin validate .          # if Claude Code is installed
```

## Adding a skill

1. `mkdir -p skills/<name>/references skills/<name>/assets`, write `SKILL.md`.
2. Add a row to the table in `README.md`.
3. Run the checks; commit with a Conventional Commits message (`feat(skills): add <name>`).
