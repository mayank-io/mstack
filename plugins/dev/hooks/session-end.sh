#!/usr/bin/env bash
# Stop hook: end-of-session reconciliation.
# Flags stale doc statuses and missing artifacts for current branch.

set -euo pipefail

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
[[ "$branch" == "unknown" || "$branch" == "HEAD" || "$branch" == "main" || "$branch" == "master" ]] && { echo '{}'; exit 0; }

docs_dir="docs"
[[ ! -d "$docs_dir" ]] && { echo '{}'; exit 0; }

has_design=false has_plan=false
design_status="" plan_status=""
issues=""

for f in "$docs_dir"/*.md; do
  [[ -f "$f" ]] || continue
  # Extract YAML frontmatter only if file starts with --- on line 1
  fm=$(awk 'NR==1 && /^---$/{n=1; next} n==1 && /^---$/{exit} n==1{print}' "$f")
  [[ -z "$fm" ]] && continue
  work=$(echo "$fm" | grep "^work:" | sed 's/^work:[[:space:]]*//' || true)
  [[ "$work" != "$branch" ]] && continue
  type=$(echo "$fm" | grep "^type:" | sed 's/^type:[[:space:]]*//' || true)
  status=$(echo "$fm" | grep "^status:" | sed 's/^status:[[:space:]]*//' || true)
  if [[ "$type" == "design" ]]; then
    has_design=true; design_status="$status"
    [[ "$status" == "draft" || "$status" == "review" ]] && issues="${issues}  - Design '$(basename "$f")' is still '$status'.\n"
  fi
  if [[ "$type" == "impl-plan" ]]; then
    has_plan=true; plan_status="$status"
    [[ "$status" == "draft" || "$status" == "review" ]] && issues="${issues}  - Plan '$(basename "$f")' is still '$status'.\n"
  fi
done

[[ "$has_design" == true && "$design_status" == "completed" && "$has_plan" == false ]] && \
  issues="${issues}  - Design is completed but no plan exists yet.\n"

[[ -n "$issues" ]] && echo "{\"systemMessage\": \"Doc conventions end-of-session (branch '$branch'):\\n${issues}\"}" || echo '{}'
