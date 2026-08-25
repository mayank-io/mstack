---
title: Orchestrator Collapse — one clip skill, per-source knowledge as templates
status: draft
created: 2026-08-24
depends-on: 2026-08-24-notes-fetch-refactor.md
---

# Orchestrator Collapse — one clip skill, per-source knowledge as templates

## 1. Objective

Retire the four surviving `mk-claude-code-plugins` capture plugins into the two-layer architecture from [the notes/fetch refactor](2026-08-24-notes-fetch-refactor.md), keeping **`notes:clip` as the single user-facing capture skill**. Per-source knowledge becomes template data, not additional skills.

## 2. Key findings

1. **`youtube-to-obsidian:process` is broken right now.** `commands/process.md:88` globs `~/.claude/plugins/{marketplaces,cache}/*/plugins/download/scripts/youtube_transcript_extractor.py`. The `download` plugin was renamed to `fetch` on 2026-08-24, so Step 1 yields an empty `$EXTRACTOR`. Line 154 carries the same stale `<download-plugin>/scripts/` reference for `verify_caption_window.py`.
2. **That path cannot be repaired, only replaced.** `mstack` is registered as a `directory` marketplace, so its scripts live under `~/Developer/github/mayank-io/mstack/`, nowhere under `~/.claude/plugins/`. Substituting `fetch` for `download` in the glob fixes nothing. The caller must invoke `fetch:youtube-transcript` **as a skill** rather than reaching into its `scripts/` directory by filesystem path.
3. **The three `*-to-obsidian` plugins have zero skills.** After the refactor they hold one command each and delegate extraction to `fetch:*` and writing to `notes:create`. What remains is per-source output shape wearing a pre-refactor name that advertises a destination (`obsidian`) the plugin no longer owns.
4. **That remainder is data, not behaviour.** Sorting it (§4.2) lands every element in something that already exists — `fetch:*`, `notes:create`, `notes:clean-transcript`, or a template file. No per-source skill survives the sort.
5. **The repo already proves the template approach.** `youtube-to-obsidian/templates/pg-gyaan.md` is 213 lines carrying its own channel-matching rule, its own Whisper settings, and its own output shape — source-specific knowledge in a data file, working one level deeper than per-source (per-channel).
6. **`notes:clip` has a silent cross-marketplace dependency.** Three of its eight routes live in `mk`. Uninstalling `youtube-to-obsidian` breaks YouTube clipping with no warning at the router.
7. **There is no `fetch:linkedin-post`.** `linkedin-to-obsidian:save` performs its own gstack extraction inline, so migrating it as-is would leave retrieval embedded in the notes layer.
8. **`fetch:x-post` is internally inconsistent.** Its header mandates the gstack browser and forbids headless; `:50` and `:206` still instruct `mcp__playwright__browser_run_code` and `browser_snapshot`.
9. **`fetch:blog-post` is unrouted.** `notes:clip` sends the fallback route to `obsidian:defuddle`, bypassing mstack's own fetcher — which does strictly more (Defuddle *plus* lazy-image recovery, plus `fetch:vedic-chart` for embedded charts).

## 3. Recommendation

Keep one capture skill. Move per-source output shape into `notes/templates/`. Push the genuine behaviour that was hiding in the orchestrators down into `fetch:*` or up into `notes:create`, both of which already exist. Retire all four `mk` plugins. Fix defects §2.1, §2.7, §2.8, §2.9 on the way through.

## 4. Architecture

### 4.1 Layer contract

```
fetch:<source>  url [output_dir]  ->  raw content + metadata   retrieval; no vault knowledge, no opinions
notes:clip      url               ->  note                     router + flow (the only entry point)
notes:create    content           ->  note in vault            owns vault conventions
```

**`fetch:*` returns raw.** Cleaning is opinionated and lossy — paragraph breaks, chapter headings, noise-marker removal. Raw can always be re-cleaned; cleaned can never be un-cleaned. The caller decides how, or whether, to clean. `fetch:youtube-transcript` therefore stays exactly as it is, emitting timestamped raw text plus metadata plus `caption_warnings`.

