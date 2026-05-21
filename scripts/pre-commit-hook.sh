#!/bin/bash
# Git pre-commit hook: Validates plugin structure
# 1. All plugins registered in marketplace.json
# 2. No "version" field in plugin.json (caching uses commit hashes)
# 3. If any plugins/** file changes, marketplace.json version must be bumped
#    in the same commit (else consumer autoUpdate won't fire).
# 4. No hardcoded personal paths in staged plugin files.
#
# Install:  scripts/install-hooks.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
MARKETPLACE_JSON="$REPO_ROOT/.claude-plugin/marketplace.json"
PLUGINS_DIR="$REPO_ROOT/plugins"

if [ ! -f "$MARKETPLACE_JSON" ] || [ ! -d "$PLUGINS_DIR" ]; then
  exit 0
fi

# === Check 1: All plugins registered in marketplace.json ===
#
# Plugins listed here are intentionally kept out of the marketplace
# (e.g., personal workflows not meant for distribution). Empty by default.
UNLISTED_PLUGINS=""

registered_plugins=$(jq -r '.plugins[].name' "$MARKETPLACE_JSON" 2>/dev/null || echo "")

unregistered=""
for plugin_dir in "$PLUGINS_DIR"/*/; do
  [ -d "$plugin_dir" ] || continue
  plugin_name=$(basename "$plugin_dir")
  manifest="$plugin_dir.claude-plugin/plugin.json"
  # Skip intentionally unlisted plugins
  if [ -n "$UNLISTED_PLUGINS" ] && echo "$UNLISTED_PLUGINS" | grep -qw "$plugin_name"; then
    continue
  fi
  if [ -f "$manifest" ]; then
    if ! echo "$registered_plugins" | grep -qx "$plugin_name"; then
      unregistered="${unregistered:+$unregistered, }$plugin_name"
    fi
  fi
done

if [ -n "$unregistered" ]; then
  echo "ERROR: Plugin(s) not registered in marketplace.json: $unregistered"
  echo "Add entries (without a 'version' field) before committing."
  exit 1
fi

# === Check 2: No "version" field in plugin.json files ===

errors=""
for plugin_dir in "$PLUGINS_DIR"/*/; do
  [ -d "$plugin_dir" ] || continue
  manifest="$plugin_dir.claude-plugin/plugin.json"
  if [ -f "$manifest" ] && jq -e 'has("version")' "$manifest" >/dev/null 2>&1; then
    errors="${errors}  - $(basename "$plugin_dir")/.claude-plugin/plugin.json"$'\n'
  fi
done

if [ -n "$errors" ]; then
  echo "ERROR: 'version' field found in plugin.json. Remove it — caching uses commit hashes."
  printf "%s" "$errors"
  exit 1
fi

# === Check 3: marketplace.json version bump required on plugin surface changes ===
#
# If any file under plugins/ is staged (added/modified/deleted), the consumer's
# autoUpdate only fires when marketplace.json's metadata.version changes.
# Enforce a version bump in the same commit.

plugin_changes=$(git diff --cached --name-only -- 'plugins/' || true)

if [ -n "$plugin_changes" ]; then
  # marketplace.json must also be staged
  if ! git diff --cached --name-only | grep -qx '.claude-plugin/marketplace.json'; then
    echo "ERROR: plugins/** changed but .claude-plugin/marketplace.json is not staged."
    echo "Bump metadata.version so consumer autoUpdate picks up the change."
    echo "Tip: run \`scripts/publish.sh\` to do this automatically."
    exit 1
  fi

  # And its version must differ from HEAD
  old_version=$(git show HEAD:.claude-plugin/marketplace.json 2>/dev/null | jq -r '.metadata.version // empty')
  new_version=$(git show :.claude-plugin/marketplace.json | jq -r '.metadata.version // empty')

  if [ -z "$new_version" ]; then
    echo "ERROR: .claude-plugin/marketplace.json has no metadata.version field."
    exit 1
  fi

  if [ "$old_version" = "$new_version" ]; then
    echo "ERROR: plugins/** changed but marketplace.json metadata.version is unchanged ($new_version)."
    echo "Bump the version (patch for additive changes) so consumer autoUpdate fires."
    echo "Tip: run \`scripts/publish.sh\` to do this automatically."
    exit 1
  fi
fi

# === Check 4: No personal data in staged plugin files ===
#
# Catches accidental re-introduction of hardcoded personal paths into
# distributed plugins. Add patterns specific to your environment here.

if [ -n "$plugin_changes" ]; then
  personal_data_errors=""

  while IFS= read -r staged_file; do
    content=$(git show ":$staged_file" 2>/dev/null) || continue

    # Generic: iCloud Obsidian vault path
    if echo "$content" | grep -q "iCloud~md~obsidian"; then
      personal_data_errors="${personal_data_errors}  - $staged_file: contains iCloud~md~obsidian path"$'\n'
    fi

    # Generic: hardcoded /Users/<owner>/Library or Developer paths
    if echo "$content" | grep -qE "/Users/[^/]+/(Library|Developer)/"; then
      personal_data_errors="${personal_data_errors}  - $staged_file: contains hardcoded /Users/<owner>/ path"$'\n'
    fi
  done <<< "$plugin_changes"

  if [ -n "$personal_data_errors" ]; then
    echo "ERROR: Personal data detected in staged plugin files:"
    printf "%s" "$personal_data_errors"
    echo "Remove personal paths before committing."
    exit 1
  fi
fi

exit 0
