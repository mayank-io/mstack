# Download Plugin

Download content from various sources as local Markdown files.

## Commands

### `/download:notion-public-site`

Download all pages from a public Notion site as Markdown files with cross-references.

**Usage:**
```bash
/download:notion-public-site <url> <output_dir> [--test]
```

**Example:**
```bash
# Test mode - download first page only
/download:notion-public-site https://guide.sillymoney.com/ ./output --test

# Full download
/download:notion-public-site https://guide.sillymoney.com/ ./output
```

**Features:**
- Automatically crawls all internal pages
- Downloads embedded images to `attachments/` folder
- Converts Notion content to clean Markdown
- Rewrites internal links as Obsidian wikilinks
- Creates an index file with table of contents

---

### `/download:youtube-transcript`

Extract transcript and metadata from a YouTube video using a persistent Chrome session.

**Usage:**
```bash
/download:youtube-transcript <YouTube URL> [--headless]
```

**Example:**
```bash
# First run - opens browser for login
/download:youtube-transcript https://www.youtube.com/watch?v=dQw4w9WgXcQ

# Subsequent runs - can use headless mode
/download:youtube-transcript https://www.youtube.com/watch?v=dQw4w9WgXcQ --headless
```

**Features:**
- Extracts video transcript with timestamps
- Gets metadata: title, channel, duration, description
- Persistent Chrome profile for YouTube login state
- Auto-detects transcript language (en, hi, ar, zh, ja, ko, ru)
- Works with age-restricted videos (when logged in)

**Output:**
```json
{
  "title": "Video Title",
  "channel": "Channel Name",
  "duration": "1:23:45",
  "url": "https://youtube.com/...",
  "language": "en",
  "transcript": "0:00 First line...\n0:15 Second line..."
}
```

**Configuration (optional):**

Create `.claude/download.local.md`:
```yaml
---
chrome_profile_path: ~/.claude/youtube-chrome-profile
headless: false
---
```

---

### `/download:blog-post`

Save a blog post/article (Medium, Substack, personal blogs) as a self-contained folder: clean markdown via Defuddle, all inline images recovered via Playwright (which Defuddle drops as lazy-loaded), and any Vedic astrology charts digitized via `/download:vedic-chart`.

**Usage:**
```bash
/download:blog-post <article URL> [output_dir]
```

**Features:**
- Defuddle for clean, low-token article text + metadata (title/author/published)
- Trims site chrome (Medium nav/footer) by structural landmarks
- Recovers high-res images in document order via Playwright, anchored to their headings
- Writes YAML frontmatter and a portable `images/` subfolder
- Invokes `download:vedic-chart` when the article contains horoscope charts

**Output:** `<output_dir>/<slug>/<slug>.md` + `<output_dir>/<slug>/images/`

---

### `/download:vedic-chart`

Convert a Vedic/Jyotish horoscope chart image (Jagannatha Hora / Parashara's Light printout) into structured JSON + ASCII North-Indian and South-Indian diagrams.

**Usage:**
```bash
/download:vedic-chart <chart image or chart .json> [output_dir]
```

**Features:**
- Reads the image's bottom longitude table (ground truth) via the `claude` vision CLI
- Computes houses deterministically; renders both North-Indian and South-Indian charts
- `--emit {json,ascii,both}`, `--style {north,south,both}`, sidecar caching, render-only from `.json`
- Standalone script (`scripts/chart_to_ascii.py`) — plain `python3`, no virtualenv

**Output:** `<stem>.json` (structured chart) + `<stem>.txt` (ASCII charts)

---

## Prerequisites

```bash
pip3 install httpx playwright
python3 -m playwright install chromium
npm install -g defuddle-cli   # for /download:blog-post
```

## Installation

```bash
claude install mk-claude-code-plugins/download
```
