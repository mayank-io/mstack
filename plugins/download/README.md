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

## Prerequisites

```bash
pip3 install httpx playwright
python3 -m playwright install chromium
```

## Installation

```bash
claude install mk-claude-code-plugins/download
```
