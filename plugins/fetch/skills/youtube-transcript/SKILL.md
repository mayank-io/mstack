---
name: youtube-transcript
description: "Extract transcript and metadata from a YouTube video using a persistent Chrome session. Use when the user shares a youtube.com or youtu.be URL and wants the transcript, video metadata, chapters, or speakers."
---

# Download YouTube Transcript

Extract the transcript and metadata from a YouTube video using Playwright with a persistent Chrome profile.


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
the logged-in sessions with it. Verified 2026-08-24: a disconnect after one
capture left the browser logged out of both X and LinkedIn, so the next capture
returned a login wall that reads as a short post. Leave the daemon running —
`connect` is safe to call again, and only whoever started it should close it.

**Never launch a headless browser.** Not `headless=True`, not `--headless`, not a
fresh `chromium.launch()`. If gstack is unavailable, stop and say so rather than
falling back — a logged-out capture is worse than no capture, because it looks fine.

## Configuration

Read the settings file at `.claude/download.local.md` to get:
- `chrome_profile_path`: Path to persistent Chrome profile (default: `~/.claude/youtube-chrome-profile`)
- `headless`: Run browser in headless mode (default: `false`)

If the settings file doesn't exist, use defaults.

**Settings file template:**
```yaml
---
chrome_profile_path: ~/.claude/youtube-chrome-profile
headless: false
---
```

## First-Time Setup

On first run, the browser will open **in visible mode** (not headless) so the user can:
1. Log into YouTube if needed
2. Accept any cookie banners
3. The login state is saved to the Chrome profile for future runs

The `--headless` flag is deprecated and ignored — this fallback always runs headed so the login prompt can be answered.

## Usage

Parse the YouTube URL from `$ARGUMENTS`. The URL can be in various formats:
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://youtube.com/watch?v=VIDEO_ID`

## Execution

Run the extraction script:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/youtube_transcript_extractor.py" "<URL>" --profile "<chrome_profile_path>"
```

Do not pass `--headless`; it is ignored.

**Important:** The script writes the transcript JSON to a file and prints its path as the **final stdout line**, prefixed per the skill contract:

```
OUTPUT_FILE:/var/folders/.../yt_transcript_abc123.json
```

Strip the prefix before using it — do not consume the whole line as a path:

```bash
last=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/youtube_transcript_extractor.py" \
         "https://youtube.com/watch?v=abc123" --profile ~/.claude/youtube-chrome-profile | tail -1)
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

- If no transcript is available, the output will include `"transcript": null` and an `"error"` field
- If the video requires login and the user isn't logged in, the browser opens for manual login
- If the browser fails to launch, suggest running `playwright install chromium`

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