### 4.2 The sort — why no per-source skill is needed

| What the orchestrators did | Where it belongs | Exists? |
|---|---|---|
| Thread detection, walk-back to first post, images at `&name=orig` | `fetch:x-post` | yes |
| Whisper fallback, `caption_warnings` detection | `fetch:youtube-transcript` | yes |
| LinkedIn page extraction | `fetch:linkedin-post` | **no — task 13** |
| Ticker wikilinks, daily-note update, `Clippings/` placement, filename sanitising, collision avoidance | `notes:create` | yes (partly by delegation — task 9) |
| Recursion into linked content | `notes:clip` — general, not a LinkedIn trait; an X post can quote a link too | yes |
| Transcript sequence: raw → clean → corruption scan | `notes:clean-transcript` | **no — task 6** |
| Frontmatter extras, body structure, which summary sections | `notes/templates/<source>.md` | **no — tasks 5, 14** |

Every row lands somewhere. The three recipes were three copies of *"read fetch output, fill a shape, call `notes:create`"* differing only in the shape.

### 4.3 Skill layout after this plan

```
mstack/plugins/fetch/skills/     alphaxiv-paper  blog-post  linkedin-post*  notion-public-site
                                 scribd-document  vedic-chart  x-post  youtube-transcript
mstack/plugins/notes/skills/     clip  clean-transcript*  create  save-local-file
mstack/plugins/notes/templates/  article.md  default.md  linkedin.md  notion.md  paper.md
                                 x.md  youtube.md  channels/pg-gyaan.md
                                                                            * = new
```

`mk-claude-code-plugins` loses `youtube-to-obsidian`, `x-to-obsidian`, `linkedin-to-obsidian`, `youtube-transcript-cleaner`.

### 4.4 One flow, one conditional — all eight routes

```
notes:clip <url>
│
├─ 1. route on host  ──▶  fetch:<source>              (curl, for PDF)
├─ 2. read the OUTPUT_FILE: / OUTPUT_DIR: final line
├─ 3. select templates/<source>.md                    (+ channels/<name>.md override if one matches)
├─ 4. if transcript  ──▶  notes:clean-transcript
├─ 5. fill the template
└─ 6. notes:create                                    (or notes:save-local-file, for PDF)
```

| Route | `fetch` skill | Template |
|---|---|---|
| `youtube.com`, `youtu.be` | `youtube-transcript` | `youtube.md` (+ channel override) |
| `x.com`, `twitter.com` | `x-post` | `x.md` |
| `linkedin.com` | `linkedin-post` | `linkedin.md` |
| `*.notion.site`, `notion.so` | `notion-public-site` | `notion.md` |
| `scribd.com` | `scribd-document` | `article.md` |
| `alphaxiv.org`, `arxiv.org` | `alphaxiv-paper` | `paper.md` |
| PDF, any host | `curl` → `notes:save-local-file` | — |
| anything else | `blog-post` (§5.2) | `article.md` |

`clip` gains one column and one conditional. Per-source knowledge moves *out* of it into files, not into it.

### 4.5 The template/skill boundary

A template that carries instructions is a skill in disguise, and nothing lints the difference. `pg-gyaan.md` is already 213 lines and specifies tool settings.

**The rule: templates describe output shape and may carry declarative settings (channel match patterns, Whisper model, language, frontmatter fields). Anything that sequences tool calls belongs in a skill.** If a template starts saying "then run X, then check Y", it has outgrown the format and the logic moves to `clip` or a `fetch:*` skill.

Task 20 adds this rule to `notes/README.md` so it survives the plan.

## 5. Decisions

### 5.1 Where does Whisper caption remediation live?

Detection already sits in `fetch` — the extractor emits `caption_warnings`. Remediation (re-transcribing the flagged window, splicing the recovered figure back in) sits in the caller today, at `process.md` Step 1.7.

