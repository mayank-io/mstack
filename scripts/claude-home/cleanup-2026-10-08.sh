#!/usr/bin/env bash
# ~/.claude cleanup runbook — docs/plans/2026-10-08-claude-home-cleanup.md, M1 link + M2 + M3 + M5.
# Run:  bash scripts/claude-home/cleanup-2026-10-08.sh            (all steps, in order)
#       bash scripts/claude-home/cleanup-2026-10-08.sh <step>...  (link | m2 | m3 | m5)
# Close any session running under ~/.claude-sk or ~/.claude-sovo first.
# Every step checks its preconditions before its first write and stops on any failure.
set -euo pipefail
shopt -s nullglob

H="${HOME:?HOME unset}"
C="$H/.claude"
A="$H/.claude-attic/2026-10-08"
R="$H/Developer/github/mayank-io/mstack"
TOOL="$R/scripts/claude-home/clone-claude-config"
[ -f "$C/settings.json" ] && [ -d "$R/.git" ] && [ -x "$TOOL" ]

say() { printf '\n== %s\n' "$*" >&2; }
count() { ls -A "$1" | wc -l | tr -d ' '; }
links() { find "$1" -maxdepth 1 -type l | wc -l | tr -d ' '; }
dangling() { find -L "$H/.claude-sk" "$H/.claude-sovo" -maxdepth 1 -type l | wc -l | tr -d ' '; }
expect() { [ "$2" = "$3" ] || { echo "GATE FAILED: $1: expected $3, got $2" >&2; exit 1; }; echo "ok  $1 = $2" >&2; }

step_link() {
  say "M1: ~/bin/clone-claude-config -> mstack"
  ln -sfn "$TOOL" "$H/bin/clone-claude-config"
  expect "~/bin/clone-claude-config target" "$(readlink "$H/bin/clone-claude-config")" "$TOOL"
}

step_m2() {
  say "M2: quarantine 21 junk entries"
  cd "$C"
  local J=( .claude.json .last-update-result.json.tmp.* \
    settings.json.bak-20260919-222829 settings.json.bak-latest settings.json.bak.20260817-135206 \
    security_warnings_state_*.json readout-cost-cache.json readout-pricing.json readout-chats \
    x-to-obsidian.local.md claude-notification.sh.disabled .obsidian scripts \
    youtube-chrome-profile youtube-chrome-profile.conf x-playwright-profile )
  local f
  for f in "${J[@]}"; do [ -e "$f" ] || { echo "missing: $f" >&2; exit 1; }; done
  [ "${#J[@]}" -eq 21 ] || { echo "expected 21 sources, found ${#J[@]} — re-measure plan §4 first" >&2; exit 1; }
  grep -q '"Skill(x-to-obsidian:save)",' settings.json || { echo "stale allow rule not found in settings.json" >&2; exit 1; }
  mkdir -p "$A"
  [ -z "$(ls -A "$A")" ] || { echo "attic not empty: $A" >&2; exit 1; }
  mv -n -- "${J[@]}" "$A"/
  expect "attic entries" "$(count "$A")" 21

  say "M2: remove stale x-to-obsidian allow rule"
  python3 -I - "$C/settings.json" <<'EOF'
import json, sys
p = sys.argv[1]; s = open(p).read()
lines = s.splitlines(keepends=True)
hits = [i for i, l in enumerate(lines) if l.strip() == '"Skill(x-to-obsidian:save)",']
assert len(hits) == 1, hits
del lines[hits[0]]
out = "".join(lines)
json.loads(out)  # still valid JSON, or nothing is written
open(p, "w").write(out)
EOF
  expect "x-to-obsidian lines in settings.json" "$(grep -c 'x-to-obsidian' settings.json || true)" 0

  say "M2: sync account dirs"
  "$TOOL" --sync --dry-run sk sovo
  "$TOOL" --sync sk sovo
  expect "~/.claude entries" "$(count "$C")" 50
  expect "~/.claude-sovo links" "$(links "$H/.claude-sovo")" 42
  expect "~/.claude-sk links" "$(links "$H/.claude-sk")" 41
  expect "dangling links" "$(dangling)" 0
}

