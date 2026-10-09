---
title: ~/.claude cleanup and re-org — attic the junk, re-home user content, make the clone tool sync
status: ready
created: 2026-10-08
---

# ~/.claude cleanup and re-org

## 1. Objective

Reduce `~/.claude` to what Claude Code and installed plugins own, move user-authored content and tool data to homes where they are version-controlled or conventionally located, and keep the two symlinked account dirs (`~/.claude-sk`, `~/.claude-sovo`) consistent with `~/.claude` as it changes.

## 2. Recommendation

1. **Quarantine 21 junk entries** to `~/.claude-attic/2026-10-08/` (outside `~/.claude`, so not symlinked into the account dirs); delete the attic after the retention window (§8.3). Nothing is `rm`'d on day one except the telemetry upload failures (§5.5).
2. **Retire, not relocate, both private browser profiles** — `youtube-chrome-profile/` (167M) + `.conf` and `x-playwright-profile/` (546M) go to the attic with the rest of §5.2 and are deleted with it. All browser work runs in the gstack browser (decided 2026-10-10, §8.2): `youtube_downloader.py` since 2026-08-24, `xaccount_iterate.py` since S4. Both are pinned in `test_browser_routing.py` `ROUTED`.
3. **Move the X harvester onto gstack (S4, shipped in code).** `xaccount_iterate.py` drives the gstack browser's tabs instead of its own Playwright profile; the `x-pilot-stop` file and its idle loop are gone, since the gstack browser stays open anyway. The fetch README's dead `chrome_profile_path` block and the x-post SKILL's profile note are corrected.
4. **Re-home user content:** `memory/testing-rules.md` → a "Testing Rules" section of global CLAUDE.md; the path-encoding + rename procedure → `mstack/docs/claude-workspace-rename-guide.md`; `auto-research-pattern.md` → `mstack/docs/auto-research-pattern.md`. `memory/feedback_always_create_command_wrapper.md` is dropped as superseded (plugin skills already autocomplete as `/plugin:skill`, and command wrappers were consolidated into skills on 2026-09-30). `~/.claude/memory/` is never loaded by Claude Code, so these rules have had no effect until now.
5. **Move `clone-claude-config` into mstack with tests and a `--sync` mode** that links new `~/.claude` entries and prunes dangling or excluded links into `~/.claude`. `~/bin/clone-claude-config` becomes a symlink to it. Without `--sync`, the entries removed in this plan leave 22 dangling symlinks in each account dir (20 after M2 alone).
6. **Purge `telemetry/` failed-event files (29M)**; transcripts (`projects/`, 6.6G) are retained indefinitely — `cleanupPeriodDays` stays unset (§8.1, decided 2026-10-10).

## 3. Milestones

| ID | Ships | Streams | Acceptance |
|---|---|---|---|
| M1 | Clone tool with `--sync`, `--dry-run`, tests, in mstack — **done 2026-10-10** (`~/bin` link included) | S1 | `uv run pytest scripts/claude-home/tests -v` → 18/18 green |
| M2 | Junk quarantined, stale permission removed, account dirs synced — **done 2026-10-10**, all gates green | S2 | §4 "After M2" column matches exactly; §5.2 gate |
| M3 | User content re-homed, CLAUDE.md updated | S3 | §5.3 gate checks return the stated counts |
| M4 | X harvester on gstack; profile docs corrected — **done 2026-10-10** | S4 | `uv run pytest plugins/fetch/scripts/tests/test_xaccount_iterate.py -v` → 20/20; `test_browse_adapter.py` → 52/52; `test_browser_routing.py` → 35/35; full suite green |
| M5 | Telemetry purged | S5 | §5.5 gate → 0 |

