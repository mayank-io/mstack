---
name: youtube-download
description: "Download a YouTube video's transcript and metadata using the gstack browser session, and its on-screen slides when the speaker points at them. Use when the user shares a youtube.com or youtu.be URL and wants the transcript, video metadata, chapters, speakers or slides."
---

# Download YouTube

Extract the transcript and metadata from a YouTube video. The script tries three tiers in order: `youtube_transcript_api` (no browser), the gstack browser's transcript panel, then Whisper over the audio.


## Browser — always gstack, never headless

Browser work goes through the **gstack browser**, which holds the user's logged-in
sessions. A fresh Playwright instance is logged out: it silently returns login walls
or truncated content that looks like a successful capture.

```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" connect        # run from the target directory — another cwd spawns a second
                    # daemon and kills the headed session
"$B" goto "<url>"
"$B" js '<expression>'
```

**Do NOT `disconnect` when done.** `browse disconnect` tears down the daemon and
the logged-in sessions with it. Leave it running — the daemon is a shared user
resource, `connect` is safe to call again, and only whoever started it should
close it.

**Never launch a headless browser.** Not `headless=True`, not `--headless`, not a
fresh `chromium.launch()`. If gstack is unavailable, stop and say so rather than
falling back — a logged-out capture is worse than no capture, because it looks fine.

## Configuration

There is nothing to configure. The browser tier drives the gstack daemon, which
supplies the session; the script does not launch a browser or manage a profile
of its own.

`--profile` and `--headless` are still accepted so older call sites keep
working, but both are ignored and the script says so on stderr. There is no
longer a `chrome_profile_path` or `headless` setting to read.

## YouTube sign-in

The transcript comes out of whatever session the headed daemon holds — the
user's own Chrome. If that session is not signed in to YouTube, the script
prints a warning and continues: public videos are unaffected, but a
members-only or age-gated one renders a watch page with **no "Show transcript"
button**, which looks exactly like a video that has no captions. When you see
that warning and the extraction comes back empty, the fix is to sign in to
YouTube in Chrome — not to conclude the video has no transcript.

## Usage

Parse the YouTube URL from `$ARGUMENTS`. The URL can be in various formats:
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://youtube.com/watch?v=VIDEO_ID`

## Execution

Run the extraction script:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/youtube_downloader.py" "<URL>"
```

Do not pass `--profile` or `--headless`; both are ignored.

**Important:** The script writes the transcript JSON to a file and prints its path as the **final stdout line**, prefixed per the skill contract:

```
OUTPUT_FILE:/var/folders/.../yt_transcript_abc123.json
```

Strip the prefix before using it — do not consume the whole line as a path:

```bash
last=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/youtube_downloader.py" \
         "https://youtube.com/watch?v=abc123" | tail -1)
case "$last" in
  OUTPUT_FILE:*) json="${last#OUTPUT_FILE:}" ;;
  *) echo "extractor did not emit a result line — stop and report it"; exit 1 ;;
esac
```

Then read the JSON from `$json`. Earlier stdout lines are progress output and caption-integrity warnings; only the last line is the contract.

## Caption verification — recovering dropped figures

YouTube auto-captions silently drop words, disproportionately **numbers in Q&A** — a CEO answering "what percentage of revenue is defense?" with "about 60%", where the caption ate the "60%". Reasoning from the lossy caption produces confidently-wrong summaries.

The extractor detects this and emits `caption_warnings` (see below). **Remediation lives here, in this skill** — recovering a figure the caption dropped is getting the content *correctly*, which is retrieval, not shaping. Callers must not locate the verify script themselves.

If `caption_warnings` is non-empty, re-transcribe those windows from the audio. Pass every window in one call — the script downloads the audio once via the android client (which bypasses YouTube's DRM/SABR wall), clips each window with ffmpeg, and Whispers it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_caption_window.py" "<URL>" \
  --windows 686-718,1204-1230 --model small
```

It prints `{"windows": [{"start", "end", "text"}]}`.

Reconcile each `text` against the native transcript for that window. When Whisper contains a figure the caption lacks — the common case — **splice the recovered words into the raw transcript** so the correction flows into everything downstream. Report each recovery to the user; never silently rely on the caption for a flagged window.

If `whisper`, `yt-dlp` or `ffmpeg` is unavailable, **do not guess the figure.** Keep the caption text and tell the user the window could not be verified.

⚠️ `caption_warnings` detects **omitted** numbers only. It cannot see a **corrupted** one (`$und00` for `$1,050`, `a,50` for `1,050`). That scan belongs to the cleaning step.

## Slides — on-screen material

A transcript cannot carry a slide. When the speaker says "this is my screenshot" or "as you can see", the content is on screen, and a note without the picture is missing it.

### When to extract

| Condition | Extract? |
|---|---|
| `slide_cues` in the transcript JSON is non-empty | **yes** |
| the matching channel template declares `slides: always` | **yes**, even with no cues |
| the matching channel template declares `slides: never` | no |
| no cues and no channel setting | no |

`slide_cues` lists transcript lines that point at on-screen material: "screenshot", "on the screen", "this slide", "as you can see", "this chart/graph/table", "you'll notice", "let me show you". A cue is a reason to look, not proof a slide exists; an interview whose host says "as you can see" yields zero slides, and that is a valid result.

