---
name: clip
description: "Clip a URL into the notes vault — route it to the right extractor and note-writer based on source type. Use when the user says \"clip this\", \"clip <url>\", \"save this to my vault\", \"add this to clippings\", or shares a URL and wants it captured as a note. Handles X/Twitter, YouTube, LinkedIn, Notion sites, PDFs, and general web pages."
---

# Clip

Route a URL to the correct extraction skill and note-writer. **This skill is a router. It does not format notes and does not know vault conventions** — the downstream skill owns that.

## Input

The user provided: `$ARGUMENTS` — a URL, optionally followed by extra instructions (e.g. "tag it to project X", "capture with the edge-idea tag"). **Pass extra instructions through to the downstream skill and honour them after it returns.**

## Step 1 — Identify the source

Match on the URL's host and path.

| Source | Route to | Writes the note? |
|--------|----------|------------------|
| `x.com`, `twitter.com` | `x-to-obsidian:save` | ✅ yes |
| `youtube.com`, `youtu.be` | `youtube-to-obsidian:process` | ✅ yes |
| `linkedin.com` | `linkedin-to-obsidian:save` | ✅ yes |
| `*.notion.site`, `notion.so` | `download:notion-public-site` | ❌ extract only |
| `scribd.com` | `download:scribd-document` | ❌ extract only |
| `alphaxiv.org`, `arxiv.org` | `download:alphaxiv-paper` | ❌ extract only |
| PDF (any host, incl. Drive/Dropbox) | `curl` + Read tool | ❌ extract only |
| anything else | `obsidian:defuddle` | ❌ extract only |

**When the route writes the note (✅):** invoke it and let it own everything — filename, frontmatter, folder, daily-note update, tags. Do not second-guess its output format.

**When the route only extracts (❌):** extract first, then invoke `obsidian-note-creator:create` to write the note. That skill owns the vault conventions; you supply title and content.

If a required skill is not installed, **say so and stop.** Do not silently half-finish with a partial extraction.

## Step 2 — Apply the per-source overrides

These are non-negotiable and exist because each one has already caused a bad capture.

### All browser-based sources (X, LinkedIn)

**Use gstack browse, never a fresh Playwright session.** The user is logged into their accounts there; a fresh Playwright session hits login walls and silently returns logged-out content.

```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" connect          # run from the vault directory — a different cwd spawns a second daemon and kills the headed session
"$B" goto "<url>"
"$B" disconnect       # when done
```

This overrides any instruction inside the downstream skill that says to use Playwright.

### X / Twitter

- **The DOM is virtualised.** A single pass loses posts as they unmount. Accumulate into a page-context variable across a scroll loop, keyed by status id, then read it out.
- **Detect threads.** If the post is `1/n`, capture every part, not just the shared one.
- **Images at original resolution** — rewrite `&name=small` to `&name=orig` before downloading.

### YouTube

- `caption_warnings` detects **omitted** numbers only. It cannot see a **corrupted** one.
- Always run a corruption scan on the cleaned transcript: tokens mixing letters and digits (`$und00`, `a,50`), a currency symbol not followed by a digit, `%` with no preceding digit.
- Anything a summary will quote — a target, a threshold, a headline figure — **re-transcribe that window with Whisper** before trusting it.

### Notion

- Content hides in **collapsed toggle blocks**, and the crawler does not expand them.
- **The failure signature is a page that is mostly headings with empty bodies.** It looks like a valid short page.
- After downloading, open the page in a browser, expand every `[aria-expanded=false]`, re-extract, and compare byte counts. Report the before/after.
- Some Notion *database group headers* will not expand. Try a few approaches, then stop and say what is still missing rather than presenting it as complete.

### PDFs

- Download with `curl` and **archive the file** into the vault's attachments folder — the link will rot.
- Check for a text layer first (`pdftotext`); fall back to the Read tool's `pages:` parameter only if there isn't one.

### Screenshot-heavy pages

- If the extracted text is very short but the page carries several images, **the images are the content.** Download them and **read them** — do not file unexamined images and summarise from the caption text.

## Step 3 — Verify before reporting

- Every wikilink resolves to a real file. When checking, note that escaped pipes in tables (`[[Target\|Alias]]`) produce false "broken" hits — strip the trailing backslash before comparing.
- Every embedded image path exists on disk.
- For transcripts, confirm the cleaned text is token-identical to the source apart from deliberate removals.

## Step 4 — Report

State: what was captured, where it was saved, and **anything that could not be captured and why.** Distinguish clearly between *"the extractor failed"* and *"the source does not have this publicly"* — they call for different follow-ups.

If a figure could not be verified, say so rather than presenting it as fact.
