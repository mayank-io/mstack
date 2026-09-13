---
name: x-post
description: "Extract content from an X/Twitter post, thread, or article using the gstack browser. Runs the tested download unit, which detects threads, walks back to the first post when the shared link lands mid-thread, downloads images at original resolution, and writes a Markdown note. Use when the user says \"read this x post\", \"get content from this tweet\", \"what does this x post say\", \"extract this tweet\", \"get the whole thread\", or shares an x.com/twitter.com URL."
---

# Download X Post

Capture an X/Twitter post or thread — text, metrics, images — through the user's logged-in **gstack browser**, and write it to a Markdown note.

**This skill owns no extraction code.** The DOM logic is [`references/extraction.js`](references/extraction.js); the orchestration is `${CLAUDE_PLUGIN_ROOT}/scripts/`. Both are tested, and both are shared with the x-account bulk harvester. Do not re-implement either here — a second copy drifts from the tested one, and the drift surfaces as a capture that looks fine and is missing half the thread.

## Browser — always gstack, never headless

Browser work goes through the **gstack browser**, which holds the user's logged-in sessions. A fresh Playwright instance is logged out: it silently returns login walls or truncated content that looks like a successful capture.

```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" connect        # run from the target directory — another cwd spawns a second
                    # daemon and kills the headed session
"$B" goto "<url>"
"$B" js '<expression>'
```

**The daemon must be in `headed` mode.** `browse status` reports either `headed` (attached to the user's real Chrome, carrying their logins) or `launched` (gstack's own Chromium on a fresh profile, logged into nothing). A `launched` daemon returns a login wall for every gated page, and a login wall reads as a *short page* rather than an error — nothing downstream will flag it. Verify the mode, and force a restart when it is wrong:

```bash
"$B" status                     # must report `mode: headed`
"$B" connect --force-restart    # only when it does not — a launched daemon holds a
                                # fresh profile with no logins, so nothing is lost
```

The `_browse.py` adapter runs this check inside `connect()` and refuses to continue if it cannot reach `headed`. Both entry points below go through it, so the check is automatic; do the same by hand when driving `$B` directly.

**Do NOT `disconnect` when done.** `browse disconnect` tears down the daemon and the logged-in sessions with it. Leave it running — the daemon is a shared user resource, `connect` is safe to call again, and only whoever started it should close it. The adapter's `close()` is deliberately a no-op, so leaving the `browse_page()` block tears down nothing.

**Never launch a headless browser.** Not `headless=True`, not `--headless`, not a fresh `chromium.launch()`. If gstack is unavailable, stop and say so rather than falling back — a logged-out capture is worse than no capture, because it looks fine.

**Page JavaScript must be synchronous, and values are passed as arguments.** `$B js` returns before a promise resolves, so `evaluate()` refuses any expression that is an `async` function or contains `await` — the result would be silently lost. Drive the waiting and looping from Python with `wait_for_timeout(ms)` between synchronous `evaluate()` calls. Pass values with `page.evaluate(js, arg)` rather than string-interpolating them into the JavaScript: an interpolated value containing a quote breaks the expression.

## Input

The user provided: `$ARGUMENTS`

- **First argument**: X/Twitter URL, of the form `https://x.com/{handle}/status/{id}` or `https://twitter.com/{handle}/status/{id}` (required).
- **Second argument**: output directory (optional, defaults to the current working directory).

Anything that is not a status URL — a profile, a search, a bare id — is refused by the script before the browser moves, because a profile page would extract whatever tweet happens to be pinned at the top and that reads as a successful capture of the wrong post.

## Step 1 — Capture the post or thread