| Option | Argument |
|---|---|
| **A — remediation in `fetch`** *(assumed default)* | Recovering a figure the caption dropped is *getting the content correctly*, not shaping it. Fidelity to the audio is the fetcher's job; detection is already there; `verify_caption_window.py` already ships in `fetch/scripts/`. |
| **B — remediation in `clip`** | It mutates the raw text, and §4.1 says `fetch` returns raw. |

**Proceeding on A.** The distinguishing line: verification makes the transcript *more faithful to the audio*; cleaning makes it *more readable*. Only the second is opinionated, so only the second is the caller's. Switching to B moves one call site.

### 5.2 `fetch:blog-post` or `obsidian:defuddle` for the fallback route?

`clip` currently routes "anything else" to `obsidian:defuddle` — a third-party plugin — while mstack's own `fetch:blog-post` sits unrouted and does strictly more.

**Proceeding on `fetch:blog-post`**, with `obsidian:defuddle` remaining its internal extractor. This removes the last third-party dependency from the clip chain and gives the fallback route the same `OUTPUT_DIR:` contract as every other route. Promoted out of "out of scope" because §4.4 makes it a live routing decision, not a future cleanup.

## 6. Status legend

⬜ todo · 🟡 in progress · ✅ done · ⚠️ blocked

## 7. Milestone 1 — restore YouTube capture

Ships: `/youtube-to-obsidian:process` works again. Done in place in `mk`, because the same edit carries into Milestone 2 and the plugin should not stay broken while the migration runs.

| # | Status | Task | Files |
|---|---|---|---|
| 1 | ✅ | Replace the `plugins/download/scripts/` glob with a `fetch:youtube-transcript` skill invocation; chain on its `OUTPUT_FILE:` line | `mk:youtube-to-obsidian/commands/process.md:75-95` |
| 2 | ✅ | Replace the `<download-plugin>/scripts/verify_caption_window.py` reference with the same skill-mediated path — done by giving `fetch:youtube-transcript` a "Caption verification" section that owns the procedure and the path | same, `:144-162` |
| 3 | ✅ | Grep both repos for any other `plugins/download` or `<download-plugin>` path reference — fixed 4 live ones (§7.1); historical design docs left frozen | `mstack:README.md`, `fetch/README.md` |
| 4 | ✅ | Verify the extraction contract end to end on a short video | — |

**Gate:** ✅ passed. `fetch:youtube-transcript` run end to end on a short video emitted `OUTPUT_FILE:/var/.../yt_transcript_dQw4w9WgXcQ.json` as its final stdout line; the parse pattern now written into both `SKILL.md` and `process.md` extracted the path cleanly; the JSON held a real 2,394-character English transcript with correct title and channel.

⚠️ **What this gate does not cover.** It verifies the extraction contract — the part that was broken. It does not exercise the full `/youtube-to-obsidian:process` LLM flow through to a written note, because doing so would file a throwaway note in the vault. The failure mode that was fixed (an empty `$EXTRACTOR` from a dead glob) is structurally gone: there is no glob left to fail.

### 7.1 Stale references found and fixed by task 3

| File | Was | Now |
|---|---|---|
| `mstack:README.md` Install | `/plugin install download@mstack` | all six plugins, `notes` and `fetch` first, with a note that they are a pair |
| `mstack:README.md` Plugins | a `download` section listing five `/download:*` commands | a `notes` section (clip first) and a `fetch` section with all seven skills and the output contract |
| `mstack:README.md` Layout | `plugins/{ccimprove,dev,download}` | all six plugins |
| `mstack:plugins/fetch/README.md` | `claude install mk-claude-code-plugins/download` | `claude install fetch@mstack` |

Historical design docs and completed plans in `mk:docs/` that reference `download:*` were **left unchanged** — they are records of what was true when written, and rewriting them would falsify the record.

⚠️ **One dormant hazard, not fixed:** `mk:docs/plans/2026-08-16-x-account-archive.md` is an unexecuted implementation plan whose every path says `plugins/download/`. If anyone runs it as written, it will fail the same way task 1 did. Tracked in §12.

## 8. Milestone 2 — YouTube runs through `clip`, knowledge becomes templates

