#!/usr/bin/env bash
# User-scope hook: first-use detection for doc-conventions.
# Fires on PreToolUse at ~/.claude/ level.
# If docs/templates/dashboard.base doesn't exist in the current project, prompts setup.

set -euo pipefail

# Only check once per project per day (each hook invocation is a new PID)
project_hash=$(pwd | md5 -q 2>/dev/null || echo "$PWD" | md5sum 2>/dev/null | cut -d' ' -f1)
STATE_FILE="/tmp/.claude-doc-conventions-first-use-${project_hash}-$(date +%Y%m%d)"
if [[ -f "$STATE_FILE" ]]; then
  echo '{}'
  exit 0
fi
touch "$STATE_FILE"

# Skip if not in a git repo
git rev-parse --git-dir &>/dev/null || { echo '{}'; exit 0; }

# Skip if doc-conventions is already set up (dashboard.base exists)
if [[ -f "docs/templates/dashboard.base" ]]; then
  echo '{}'
  exit 0
fi

# Skip known non-project directories (home dir, plugins repo itself, etc.)
cwd=$(pwd)
case "$cwd" in
  "$HOME"|"$HOME/.claude"*) echo '{}'; exit 0 ;;
esac

# Check if this is a real project (has source files or CLAUDE.md)
has_source=false
if [[ -f "CLAUDE.md" ]] || [[ -f "Cargo.toml" ]] || [[ -f "package.json" ]] || [[ -f "pyproject.toml" ]] || [[ -f "go.mod" ]] || [[ -f "Makefile" ]]; then
  has_source=true
fi

if [[ "$has_source" == true ]]; then
  echo '{"systemMessage": "This project does not have doc-conventions set up. Run /dev:setup-doc-conventions to install templates, dashboard, and workflow hooks. Or ignore this if doc-conventions is not needed for this project."}'
else
  echo '{}'
fi