One command does the whole capture:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/xpost_download.py "<url>" [out_dir]
```

**IMPORTANT:** run this via the Bash tool with `timeout: 300000` (5 minutes). A long thread scrolls up to 14 ticks with a dwell between each, plus a second page load when the link turns out to be mid-thread.

What it does, in order:

1. Opens the **gstack browser** in headed mode via `_browse.sync_browse_page()` — never a headless or freshly launched one.
2. Navigates to the URL and waits for `article`.
3. Injects `references/extraction.js` and calls `findRoot()`. If the shared link is mid-thread, it re-navigates to the root and restarts from there.
4. Scrolls the conversation, unioning same-author posts on **every** tick, and clusters them into the genuine thread.
5. Downloads up to 4 images per post with `curl`, at original resolution.
6. Renders one Markdown note (YAML frontmatter, thread posts as inline `n/N` markers) and prints the path.

What it writes, under `<out_dir>`:

| Path | Contents |
|---|---|
| `<handle>/posts/<date> @<handle> - <slug>.md` | the note — frontmatter (`source`, `author`, `date`, `status_id`, `post_type`, `thread_length`, `likes`, `reposts`, `views`, `media`, and for a video post `media_type`, `video_duration`, `video_seconds`, `transcript: pending`) plus body |
| `<handle>/attachments/<handle>-<statusId>-<N>.jpg` | the images, referenced from the note as `![...](attachments/...)` |

**Output contract:** the **final stdout line** is `OUTPUT_FILE:<absolute path to the note>`. Progress goes to stderr. On failure the script exits non-zero and emits **no** `OUTPUT_FILE:` marker — a marker on a failed capture would send the caller off to summarise a note that was never written. Chain on that last line; do not guess the filename from the slug.

## Step 1.5 — Video posts

**A video post captured as its caption alone is not a capture.** The caption is the hook; the video is the content. This is the `notes:clip` Step 2.6 invariant — reproduce the source, then summarise it — applied to X, and it is the rule the earlier video clippings in the vault break by carrying a "not transcribed here" callout where the body should be.

### How you know

`xpost_download.py` detects video and reports it two ways:

| Signal | Where |
|---|---|
| `VIDEO_DETECTED:<status_url>\t<seconds>` | **stderr**, one line |
| `MEDIA_PREDATES_POST:<media_id>\t<n> days\tuploaded <date>` | **stderr**, when the video is older than the post |
| `media_type: video`, `video_duration`, `video_seconds`, `video_media_id`, `video_uploaded`, `transcript: pending` | the note's frontmatter |

`transcript: pending` is the debt marker. A note that still says `pending` is unfinished.

Duration comes from the play button's `aria-label` (`"Play Video. 53 minutes 35 seconds long"`) — the only place X renders one. **It is frequently absent.** On a cold load the player mounts as `<video aria-label="Embedded video">` and the duration is computed later, so a post reports `media_type: video` with **no** `video_seconds`. That means *unknown*, not *short*; take the duration from `yt-dlp -J` when you need it. GIFs are flagged `media_type: gif` and owe no transcript.

**The player mounts lazily.** X renders the `tweetPhoto` container first and hydrates the video into it a beat later; extracting in between reports a video post as having no video and produces a note that reads as a complete short text post. `extraction.js mediaReady()` is the gate and `x_extract.wait_for_media()` polls it — the same trap `imagesReady()` guards for images. This is not theoretical: the first capture of the post that motivated this step missed the video entirely.

### Transcribe it

The extractor cannot do this itself: it runs under a 5-minute Bash timeout and a 53-minute source will not fit. Run transcription as its own step, with `timeout: 1800000` (30 minutes) on the Bash call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/whisper_transcriber.py" \
  "<status_url>" --backend mlx --model large-v3-turbo --language auto
```

`--backend mlx` runs mlx-whisper through `uvx` (Apple Silicon; nothing to install). yt-dlp reaches X video **without cookies**, so transcription does not depend on the browser session even though the post capture does. The final stdout line is `OUTPUT_FILE:<path to JSON>`; chain on it.

Then run `notes:clean-transcript` on the result. **Never clean a transcript by hand** — that skill's verbatim invariant is enforced by a test, and an intention to stay verbatim is not.

### Check for a decoder loop before you trust it

Whisper conditions on its own output, and on long audio it can catch a phrase and emit it for the rest of the file. **The transcript still runs to the full duration and still reads as English**, so a length check, a coverage check and a spot-read of the opening all pass while the content is gone. The 53-minute lecture this step was written for lost its last 11 minutes to `"the crash of 1929"` repeated ~500 times.

The script flags this on stderr:

```
WARNING: 23 segment(s) look like a decoder repetition loop, first at 42:34.
Re-run with --no-condition-on-previous-text.
```

Do exactly that, and use `--audio <path>` so the source is not downloaded twice. `repetition_warnings` in the output JSON must be empty before the transcript goes into a note.

### Check who actually made the video

X shows the *poster*, not the author. Before attributing a re-upload:

```bash
yt-dlp -J "<status_url>" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['id'], d['duration'], d.get('description',''))"
```