Ships: `notes:clip <youtube-url>` works end to end with no `*-to-obsidian` plugin involved. This is the milestone that proves the architecture; everything after it is repetition.

| # | Status | Task | Files |
|---|---|---|---|
| 5 | ✅ | Extract `templates/default.md` → `notes/templates/youtube.md` and `pg-gyaan.md` → `notes/templates/channels/pg-gyaan.md`; strip anything that sequences tool calls per §4.5 | `mstack:plugins/notes/templates/` |
| 6 | ✅ | Create `notes:clean-transcript` from `youtube-transcript-cleaner` — drop the stuttering name; own the corruption scan (`$und00`, `a,50`, `%` with no preceding digit) that `clip` §3 already mandates | `mstack:plugins/notes/skills/clean-transcript/SKILL.md` |
| 7a | ✅ | **Prerequisite:** stand up a Python test harness in `mstack` — none exists today (no `pyproject.toml`, no `uv.lock`, no `tests/`), so §11.6 is currently unrunnable | `mstack:pyproject.toml` |
| 7b | ✅ | Ship the cleaner as a deterministic script, not prose — guarantees verbatim by construction (spec in §11) | `.../clean-transcript/scripts/clean.py` |
| 8 | ✅ | Implement §5.1 decision A — caption remediation invoked from `fetch:youtube-transcript` (pulled forward into M1; it was the only fix for task 2 that did not reintroduce path-reaching) | `mstack:plugins/fetch/skills/youtube-transcript/SKILL.md` |
| 9 | ✅ | Make `notes:create` conventions explicit rather than delegated: daily-note append and ticker wikilinking currently rely on the vault's `CLAUDE.md` being read and obeyed, which did not fire during the 2026-08-24 X clip | `mstack:plugins/notes/skills/create/SKILL.md` |
| 10 | ✅ | Teach `clip` the flow in §4.4 — template column, the transcript conditional, template selection with channel override | `mstack:plugins/notes/skills/clip/SKILL.md` |
| 11 | ✅ | Verify: `notes:clip <youtube-url>` end to end; confirm cleaned text is token-identical to raw apart from deliberate removals | — |
| 12 | 🟡 | Verify: a `pg gyaan` URL selects the channel override and applies its Whisper settings | — |

**Gate:** ✅ passed, with one partial.

| Check | Result |
|---|---|
| Task 7b suite (§11) | 29/29 green, and **mutation-tested** — see §8.1 |
| Task 11 token identity, real video | 487 raw tokens → 487 clean tokens, **identical** |
| Task 12 channel selection | 5/5 — `PG Gyaan`, `pggyaan`, `PG ज्ञान` → override; `Rick Astley`, `ARK Invest` → default |
| Task 12 Hindi pipeline end to end | 🟡 **not run** — see below |

🟡 **Task 12 is half-verified.** Template *selection* is proven deterministically against the patterns the template itself declares. What is not exercised is a real `pg gyaan` capture through Whisper `medium` in Hindi, with the IST→PST conversion and date wikilinks the template specifies. That needs a live Hindi video and a slow transcription; deferred to the first real pg-gyaan clip.

### 8.1 Mutation testing — why the suite is trusted

29/29 green on first run is not evidence; a suite that has never failed proves nothing. Three deliberate breakages:

| Mutation | Caught? |
|---|---|
| Capitalise the first word (i.e. "fix grammar") | ✅ 3 tests fail, including `test_verbatim_invariant` |
| Chapter boundary `>=` → `>` (start-exclusive) | ✅ `test_chapter_boundary_inclusive` fails |
| Drop the noise-only-segment guard | ❌ **survived** |

The third exposed a hole in the test, not in the code. `test_noise_only_line_dropped` compared token streams, and a `\S+` tokeniser normalises away the double space an empty segment leaves. Tightened to assert the exact body (`"alpha beta\n"`) plus the parse output directly; the mutation now fails it. **The gap was in the assertion, and only mutation testing surfaced it.**

## 9. Milestone 3 — remaining sources

