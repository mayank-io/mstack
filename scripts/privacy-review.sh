#!/bin/bash
# Model privacy review of the whole staged diff, run by scripts/publish.sh.
#
# A pattern scan finds strings. This asks what the text lets a stranger infer
# about the author: household, accounts, habits, what was read or clipped, and
# personal projects, including new ones no term list knows yet.
#
# Usage:  scripts/privacy-review.sh
# Exit 0: nothing staged, the review passed, or PRIVACY_REVIEWED=1.
# Exit 1: the review reported findings (printed to stderr).
# Exit 2: the review could not run or gave no verdict.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
PROMPT_FILE="$REPO_ROOT/scripts/privacy-review-prompt.md"

if [ "${PRIVACY_REVIEWED:-}" = "1" ]; then
  echo "privacy-review: skipped, PRIVACY_REVIEWED=1." >&2
  exit 0
fi

diff_text="$(git -C "$REPO_ROOT" diff --cached --unified=3 -- . ':(exclude)uv.lock')"
if [ -z "$diff_text" ]; then
  exit 0
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "privacy-review: the claude CLI is not on PATH, so the review cannot run." >&2
  echo "Install it, or re-run with PRIVACY_REVIEWED=1 after reviewing the diff yourself." >&2
  exit 2
fi

echo "privacy-review: reviewing the staged diff…" >&2
if ! verdict="$(printf '%s\n' "$diff_text" | claude -p "$(cat "$PROMPT_FILE")" --tools "" --no-session-persistence)"; then
  echo "privacy-review: the claude CLI failed; no verdict." >&2
  exit 2
fi

case "$(printf '%s\n' "$verdict" | tail -n 1)" in
  "PRIVACY: PASS")
    exit 0
    ;;
  "PRIVACY: FINDINGS")
    printf '%s\n' "$verdict" >&2
    echo "privacy-review: findings above. Fix them, or re-run with PRIVACY_REVIEWED=1 to publish as is." >&2
    exit 1
    ;;
  *)
    printf '%s\n' "$verdict" >&2
    echo "privacy-review: no verdict line in the reply; treating as not reviewed." >&2
    exit 2
    ;;
esac
