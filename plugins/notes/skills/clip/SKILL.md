---
name: clip
description: "Capture a URL into the notes vault — route it to the right fetcher and note-writer for that source. Use when the user says \"clip <url>\", \"clip this link\", or shares a URL and wants it saved as a note. Handles X/Twitter, YouTube, LinkedIn, Notion sites, PDFs and general web pages. For a file already on disk, use notes:save-local-file instead."
---

# Clip

Route a URL to the correct extraction skill and note-writer. **This skill is a router. It does not format notes and does not know vault conventions** — the downstream skill owns that.

## Input

The user provided: `$ARGUMENTS` — a URL, optionally followed by extra instructions (e.g. "tag it to project X", "capture with the edge-idea tag"). **Pass extra instructions through to the downstream skill and honour them after it returns.**

## Step 1 — Identify the source

Match on the URL's host and path.

| Source | Fetch with | Template |
|--------|-----------|----------|
| `youtube.com`, `youtu.be` | `fetch:youtube-transcript` | `youtube.md` (+ channel override) |
| `x.com`, `twitter.com` | `fetch:x-post` | `x.md` |
| `linkedin.com` | `fetch:linkedin-post` | `linkedin.md` |
| `*.notion.site`, `notion.so` | `fetch:notion-public-site` | `notion.md` |
| `scribd.com` | `fetch:scribd-document` | `article.md` |
| `alphaxiv.org`, `arxiv.org` | `fetch:alphaxiv-paper` | `paper.md` |
| PDF (any host, incl. Drive/Dropbox) | `curl` → `notes:save-local-file` | — |
| anything else | `fetch:blog-post` | `article.md` |

The fallback goes to **`fetch:blog-post`**, not `obsidian:defuddle`. `blog-post` uses Defuddle internally *and* recovers the lazy-loaded images Defuddle drops, digitizes embedded Vedic charts via `fetch:vedic-chart`, and emits the same `OUTPUT_DIR:` contract as every other route. Routing straight to `defuddle` skips all of that and reaches outside this marketplace for a capability we already own.

**Every route is the same six steps.** There is no per-source skill, and there should never be one — what varies between sources is output shape, and shape lives in `templates/`.

```
1. route on host        ──▶  fetch:<source>          (curl, for PDF)
2. read its OUTPUT_FILE: / OUTPUT_DIR: final line     — Step 2
3. select templates/<source>.md, and templates/channels/<name>.md if one matches
4. if the content is a transcript  ──▶  notes:clean-transcript
5. fill the template
6. notes:create                     (or notes:save-local-file, for PDF)
```

**Templates describe shape, never sequence.** A template may carry declarative settings — channel match patterns, a Whisper model, a language, frontmatter fields, required tags. If one starts saying "then run X, then check Y", it has outgrown the format and that logic belongs here or in a `fetch:*` skill. A channel template **overrides** the source template entirely; it does not merge with it.

**`notes:create` owns the vault, not you.** It locates the vault, reads its `CLAUDE.md`, applies the vault's link conventions, writes the file, links it into today's daily note, and verifies the links resolve. Supply title, content, folder and frontmatter — nothing about layout.

**PDF is the one exception to step 6.** `notes:save-local-file` writes the note *and* archives the file into the vault's attachments, so it replaces both the template fill and `notes:create`.

Pass the fetch skill an `output_dir` when you want the artefacts somewhere specific; omit it and they land in a temp directory. Either way, learn where they landed from the result line — see Step 2.

If a required skill is not installed, **say so and stop.** Do not silently half-finish with a partial extraction.

## Step 2 — Chain on the result line, never guess the path

Every `fetch:*` skill prints a machine-parseable **final stdout line**:

```
OUTPUT_FILE:/absolute/path/to/file        # one artefact
OUTPUT_DIR:/absolute/path/to/directory    # a set of files
```

**Read that line and use it.** Do not reconstruct paths from the URL, the title, or the working directory — that is how output gets written to the wrong place or a summary gets written about a file that was never opened.

```bash
last=$(… fetch command … | tail -1)
case "$last" in
  OUTPUT_FILE:*) path="${last#OUTPUT_FILE:}" ;;
  OUTPUT_DIR:*)  path="${last#OUTPUT_DIR:}"  ;;
  *) echo "fetch skill did not emit a result line — stop and report it"; exit 1 ;;
esac
```

**If the marker is absent, stop and say so.** A fetch skill that does not emit one is a bug in that skill, not a licence to guess.

Then hand the resolved path onward:

- `OUTPUT_FILE:` pointing at a **document** (PDF, image) → `notes:save-local-file`
- `OUTPUT_FILE:` pointing at **extracted text/JSON** → read it, build the note, → `notes:create`
- `OUTPUT_DIR:` → read what you need from the directory, → `notes:create`

