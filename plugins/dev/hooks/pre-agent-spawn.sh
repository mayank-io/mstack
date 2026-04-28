#!/usr/bin/env bash
# PreToolUse: fires before Agent tool calls.
# Injects branch name and active doc list into agent context.

set -euo pipefail

input=$(cat)
command -v jq &>/dev/null || { echo '{}'; exit 0; }

tool_name=$(echo "$input" | jq -r '.tool_name // empty')
[[ "$tool_name" != "Agent" ]] && { echo '{}'; exit 0; }

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
docs_dir="docs"
matches=""

if [[ -d "$docs_dir" ]]; then
  for f in "$docs_dir"/*.md; do
    [[ -f "$f" ]] || continue
    fm=$(awk '/^---$/{n++; next} n==1{print} n==2{exit}' "$f")
    work=$(echo "$fm" | grep "^work:" | sed 's/^work:[[:space:]]*//' || true)
    if [[ "$work" == "$branch" ]]; then
      type=$(echo "$fm" | grep "^type:" | sed 's/^type:[[:space:]]*//' || true)
      status=$(echo "$fm" | grep "^status:" | sed 's/^status:[[:space:]]*//' || true)
      matches="${matches}  - $(basename "$f") [${type:-?}: ${status:-?}]\n"
    fi
  done
fi

if [[ -n "$matches" ]]; then
  echo "{\"systemMessage\": \"Agent context: branch='$branch'. Docs:\\n${matches}Use work: $branch in any docs you create.\"}"
else
  echo '{}'
fi
