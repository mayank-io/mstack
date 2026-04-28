#!/usr/bin/env bash
# PostToolUse: fires after Write/Edit on docs/*.md.
# Validates frontmatter, checks orphans, prompts status advance.

set -euo pipefail

input=$(cat)
command -v jq &>/dev/null || { echo '{}'; exit 0; }

tool_name=$(echo "$input" | jq -r '.tool_name // empty')
file_path=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty')

[[ "$tool_name" != "Edit" && "$tool_name" != "Write" ]] && { echo '{}'; exit 0; }
[[ "$file_path" != *"/docs/"* || "$file_path" == *"/templates/"* ]] && { echo '{}'; exit 0; }
[[ "$(basename "$file_path")" == "dashboard.base" ]] && { echo '{}'; exit 0; }
[[ ! -f "$file_path" ]] && { echo '{}'; exit 0; }

# Extract YAML frontmatter only if file starts with --- on line 1
fm=$(awk 'NR==1 && /^---$/{n=1; next} n==1 && /^---$/{exit} n==1{print}' "$file_path")

if [[ -z "$fm" ]]; then
  echo '{"systemMessage": "Doc conventions: '"$(basename "$file_path")"' has no YAML frontmatter. Add type, status, stage, work, created, related fields."}'
  exit 0
fi

type=$(echo "$fm" | grep "^type:" | sed 's/^type:[[:space:]]*//' || true)
status=$(echo "$fm" | grep "^status:" | sed 's/^status:[[:space:]]*//' || true)
related=$(echo "$fm" | grep "related:" || true)
messages=""

[[ -z "$type" ]] && messages="${messages}Missing 'type'. "
[[ -z "$status" ]] && messages="${messages}Missing 'status'. "

# No orphans check
if [[ "$type" == "design" || "$type" == "impl-plan" || "$type" == "cutover-plan" ]]; then
  if [[ -z "$related" ]] || echo "$related" | grep -q "\[\]"; then
    messages="${messages}This $type has no related docs linked. "
  fi
fi

# Auto-advance prompt
if [[ "$status" == "draft" && ("$type" == "design" || "$type" == "impl-plan" || "$type" == "cutover-plan" || "$type" == "analysis") ]]; then
  messages="${messages}Status is 'draft'. If complete, update to 'active' and invoke review agent. "
fi

[[ -n "$messages" ]] && echo "{\"systemMessage\": \"Doc conventions: $(basename "$file_path"): ${messages}\"}" || echo '{}'
