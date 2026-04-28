---
name: clean-permissions
description: "Clean permissions allow list in settings.json — removes one-off command pastes, entries redundant with broader wildcards, and dead MCP references. Use when user says \"clean permissions\", \"audit permissions\", \"clean up settings\", or \"prune allow list\"."
---

# Clean Permissions Allow List

Remove cruft from `~/.claude/settings.json` permissions allow list. Three categories of junk accumulate over time:

1. **One-off command pastes** — full multi-line scripts, hardcoded IDs/paths/dates that got auto-approved during sessions
2. **Redundant entries** — specific entries subsumed by a broader wildcard already in the list (e.g. `WebFetch(domain:example.com)` when `WebFetch(domain:*)` exists)
3. **Dead references** — MCP tools for servers that have been removed or disabled

## Step 1: Read current state

Read `~/.claude/settings.json` and extract the `permissions.allow` array. Report the current count.

## Step 2: Run the cleanup script

Run this Python script via Bash to identify and remove cruft. The script is non-destructive until the user confirms — it prints a plan first.

IMPORTANT: Always run this script exactly. Do not improvise the cleanup logic.

```python
import json, os, re, sys

with open(os.path.expanduser('~/.claude/settings.json')) as f:
    settings = json.load(f)

allow = settings['permissions']['allow']
before = len(allow)
print(f"Current entries: {before}")

# === Build wildcard index for redundancy detection ===
#
# Permission format semantics:
#   Bash(COMMAND_PREFIX:*)  — matches any Bash command starting with COMMAND_PREFIX
#   mcp__SERVER__*          — matches any MCP tool on that server
#   WebFetch(domain:*)      — matches any domain
#
# So Bash(gh pr:*) covers Bash(gh pr create:*) because "gh pr create"
# starts with "gh pr". We extract the command prefix for semantic matching.

bash_wildcards = []    # list of command prefixes from Bash(CMD:*) entries
mcp_wildcards = []     # list of prefixes from mcp__X__* entries
has_webfetch_star = False

for e in allow:
    # Bash(gh pr:*) -> command prefix "gh pr"
    m = re.match(r'^Bash\((.+?):\*\)$', e)
    if m:
        bash_wildcards.append(m.group(1))
        continue
    # mcp__playwright__* -> prefix "mcp__playwright__"
    if e.endswith('__*') and e.startswith('mcp__'):
        mcp_wildcards.append(e[:-1])  # "mcp__playwright__"
        continue
    # WebFetch(domain:*)
    if e == 'WebFetch(domain:*)':
        has_webfetch_star = True
        continue

# === Detect one-off pastes (category 3) ===
oneoff_patterns = [
    r'^Bash\(for id in ',
    r'^Bash\(do echo ',
    r'^Bash\(do\)$',
    r'^Bash\(done\)$',
    r'^Bash\(fi\)$',
    r'^Bash\(# ',
    r'^Bash\(echo === ',
    r'^Bash\(echo .+?:\*\)$',
    r'^Bash\(export (PATH|GOPATH)=',
    r'^Bash\(/usr/bin/curl ',
    r'^Bash\(/opt/homebrew/bin/jq ',
]

cat3_oneoff = set()
for e in allow:
    # Multi-line bash -c scripts (NOT the wildcard Bash(bash -c:*))
    if e.startswith("Bash(bash -c '") and e != "Bash(bash -c:*)":
        cat3_oneoff.add(e)
        continue
    for pat in oneoff_patterns:
        if re.match(pat, e):
            cat3_oneoff.add(e)
            break

# === Detect redundant entries (category 2) ===
cat2_redundant = set()
for e in allow:
    if e in cat3_oneoff:
        continue

    # Check Bash entries: Bash(CMD:*) is redundant if a shorter CMD prefix exists
    m = re.match(r'^Bash\((.+?):\*\)$', e)
    if m:
        cmd = m.group(1)
        for wc_cmd in bash_wildcards:
            if cmd != wc_cmd and cmd.startswith(wc_cmd):
                cat2_redundant.add(e)
                break
        continue

    # Check non-wildcard Bash entries: Bash(FULL_CMD) covered by Bash(PREFIX:*)
    m2 = re.match(r'^Bash\((.+?)\)$', e)
    if m2 and not e.endswith(':*)'):
        cmd = m2.group(1)
        for wc_cmd in bash_wildcards:
            if cmd.startswith(wc_cmd):
                cat2_redundant.add(e)
                break
        continue

    # Check MCP entries: individual tool covered by server wildcard
    if e.startswith('mcp__') and not e.endswith('__*'):
        for wc_prefix in mcp_wildcards:
            if e.startswith(wc_prefix):
                cat2_redundant.add(e)
                break
        continue

    # Check WebFetch: specific domain redundant with WebFetch(domain:*)
    if has_webfetch_star and e.startswith('WebFetch(domain:') and e != 'WebFetch(domain:*)':
        cat2_redundant.add(e)
        continue

# === Detect dead MCP refs (category 1) ===
# Known plugin-provided MCP prefixes that don't need a mcpServers entry
plugin_mcp = {'context7', 'playwright', 'plugin_playwright_playwright',
              'plugin_context7_context7', 'plugin_serena_serena'}
mcp_servers = settings.get('mcpServers', {})
active_servers = {k for k, v in mcp_servers.items() if not v.get('disabled', False)}

cat1_dead = set()
for e in allow:
    if e in cat2_redundant or e in cat3_oneoff:
        continue
    m = re.match(r'^mcp__(.+?)__', e)
    if m:
        server = m.group(1)
        if server not in active_servers and server not in plugin_mcp:
            cat1_dead.add(e)

# === Consolidate individual mcp__plugin_* to wildcards ===
plugin_groups = {}
for e in cat2_redundant:
    m = re.match(r'^(mcp__plugin_\w+__)', e)
    if m:
        plugin_groups.setdefault(m.group(1), []).append(e)

new_wildcards = []
for prefix, entries in plugin_groups.items():
    wc = prefix + '*'
    if wc not in allow:
        new_wildcards.append(wc)

# === Report ===
remove_set = cat1_dead | cat2_redundant | cat3_oneoff

print(f"\n--- Category 1: Dead MCP ({len(cat1_dead)}) ---")
for e in sorted(cat1_dead):
    print(f"  {e}")

print(f"\n--- Category 2: Redundant ({len(cat2_redundant)}) ---")
for e in sorted(cat2_redundant):
    print(f"  {e}")

print(f"\n--- Category 3: One-off pastes ({len(cat3_oneoff)}) ---")
for e in sorted(cat3_oneoff):
    print(f"  {e[:80]}{'...' if len(e) > 80 else ''}")

if new_wildcards:
    print(f"\n--- New wildcards to add ({len(new_wildcards)}) ---")
    for w in new_wildcards:
        print(f"  {w}")

after = before - len(remove_set) + len(new_wildcards)
print(f"\nBefore: {before} | Removing: {len(remove_set)} | Adding: {len(new_wildcards)} | After: {after}")

if '--apply' not in sys.argv:
    print("\nDry run. Pass --apply to write changes.")
    sys.exit(0)

# === Apply ===
cleaned = [e for e in allow if e not in remove_set]
cleaned.extend(new_wildcards)

settings['permissions']['allow'] = cleaned
with open(os.path.expanduser('~/.claude/settings.json'), 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')

print(f"Written. Final count: {len(cleaned)}")
```

## Step 3: Present plan

Run the script WITHOUT `--apply` first (dry run). Show the output to the user and ask for confirmation.

## Step 4: Execute cleanup

If the user approves, run again WITH `--apply`.

## Step 5: Verify

Read back `~/.claude/settings.json`, print the final allow list with total count, and confirm the JSON is valid with `python3 -c "import json,os; json.load(open(os.path.expanduser('~/.claude/settings.json')))"` .
