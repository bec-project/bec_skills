# bec_skills

Agent skills for working on [BEC](https://github.com/bec-project) - the Beamline Experiment
Control system and its ecosystem (`bec`, `bec_widgets`, `ophyd_devices`, beamline plugin repos).
Each skill is a folder with a `SKILL.md` following the open
[Agent Skills](https://agentskills.io/specification) format, so the same files work in
Claude Code, OpenAI Codex CLI and Gemini CLI.

| skill | what it does |
|---|---|
| [`bec-deep-review`](skills/bec-deep-review/SKILL.md) | Thorough review of a PR / branch pair / working tree: bugs, design, thread/Qt/Redis pitfalls, test gaps, **including** problems found outside the change (tagged `introduced` / `exposed` / `pre-existing`). |
| [`bec-focused-review`](skills/bec-focused-review/SKILL.md) | Review restricted to what the change introduces; pre-existing problems go to a clearly separated section. |
| [`bec-new-widget`](skills/bec-new-widget/SKILL.md) | New `BECWidget` + Qt widget: lifecycle/cleanup, SafeSlot, dispatcher, RPC via `bw-generate-cli`, plugin-repo placement, leak-detecting tests. |
| [`bec-widget-safety-audit`](skills/bec-widget-safety-audit/SKILL.md) | Audit existing widgets for Qt lifecycle and thread safety: cleanup, destruction paths, deferred callbacks, signal proxies, cell widgets, exit crashes; runtime probes on the packaged fixtures, every finding with a failing test. |
| [`bec-new-plot-widget`](skills/bec-new-plot-widget/SKILL.md) | New plotting widget on `PlotBase`: imposed layout/properties, toolbar bundles, settings panels, throttled data flow, pyqtgraph performance and cleanup. |
| [`bec-new-scan`](skills/bec-new-scan/SKILL.md) | New scan on the v4 `ScanBase` template: all ten hooks, `ScanActions`/`ScanComponents`, typed arguments, plugin export, v4 tests. |
| [`bec-device-config`](skills/bec-device-config/SKILL.md) | Device configuration YAML: schema, readoutPriority/onFailure choices, composite configs with `!include`, validation with `ophyd_test`, loading with `bec.config`. |

Every skill carries `references/` (loaded on demand) and, where useful, `assets/` with runnable
templates. Skills are self-contained; nothing depends on files outside its own folder.

## Install

Clone once, then link the skills into the agent(s) you use. Symlinks mean a `git pull` updates
all agents at once.

```bash
git clone <this repo> ~/bec_skills
cd ~/bec_skills
scripts/install.sh                      # all agents, user scope (~/.claude, ~/.agents, ~/.gemini)
scripts/install.sh --agent claude       # one agent
scripts/install.sh --scope project      # into ./.claude/skills, ./.agents/skills, ./.gemini/skills of $PWD
scripts/install.sh --copy               # copy instead of symlink
```

### Claude Code

Three options:

1. **Symlink** (what `install.sh --agent claude` does): `~/.claude/skills/<skill>` for every
   project, or `<repo>/.claude/skills/<skill>` for one project. Claude Code picks up changes live.
2. **Plugin from this repo** - the repo is also a Claude Code plugin + marketplace
   (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`):

   ```
   /plugin marketplace add bec-project/bec_skills      # or a local path: /plugin marketplace add ~/bec_skills
   /plugin install bec-skills@bec-skills
   ```

   Skills are then namespaced: `/bec-skills:bec-new-widget`. For a team, pin it in the project's
   `.claude/settings.json`:

   ```json
   {
     "extraKnownMarketplaces": {
       "bec-skills": {"source": {"source": "github", "repo": "bec-project/bec_skills"}}
     },
     "enabledPlugins": {"bec-skills@bec-skills": true}
   }
   ```
3. **Ad hoc** for one session: `claude --plugin-dir ~/bec_skills`.

Invoke manually with `/bec-new-scan ...` or let Claude pick the skill from its description.
`claude plugin validate .` checks the plugin manifest.

### OpenAI Codex CLI

Codex reads `SKILL.md` folders from `.agents/skills/` in the current directory and every parent
up to the repo root, from `~/.agents/skills/` (user), and from `/etc/codex/skills`. Older builds
also read `~/.codex/skills/`.

```bash
scripts/install.sh --agent codex                 # -> ~/.agents/skills/<skill>
scripts/install.sh --agent codex --scope project # -> ./.agents/skills/<skill>
scripts/install.sh --agent codex --legacy-codex  # additionally ~/.codex/skills
```

Use `$bec-new-widget` in a prompt to invoke a skill explicitly, `/skills` to browse; Codex also
activates skills implicitly from their descriptions. Disable one in `~/.codex/config.toml`:

```toml
[[skills.config]]
path = "/Users/me/.agents/skills/bec-deep-review/SKILL.md"
enabled = false
```

### Gemini CLI

Gemini reads `~/.gemini/skills/` and `~/.agents/skills/` (user) and `.gemini/skills/` /
`.agents/skills/` (workspace). A Codex install therefore already serves Gemini; the installer
links into `.gemini/skills` as well for clarity.

```bash
scripts/install.sh --agent gemini
gemini skills install https://github.com/bec-project/bec_skills.git --consent   # alternative: install from git
gemini skills list --all
```

In a session: `/skills list`, `/skills reload`, `/skills enable|disable <name>`. Gemini asks for
confirmation before activating a skill the first time.

### Other agents

Any tool implementing the Agent Skills spec (Cursor, OpenCode, ...) can point at
`skills/<name>/`. Validate the folder with `skills-ref validate skills/<name>`.

## Using the review skills

Both take the same targets: a PR number/URL (`gh` must be authenticated), `base..head`, a branch
name (compared against `main`), or nothing (working tree). By default they never post to GitHub or
modify files. Pick `bec-focused-review` for merge decisions and `bec-deep-review` for audits, onboarding
onto unfamiliar code, or when you suspect the surrounding module.

```
/bec-focused-review https://github.com/bec-project/bec_widgets/pull/1285
/bec-deep-review feature/nidaq-rewrite..main
/bec-focused-review 1285 --prove
```

**Prove mode** (`prove` / `--prove`) additionally leaves runnable evidence for the developer on a
local branch `review/<N>-proof` in a dedicated worktree: failing unit tests written as the future
regression tests (`tests/review_proof/`), reproduction scripts and BEC IPython client recipes
(`review_proof/`), plus a README mapping each finding to its proof and the observed output. The
worktree and its environment are created with
[agent-worktree-manager](https://github.com/wyzula-jan/agent_worktree_manager) (`awm`) when it is
installed, otherwise with `git worktree` and a venv. Nothing is pushed and nothing is fixed on that
branch.

**Post mode** (`post` / `--post`, `bec-focused-review` only) publishes the finished review on the PR
as one GitHub review, rendered from the target repo's `.github/pull_request_review_template.md`
(bundled fallback: `assets/pull_request_review_template.md`). It is always submitted as a
`COMMENT` - the APPROVE / REQUEST CHANGES verdict is text, so an agent never supplies a required
approval - and re-running it edits the earlier review with the same model designation instead of
adding another. The review names the harness, the skill and the full model designation, and a
visible disclosure line states that an agent wrote it and which account posted it. The complete
body is shown for confirmation before anything is sent.

```
/bec-focused-review 1285 --post
```

## Repository layout

```
bec_skills/
├── README.md
├── AGENTS.md                  # how to add/maintain skills here
├── .claude-plugin/
│   ├── plugin.json            # Claude Code plugin manifest
│   └── marketplace.json       # single-plugin marketplace pointing at this repo root
├── scripts/
│   ├── install.sh             # symlink/copy skills into agent skill dirs
│   └── validate_skills.py     # frontmatter / naming / link checks (CI)
└── skills/
    └── <skill-name>/
        ├── SKILL.md
        ├── references/        # loaded on demand by the agent
        └── assets/            # templates the agent copies from
```

## Contributing

1. Add `skills/<name>/SKILL.md` (name = folder name, lowercase-hyphen, description that says
   *when* to use it), plus `references/` and `assets/` as needed. Keep `SKILL.md` under 500 lines.
2. Facts must come from the current BEC sources; quote file paths and class names, not memory.
3. `python scripts/validate_skills.py` must pass.
4. Conventional Commits (`feat(skills): add bec-new-dap-plugin`).
