#!/usr/bin/env python3
"""Validate every skills/*/SKILL.md against the Agent Skills spec (agentskills.io).

Checks: frontmatter present and first in file, `name` matches the directory name and the
name rules (1-64 chars, [a-z0-9-], no leading/trailing/double hyphen), `description` is
1-1024 chars, body under 500 lines, every relative link/path mentioned in the body exists.
Exit code 1 on any failure so it can run in CI.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\]\(((?:references|scripts|assets)/[^)#\s]+)")
PATH_RE = re.compile(r"`((?:references|scripts|assets)/[^`\s]+)`")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    meta: dict[str, str] = {}
    current = None
    for line in text[4:end].splitlines():
        if line.startswith(" ") and current:
            meta[current] += " " + line.strip()
        elif ":" in line:
            key, _, val = line.partition(":")
            current = key.strip()
            meta[current] = val.strip().strip('"').strip("'")
    return meta, text[end + 4 :]


def check(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return [f"{skill_dir.name}: missing SKILL.md"]
    text = md.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    if parsed is None:
        return [f"{skill_dir.name}: SKILL.md must start with a '---' frontmatter block"]
    meta, body = parsed
    name = meta.get("name", "")
    desc = meta.get("description", "")
    if not name:
        errors.append(f"{skill_dir.name}: frontmatter lacks `name`")
    elif name != skill_dir.name:
        errors.append(f"{skill_dir.name}: name '{name}' does not match directory name")
    elif not (1 <= len(name) <= 64 and NAME_RE.match(name)):
        errors.append(f"{skill_dir.name}: name '{name}' violates [a-z0-9-] / hyphen rules")
    if not desc:
        errors.append(f"{skill_dir.name}: frontmatter lacks `description`")
    elif len(desc) > 1024:
        errors.append(f"{skill_dir.name}: description is {len(desc)} chars (max 1024)")
    lines = body.count("\n")
    if lines > 500:
        errors.append(f"{skill_dir.name}: body is {lines} lines (keep SKILL.md under 500)")
    for rel in set(LINK_RE.findall(body)) | set(PATH_RE.findall(body)):
        if not (skill_dir / rel).exists():
            errors.append(f"{skill_dir.name}: referenced file '{rel}' does not exist")
    return errors


SHARED_COPIES = [
    ("bec-deep-review/references/bec-review-checklist.md",
     "bec-focused-review/references/bec-review-checklist.md"),
    ("bec-deep-review/references/proof-branch.md",
     "bec-focused-review/references/proof-branch.md"),
    ("bec-new-widget/references/repo-context.md",
     "bec-new-plot-widget/references/repo-context.md"),
    ("bec-new-widget/references/lifecycle.md",
     "bec-widget-safety-audit/references/lifecycle.md"),
]


def check_shared_copies() -> list[str]:
    errors = []
    for a, b in SHARED_COPIES:
        pa, pb = ROOT / a, ROOT / b
        if not (pa.exists() and pb.exists()):
            errors.append(f"shared copy missing: {a} / {b}")
        elif pa.read_bytes() != pb.read_bytes():
            errors.append(f"shared copies differ: {a} != {b} (copy one over the other)")
    return errors


def main() -> int:
    dirs = sorted(p for p in ROOT.iterdir() if p.is_dir())
    all_errors: list[str] = check_shared_copies()
    for d in dirs:
        errs = check(d)
        all_errors.extend(errs)
        print(("FAIL " if errs else "ok   ") + d.name)
        for e in errs:
            print("     " + e)
    print(f"\n{len(dirs)} skills, {len(all_errors)} problems")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
