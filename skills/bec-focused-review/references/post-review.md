# Post mode - publish the review on the PR

Read this only when post mode is active (the invocation contains `post` / `--post`, or the user
asks to post / publish / submit the review on GitHub). It adds one step after the chat report;
Phases 0-3 and the report itself are unchanged. Everything that goes to GitHub is visible to the
author and the whole organisation, so the user approves the exact text before it is sent.

## 0. Preconditions - otherwise stay in chat

- The target is a GitHub PR (number or URL). Branch pairs and working trees cannot be posted;
  say so and deliver the chat report only.
- `gh auth status` succeeds. Note the account: `gh api user -q .login`.
- The head SHA recorded in Phase 0 (`gh pr view <N> --json headRefOid,baseRefOid,url`) is the
  commit the review covers. Keep it; step 4 compares against it.

## 1. Pick the template

1. The target repository's own copy, on its default branch (a 404 means it has none):
   `gh api -H "Accept: application/vnd.github.raw+json" repos/<owner>/<repo>/contents/.github/pull_request_review_template.md`
2. Otherwise the bundled fallback `assets/pull_request_review_template.md`, which has the same
   layout.

Follow the instructions in the template's HTML comments, then delete those comments from the
rendered body. Where the repository template and this file disagree, this file wins on exactly
two points: the GitHub event is always `COMMENT` (step 5), and a verdict change never edits a
formal review in place (step 3).

## 2. Render the body

Write it to `<scratch>/review-body.md`. Map the chat report onto the template:

| chat report | template |
|---|---|
| verdict `approve` | `**Verdict:** APPROVE` |
| verdict `approve with fixes` | `APPROVE` if no finding blocks merging (list them, severity says "non-blocking"); `REQUEST CHANGES` if any does |
| verdict `request changes` | `REQUEST CHANGES` |
| findings (introduced / exposed) | "Findings introduced or exposed by this change", same order, same CONFIRMED / PLAUSIBLE |
| "Cleanup in the change" | "Optional improvements" |
| "Pre-existing problems noticed" | "Pre-existing issues - separate, non-blocking follow-ups" |
| "What was checked and found fine" | "What was checked and found sound" |
| Phase 3 commands and results | "Validation"; unrun checks and unverified author claims go to **Limitations** |

Rules for the body:

- **Model line**: the full designation your harness reports (model name/version, variant,
  reasoning effort). Never guess a component; write `not reported` for it. **Reviewer**: the agent
  / harness name (e.g. the CLI you run in), not the GitHub account.
- **Links are immutable**: commit links `https://github.com/<owner>/<repo>/commit/<sha>`, source
  links `https://github.com/<owner>/<repo>/blob/<head sha>/<path>#L<line>` - never `blob/main`.
- **No local detail**: no absolute paths, scratch directories, venv or host names, usernames. Test
  commands are written relative to the repository root.
- **Prove mode**: the proof branch is local and unpushed, so do not link it. Per finding, either
  inline the minimal failing test or snippet in a nested `<details>` block, or give the command
  and the decisive output line.
- No findings: use the template's "No remaining introduced or exposed findings were identified."

## 3. Find an existing review to replace

```bash
gh api --paginate repos/<owner>/<repo>/pulls/<N>/reviews \
  -q '.[] | {id, state, commit_id, html_url, login: .user.login, body}'
```

A review is "yours" when `login` equals the authenticated account **and** its `**Model:**` line
equals the one you rendered, character for character. Then:

- yours, `state == "COMMENTED"` -> update its body in place (step 5b). Its GitHub `commit_id`
  stays at the old commit; the **Reviewed commit** line in the body is authoritative.
- yours, `APPROVED` or `CHANGES_REQUESTED` -> a submitted review's state can never be edited.
  Post a new COMMENT review (step 5a) and tell the user the old formal review still counts (a
  change request keeps blocking) until they dismiss it or submit a new formal review themselves.
- several matches -> update the newest, list the others to the user; do not delete anything.
- none -> post a new review.
- same account but a different model line -> a separate review, never touch it.

## 4. Check the head, then ask

1. Re-read `headRefOid`. If it moved since Phase 0, stop: list the new commits
   (`gh api repos/<owner>/<repo>/compare/<old>...<new> -q '.commits[].commit.message'`) and ask
   whether to re-review. Never post a review of an old head as if it covered the new one.
2. Show the user: repository and PR, the account, create vs. update (with the review URL), the
   reviewed SHA, and the complete rendered body. Wait for an explicit yes. A `post` in the
   invocation authorises preparing the review, not skipping this confirmation.

## 5. Submit - COMMENT only

a. New review, pinned to the reviewed commit:

```bash
gh api -X POST repos/<owner>/<repo>/pulls/<N>/reviews \
  -f commit_id=<head sha> -f event=COMMENT -F body=@<scratch>/review-body.md -q .html_url
```

b. Update in place:

```bash
gh api -X PUT repos/<owner>/<repo>/pulls/<N>/reviews/<review id> \
  -F body=@<scratch>/review-body.md -q .html_url
```

Never send `event=APPROVE` or `event=REQUEST_CHANGES` and never use `gh pr review --approve` /
`--request-changes`, even when the verdict says so: the verdict lives in the text. A formal review
from an agent would count towards the repository's required approvals, and it cannot be amended
later. Only a user who explicitly asks for a formal review in this conversation changes this, and
then only for that one submission.

No inline line comments: every finding is in the one review body with a permalink. A `422` that
mentions a pending review means the account has an unsubmitted draft review on this PR - stop and
tell the user; do not submit or delete their draft.

## 6. Report back

End the chat report with the review URL returned by the API, whether it was created or updated,
and the reviewed SHA. If the post failed, give the error and leave `<scratch>/review-body.md` in
place so the user can paste it themselves.
