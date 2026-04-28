#!/usr/bin/env bash
# Session-Start Hook (fires once per session on first PreToolUse)
# Reads docs/ frontmatter filtered by current branch and injects summary.

set -euo pipefail

# Idempotent: only fire once per project per day
project_hash=$(pwd | md5 -q 2>/dev/null || echo "$PWD" | md5sum 2>/dev/null | cut -d' ' -f1)
STATE_FILE="/tmp/.claude-doc-conventions-session-${project_hash}-$(date +%Y%m%d)"
if [[ -f "$STATE_FILE" ]]; then
  echo '{}'
  exit 0
fi
touch "$STATE_FILE"

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
if [[ "$branch" == "unknown" || "$branch" == "HEAD" ]]; then
  echo '{"systemMessage": "Doc conventions: not on a named branch. Workflow docs cannot be scoped."}'
  exit 0
fi

docs_dir="docs"
[[ ! -d "$docs_dir" ]] && { echo '{"systemMessage": "Doc conventions: no docs/ directory found."}'; exit 0; }

matches=""
for f in "$docs_dir"/*.md; do
  [[ -f "$f" ]] || continue
  [[ "$(basename "$f")" == "dashboard.base" ]] && continue
  fm=$(awk '/^---$/{n++; next} n==1{print} n==2{exit}' "$f")
  work=$(echo "$fm" | grep "^work:" | sed 's/^work:[[:space:]]*//')
  if [[ "$work" == "$branch" ]]; then
    type=$(echo "$fm" | grep "^type:" | sed 's/^type:[[:space:]]*//')
    status=$(echo "$fm" | grep "^status:" | sed 's/^status:[[:space:]]*//')
    matches="${matches}  - $(basename "$f") [type: ${type:-?}, status: ${status:-?}]\n"
  fi
done

if [[ -z "$matches" ]]; then
  echo "{\"systemMessage\": \"Doc conventions: branch '$branch' has no docs yet. Consider creating a plan before writing code.\"}"
else
  echo "{\"systemMessage\": \"Doc conventions: branch '$branch' active docs:\\n${matches}Read docs/dashboard.base for full overview.\"}"
fi