Ships: all eight routes resolve inside `mstack`, through one skill.

| # | Status | Task | Files |
|---|---|---|---|
| 13 | ⬜ | Create `fetch:linkedin-post` from the extraction half of `linkedin-to-obsidian/commands/save.md` — resolves §2.7 | `mstack:plugins/fetch/skills/linkedin-post/SKILL.md` |
| 14 | ⬜ | Write the remaining templates: `x.md`, `linkedin.md`, `notion.md`, `paper.md`, `article.md`, `default.md` | `mstack:plugins/notes/templates/` |
| 15 | ⬜ | Move recursion-into-linked-content from LinkedIn into `clip` as general behaviour; guard against cycles | `clip/SKILL.md` |
| 16 | ⬜ | Purge the Playwright instructions in `fetch:x-post` `:50` and `:206`; replace with gstack via `_browse.py` — resolves §2.8 | `mstack:plugins/fetch/skills/x-post/SKILL.md` |
| 17 | ⬜ | Audit every `fetch:*` and `notes:*` skill for any other surviving `mcp__playwright__` or headless instruction | `mstack` |
| 18 | ⬜ | Implement §5.2 — route the fallback to `fetch:blog-post`; resolves §2.9 | `clip/SKILL.md` |
| 19 | ⬜ | Verify each remaining route once: X thread with images, LinkedIn post with a linked X post, Notion site, Scribd doc, arXiv paper, PDF, plain article | — |

**Gate:** seven notes written, images on disk at original resolution, the LinkedIn recursion produces two notes, and no route invokes Playwright.

## 10. Milestone 4 — retire the `mk` plugins

Ships: one repo owns capture; no cross-marketplace dependency; one entry point.

| # | Status | Task | Files |
|---|---|---|---|
| 20 | ⬜ | Update `notes/README.md` and `fetch/README.md` — the §4.1 raw rule, the §4.4 flow, and the §4.5 template/skill boundary | both plugins |
| 21 | ⬜ | Remove the four plugins from `mk` `marketplace.json` and delete their directories (check for `.DS_Store` survivors — one blocked a deletion on 2026-08-24) | `mk` |
| 22 | ⬜ | Bump `mk` `metadata.version` — the pre-commit hook rejects plugin changes without it | `mk:.claude-plugin/marketplace.json` |
| 23 | ⬜ | Bump `mstack` `metadata.version` 0.6.0 → 0.7.0 | `mstack:.claude-plugin/marketplace.json` |
| 24 | ⬜ | Uninstall the four retired plugins locally, `/reload-plugins`, confirm no skill name 404s | — |
| 25 | ⬜ | Verify: all eight `clip` routes resolve with the four `mk` plugins uninstalled | — |
| 26 | ⬜ | Commit and push both repos; rebase, no merge commits, no Claude Code signature | — |

**Gate:** task 25 passes — the cross-marketplace dependency (§2.6) is gone by demonstration, not by assertion.

## 11. Test specification for `clean.py` (task 7b)

The only code artifact in this plan. Everything else is skill prose or template data.

### 11.1 Contract

```
clean.py raw.txt out.md [meta.json]
```

Deletes timestamps and noise markers, inserts whitespace and chapter headings. **Never rewrites a word** — the output token stream is provably the input minus deliberate deletions. Writes `out.md`; prints `segments:`, `chapters inserted:`, `chars out:` to stderr; emits `OUTPUT_FILE:<path>` as the final stdout line.

### 11.2 Smoke investigation

| Input line | Parsed `secs` | Emitted text |
|---|---|---|
| `0:15 the market has been volatile` | 15 | `the market has been volatile` |
| `1:02:33 and then it turned` | 3753 | `and then it turned` |
| `12:04 [Music] back to the charts` | 724 | `back to the charts` |
| `0:00 first` then `continued here` (no timestamp) | 0 | `first continued here` — appended to the prior segment |

`mm:ss` vs `hh:mm:ss` is decided by group count, not magnitude: `1:02:33` is 3753s, `62:33` is 3753s, `1:02` is 62s.