Dependencies: M2 needs M1 (the sync prunes what M2 removes) and M4 (M2 attics the X profile, which only M4 stops using — attic it first and the next harvest recreates it, logged out). M4 changes only code, never `~/.claude`. M3 and M5 touch disjoint content and may run in any order after M2; each ends with `clone-claude-config --sync sk sovo` so the account dirs never carry dangling links. §4's columns assume the order M2 → M3. If M3 runs before M2, gate it on its own delta instead: −2 entries, −2 links per account dir, +2 attic.

Runbook: `scripts/claude-home/cleanup-2026-10-08.sh [link|m2|m3|m5]` runs the `~/bin` link and the `~/.claude` side of M2, M3 and M5, checking each step's gate and stopping at the first mismatch. M3 refuses to run until `docs/auto-research-pattern.md` and `docs/claude-workspace-rename-guide.md` are committed.

## 4. Smoke investigation (measured 2026-10-08)

| Quantity | Before | After M2 | After M2–M3 | How measured |
|---|---|---|---|---|
| Top-level entries in `~/.claude` (`ls -A \| wc -l`) | 71 | 50 | 48 | M2: 21 to attic (§5.2). M3: `memory`, `auto-research-pattern.md` to attic |
| Symlinks in `~/.claude-sk` and in `~/.claude-sovo` (each, after `--sync`; `find -maxdepth 1 -type l \| wc -l`) | sovo 62, sk 61 | sovo 42, sk 41 | sovo 40, sk 39 | 71 entries − 9 `EXCLUDE` names = 62; `sk` holds a real per-account `.last-update-result.json` in place of that link (re-measured 2026-10-10). `.claude.json` is excluded from linking, so M2 removes 20 links, M3 2 |
| Dangling symlinks per account dir if the removals ran without `--sync` | 0 | 20 | 22 | the failure `--sync` exists to fix |
| Entries in `~/.claude-attic/2026-10-08/` | — | 21 | 23 | §5.2, then `memory/` and `auto-research-pattern.md` from §5.3 |
| `~/.claude/telemetry` failed-event files | 24 (29M), newest 2026-09-14 | 24 | 24 | 0 after M5 |
| Global CLAUDE.md lines containing `~/.claude/auto-research-pattern.md` | 2 (Key Paths, Auto-Research Loops) | 2 | 0 | both repointed to mstack in M3 |
| `~/.claude/settings.json` lines containing `x-to-obsidian` | 1 (`Skill(x-to-obsidian:save)` allow rule, line 68) | 0 | 0 | removed in M2 |

## 5. Streams

### 5.1 S1 — `clone-claude-config` v2 in mstack (M1)

**Location.** `mstack/scripts/claude-home/clone-claude-config` (bash, moved from `~/bin`); `~/bin/clone-claude-config` → symlink to it. Tests in `mstack/scripts/claude-home/tests/test_clone_claude_config.py`; add `"scripts"` to `[tool.pytest.ini_options] testpaths` in `pyproject.toml`.

**Interface.**

```
clone-claude-config [--sync] [--dry-run] <name>...
```

- No `<name>` → usage on stderr, exit 2.
- Create mode (default): unchanged from v1 — new dir gets one symlink per `~/.claude` entry not in `EXCLUDE`, plus its own `.claude.json` (copy of `~/.claude.json` minus `IDENTITY_KEYS`); an existing dir with no symlinks is moved to `~/.claude-<name>.fresh-<epoch>` and its identity keys carried over; an existing dir with symlinks is skipped (stderr `already linked`, exit 0 for that name).
- `--sync`: for an existing linked dir — (a) link every non-excluded `~/.claude` entry that has no entry of the same name in the dir; (b) remove every symlink whose target is under `$HOME/.claude/` (prefix with the trailing slash) and does not exist; (c) remove every symlink whose basename is in `EXCLUDE` and whose target is under `$HOME/.claude/` (a name excluded after the dir was cloned). Never touches `.claude.json`, real files, or symlinks pointing anywhere else. A name whose dir does not exist is created as in create mode.
- `--dry-run`: print each planned action to stdout as `link <dst>`, `unlink <dst>`, `move <src> <dst>`, `write <dst>/.claude.json`; change nothing; exit 0. Valid with and without `--sync`.
- Progress and summaries to stderr; stdout carries only `--dry-run` actions.

