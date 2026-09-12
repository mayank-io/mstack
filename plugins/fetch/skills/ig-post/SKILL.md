---
name: ig-post
description: "Extract an Instagram reel or post — caption, author, metrics, images — and download the video, then transcribe its audio so the spoken content is captured, not just the caption. Use when the user says \"clip this reel\", \"what does this instagram post say\", \"download this reel\", \"transcribe this reel\", or shares an instagram.com/reel/, /p/, or /tv/ URL."
---

# Fetch Instagram Post

Pull an Instagram reel or post — caption, author, metrics, media — into a directory, and **transcribe the audio**. This skill knows nothing about vaults; it retrieves and stops. `notes:clip` turns the result into a note.

## The one thing that makes this skill necessary

**On a reel, the caption is not the content.** A 90-second talking-head reel carries its argument in the audio; the caption is a teaser ending in "comment INFLUENCE below". Capturing the caption and stopping produces a note that looks complete and contains none of the substance. **Always transcribe.**

## Input

- **First argument** — Instagram URL (required): `instagram.com/reel/<id>`, `/p/<id>`, or `/tv/<id>`. Strip `?igsh=…` share params.
- **Second argument** — output directory (optional). Omitted, a temp directory is used. Created if missing. **Never write outside it.**

## Step 1 — The browser must be gstack, and logged in

Instagram shows a login wall to logged-out sessions. Critically, **the wall still renders the author, caption and metrics in the OpenGraph tags**, so a logged-out capture yields a plausible-looking result with no video and no transcript. That is the failure this skill exists to prevent.

```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" status                     # must report `mode: headed`
"$B" connect --force-restart    # only if it does not
```

Then confirm the Instagram session specifically — `headed` is necessary but not sufficient, because the user can be logged into X and not Instagram:

```javascript
() => ({
  loggedIn: !!document.querySelector('svg[aria-label="Home"], a[href="/direct/inbox/"]'),
  loginWall: /Log in|Sign up/i.test(document.body.innerText.slice(0, 400))
})
```

If `loggedIn` is false, **stop and ask the user to log in inside the gstack browser**, then poll until they have. Do not fall back to a logged-out capture.

⚠️ **Do NOT `disconnect` when done** — it tears down the daemon and the user's sessions with it.

## Step 2 — Metadata from OpenGraph, not the DOM

Instagram's rendered DOM is obfuscated and changes often. The `og:` tags are server-rendered, stable, and carry everything needed:

```javascript
() => {
  const og = {};
  document.querySelectorAll('meta[property^="og:"]').forEach(m =>
    og[m.getAttribute('property')] = m.getAttribute('content'));
  const v = document.querySelector('video');
  return { og, duration: v ? v.duration : null, poster: v ? v.poster : '' };
}
```

| Field | Where |
|---|---|
| author handle + display name | `og:title` — `"DAVID IMONITIE on Instagram: \"…\""` |
| full caption | `og:title` / `og:description` (**longer than the visible caption — it is not truncated**) |
| likes, comments, **date** | `og:description` — `"154K likes, 1,846 comments - davidimonitie on May 25, 2026: …"` |
| canonical URL (reveals the author slug) | `og:url` |
| thumbnail | `og:image` |
| duration | the `<video>` element, not the meta tags |

**Cross-check the date against the on-page `<time datetime>`.** They disagree on edited posts — one is the original publication, the other the edit. Record both and say which is which rather than picking one silently.

## Step 3 — Download the video (the part that has three dead ends)

The `<video>` element's `src` is a `blob:` URL and cannot be fetched. Instagram streams DASH, so there is no `video_url` in the page scripts and no `.mp4` in the resource log — only thumbnails and avatars. **Do not spend time scraping for a media URL; there isn't one.**

Use `yt-dlp`, but it needs the *gstack profile's* cookies. All measured 2026-09-12 on a logged-in session:

| Attempt | Result |
|---|---|
| `yt-dlp <url>` | `login required` |
| `yt-dlp --cookies-from-browser chrome` | `login required` — reads Chrome's **default** profile; gstack uses its own |
| `yt-dlp --cookies-from-browser chrome:~/.gstack/chromium-profile` | `login required` — the cookie DB is encrypted and locked while the browser runs |
| **`browse cookies` → Netscape → `--cookies FILE`** | ✅ **downloads** |

So:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gstack_cookies.py" "$OUT/cookies.txt" instagram
yt-dlp --cookies "$OUT/cookies.txt" --no-progress \
       -o "$OUT/%(id)s.%(ext)s" --write-info-json "$URL"
```

`--write-info-json` is worth it: it carries `like_count`, `comment_count`, `timestamp` and `duration` as structured values, which beats parsing `"154K likes"` out of prose.

**`cookies.txt` holds a live session token.** The script writes it `0600`. Delete it when finished, and never copy it into the vault or a repo.

## Step 4 — Transcribe

```bash
ffmpeg -nostdin -loglevel error -y -i "$OUT/<id>.mp4" -vn -ac 1 -ar 16000 "$OUT/<id>.wav"
whisper "$OUT/<id>.wav" --model medium.en --language en \
        --output_dir "$OUT" --output_format txt --verbose False
```

- `medium.en` is the floor for this material. Reels are loud, music-backed and fast; `base`/`small` drop numbers and brand names — exactly the tokens a note will quote.
- Whisper on a ~90s clip runs past a 120s tool timeout on CPU. **Run it in the background** and collect the result, rather than letting the call die and re-running it.
- Transcribe **every** reel, including short ones. A 19-second reel is still 60+ words that exist nowhere else.
- Whisper invents text over silence and music stings. Check the transcript against the caption's topic before trusting it; if a reel is music-only with on-screen text, say the audio carried no speech instead of filing a hallucinated paragraph.

## Step 5 — On-screen text

Reels often carry burnt-in captions or a list that is never spoken. When the transcript is short relative to the duration, sample frames and read them:

```bash
ffmpeg -nostdin -loglevel error -i "$OUT/<id>.mp4" -vf fps=1/3 "$OUT/frame-%02d.jpg"
```

Then open the frames. As with `fetch:linkedin-post`, **if the body is thin and there is an image, the image is the content.**

## Step 6 — Report

Write the extracted fields as JSON alongside the media, then print the directory as the **final stdout line**:

```
OUTPUT_DIR:/absolute/path/to/output
```

The marker must be last. Callers chain on it and must never reconstruct the path.

Report the transcript's word count and the video duration together — a 90-second reel that produced 12 words means the transcription failed, and that is invisible from the transcript alone.

## Failure modes worth naming

- **A caption-only capture** — the signature is a note with no transcript and a `duration` field. It reads as complete. This is the default failure if Step 3 is skipped.
- **`login required` from yt-dlp while the browser is clearly logged in** — you used the wrong cookie jar. See the table in Step 3.
- **A confident transcript of a silent video** — Whisper hallucinating over music. Cross-check against the caption.
- **`og:description` and `<time datetime>` disagreeing** — an edited post, not a bug. Record both.
- **Rate limiting** — Instagram throttles aggressively. Space out consecutive fetches; do not retry in a tight loop.