**One documented exception:** `fetch:vedic-chart` streams its product to stdout when no `output_dir` is given and emits no marker. Pass it an `output_dir` when clipping.

## Step 2.5 — Follow what the source shares

Captured content often points at other content: a LinkedIn post sharing a YouTube video, an X post quoting an article, a blog post embedding a tweet. **This is general behaviour, not a LinkedIn trait** — it lives here because `clip` is the only skill that can route a URL, and a `fetch:*` skill that started pulling in YouTube videos would have stopped being a fetch skill.

When a fetch result carries a `links` field, or the content obviously centres on a shared URL:

1. **Clip each shared URL by re-entering this skill.** It routes them the same way it routed the first.
2. **Link the results together** — the parent note references each child by wikilink, so the relationship survives.
3. **Judge before recursing.** Follow a link the post is *about*: the video it discusses, the article it quotes. Do not follow navigation, profile links, tracking URLs, or a bare domain mention.

**Guard against cycles — this recursion is unbounded otherwise.** Two posts quoting each other, or a page linking its own canonical URL, will loop forever.

- Keep a set of already-clipped URLs for this invocation, **normalised** — strip `utm_*` and other tracking params, resolve shorteners, drop the fragment, lower-case the host. `x.com/u/status/1?s=20` and `x.com/u/status/1` are the same post.
- Never clip a URL already in the set, and add each URL *before* fetching it, not after.
- **Depth limit 1 by default.** Clip what the post shares; do not clip what *that* shares. Going deeper needs the user to ask.
- If a note already exists for a URL, link to it rather than re-clipping.

**Say what you followed and what you skipped.** A silently-skipped link looks identical to a link that was never there.

## Step 3 — Apply the per-source overrides

These are non-negotiable and exist because each one has already caused a bad capture.

### All browser-based sources (X, LinkedIn)

**Use gstack browse, never a fresh Playwright session.** The user is logged into their accounts there; a fresh Playwright session hits login walls and silently returns logged-out content.

```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" connect          # run from the vault directory — a different cwd spawns a second daemon and kills the headed session
"$B" goto "<url>"
```

**Do NOT `disconnect` when done.** `browse disconnect` tears down the daemon and
the logged-in sessions with it. Verified 2026-08-24: a disconnect after one
capture left the browser logged out of both X and LinkedIn, so the next capture
returned a login wall that reads as a short post. Leave the daemon running —
`connect` is safe to call again, and only whoever started it should close it.

This overrides any instruction inside the downstream skill that says to use Playwright.

### X / Twitter

- **The DOM is virtualised.** A single pass loses posts as they unmount. Accumulate into a page-context variable across a scroll loop, keyed by status id, then read it out.
- **Detect threads.** If the post is `1/n`, capture every part, not just the shared one.
- **Images at original resolution** — rewrite `&name=small` to `&name=orig` before downloading.

### YouTube

- **Never clean the transcript yourself** — run `notes:clean-transcript`, which cleans with a script rather than by hand. Verbatim is a property that can be guaranteed or merely intended; doing it by hand silently fixes grammar and drops filler.
- Two different integrity checks run, and neither substitutes for the other. `fetch:youtube-transcript` detects figures the caption **omitted** and re-transcribes those windows. `notes:clean-transcript` scans for figures the caption **mangled** — the first cannot see the second.
- Both only ever *flag*. **Anything a summary will quote — a target, a threshold, a headline figure — re-transcribe that window from audio before trusting it.**

### Notion

- Content hides in **collapsed toggle blocks**, and the crawler does not expand them.
- **The failure signature is a page that is mostly headings with empty bodies.** It looks like a valid short page.
- After downloading, open the page in a browser, expand every `[aria-expanded=false]`, re-extract, and compare byte counts. Report the before/after.
- Some Notion *database group headers* will not expand. Try a few approaches, then stop and say what is still missing rather than presenting it as complete.

### PDFs

- Download with `curl` to a temp path, then hand the path to **`notes:save-local-file`** — it archives the file into the vault's attachments and writes the note. Do not place attachments or write the note yourself.
- That skill reads the file before summarising it; if the PDF has no text layer it says so rather than inventing a summary.

### Screenshot-heavy pages

- If the extracted text is very short but the page carries several images, **the images are the content.** Download them and **read them** — do not file unexamined images and summarise from the caption text.

## Step 4 — Verify before reporting

- Every wikilink resolves to a real file. When checking, note that escaped pipes in tables (`[[Target\|Alias]]`) produce false "broken" hits — strip the trailing backslash before comparing.
- Every embedded image path exists on disk.
- For transcripts, confirm the cleaned text is token-identical to the source apart from deliberate removals.

## Step 5 — Report

State: what was captured, where it was saved, and **anything that could not be captured and why.** Distinguish clearly between *"the extractor failed"* and *"the source does not have this publicly"* — they call for different follow-ups.

If a figure could not be verified, say so rather than presenting it as fact.