**Order of operations (no partial state).** For each name, every check and every read completes before the first write: `jq` present, `~/.claude/settings.json` and `~/.claude.json` present, and the new `.claude.json` rendered by `jq` into a `mktemp` file — reading the unlinked dir's own `.claude.json` in place when converting. Only then does the first write happen (the conversion `mv`, or `mkdir`). A `jq` failure therefore leaves the existing dir untouched and creates no `.fresh-*`. The temp file is removed by an `EXIT` trap.

**Boundary semantics.**
- "Into `~/.claude`" means `readlink` output starts with `$HOME/.claude/` — a link to `$HOME/.claude-sk/x` or `$HOME/.claudefoo` is not ours and is never pruned.
- A dangling link is pruned only if its target is missing at run time; a target that is itself a dangling symlink counts as missing (`[ -e ]` semantics).
- An entry present in both source and dest as a real (non-symlink) file is left alone in both modes, and reported on stderr as `kept local <name>`. A real file whose name is in `EXCLUDE` (e.g. the per-account `mcp-needs-auth-cache.json`, `seed-admin`) is left alone silently — that is the expected state.

**Error paths.** `HOME` unset or empty → exit non-zero before any write (`${HOME:?}`). `~/.claude/settings.json` missing → exit 1. Empty `<name>` (`''`) → exit non-zero. `~/.claude.json` missing → exit 1 with message, no dir created. `jq` missing → exit 1 before any write. Unlinked dir's `.claude.json` unparseable → exit 1, dir untouched.

**Tests** (pytest drives the script with `env={"HOME": tmp_path, "PATH": ...}`; fixture builds `tmp/.claude/{settings.json,CLAUDE.md,projects/,daemon/}` and `tmp/.claude.json` with `oauthAccount`, `userID`, `mcpServers`; a `no_jq_path` fixture builds a tmp bin dir symlinking every external tool the script calls except `jq`):

1. create: links `settings.json`, `CLAUDE.md`, `projects`; not `daemon`.
2. create: `.claude.json` has `mcpServers`, lacks `oauthAccount` and `userID`; mode `0600`.
3. convert: pre-existing unlinked dir with `oauthAccount.emailAddress = "a@b"` → moved to `.fresh-*`, new `.claude.json` carries `a@b`.
4. existing linked dir, no `--sync` → unchanged, stderr contains `already linked`, exit 0.
5. `--sync` links an entry added to source after the clone.
6. `--sync` prunes a link whose `~/.claude` target was removed.
7. `--sync` keeps a dangling link pointing at `$HOME/.claude-other/x` (prefix boundary).
8. `--sync` keeps a real file in the dest that also exists in source, and a valid link; stderr contains `kept local <name>`; `.claude.json` byte-identical before/after.
9. `--dry-run --sync` prints `unlink` / `link` lines on stdout and changes nothing (dir listing identical before/after).
10. no args → exit 2, usage on stderr.
11. `HOME=''` → non-zero, no dir created.
12. missing `~/.claude/settings.json` → exit 1.
13. missing `~/.claude.json` → exit 1, `~/.claude-<name>` not created.
14. name `''` → non-zero.
15. `PATH` without `jq` → exit 1, `~/.claude-<name>` not created.
16. `--dry-run` create mode on a pre-existing unlinked dir → stdout has exactly one `move <dst> <dst>.fresh-<epoch>` and one `write <dst>/.claude.json`, plus one `link` per non-excluded entry; dir listing identical; no `.fresh-*` exists.
17. convert with an unparseable `.claude.json` in the unlinked dir → exit 1; dir contents byte-identical; no `.fresh-*` exists.
18. `--sync` removes a link `daemon.log` → `$HOME/.claude/daemon.log` (excluded name, target exists); a real `mcp-needs-auth-cache.json` in the dest is kept and not reported.

