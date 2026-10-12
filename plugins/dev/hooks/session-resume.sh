#!/usr/bin/env bash
# SessionStart hook (matcher: resume). Fires on `claude --resume` / `--continue`.
# If /dev:safe-pause left a RESUME.md for this session (by session id, else by cwd),
# tell Claude to run /dev:safe-resume first. Otherwise output nothing and let
# Claude Code's own resume proceed untouched.
set -euo pipefail

input=$(cat)
session_id=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id",""))' 2>/dev/null || true)
cwd=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("cwd",""))' 2>/dev/null || true)
[[ -n "$cwd" ]] || cwd=$PWD

args=(locate --cwd "$cwd")
[[ -n "$session_id" ]] && args+=(--session-id "$session_id")

if resume=$(python3 "${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT unset}/scripts/pause_state.py" "${args[@]}" 2>/dev/null); then
  python3 - "$resume" <<'PY'
import json, sys
path = sys.argv[1]
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext":
    f"A /dev:safe-pause state exists for this session at {path}. Before doing anything else, run the dev:safe-resume skill: "
    f"it verifies every recorded worktree tip and continues at the recorded boundary. Do not start new work until it has run."}}))
PY
else
  echo '{}'
fi
