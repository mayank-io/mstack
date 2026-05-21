#!/bin/bash
# Wires git hooks from scripts/ into .git/hooks/ via symlink,
# so edits to the tracked files apply automatically.
#
# Usage:  scripts/install-hooks.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/.git/hooks"

ln -sf ../../scripts/pre-commit-hook.sh pre-commit
echo "Installed: .git/hooks/pre-commit -> ../../scripts/pre-commit-hook.sh"