### How

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/youtube_slides.py" "<URL>" [output_dir]
```

Run it outside the command sandbox. It downloads the video (clients `web_safari`, `tv`, then `android`), samples a small grey frame every second, keeps frames that look like slides, and writes the most complete copy of each distinct slide:

```
<output_dir>/slides/01-0035.png …   one per distinct slide, at source resolution
<output_dir>/contact_sheet.png      all slides tiled; absent when there are none
<output_dir>/slides.json            {"video_id", "source_height", "interval", "samples", "slides": [{"index", "file", "t", "appearances", "ink"}]}
```

The final stdout line is `OUTPUT_DIR:<path>`, also when zero slides are found. On a download failure it exits 1 and prints no marker. `--video <file>` runs on a local file instead of downloading.

### What it handles, and why

- **Slides that build up.** Lines revealed one at a time and annotations drawn on stay one slide; the exported copy is the one with the most ink, i.e. the most complete.
- **Slides shown more than once.** One file, with every time range in `appearances`.
- **Dissolves.** A one-second blend of the talking head into a slide is dropped; runs under 2 s are not slides.
- **An opening slide.** Sampling at a fixed interval sees a slide that is on screen from the first second; scene-change detection does not, because there is no cut.

### After it runs

- **Look at `contact_sheet.png` before using the slides.** The classifier separates flat slides from camera footage; a mostly-flat scene (a whiteboard wall, a plain studio) can pass as a slide.
- **Check `source_height`.** The `android` fallback delivers 360p, and the script warns on stderr below 720p. Small text may be unreadable; say so rather than guessing a figure.
- **Read the figures off the image, not OCR.** OCR mangles numbers the way captions do.

⚠️ **Never take slides from browser screenshots of the player.** On 2026-10-09 the gstack player stopped seeking after the first frame, and seven screenshots at seven timestamps came out byte-identical, with no error.

## Output Format (v2.0)

The script saves JSON to a temp file with the following structure:

```json
{
  "title": "Video Title",
  "channel": "Channel Name",
  "duration": "1:23:45",
  "description": "Video description...",
  "published_date": "Jan 1, 2026",
  "url": "https://youtube.com/watch?v=...",
  "video_id": "abc123",
  "thumbnail_url": "https://i.ytimg.com/vi/abc123/maxresdefault.jpg",
  "language": "en",
  "transcript": "0:00 First line of transcript\n0:15 Second line...",
  "chapters": [
    {"timestamp": "0:00", "seconds": 0, "title": "Introduction"},
    {"timestamp": "5:30", "seconds": 330, "title": "Main Topic"},
    {"timestamp": "15:00", "seconds": 900, "title": "Deep Dive"}
  ],
  "speakers": [
    {"name": "David Puell", "role": "speaker"},
    {"name": "Yassine Elmandjra", "role": "guest"}
  ]
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Video title |
| `channel` | string | YouTube channel name |
| `duration` | string | Video duration (H:MM:SS or M:SS) |
| `description` | string | Full video description text |
| `published_date` | string | Publication date if available |
| `url` | string | Original YouTube URL |
| `video_id` | string | YouTube video ID extracted from URL |
| `thumbnail_url` | string | URL to max resolution thumbnail |
| `language` | string | Auto-detected language code (en, hi, zh, etc.) |
| `transcript` | string | Raw transcript with timestamps |
| `chapters` | array | Chapters extracted from description timestamps |
| `speakers` | array | Speakers identified from description |
| `caption_warnings` | array | Windows where the caption likely dropped a figure (see Caption verification) |
| `slide_cues` | array | `{"seconds", "phrase", "line"}` for each transcript line pointing at on-screen material (see Slides) |

### Language Detection

The script auto-detects the transcript language:
- `en` - English
- `hi` - Hindi (Devanagari)
- `ar` - Arabic
- `zh` - Chinese
- `ja` - Japanese
- `ko` - Korean
- `ru` - Russian (Cyrillic)

### Chapter Extraction

Chapters are extracted from timestamp patterns in the video description:
- Pattern: `0:00 Chapter Title` or `1:23:45 - Chapter Title`
- Each chapter includes `timestamp`, `seconds` (for sorting), and `title`
- Chapters are sorted by timestamp

### Speaker Extraction

Speakers are identified from description patterns:
- "Guests: Name1, Name2"
- "Featuring: Name"
- "With: Name"
- "Speakers: Name1 and Name2"
- Title patterns like "with Name" or "| Name"

## Error Handling

- If no transcript is available from any tier, the script writes the metadata JSON but emits **no** `OUTPUT_FILE:` line and exits 3. An absent marker means stop and report, never "build the note anyway"
- If the browser session is not signed in to YouTube, the script warns on stderr and continues — see "YouTube sign-in" above
- If gstack is unavailable or stuck in `launched` mode, the browser tier is skipped with a loud stderr message and the run falls through to Whisper. It never substitutes a logged-out browser

## Technical Notes

### Temp File Output
The script saves output to a temp file instead of stdout to avoid truncation for long videos. The file path is printed to stdout for the caller to read.

### Lazy Loading Handling
The transcript panel is scrolled to trigger lazy loading of all segments before extraction. This ensures complete transcripts for long videos (1+ hours).

### Deduplication
Transcript segments are deduplicated to remove repeated lines that can occur from the scrolling process.

## Example Output

After successful extraction, present the result clearly:

```
## Video Metadata
- **Title:** Stablecoins, Regulation, Mining And 2026 Outlook
- **Channel:** ARK Invest
- **Duration:** 1:11:43
- **Language:** en
- **URL:** https://youtube.com/watch?v=...
- **Video ID:** abc123
- **Thumbnail:** https://i.ytimg.com/vi/abc123/maxresdefault.jpg

## Chapters (8 found)
1. 0:00 - Introduction
2. 5:30 - Market Overview
...

## Speakers (3 identified)
- David Puell
- Yassine Elmandjra
- Frank Downing

## Transcript
[transcript text - first 500 chars preview]
...

Full transcript saved to: /tmp/yt_transcript_abc123.json
```