**The strongest tell needs no network call at all.** The poster path carries the media id — `pbs.twimg.com/amplify_video_thumb/<media_id>/…` — and that id is a Snowflake, so it timestamps the upload exactly as a status id does. The script decodes it into `video_uploaded` and warns when the video is more than a day older than the post carrying it. On the post that motivated this step the gap was **10.1 days**, which no amount of reading the page would have revealed.

Two further tells:

- **The yt-dlp `id` differs from the status id in the URL** — the media was uploaded under a different post. (It matches the `video_media_id` above.)
- **A `t.co` link in the description resolves to another account's status with the same duration.** Resolve with `curl -sIL -o /dev/null -w '%{url_effective}' <t.co url>`; match duration to the centisecond, which is what makes it proof rather than a guess. Cross-check the other post's own `video_media_id`: identical ids are the same upload, not merely the same video.

When either fires, the poster is an amplifier. Credit the content to the original author and record the re-upload — a clipping that names the wrong author is worse than no clipping.

### Do not substitute a still

A final-frame screenshot is a supplement for a chart video, never a replacement for speech. A note whose "content" is one still has the same problem as a note that is only a caption.

## Step 2 — X Articles (long-form)

**The script does not cover X Articles, and it fails loudly rather than quietly.** A regular tweet has `[data-testid="tweetText"]`; an X Article does not, so extraction returns empty text for a 40,000-character essay and the script exits with `no content`. **Emptiness is the detection signal, not a result.**

