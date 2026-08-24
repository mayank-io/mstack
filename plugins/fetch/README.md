# Fetch Plugin

Fetch content from a source into a directory. Sources include YouTube, X, Notion, Scribd, arXiv and blogs, plus Vedic chart digitisation from a local image.

**Nothing in this plugin knows about vaults.** Where output lands is a parameter. That is what lets the same skills serve a one-off dump to `/tmp` and a vault capture driven by `notes:clip`.

## Skill contract

Every `fetch:*` skill conforms to this. New skills must too.

### Input

```
fetch:<source>  <url-or-path>  [output_dir]
```

- **`output_dir` is optional.** When omitted, write to a fresh temp directory.
- **Create `output_dir` if it does not exist.** Do not fail because a parent is missing.
- **Never write outside `output_dir`.** No writes to the vault, the cwd, or anywhere the caller did not name.
- The parameter is always spelled `output_dir` — not `download_dir`, not `dest`.

### Output

The **final line of stdout** is machine-parseable, so a caller can chain on it without parsing prose:

```
OUTPUT_FILE:/absolute/path/to/file        # a single artefact
OUTPUT_DIR:/absolute/path/to/directory    # a set of files
```

Emit exactly one such line, last. Human-readable progress may precede it and is ignored by callers.

**One documented exception:** `fetch:vedic-chart` streams the chart JSON and ASCII to stdout when no `output_dir` is given — there, stdout *is* the product. It emits `OUTPUT_DIR:` only when writing files.

### Why it matters

`notes:clip` routes a URL to a `fetch:*` skill and then hands the result to `notes:create` or `notes:save-local-file`. Without a uniform result line the router has to guess where output landed — which is how paths get hand-computed and quietly wrong.

## Commands

### `/fetch:notion-public-site`

Download all pages from a public Notion site as Markdown files with cross-references.

**Usage:**
```bash
/fetch:notion-public-site <url> <output_dir> [--test]
```

**Example:**
```bash
# Test mode - download first page only
/fetch:notion-public-site https://guide.sillymoney.com/ ./output --test

# Full download
/fetch:notion-public-site https://guide.sillymoney.com/ ./output
```

**Features:**
- Automatically crawls all internal pages
- Downloads embedded images to `attachments/` folder
- Converts Notion content to clean Markdown
- Rewrites internal links as Obsidian wikilinks
- Creates an index file with table of contents

---

### `/fetch:youtube-transcript`

Extract transcript and metadata from a YouTube video using a persistent Chrome session.

**Usage:**
```bash
/fetch:youtube-transcript <YouTube URL> [output_dir]
```

**Example:**
```bash
# First run - opens browser for login
/fetch:youtube-transcript https://www.youtube.com/watch?v=dQw4w9WgXcQ

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

### `/fetch:blog-post`

Save a blog post/article (Medium, Substack, personal blogs) as a self-contained folder: clean markdown via Defuddle, all inline images recovered via Playwright (which Defuddle drops as lazy-loaded), and any Vedic astrology charts digitized via `/fetch:vedic-chart`.

**Usage:**
```bash
/fetch:blog-post <article URL> [output_dir]
```

**Features:**
- Defuddle for clean, low-token article text + metadata (title/author/published)
- Trims site chrome (Medium nav/footer) by structural landmarks
- Recovers high-res images in document order via Playwright, anchored to their headings
- Writes YAML frontmatter and a portable `images/` subfolder
- Invokes `fetch:vedic-chart` when the article contains horoscope charts

**Output:** `<output_dir>/<slug>/<slug>.md` + `<output_dir>/<slug>/images/`

---

### `/fetch:vedic-chart`

Convert a Vedic/Jyotish horoscope chart image (Jagannatha Hora / Parashara's Light printout) into structured JSON + ASCII North-Indian and South-Indian diagrams.

**Usage:**
```bash
/fetch:vedic-chart <chart image or chart .json> [output_dir]
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
npm install -g defuddle-cli   # for /fetch:blog-post
```

## Installation

```bash
claude install mk-claude-code-plugins/download
```
