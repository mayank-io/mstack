---
title: Notes / Fetch Refactor
status: complete
created: 2026-08-24
---

# Notes / Fetch Refactor

## 1. Objective

Establish one user-facing capture skill (`notes:clip`) over a clean two-layer split: `fetch:*` gets content from a source into a directory, `notes:*` writes it into an Obsidian vault. Retire `obsidian-note-creator`.

## 2. Architecture

```
fetch:<source> <url-or-path> [output_dir]     get content        (no vault knowledge)
notes:create   content -> note                write to vault     (owns conventions)
notes:save-local-file  file -> note           file into vault
notes:clip     URL -> note                    router             (user-facing)
```

Vault defaults to the one Claude Code is running in, detected by walking up for a `.obsidian/` directory. No `vault_path` config.

## 3. Status legend

⬜ todo · 🟡 in progress · ✅ done · ⚠️ blocked

## 4. Phase 1 — notes gains the writing skills

| # | Status | Task | Files |
|---|--------|------|-------|
| 1 | ✅ | Create `notes:create` — note-writing primitive migrated from obsidian-note-creator | `plugins/notes/skills/create/SKILL.md` |
| 2 | ✅ | Create `notes:save-local-file` — file clipping migrated from `obsidian-note-creator:clip` | `plugins/notes/skills/save-local-file/SKILL.md` |
| 3 | ✅ | Vault detection by `.obsidian/` walk-up, replacing `vault_path` config | both new skills |
| 4 | ✅ | Repoint `notes:clip` extract-only routes to `notes:create` | `plugins/notes/skills/clip/SKILL.md` |
| 5 | ✅ | Fix `notes:clip` PDF route to delegate to `notes:save-local-file` | same |
| 6 | ✅ | Fix `notes:clip` description — remove trigger collision, scope to URLs | same |
| 7 | ✅ | Repoint `youtube-to-obsidian` to `notes:create` | mk-claude-code-plugins |

## 5. Phase 2 — deprecate

| # | Status | Task | Files |
|---|--------|------|-------|
| 8 | ✅ | Deprecate `obsidian-note-creator` plugin | mk-claude-code-plugins |

## 6. Phase 3 — rename and uniform contract

| # | Status | Task | Files |
|---|--------|------|-------|
| 9 | ✅ | Rename plugin `download` → `fetch` | dir, `plugin.json`, `marketplace.json` |
| 9a | ✅ | **Define the fetch skill contract** — input `[output_dir]`, temp when omitted, create dir if missing, machine-parseable final stdout line | `plugins/fetch/README.md` |
| 9b | ✅ | Normalize the result line to `OUTPUT_FILE:` / `OUTPUT_DIR:` across all 7 skills | 7 skills + 5 scripts |
| 9c | ✅ | Make `notes:clip` consume the result line instead of assuming paths | `plugins/notes/skills/clip/SKILL.md` |
| 10 | ✅ | `notion-public-site`: make `output_dir` optional | command + script |
| 11 | ✅ | `alphaxiv-paper`: add `[output_dir]` | command + skill |
| 12 | ✅ | `youtube-transcript`: add `[output_dir]` | command + skill |
| 13 | ✅ | `x-post`: rename `download_dir` → `output_dir` | command + skill |
| 14 | ✅ | Update `download:` → `fetch:` in `notes:clip` | `plugins/notes/skills/clip/SKILL.md` |
| 15 | ✅ | Update `download:` → `fetch:` in `x-to-obsidian`, `youtube-to-obsidian` | mk-claude-code-plugins |
| 16 | ✅ | Update the `download:blog-post` cross-ref in `vedic-chart` | `skills/vedic-chart/SKILL.md` |

## 7. Phase 4 — browser

| # | Status | Task | Files |
|---|--------|------|-------|
| 17 | ✅ | Playwright → gstack in fetch skill instructions | 5 skills + commands |
| 18 | ✅ | Playwright → gstack in `x-to-obsidian`, `linkedin-to-obsidian` | mk-claude-code-plugins |
| 19 | ✅ | Scripts launching headless Chromium — **decision: (a) drive the `$B` CLI** (2026-08-24) | `notion_public_site_downloader.py`, `scribd_extractor.py` |
| 20 | ✅ | *(found during final sweep, not in original plan)* `youtube_transcript_extractor.py` Playwright fallback forced headed; `--headless` deprecated to a no-op | `scripts/youtube_transcript_extractor.py` + skill |

## 8. Out of scope, tracked elsewhere

- Clip the Justin Banks X post — blocked on X 403 rate limit
- Trading journal design v2 — awaiting approval in the vault
- Stale marketplaces (`*.bak`, `temp_*`) registering duplicate `download` copies

## 9. Log

| Date | Entry |
|------|-------|
| 2026-08-24 | Plan created |
| 2026-08-24 | Task 20 done — final sweep found a 3rd Playwright user (youtube fallback, persistent profile). Forced headed, `--headless` now a warned no-op. Contradictory skill instructions removed |
| 2026-08-24 | Task 19 done — new `scripts/_browse.py` adapter drives `$B` behind a Playwright-shaped API; notion + scribd rewritten, zero headless launches. Live-tested notion end-to-end |
| 2026-08-24 | Tasks 17-18 done — gstack block added to 5 fetch skills; x-to-obsidian + linkedin-to-obsidian switched off Playwright/MCP entirely |
| 2026-08-24 | Tasks 14-16 done — all `download:` refs repointed to `fetch:` across both repos; T16 already covered by the T9 bulk rename |
| 2026-08-24 | Tasks 10-13 done — all 7 skills now take `[output_dir]`; notion optional + temp default; youtube gained `--output-dir`; x-post renamed. **Fixed a regression from 9b**: youtube consumed whisper's bare-path stdout, now parses the marker |
| 2026-08-24 | Task 9c done — clip parses the result line, refuses to guess paths; steps renumbered 1-5 |
| 2026-08-24 | Task 9b done — 5 scripts emit `OUTPUT_FILE:`/`OUTPUT_DIR:` as final stdout line; live-tested youtube extractor; vedic-chart exception documented |
| 2026-08-24 | Tasks 9+9a done — plugin renamed to `fetch` (marketplace v0.6.0, 13 files); skill contract documented in fetch/README |
| 2026-08-24 | Task 8 done — obsidian-note-creator removed from marketplace + repo (recoverable from git); notes/README repointed |
| 2026-08-24 | Task 7 done — youtube-to-obsidian repointed to `notes:create`; vault-config prerequisite removed |
| 2026-08-24 | Tasks 4-6 done — clip repointed to `notes:create` / `notes:save-local-file`; description scoped to URLs, collision removed |
| 2026-08-24 | Task 2+3 done — `notes:save-local-file`; both new skills use `.obsidian/` walk-up |
| 2026-08-24 | Task 1 done — `notes:create` skill + command; vault via `.obsidian/` walk-up, no config; emits `OUTPUT_FILE:` |
