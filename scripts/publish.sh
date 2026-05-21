#!/bin/bash
# Publish mstack marketplace:
# 1. Bump marketplace.json metadata.version (patch by default)
# 2. Commit any staged plugin changes together with the version bump
# 3. Push to origin
# 4. Print the two manual Claude Code steps that must follow
#
# Usage:
#   scripts/publish.sh                   # patch bump, stage nothing extra
#   scripts/publish.sh minor
#   scripts/publish.sh major
#   scripts/publish.sh patch "add dev:next-idea skill"        # custom message

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
MARKETPLACE_JSON="$REPO_ROOT/.claude-plugin/marketplace.json"

cd "$REPO_ROOT"

bump_type="${1:-patch}"
message="${2:-}"

case "$bump_type" in
  patch|minor|major) ;;
  *) echo "Usage: $0 [patch|minor|major] [commit-message]" >&2; exit 1 ;;
esac

# Must have a clean-ish working tree: either nothing staged, or staged changes
# that we'll bundle with the version bump.
if ! git diff --quiet && [ -z "$(git diff --cached --name-only)" ]; then
  echo "ERROR: You have unstaged changes. Stage them first (git add), then re-run." >&2
  git status --short
  exit 1
fi

# Read and bump version
current=$(jq -r '.metadata.version' "$MARKETPLACE_JSON")
IFS=. read -r major minor patch <<<"$current"

case "$bump_type" in
  major) major=$((major+1)); minor=0; patch=0 ;;
  minor) minor=$((minor+1)); patch=0 ;;
  patch) patch=$((patch+1)) ;;
esac

new_version="$major.$minor.$patch"
echo "Version: $current → $new_version"

# Update file atomically
tmp=$(mktemp)
jq --arg v "$new_version" '.metadata.version = $v' "$MARKETPLACE_JSON" >"$tmp"
mv "$tmp" "$MARKETPLACE_JSON"

git add "$MARKETPLACE_JSON"

# Compose commit message
if [ -z "$message" ]; then
  # Infer from staged files
  staged_summary=$(git diff --cached --name-only | sed -n 's|^plugins/\([^/]*\)/.*|\1|p' | sort -u | paste -sd, -)
  if [ -n "$staged_summary" ]; then
    message="chore: bump marketplace to $new_version ($staged_summary)"
  else
    message="chore: bump marketplace to $new_version"
  fi
fi

git commit -m "$message"

current_branch=$(git symbolic-ref --short HEAD)
echo "Pushing $current_branch to origin…"
git push origin "$current_branch"

cat <<EOF

Published $new_version.

Next, in Claude Code:
  /plugin update mstack
  /reload-plugins

EOF
