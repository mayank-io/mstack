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
| `youtube.com`, `youtu.be` | `fetch:youtube-download` | `youtube.md` (+ channel override) |
| `x.com`, `twitter.com` | `fetch:x-post` | `x.md` |
| `linkedin.com` | `fetch:linkedin-post` | `linkedin.md` |
| `*.notion.site`, `notion.so` | `fetch:notion-public-site` | `notion.md` |
| `scribd.com` | `fetch:scribd-document` | `article.md` |
| `alphaxiv.org`, `arxiv.org` | `fetch:alphaxiv-paper` | `paper.md` |
| `pubmed.ncbi.nlm.nih.gov`, `ncbi.nlm.nih.gov/pmc` | `fetch:pubmed-nlm` | `paper.md` |
| `instagram.com` | `fetch:ig-post` | `article.md` |
| PDF (any host, incl. Drive/Dropbox) | `curl` → `notes:save-local-file` | — |
| anything else | `fetch:blog-post` | `article.md` |

The fallback goes to **`fetch:blog-post`**, not `obsidian:defuddle`. `blog-post` uses Defuddle internally *and* recovers the lazy-loaded images Defuddle drops, digitizes embedded Vedic charts via `fetch:vedic-chart`, and emits the same `OUTPUT_DIR:` contract as every other route. Routing straight to `defuddle` skips all of that and reaches outside this marketplace for a capability we already own.

**Every route is the same six steps.** There is no per-source skill, and there should never be one — what varies between sources is output shape, and shape lives in `templates/`.

**Templates live at the plugin root — `${CLAUDE_PLUGIN_ROOT}/templates/` — not beside this skill.** There is no `skills/clip/templates/`; a path resolved relative to this file finds nothing.