step_m3() {
  say "M3: update global CLAUDE.md (backup in \$TMPDIR)"
  [ -f "$R/docs/auto-research-pattern.md" ] && [ -f "$R/docs/claude-workspace-rename-guide.md" ]
  cmp -s "$C/auto-research-pattern.md" "$R/docs/auto-research-pattern.md" || { echo "mstack copy of auto-research-pattern.md differs from the original" >&2; exit 1; }
  git -C "$R" ls-files --error-unmatch docs/auto-research-pattern.md docs/claude-workspace-rename-guide.md >/dev/null \
    || { echo "commit the mstack docs before removing the originals" >&2; exit 1; }
  cp "$C/CLAUDE.md" "${TMPDIR:-/tmp}/CLAUDE.md.pre-m3.$(date +%s)"
  python3 -I - "$C/CLAUDE.md" <<'EOF'
import sys
p = sys.argv[1]; s = open(p).read()
def rep(a, b):
    global s
    assert s.count(a) == 1, a[:70]; s = s.replace(a, b)
rep("- Auto-research pattern (full spec): `~/.claude/auto-research-pattern.md`\n",
    "- Auto-research pattern (full spec): `/Users/mayank/Developer/github/mayank-io/mstack/docs/auto-research-pattern.md`\n"
    "- Renaming a Claude Code workspace directory (path encoding, session migration): `/Users/mayank/Developer/github/mayank-io/mstack/docs/claude-workspace-rename-guide.md`\n")
rep("Full spec: `~/.claude/auto-research-pattern.md` (read it before building anything)",
    "Full spec: `/Users/mayank/Developer/github/mayank-io/mstack/docs/auto-research-pattern.md` (read it before building anything)")
rep("then `/login`.\n",
    "then `/login`.\n"
    "- `~/bin/clone-claude-config` is a symlink to `mstack/scripts/claude-home/clone-claude-config`. After any top-level change to `~/.claude`, run `clone-claude-config --sync sk sovo` (add `--dry-run` to preview) so the account dirs gain new entries and drop dangling links.\n")
rep("\n## Auto-Research Loops\n", """
## Testing Rules
- Failing tests are NEVER OK. Always fix the bug, whether we started the failure or someone else did.
- Never comment out, skip, or ignore a failing test.
- If a test itself needs to change, seek human review first.
- Respect every test. If it fails, understand why and fix the root cause.
- An "e2e test" covers the entire customer journey end-to-end: no mocking, no unit testing. Run the actual external tools (CLI, APIs), use real files, and verify real side effects. Mark slow tests with `pytest.mark.timeout` and document how to run them. Why: the kundali bot's mocked tests passed while the real `claude -p` call failed silently for want of `--permission-mode bypassPermissions`.

## Auto-Research Loops
""")
open(p, "w").write(s)
EOF
  expect "auto-research-pattern mentions" "$(grep -c 'auto-research-pattern' "$C/CLAUDE.md")" 2
  expect "~/.claude/auto-research-pattern mentions" "$(grep -c '~/.claude/auto-research-pattern' "$C/CLAUDE.md" || true)" 0
  expect "Testing Rules headers" "$(grep -c '^## Testing Rules' "$C/CLAUDE.md")" 1

  say "M3: attic memory/ and auto-research-pattern.md"
  [ -e "$A" ] || { echo "run m2 first: no attic at $A" >&2; exit 1; }
  local before; before="$(count "$C")"
  mv -n -- "$C/memory" "$C/auto-research-pattern.md" "$A"/
  test ! -e "$C/memory" && test ! -e "$C/auto-research-pattern.md"
  "$TOOL" --sync sk sovo
  expect "~/.claude entries" "$(count "$C")" "$((before - 2))"
  expect "attic entries" "$(count "$A")" 23
  expect "dangling links" "$(dangling)" 0
}

step_m5() {
  say "M5: purge telemetry upload failures"
  rm -f -- "$C"/telemetry/1p_failed_events.*.json
  expect "failed-event files older than 24h" "$(find "$C/telemetry" -name '1p_failed_events.*.json' -mtime +0 | wc -l | tr -d ' ')" 0
}

[ "$#" -gt 0 ] || set -- link m2 m3 m5
for s in "$@"; do
  case "$s" in
    link) step_link ;; m2) step_m2 ;; m3) step_m3 ;; m5) step_m5 ;;
    *) echo "unknown step: $s (link | m2 | m3 | m5)" >&2; exit 2 ;;
  esac
done
say "done: $*"
