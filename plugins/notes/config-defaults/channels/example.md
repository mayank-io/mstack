# Channel Template: Example

A format reference. Channel templates are per-user config: `notes:clip` reads them from `~/.mstack/notes/channels/*.md`. `ccimprove:setup-config` copies this file there; copy it again under the channel's name and edit that copy.

A channel template **overrides** `youtube.md` entirely; it does not merge with it. It describes shape and declarative settings only, and never sequences tool calls.

## Channel Matching

Match this template when the channel name contains (case-insensitive):
- "example channel"
- "examplechannel"

## Settings

Any setting from `youtube.md` may be overridden here.

- **model:** medium
- **language:** en
- **slides:** always

## Frontmatter

```yaml
---
title: "{{title}}"
author:
  - "[[@Example Channel]]"
duration: "{{duration}}"
published: {{published_date}}
source: {{url}}
image: {{thumbnail_url}}
created: {{created_date}}
channel: example channel
tags:
  - videos
  - youtube
  - clippings
categories:
  - "[[Clippings]]"
---
```

## Body

```markdown
# Summary: {{title}}

**Speaker:** Example Channel

## Core Themes

### Theme 1: [what the video covers first]
- [point]

## Key Data Points

| Metric | Value | Context |
|--------|-------|---------|

## Notable Quotes

> "[quote, in the speaker's language]"
> ([translation, when the language is not English])

---

# About

![{{title}}]({{url}})

# Description

{{description}}

---

# Transcript

[Full transcript, verbatim]
```

## Post-Processing Checklist

1. Every date is a wikilink in the vault's daily-note format.
2. The author link matches the frontmatter `author` entry.
3. The tags listed above are all present.