**Gate.** `cd mstack && uv run pytest scripts/claude-home/tests -v` → 18/18.

### 5.2 S2 — Quarantine junk and sync account dirs (M2)

Run from a plain terminal (or with the `!` prefix — the jyotish.ai vault-guard hook refuses writes it cannot trace, and the session sandbox denies writes to `~/.claude/settings.json`), with no session open under `~/.claude-sk` or `~/.claude-sovo`. The script is bash (`shopt`), so save it and run it with `bash <file>`; do not paste it into zsh.

```bash
set -euo pipefail
shopt -s nullglob
C="${HOME:?}/.claude"; A="${HOME:?}/.claude-attic/2026-10-08"
[ -f "$C/settings.json" ]
cd "$C"
J=( .claude.json .last-update-result.json.tmp.* \
    settings.json.bak-20260919-222829 settings.json.bak-latest settings.json.bak.20260817-135206 \
    security_warnings_state_*.json readout-cost-cache.json readout-pricing.json readout-chats \
    x-to-obsidian.local.md claude-notification.sh.disabled .obsidian scripts \
    youtube-chrome-profile youtube-chrome-profile.conf x-playwright-profile )
for f in "${J[@]}"; do [ -e "$f" ] || { echo "missing: $f" >&2; exit 1; }; done
[ "${#J[@]}" -eq 21 ] || { echo "expected 21 sources, found ${#J[@]} — re-measure §4 before moving anything" >&2; exit 1; }
mkdir -p "$A"
[ -z "$(ls -A "$A")" ] || { echo "attic not empty: $A" >&2; exit 1; }
mv -n -- "${J[@]}" "$A"/
[ "$(ls -A "$A" | wc -l | tr -d ' ')" -eq 21 ] || { echo "attic count != 21" >&2; exit 1; }
clone-claude-config --sync --dry-run sk sovo   # review: 20 unlink lines per dir; any link line names an entry created after 2026-10-08 — confirm it
clone-claude-config --sync sk sovo
```

Every source is checked before the first move, so a vanished `.last-update-result.json.tmp.*` (Claude Code cleans these itself) stops the run with nothing moved rather than half-way through.

Then remove the stale allow rule `"Skill(x-to-obsidian:save)",` from `~/.claude/settings.json` (line 68 on 2026-10-08) — its skill and its config file are both gone.

