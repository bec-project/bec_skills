#!/usr/bin/env bash
# Install (symlink) the BEC skills into the skill directories of one or more agent CLIs.
#
#   scripts/install.sh [--agent claude|codex|gemini|all] [--scope user|project] [--copy] [--target DIR]
#
# Default: --agent all --scope user. Symlinks are used so a `git pull` in this repo updates every
# agent at once; pass --copy for a plain copy (e.g. when the repo is not kept around).
#
# Claude Code   user:    ~/.claude/skills/<skill>              project: <project>/.claude/skills/<skill>
# Codex CLI     user:    ~/.agents/skills/<skill>              project: <project>/.agents/skills/<skill>
#               (legacy ~/.codex/skills is still scanned by older Codex builds; add --legacy-codex to fill it too)
# Gemini CLI    user:    ~/.gemini/skills/<skill>              project: <project>/.gemini/skills/<skill>
#               (Gemini also reads ~/.agents/skills and .agents/skills, so a Codex install covers Gemini as well)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
agent=all
scope=user
mode=link
legacy_codex=0
target_root=""
project_dir="$PWD"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) agent="$2"; shift 2 ;;
    --scope) scope="$2"; shift 2 ;;
    --copy) mode=copy; shift ;;
    --legacy-codex) legacy_codex=1; shift ;;
    --target) target_root="$2"; shift 2 ;;
    --project) project_dir="$2"; shift 2 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

skills=()
for d in "$here"/skills/*/; do
  [[ -f "$d/SKILL.md" ]] && skills+=("$(basename "$d")")
done
[[ ${#skills[@]} -gt 0 ]] || { echo "no skills found under $here/skills" >&2; exit 1; }

dirs=()
if [[ -n "$target_root" ]]; then
  dirs+=("$target_root")
else
  base="$HOME"; [[ "$scope" == project ]] && base="$project_dir"
  case "$agent" in
    claude) dirs+=("$base/.claude/skills") ;;
    codex)  dirs+=("$base/.agents/skills"); [[ $legacy_codex == 1 && "$scope" == user ]] && dirs+=("$HOME/.codex/skills") ;;
    gemini) dirs+=("$base/.gemini/skills") ;;
    all)    dirs+=("$base/.claude/skills" "$base/.agents/skills" "$base/.gemini/skills")
            [[ $legacy_codex == 1 && "$scope" == user ]] && dirs+=("$HOME/.codex/skills") ;;
    *) echo "unknown agent: $agent" >&2; exit 2 ;;
  esac
fi

for dir in "${dirs[@]}"; do
  mkdir -p "$dir"
  for s in "${skills[@]}"; do
    src="$here/skills/$s"; dst="$dir/$s"
    if [[ -L "$dst" || -e "$dst" ]]; then
      if [[ -L "$dst" && "$(readlink "$dst")" == "$src" ]]; then
        echo "ok      $dst"; continue
      fi
      echo "skip    $dst (exists and is not a link to this repo; remove it to reinstall)"; continue
    fi
    if [[ $mode == link ]]; then ln -s "$src" "$dst"; echo "linked  $dst"
    else cp -R "$src" "$dst"; echo "copied  $dst"; fi
  done
done

echo
echo "Installed: ${skills[*]}"
echo "Claude Code picks up ~/.claude/skills and .claude/skills live; Codex and Gemini may need a restart or '/skills reload'."