```
1. route on host        ──▶  fetch:<source>          (curl, for PDF)
2. read its OUTPUT_FILE: / OUTPUT_DIR: final line     — Step 2
3. select ${CLAUDE_PLUGIN_ROOT}/templates/<source>.md, and …/templates/channels/<name>.md if one matches
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

## Step 2.6 — The clip invariant: the source goes in the note, verbatim

**A clip is an archive of the source. A note that contains only your reading of the source is not a clip and must not be written as one.**

This is a routing-level guarantee, not a matter of shape — shape lives in `templates/`. The invariant is that the captured artefact **reaches the note**:

1. **The summary sits above the source.** A reader who stops after the first screen gets the gist.
2. **The source itself is reproduced next, verbatim** — full transcript, full post text, full article body. Cleaned per `notes:clean-transcript`, never condensed, never paraphrased, never excerpted down to the parts you found interesting.
3. **Your own analysis — verification, critique, scoring, reconciliation — comes last, after the source, under its own heading.** It is clearly separable from the source and never interleaved with it.

**Why the order is fixed:** the transcript is the durable asset and the only part that cannot be regenerated later. Analysis is cheap and revisable; a source you failed to archive is gone when the video is delisted or the post is deleted. Putting analysis first also lets a thin capture masquerade as a thorough one — the note looks substantial while containing nothing that was actually said.

**Two failure modes this exists to stop, both of which have happened:**

- **Analysis-only note.** A long, well-structured note of themes, verification and critique, with the source never archived. It reads as complete and is unrecoverable.
- **Quote-mining.** Reproducing only the three or four lines the analysis argues about. The reader cannot check context, and a claim you skipped cannot be revisited.

**Gate, enforced in Step 4:** if the note does not contain the source verbatim, do not report the clip as done. Say what failed to extract and why. **An honest "extraction failed" is worth more than a note that looks finished.**

If the source genuinely has no reproducible body — a paywalled article, a video with captions disabled and audio unavailable — say that in the note, in place of the transcript, and set the reading fields accordingly. **Do not silently substitute your summary for the thing you could not get.**

🔴 **Capture everything you *can* get, though.** A body you cannot reproduce does not make the rest of the page unavailable: **harvest the images, the headline, deck, byline, date, chart source lines and every figure cited**, and say explicitly in the note which single part is missing and why. Degrading the whole clip because one component is restricted is the failure mode to avoid.

## Step 3 — Apply the per-source overrides

These are non-negotiable and exist because each one has already caused a bad capture.

### All browser-based sources (X, LinkedIn)

**Use gstack browse, never a fresh Playwright session.** The user is logged into their accounts there; a fresh Playwright session hits login walls and silently returns logged-out content.

```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" connect          # run from the vault directory — a different cwd spawns a second daemon and kills the headed session
"$B" goto "<url>"
```

**Run `$B` outside the command sandbox.** Inside it, `$B status` reports `Headed server running (PID …) but not responding` for a daemon that is healthy — the sandbox blocks the connection, not the daemon. Re-run `status` unsandboxed before force-restarting anything.

**Do NOT `disconnect` when done.** `browse disconnect` tears down the daemon and
the logged-in sessions with it. Leave it running — the daemon is a shared user
resource, `connect` is safe to call again, and only whoever started it should
close it.

This overrides any instruction inside the downstream skill that says to use Playwright.

### X / Twitter

- **The DOM is virtualised.** A single pass loses posts as they unmount. Accumulate into a page-context variable across a scroll loop, keyed by status id, then read it out.
- **Detect threads.** If the post is `1/n`, capture every part, not just the shared one.
- **Images at original resolution** — rewrite `&name=small` to `&name=orig` before downloading.

### YouTube

- **Route through `fetch:youtube-download`. Always.** Do not hand-roll `yt-dlp`, do not scrape `--write-auto-sub` VTT yourself, do not call Whisper directly. That skill already handles the client fallbacks, the caption-omission detection and the re-transcription windows; a hand-rolled pull silently skips all of it and produces a transcript that looks fine.
- **`fetch:*` skills are the only sanctioned extractors.** If you find yourself reaching for `curl`, `yt-dlp` or a browser to get content a `fetch:*` skill already covers, stop — you have left the routing table, and everything downstream of that point is unverified by the pipeline.
- **Never clean the transcript yourself** — run `notes:clean-transcript`, which cleans with a script rather than by hand. Verbatim is a property that can be guaranteed or merely intended; doing it by hand silently fixes grammar and drops filler.
- Two different integrity checks run, and neither substitutes for the other. `fetch:youtube-download` detects figures the caption **omitted** and re-transcribes those windows. `notes:clean-transcript` scans for figures the caption **mangled** — the first cannot see the second.
- Both only ever *flag*. **Anything a summary will quote — a target, a threshold, a headline figure — re-transcribe that window from audio before trusting it.**

### Notion

- Content hides in **collapsed toggle blocks**, and the crawler does not expand them.
- **The failure signature is a page that is mostly headings with empty bodies.** It looks like a valid short page.
- After downloading, open the page in a browser, expand every `[aria-expanded=false]`, re-extract, and compare byte counts. Report the before/after.
- Some Notion *database group headers* will not expand. Try a few approaches, then stop and say what is still missing rather than presenting it as complete.

### PDFs

- Download with `curl` to a temp path, then hand the path to **`notes:save-local-file`** — it archives the file into the vault's attachments and writes the note. Do not place attachments or write the note yourself.
- That skill reads the file before summarising it; if the PDF has no text layer it says so rather than inventing a summary.

### 🔴 Images are part of every clip — not an extra

**Whenever a page is read in a browser, harvest its images in the same pass.** Text extraction does not carry them, and coming back for them later means the user had to ask. A clip that quotes a chart's numbers but does not embed the chart is incomplete.

```javascript
// run against the open tab, after the page has settled
const a = document.querySelector('article') || document.body;
[...new Set([...a.querySelectorAll('img')].map(i => {
  let u = i.currentSrc || i.src || '';
  const ss = i.getAttribute('srcset');
  if (ss) { const p = ss.split(',').map(s => s.trim().split(' ')[0]).filter(Boolean);
            if (p.length) u = p[p.length - 1]; }          // widest variant
  return { u, w: i.naturalWidth || i.width || 0 };
}).filter(o => o.u && o.w >= 200).map(o => o.u))]           // drop icons and avatars
```

- **Take the widest `srcset` variant**, not `img.src`. News sites ship 5+ widths of the same asset; `src` is usually the smallest. Publisher chart URLs often encode the width (`…_300px.jpg` … `…_700px.jpg`) — take the largest.
- **Download to the vault's `attachments/`, embed with a relative path, and verify the file exists** (Step 4 already requires this).
- **Read the images you download.** A chart's content is in the picture; transcribe the figures you rely on and check them against the body text.
- **This applies even when the body cannot be reproduced.** A paywalled or rights-restricted article still gets its charts archived — the images are frequently the most re-usable part, and they are what makes the note useful later. **Not reproducing the prose is never a reason to skip the images.**

## Step 4 — Verify before reporting

- Every wikilink resolves to a real file. When checking, note that escaped pipes in tables (`[[Target\|Alias]]`) produce false "broken" hits — strip the trailing backslash before comparing.
- **Images were harvested, not skipped.** Every embedded image path exists on disk — and if the page had images and the note has none, that is a failed clip, not a stylistic choice. Say so rather than reporting success.
- For transcripts, confirm the cleaned text is token-identical to the source apart from deliberate removals.
- **The note contains the source verbatim** (Step 2.6). Check the body, not your intention to have written it: a transcript section that is absent, truncated, or replaced by a summary is a failed clip. Report it as such rather than reporting success.
- **Analysis is below the source, under its own heading**, and no analytical aside has been interleaved into the transcript.

## Step 5 — Report

State: what was captured, where it was saved, and **anything that could not be captured and why.** Distinguish clearly between *"the extractor failed"* and *"the source does not have this publicly"* — they call for different follow-ups.

If a figure could not be verified, say so rather than presenting it as fact.