When that happens, capture the article by hand with `extractLongform()` from the same `references/extraction.js` — see [Driving extraction.js directly](#driving-extractionjs-directly) for the harness. It returns `{body, headings, links, images}`.

**The body arrives as ONE block, and the headings are inside it.** This is the part that produces a mangled note if you assume otherwise. Measured on a real article (`saylor/2091923153542840808`, 43,261 characters):

| Assumption | Reality on a live article |
|---|---|
| Sequential paragraph elements | **1** `longformRichTextComponent`, 43,261 chars |
| `<p>` tags to iterate | **0** — X renders divs and `<br>`, no paragraph tags |
| Headings are separate from the body | **28 headings, all 28 also present inside the body text** |

So the heading list is an *index*, not content to concatenate. Appending headings to the body duplicates every one; rendering only the headings loses the entire article.

**Rebuild the structure by splitting the body on its own headings, in order:**

```python
pos, cur = [], 0
for h in headings:                       # document order
    i = body.find(h["text"], cur)
    if i == -1:
        continue                         # report it; do not silently drop
    pos.append((i, h)); cur = i + len(h["text"])

intro = body[:pos[0][0]].strip()
sections = [
    (h, body[i + len(h["text"]) : (pos[n+1][0] if n+1 < len(pos) else len(body))].strip())
    for n, (i, h) in enumerate(pos)
]
```

**Verify the split reassembles.** `len(intro) + sum(len(heading) + len(text))` should equal the body length to within trimmed whitespace. A heading that appears twice in the body, or a `find` that misses, silently drops a whole section otherwise — and the note still looks complete.

**Why not `"$B" snapshot`:** it returned **53,899 bytes** for this one article, and the accessibility tree flattens the heading/body relationship the split above depends on. The DOM carries the same content with the structure intact.

Preserve in the output: section headings with their level, the intro before the first heading, embedded links (a well-sourced article can carry 59 of them — worth keeping as a reference list), and image positions.

## Step 3 — Present the result

Read the note the script wrote (`OUTPUT_FILE:`) and summarise it for the user: author, date, engagement, whether it was a single post or an *n*-post thread, and how many images landed in `attachments/`. Quote the content rather than paraphrasing it when the user asked what the post *says*.

If the user wanted the content in conversation rather than on disk, present it as:

```
## @{handle} — {title or first line}{ (Thread: n posts) if a thread}

**Date:** {date}
**Engagement:** {likes} likes, {reposts} reposts, {views} views
**URL:** {original url}

---

{post content — for a thread, each post prefixed **i/n**}

---

**Images:** {count} downloaded
{list each filename}
```

## Where each failure mode is handled

Every one of these was a real, silently-wrong capture. They now live in code, not in prose here — this table says **where**, so a regression is fixed in the one place every consumer shares.

| Failure mode | Handled in | Why it is not obvious |
|---|---|---|
| **Thread virtualization** — articles unmount as they scroll out of the viewport, so a single pass after scrolling sees only the last screenful | `x_extract.collect_thread_posts` — unions same-author posts on **every** tick and stops when the union stops growing, not when the visible count stops changing | The capture succeeds and returns the tail of the thread |
| **Mid-thread links** — a shared link is frequently NOT the first post; people copy a middle or final post | `extraction.js findRoot()` reads the ancestor articles X renders ABOVE the focal one; `xpost_download.download_url` re-navigates to the root before capturing | Extracting from the focal post yields a coherent-looking note that starts at post 7/7 |
| **Same author ≠ same thread** — the author's replies to commenters render under the same handle | `x_threads.cluster` + `x_snowflake.same_thread` (30-minute Snowflake gap), plus `isReplyToOther` from `extraction.js` | The false positives are real posts by the right author; only the timestamp gap distinguishes them |
| **Image resolution** — `&name=small/medium/large` are downscales | `extraction.js` rewrites every `pbs.twimg.com/media` src to `name=orig` | A downscaled chart or screenshot is unreadable at exactly the point it matters, and nothing errors |
| **Images not yet loaded** — X mounts `<img alt="Image">` before the src is set | `extraction.js imagesReady()`, polled from the driver; `expectedImageCount` (from `a[href*="/photo/"]`) cross-checks the result | A four-image post extracts zero images and looks like a text-only post |
| **Video posts** — the caption is the hook, the video is the content | `extraction.js extractVideo()` sets `media_type`/`video_duration` and `transcript: pending`; [Step 1.5](#step-15--video-posts) transcribes | A 53-minute lecture captures as one sentence and reads as a complete short post |
| **Decoder repetition loops** — Whisper emits one phrase for the rest of the file | `whisper_transcriber.detect_repetition_loops()` warns on stderr; re-run with `--no-condition-on-previous-text` | The transcript runs the full duration and reads as English, so every coverage check passes while the content is gone |
| **Re-uploads** — X shows the poster, not the author | `yt-dlp -J` id/`t.co` cross-check in [Step 1.5](#step-15--video-posts) | The note credits the wrong person, and nothing on the page contradicts it |
| **X Articles** — no `tweetText` element at all | `extraction.js extractLongform()`, driven per [Step 2](#step-2--x-articles-long-form) | Extraction returns `""` for a 40k-character essay |
| **Arguments dropped into page JS** — until 2026-08-24 the adapter discarded `evaluate()` args | `_browse.evaluate()` applies them, and refuses an arrow that is not a parenthesised function literal | `focalId` arriving as `undefined` made the root walk report "not a thread" for every real thread |
| **A logged-out browser** | `_browse.connect()` refuses anything but `headed` mode | A login wall renders as a short page, not an error |

## Driving extraction.js directly

For debugging, for X Articles, or when you need a single value rather than a whole note. This is the **same** extractor the script runs — never paste its function bodies into this file or into a one-off snippet.

```python
import asyncio, json, pathlib, sys
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/scripts")
from _browse import browse_page

SRC = pathlib.Path("${CLAUDE_PLUGIN_ROOT}/skills/x-post/references/extraction.js").read_text()
# The file is a bare IIFE statement. The adapter wraps whatever it is given in
# JSON.stringify((...)), and a statement in that position is a syntax error —
# the injection would fail and leave the page with no extractor at all. Handing
# it a function literal makes the file a block body, which is legal in both drivers.
INJECT = "() => {\n" + SRC + "\nreturn typeof window.__xExtract;\n}"

async def main():
    async with browse_page() as page:                  # headed, carries the user's session
        await page.goto("THE_URL_HERE")
        await page.wait_for_selector("article", timeout=15000)
        assert await page.evaluate(INJECT) == "object"  # injection took

        for _ in range(15):                             # poll up to 7.5s for media
            if await page.evaluate("() => window.__xExtract.imagesReady()"):
                break
            await page.wait_for_timeout(500)

        focal = await page.evaluate("() => window.__xExtract.extractFocal()")
        print(json.dumps(focal, indent=2))

asyncio.run(main())
```

Replace `THE_URL_HERE` with the actual URL. The exported functions:

| Call | Returns |
|---|---|
| `window.__xExtract.extractFocal()` | the first `<article>` on the page: `{statusId, handle, displayName, content, timestamp, metrics, expectedImageCount, images}` |
| `window.__xExtract.extractArticle(node)` | the same shape for a specific `<article>` element |
| `window.__xExtract.extractVideo(node)` | `{present, isGif, durationLabel, seconds, poster}`, or `null` when the post has no video |
| `window.__xExtract.extractAllByAuthor(h)` | every same-author article currently in the DOM, full content, plus `isReplyToOther`, sorted by Snowflake id |
| `window.__xExtract.findRoot(f, h)` | `{hasEarlier, rootId, ancestors}` for focal id `f` and handle `h` |
| `window.__xExtract.detectThreadMembers(h)` | same-author candidates as `{statusId, snippet, isReplyToOther}` — filtering to the genuine chain is the caller's job |
| `window.__xExtract.extractLongform()` | X Article: `{body, headings, links, images}`, or `{error: 'not an article'}` |
| `window.__xExtract.imagesReady()` | `true` once every `img[alt="Image"]` has a real `pbs.twimg.com` src |

Two rules when calling these:

- **Parenthesise arrow parameters.** `(h) => window.__xExtract.extractAllByAuthor(h)` — the adapter only applies arguments to a recognised function literal, and `h => …` is rejected rather than silently losing the handle. An author filter matching nobody returns zero posts, not an error.
- **Pass values as arguments, never by interpolation.** `await page.evaluate(js, handle)`, not an f-string — a handle containing a quote breaks the expression.

**Robustness — ancestors can lazy-load.** If `findRoot` reports `hasEarlier: false` but the post looks like a continuation (starts mid-sentence or with "And"/"But", opens with a list marker, or shows a "Show this thread" affordance), scroll UP a few times and re-check:

```python
for _ in range(5):
    await page.evaluate("() => window.scrollBy(0, -window.innerHeight)")
    await page.wait_for_timeout(800)
```

The wait cannot live in page JS — `$B js` returns before a promise resolves, so an in-page `await sleep()` loses the result silently.

## Using the download unit from Python

`xpost_download` is a library as well as a CLI. Given a page already sitting on a post, capture it without re-navigating:

```python
xpost_download.download_open_post(page, handle, out_dir, day, download_media=True)
```

It returns `{note, fname, status_id, root_id, is_thread, post_count, media, author_name, date, member_ids}`, or `{"error": ...}`. `page` must be a **sync**-shaped page — `_browse.sync_browse_page()` gives you one over gstack. This is the seam the x-account bulk harvester uses: `scripts/xaccount_iterate.py <handle> <out_dir> <max_posts>` scrolls a profile, Cmd+Clicks each post into a new tab, and hands the tab to `download_open_post`. Note that the iterator currently drives its **own** Playwright profile at `~/.claude/x-playwright-profile` rather than gstack, so it is not covered by the headed-mode guarantee above; prefer this skill's CLI for single posts.

## Tips

- X blocks direct HTTP fetching — a real browser is required, and it must be the gstack one. A logged-out browser returns a login wall that looks like an empty post rather than an error.
- Status IDs are Snowflake-based: ascending order is chronological, and posts written in one sitting have near-adjacent ids. That is what the 30-minute gap in `x_snowflake.same_thread` keys on.
- Thread posts rendered in the conversation view can be truncated; the extractor reads each article's own `tweetText`, and `extractAllByAuthor` collects them from the conversation page rather than by navigating to every status URL (which looks robotic).
- Re-running the script overwrites the note for the same post; images already downloaded are re-fetched.
- If the capture comes back with fewer posts than the thread visibly has, the usual cause is the scroll budget (`collect_thread_posts(..., scrolls=14)`), not the extractor.

## Examples

```bash
# Single tweet, note written under the current directory
/fetch:x-post https://x.com/elonmusk/status/123456

# Thread, into a specific directory
/fetch:x-post https://x.com/bourboncap/status/2020489596505592084 ./captures
```

- **Mid-thread link** — `https://x.com/ericjackson/status/1997633594659836065` is post 7/7. `findRoot` finds 6 earlier same-author posts above the focal one, the script re-navigates to `…633559859790018` ("…here's the truth 👇"), and the note contains the genuine 7-post thread in order. The author's later replies to commenters, which sit after a large Snowflake gap, are excluded.
- **X Article** — `https://x.com/0xMovez/status/2004570871294239187` exits with `no content` because there is no `tweetText`. Fall back to [Step 2](#step-2--x-articles-long-form).
