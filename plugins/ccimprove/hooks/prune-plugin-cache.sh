#!/usr/bin/env bash
# Prune orphaned plugin-cache directories.
#
# `claude plugin update` copies the plugin into a new commit-sha directory and
# leaves the old one behind — still loaded, not merely wasting disk. Every
# duplicate sha contributes its own copy of each skill to the slash menu.
#
# Wired to two events, because an update can arrive three ways and only one of
# them goes through a tool call this session can see:
#   - PostToolUse/Bash : immediate, when the update runs through Claude
#   - SessionStart     : the catch-all, for `/plugin` in the UI or a plain
#                        terminal run — caught at the next session instead
#
# Hooks must emit JSON on stdout and must not fail the tool call, so every
# path here exits 0 with '{}'.

set -uo pipefail

SCRIPT="${CLAUDE_PLUGIN_ROOT}/scripts/prune_plugin_cache.py"
STAMP="/tmp/.claude-prune-plugin-cache-$(date +%Y%m%d%H)"

payload="$(cat 2>/dev/null || true)"

# PostToolUse fires on every Bash call. Only act when the command was actually
# a plugin operation — anything else is not worth a filesystem walk.
if [[ -n "$payload" ]] && printf '%s' "$payload" | grep -q '"tool_name"'; then
  if ! printf '%s' "$payload" | grep -Eq 'plugin[[:space:]]+(update|install|marketplace)'; then
    echo '{}'
    exit 0
  fi
else
  # SessionStart: at most once an hour, so opening several sessions in a row
  # does not re-walk the cache each time.
  if [[ -f "$STAMP" ]]; then
    echo '{}'
    exit 0
  fi
  touch "$STAMP" 2>/dev/null || true
fi

if [[ ! -f "$SCRIPT" ]]; then
  echo '{}'
  exit 0
fi

# --quiet: say nothing when there is nothing to prune, which is the usual case.
python3 "$SCRIPT" --quiet >/dev/null 2>&1 || true

echo '{}'
exit 0
