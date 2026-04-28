#!/usr/bin/env bash
# add-frontmatter.sh <file> <type> <status> <stage> [work] [related]
# Adds YAML frontmatter to an existing markdown file that lacks it.

set -euo pipefail

file="$1"
type="$2"
status="$3"
stage="$4"
work="${5:-}"
related="${6:-}"

if [[ ! -f "$file" ]]; then
  echo "Error: file not found: $file"
  exit 1
fi

# Check if frontmatter already exists
first_line=$(head -1 "$file")
if [[ "$first_line" == "---" ]]; then
  echo "Skipping $file: frontmatter already exists"
  exit 0
fi

# Extract date from filename (YYYY-MM-DD prefix) or use file mod time
basename_f=$(basename "$file")
if [[ "$basename_f" =~ ^([0-9]{4}-[0-9]{2}-[0-9]{2})- ]]; then
  created="${BASH_REMATCH[1]}"
else
  created=$(stat -f '%Sm' -t '%Y-%m-%d' "$file" 2>/dev/null || date -r "$file" '+%Y-%m-%d' 2>/dev/null || date '+%Y-%m-%d')
fi

# Build frontmatter
fm="---\ntype: $type\nstatus: $status\nstage: $stage"
if [[ -n "$work" ]]; then
  fm="$fm\nwork: $work"
fi
fm="$fm\ncreated: $created"
if [[ -n "$related" ]]; then
  fm="$fm\nrelated:\n  - \"[[$related]]\""
else
  fm="$fm\nrelated: []"
fi
fm="$fm\n---\n"

# Prepend frontmatter
temp=$(mktemp)
printf "%b" "$fm" > "$temp"
cat "$file" >> "$temp"
mv "$temp" "$file"

echo "Added frontmatter to $file"