Not quarantined, on purpose: `downloads/` and `agents/` (empty, but Claude Code-owned names), `.DS_Store` (Finder recreates it), `security/` (security-guidance plugin's live state). The `security_warnings_state_<session>.json` files are written by the same plugin (`hooks/session_state.py`), but are per-session and stale (newest 2026-05-28), so they go.

**Gate.**
- §4 "After M2" column: `ls -A ~/.claude | wc -l` → 50; `find ~/.claude-sovo -maxdepth 1 -type l | wc -l` → 42, `~/.claude-sk` → 41; `ls -A ~/.claude-attic/2026-10-08 | wc -l` → 21.
- `find -L ~/.claude-sk ~/.claude-sovo -maxdepth 1 -type l | wc -l` → 0 (no dangling links).
- `grep -c 'x-to-obsidian' ~/.claude/settings.json` → 0; `jq . ~/.claude/settings.json >/dev/null` exits 0.
- `CLAUDE_CONFIG_DIR=~/.claude-sk claude --resume` lists sessions.

### 5.3 S3 — Re-home user content (M3)

`~/.claude/CLAUDE.md` is write-denied in the session sandbox and `~/.claude/memory/` moves need the same treatment as §5.2, so the CLAUDE.md edits and the attic moves run from a plain terminal or with the `!` prefix. The mstack files are written and committed normally.

| Source | Destination | Action |
|---|---|---|
| `~/.claude/memory/testing-rules.md` | global CLAUDE.md, new `## Testing Rules` section after `## Logging Principles` | Body copied verbatim minus frontmatter; the e2e "Why" incident kept as one sentence |
| `~/.claude/memory/feedback_claude_path_encoding.md` + `reference_rename_claude_workspace.md` | `mstack/docs/claude-workspace-rename-guide.md` | Merged into one evergreen guide (the encoding note becomes its §1); one Key Paths line in CLAUDE.md points to it |
| `~/.claude/memory/feedback_always_create_command_wrapper.md` | — | Dropped as superseded (§2.4) |
| `~/.claude/auto-research-pattern.md` | `mstack/docs/auto-research-pattern.md` | `git mv`-equivalent: copy, commit in mstack, then attic the original; repoint both CLAUDE.md references |

Once the mstack copies are committed and CLAUDE.md is updated, `~/.claude/memory/` and `~/.claude/auto-research-pattern.md` go to the attic (attic count 21 → 23), then `clone-claude-config --sync sk sovo`.

**Gate.**
- `grep -c 'auto-research-pattern' ~/.claude/CLAUDE.md` → 2, and `grep -c '~/.claude/auto-research-pattern' ~/.claude/CLAUDE.md` → 0.
- `grep -c '^## Testing Rules' ~/.claude/CLAUDE.md` → 1.
- `test ! -e ~/.claude/memory && test ! -e ~/.claude/auto-research-pattern.md`.
- Entry and link counts drop by 2 from their pre-M3 values; `find -L ~/.claude-sk ~/.claude-sovo -maxdepth 1 -type l | wc -l` → 0.
- `nautilus-trader-strategies/docs/plans/2026-10-04-astro-event-study-design.md` keeps its old path: it is a dated record, not a live pointer.

### 5.4 S4 — X harvester on gstack (M4)

Decided 2026-10-10 (§8.2 a): every browser-driving script runs in the user's gstack browser; no script keeps a private profile.

**`_browse.py` — tab surface** on `BrowsePage`, mirrored on `SyncBrowsePage`:

- `new_tab(url: str) -> int` — `$B newtab <url> --json`; returns `tabId`. Empty url → `ValueError`; a reply without an int `tabId` → `BrowseError` (no id means the tab could never be closed).
- `active_tab() -> int` — the `→ [N]` line of `$B tabs`; none marked → `BrowseError`.
- `switch_tab(tab_id: int)`, `close_tab(tab_id: int)` — `$B tab N` / `$B closetab N`. Anything but an `int` (including `None` and `bool`) → `TypeError` before any call, because both commands act on the ACTIVE tab when the id is missing — possibly one of the user's own.

**`xaccount_iterate.py` — rewritten over `sync_browse_page()`.** Import has no side effects (argv parsed in `main()`).

- `parse_args(argv) -> (handle, out_dir, max_posts)`; wrong arity or `max_posts` ≤ 0 / non-int → usage on stderr, exit 2.
- `harvest(page, handle, out, maxp, day, cfg=CFG, sleep=None) -> list[str]`: checks the X login on `/home` (logged out → `NotLoggedIn` before any tab opens), loads the profile, records the profile tab id, then per unseen status id: `new_tab(status url)` → wait for `article` → `xpost_download.download_open_post(page, …)` → `close_tab` + `switch_tab(profile)` in a `finally`. A `BrowseError` on the post tab skips that post; any other exception propagates after the tab is closed. The daily render budget is now checked before each post (it was charged but never checked).
- `main(argv=None) -> int`: exit 0 done, 3 not logged in (message names `/open-gstack-browser`). Progress on stderr; stdout empty. The `x-pilot-stop` file and idle loop are removed.

**Docs.** fetch README `download.local.md` / `chrome_profile_path` block removed; x-post SKILL's harvester note rewritten. Historical comments in `youtube_downloader.py:460` and `test_browser_routing.py` stay.

**Tests.** `test_xaccount_iterate.py` (20): one tab per post and each closed; download runs on the post tab; `max_posts` cap; thread members not reopened; manifest written; empty timeline opens nothing; logged-out raises before any tab; download error / unreachable post / unexpected exception all leave only the profile tab, active; budget stops the harvest; CLI arity, `max_posts` validation, exit 3 and stderr-only output. `test_browse_adapter.py` +15 tab tests (52 total). `test_browser_routing.py` adds `xaccount_iterate.py` to `ROUTED` (no Playwright import, no `headless=`, no `BrowsePage(`, no `disconnect`).

**Gate.** `uv run pytest plugins -q` → 468 passed, no warnings.

### 5.5 S5 — Telemetry and retention (M5)

`telemetry/1p_failed_events.*.json` are events Claude Code failed to upload; deleting them loses only those uploads. `rm ~/.claude/telemetry/1p_failed_events.*.json` directly — they carry no user data worth restoring, and leaving them out of the attic keeps §4's attic count exact. The newest is from 2026-09-14, so failures are not currently accumulating. `projects/` is not touched (§8.1).

**Gate.** `find ~/.claude/telemetry -name '1p_failed_events.*.json' -mtime +0 | wc -l` → 0 (no failed-event file older than 24h survives; a fresh failure landing after the purge does not fail the gate).

## 6. Global CLAUDE.md changes (collected)

1. Key Paths: `auto-research-pattern` → `mstack/docs/auto-research-pattern.md`; add `claude-workspace-rename-guide.md`.
2. Auto-Research Loops: "Full spec" path repointed.
3. New `## Testing Rules` (S3).
4. Multiple Claude Code Logins: tool path is now `mstack/scripts/claude-home/clone-claude-config` (symlinked from `~/bin`); after any top-level change to `~/.claude`, run `clone-claude-config --sync sk sovo`.

## 7. Out of scope

- `skills/gstack` (1.1G) and `security/agent-sdk-venv` (267M): owned by gstack and the security-guidance plugin; their size is their installers' business.
- `hooks/herdr-agent-state.sh`: active, referenced from `settings.json`; moving it into a plugin is a separate change.
- Other stale allow rules in `settings.json` (project-relative `./scripts/*.sh` entries): they are inert outside their projects and belong to a permissions cleanup (`ccimprove:clean-permissions`), not this plan.

## 8. Open decisions (MK)

1. **Transcript retention — decided 2026-10-10: (a) leave `cleanupPeriodDays` unset.** All transcripts are retained; nothing under `projects/` is cleaned up by this plan.
2. **X harvester on gstack — decided 2026-10-10: (a).** Every browser-driving script runs in the gstack browser; private profiles are retired (§2.2, §5.4).
3. **Attic retention.** Default: delete `~/.claude-attic/2026-10-08/` after 14 days with no regressions.

## 9. Appendix — inventory basis

Top-level classification and sizes are from the 2026-10-08 audit (`du -sh ~/.claude/* ~/.claude/.[!.]*`). Owners were confirmed by grep across `mstack`, `mk-claude-code-plugins`, `~/.claude/settings.json`, `installed_plugins.json` and `~/.claude/plugins/cache`: `x-playwright-profile` ← `xaccount_iterate.py:21`; `youtube-chrome-profile` ← no live reader; `x-to-obsidian.local.md` ← no installed plugin (one stale allow rule, `settings.json:68`); `security_warnings_state_*.json` ← security-guidance `hooks/session_state.py` (per-session, stale); `scripts/`, `readout-chats/` ← empty; `vercel-plugin-*` ← `vercel@claude-plugins-official` (installed, kept); `~/.claude/memory/` ← referenced by nothing. Account dirs: `seed-admin` and `mcp-needs-auth-cache.json` in `~/.claude-sk` are real per-account files, confirming `EXCLUDE` works for create mode.