### 11.3 Boundary semantics

- Chapter headings insert when `secs >= chapter.start` — **start-inclusive**. A segment at exactly `chapters[i].start` falls under that heading, not the previous one.
- Paragraph flush requires **both** `buf_len >= 700` **and** the segment ending in `. ? ! " ”`. A 5,000-character run with no sentence terminator emits as one paragraph — correct, not a bug.
- A noise marker consuming an entire line yields empty text and is dropped; it must not create an empty paragraph or swallow the next segment's timestamp.

### 11.4 Unit tests

| Test | Assertion |
|---|---|
| `test_parse_mmss` / `test_parse_hhmmss` | §11.2 values exactly |
| `test_continuation_line` | untimestamped line appends to the prior segment |
| `test_noise_removed` | `[Music]`, `[Applause]`, `[Laughter]`, `[inaudible]` deleted, case-insensitive |
| `test_noise_only_line_dropped` | no empty paragraph emitted |
| `test_chapter_boundary_inclusive` | segment at exactly `start` lands under the new heading |
| `test_chapter_before_first` | segments before `chapters[0].start` emit with no heading |
| `test_no_chapters` | absent or empty `meta.json` → no headings, no crash |
| `test_verbatim_invariant` | **load-bearing** — `tokens(out) == tokens(raw) - timestamps - noise`, over a real 50k-char transcript |
| `test_corruption_scan` | flags `$und00`, `a,50`, `%` with no preceding digit; does **not** flag `$1,050` or `60%` |
| `test_output_marker` | final stdout line is `OUTPUT_FILE:<abs path>` |

### 11.5 Error paths

| Condition | Behaviour |
|---|---|
| `raw.txt` missing | non-zero exit, stderr message, no `out.md` |
| `raw.txt` empty | exit 0, empty `out.md`, `segments: 0` |
| `meta.json` malformed | non-zero exit — do **not** silently proceed with zero chapters, which would look like success |
| `meta.json` chapter missing `start_time` | non-zero exit naming the chapter |
| no timestamps anywhere | whole file becomes one segment at `secs=0`; do not error |

### 11.6 Command

```bash
uv run pytest plugins/notes/skills/clean-transcript/tests/ -v
```

⚠️ **Does not work until task 7a lands.** `mstack` has no Python test harness — no `pyproject.toml`, no `uv.lock`, no `tests/` anywhere in the repo. Until then §11.4 and §11.5 are a specification with no runner.

**Acceptance:** 10/10 unit tests and 5/5 error-path tests green, with `test_verbatim_invariant` run against a real transcript over 50,000 characters.

## 12. Out of scope

- `mk:gmail` — in the repo but not declared in `marketplace.json`; superseded by `gogcli`. Leave as is.
- Renaming `notes:clip`. It is the user-facing verb and stays.
- The `edge-idea` collection system — designed, not built, tracked separately.
- `fetch:vedic-chart` — reachable from `fetch:blog-post` and standalone, never a `clip` route.

## 13. Log

| Date | Note |
|---|---|
| 2026-08-24 | Plan created after `notes:clip` was exercised on an X post and the survey found `youtube-to-obsidian:process` broken by the `download`→`fetch` rename. |
| 2026-08-24 | M1 complete — `mstack 67d7219` (0.6.1), `mk 094def0` (1.2.1). Task 8 pulled forward: no fix for task 2 avoided path-reaching except moving caption remediation into `fetch`. |
| 2026-08-24 | M2 complete but for the Hindi end-to-end check (§8, task 12). Templates migrated unchanged — both were already shape + declarative settings, so §4.5 required no edits to them. |
| 2026-08-24 | Rewritten. First draft added `notes:youtube` / `notes:x` / `notes:linkedin` as per-source skills. Sorting their contents (§4.2) showed every element already had a home, so the three skills were dropped and per-source knowledge became template data — keeping `clip` the single entry point. Milestone 3 shrank accordingly; `fetch:linkedin-post` and the `blog-post` routing decision were promoted in. |
