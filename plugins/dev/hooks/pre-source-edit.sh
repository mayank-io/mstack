#!/usr/bin/env bash
# PreToolUse: fires before Edit/Write on source files.
# Checks for active impl plan on current branch.

set -euo pipefail

input=$(cat)
command -v jq &>/dev/null || { echo '{}'; exit 0; }

tool_name=$(echo "$input" | jq -r '.tool_name // empty')
file_path=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty')

[[ "$tool_name" != "Edit" && "$tool_name" != "Write" ]] && { echo '{}'; exit 0; }
[[ "$file_path" == *"/docs/"* || "$file_path" == *"/templates/"* ]] && { echo '{}'; exit 0; }

# Only check source files
ext="${file_path##*.}"
case "$ext" in
  rs|py|ts|tsx|js|jsx|go|java|rb|sh) ;;
  *) echo '{}'; exit 0 ;;
esac

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

if [[ "$branch" == "main" || "$branch" == "master" ]]; then
  echo '{"systemMessage": "Doc conventions: editing source on main. If this is more than a trivial fix, consider a feature branch with a plan."}'
  exit 0
fi
[[ "$branch" == "unknown" || "$branch" == "HEAD" ]] && { echo '{}'; exit 0; }

docs_dir="docs"
[[ ! -d "$docs_dir" ]] && { echo '{"systemMessage": "Doc conventions: no docs/ directory. Create a plan before writing code."}'; exit 0; }

plan_found=false
plan_status=""
plan_name=""
design_needs_review=false
design_name=""

for f in "$docs_dir"/*.md; do
  [[ -f "$f" ]] || continue
  fm=$(awk '/^---$/{n++; next} n==1{print} n==2{exit}' "$f")
  work=$(echo "$fm" | grep "^work:" | sed 's/^work:[[:space:]]*//')
  [[ "$work" != "$branch" ]] && continue
  type=$(echo "$fm" | grep "^type:" | sed 's/^type:[[:space:]]*//')
  status=$(echo "$fm" | grep "^status:" | sed 's/^status:[[:space:]]*//')
  if [[ "$type" == "impl-plan" ]]; then
    plan_found=true
    plan_status="$status"
    plan_name="$(basename "$f")"
  fi
  if [[ "$type" == "design" && ("$status" == "draft" || "$status" == "review") ]]; then
    design_needs_review=true
    design_name="$(basename "$f")"
  fi
done

msg=""
if [[ "$plan_found" == false ]]; then
  msg="No plan found for branch '$branch'. Create one from docs/templates/impl-plan.md before writing code."
elif [[ "$plan_status" == "draft" ]]; then
  msg="Plan '$plan_name' is still in draft. Complete and review it before writing code."
elif [[ "$plan_status" == "review" ]]; then
  msg="Plan '$plan_name' is in review. Complete the review before writing code."
fi

if [[ "$design_needs_review" == true ]]; then
  [[ -n "$msg" ]] && msg="$msg Also, design doc '$design_name' hasn't been reviewed yet." || msg="Design doc '$design_name' hasn't been reviewed yet."
fi

[[ -n "$msg" ]] && echo "{\"systemMessage\": \"Doc conventions: $msg\"}" || echo '{}'
