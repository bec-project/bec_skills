<!--
Fallback copy of the BEC review template (layout of bec-project/bec
.github/pull_request_review_template.md). Prefer the target repository's own
copy when it has one; use this file only when it does not.

Replace placeholders and remove these instructions and unused optional sections.
Record only checks actually performed. The review applies to the reviewed commit;
check for newer commits before submitting and state any unreviewed changes.

Verdict (text only): APPROVE when no blocking findings remain; REQUEST CHANGES
when fixes are required; COMMENT when no approval decision is being made.
Summarize any blocking findings in the visible verdict reason.
An agent submits the review with the GitHub event COMMENT whatever the verdict:
a formal APPROVE would count towards required approvals, and the state of a
submitted formal review can never be edited afterwards.
Include the full model designation supplied by the review environment: model
family/version, variant, and reasoning effort, for example
"<model family> <version>, <variant>, effort <level>". Do not shorten it or omit
known settings. Do not guess missing details; mark unavailable components as
"not reported". For a human review, omit the model field and the disclosure
line below the reviewed commit.
Before posting, check for an existing COMMENT review on the same PR by the same
account with the exact same full model designation. Edit that review's body in
place rather than adding a duplicate, updating its verdict, reviewed commit,
findings, and validation. Keep reviews from different model designations separate.
Use immutable commit and source links. If local changes were also reviewed,
describe them explicitly: the commit alone does not identify that review scope.
-->

**Verdict:** {{APPROVE / REQUEST CHANGES / COMMENT}} — {{brief reason}}.

**Reviewer:** {{reviewer or agent name}}
**Model:** {{full model designation: family/version, variant, reasoning effort}}
**Reviewed commit:** [{{full head SHA}}]({{repository URL}}/commit/{{full head SHA}})

> This review was written by {{model}} running in {{agent or harness}} with {{skill, if any}}, then read and posted by @{{GitHub account}}.

<details>
<summary>Review details</summary>

**Base:** [{{full base SHA}}]({{repository URL}}/commit/{{full base SHA}})
**Scope:** {{head branch}} against {{base branch}}; {{files and behaviors reviewed}}.

### Findings introduced or exposed by this change

<!--
If none, replace the finding block with:
"No remaining introduced or exposed findings were identified."
Otherwise, repeat the block below, most severe first, up to ten findings.
"Introduced" means caused by the change; "exposed" means an existing defect is
made reachable, more likely, or worse by the change. Keep inherited issues below.
CONFIRMED requires a reproduction or concrete code path; PLAUSIBLE requires a
specific realistic failure scenario. Distinguish required fixes from suggestions.
-->

#### 1. [{{introduced / exposed}}] {{one-line defect}}

**Severity:** {{severity and whether it blocks approval}} · **Confidence:** {{CONFIRMED / PLAUSIBLE}}
**Location:** [{{file}}:{{line}}]({{immutable source permalink}})

{{Concrete trigger, incorrect behavior, impact, and how this change causes or exposes it.}}

**Evidence:** {{test result, reproduction, or concrete code path}}.
**Suggested fix:** {{specific change; name an existing helper or hook where appropriate}}.

### What was checked and found sound

- {{Author claim or risky behavior checked, and the evidence supporting it.}}
- {{Material assumption or explicitly accepted behavior, if relevant.}}

### Validation

- `{{exact command}}` → {{result, including passed/failed/skipped counts where relevant}}.
- {{Relevant environment, simulated services, or manual reproduction and result.}}
- **Limitations:** {{checks not run, unverified claims, or gaps and their effect on the verdict; omit if none}}.

### Optional improvements

<!-- Omit if none. Required fixes belong in findings, not here. -->
- {{Non-blocking suggestion within the change; cite the rule for convention feedback.}}

### Pre-existing issues — separate, non-blocking follow-ups

<!-- Omit if none. Explain why each issue predates and is not worsened by the change. -->
- [{{file}}:{{line}}]({{immutable source permalink}}) — {{issue, impact, and evidence it is pre-existing}}.

</details>
