# Notes Plugin

Capture external sources into an Obsidian vault. **`clip` is the single entry point** — hand it a URL and it routes, fetches, formats and files.

## Skills

| Skill | Role |
|---|---|
| `clip` | URL → note. The only skill you invoke directly. |
| `clean-transcript` | raw transcript → readable verbatim Markdown, guaranteed by a script |
| `create` | write a note into the current vault; owns frontmatter, folder, filename, links |
| `save-local-file` | a file already on disk → note, archiving the file into attachments |

```
clip https://x.com/user/status/123
clip https://youtube.com/watch?v=abc
/notes:clip https://example.com/article  tag it to project X
```

## How clip works

One flow, one conditional, for every route:

```
1. route on host        ──▶  fetch:<source>          (curl, for PDF)
2. read its OUTPUT_FILE: / OUTPUT_DIR: final line
3. select templates/<source>.md  + templates/channels/<name>.md if one matches
4. if the content is a transcript  ──▶  notes:clean-transcript
5. fill the template
6. notes:create                    (or notes:save-local-file, for PDF)
```

| Source | Fetch with | Template |
|---|---|---|
| YouTube | `fetch:youtube-transcript` | `youtube.md` (+ channel override) |
| X / Twitter | `fetch:x-post` | `x.md` |
| LinkedIn | `fetch:linkedin-post` | `linkedin.md` |
| Notion site | `fetch:notion-public-site` | `notion.md` |
| Scribd | `fetch:scribd-document` | `article.md` |
| arXiv / alphaXiv | `fetch:alphaxiv-paper` | `paper.md` |
| PDF (incl. Drive) | `curl` → `notes:save-local-file` | — |
| anything else | `fetch:blog-post` | `article.md` |

## Design

### There is no per-source skill, and there should never be one

An earlier design added `notes:youtube`, `notes:x` and `notes:linkedin`. Sorting what those "recipes" actually contained showed every element already had a home:

| What it did | Where it belongs |
|---|---|
| Thread detection, image download, Whisper fallback | the `fetch:*` skill |
| Ticker wikilinks, daily-note update, folder, filename | `notes:create` |
| Recursion into shared content | `clip` — general, not a LinkedIn trait |
| Transcript cleaning and corruption scan | `notes:clean-transcript` |
| Frontmatter extras, body structure, summary sections | **a template** |

The three recipes were three copies of *"read fetch output, fill a shape, call create"* differing only in the shape. So shape moved to `templates/` and the skills disappeared.

### Templates describe shape, never sequence

**The boundary that keeps this design from decaying.** A template may carry declarative settings — channel match patterns, a Whisper model, a language, frontmatter fields, required tags. If one starts saying *"then run X, then check Y"*, it has outgrown the format and that logic belongs in `clip` or a `fetch:*` skill.

Nothing lints this. `templates/channels/pg-gyaan.md` is already 213 lines and specifies tool settings; it stays a template because it never sequences a call. A channel template **overrides** its source template entirely — it does not merge.

### The layer split

`fetch:*` retrieves and returns **raw**. `notes:*` writes into a vault. Cleaning is opinionated and lossy — paragraph breaks, chapter headings, noise removal — so it belongs to the caller, not the fetcher. Raw can always be re-cleaned; cleaned can never be un-cleaned.

## Traps this plugin encodes

Each one has produced a bad capture:

- **Browser sources use gstack, never a fresh Playwright session** — a logged-out capture looks like a successful short one.
- **`$B js` does not await promises.** Page JavaScript must be synchronous; drive waits from Python. An in-page `await` silently returns nothing, which reads as "no results".
- **X virtualises its DOM** — a single pass loses posts; accumulate across a scroll loop keyed by status id.
- **Images at `name=orig`, not `name=large`** — a downscaled chart is unreadable at the point it matters.
- **YouTube caption warnings catch *omitted* numbers, not *corrupted* ones.** `$und00` for `$1,050` reads as authoritative. `clean-transcript` scans for the second class; anything a summary will quote gets re-transcribed from audio.
- **Notion hides content in collapsed toggles** — a page that is all headings with empty bodies is not a short page, it is an unexpanded one.
- **LinkedIn truncates behind "…see more"** — expand before reading.
- **Screenshot-heavy pages carry their content in the images** — download *and read* them.
- **PDFs get archived locally**, because the link will rot.
- **Recursion needs a cycle guard.** Two posts quoting each other loop forever; normalise URLs before comparing and cap depth.

## Dependencies

Everything `clip` routes to lives in this marketplace: `fetch:*` for extraction, this plugin for writing. There is no cross-marketplace dependency.

If a required skill is missing, `clip` reports it and stops rather than half-finishing.

## Tests

```bash
uv run --group dev pytest plugins/notes/skills/clean-transcript/tests/ -v
```

`clean.py` is the only code here; everything else is skill prose and template data. Its suite is mutation-tested — if you change it, break it deliberately and confirm a test fails. A suite that has never failed proves nothing.
