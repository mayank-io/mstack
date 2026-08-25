# YouTube Template

Output shape for a YouTube video note. Selected by `notes:clip` for any `youtube.com` / `youtu.be` URL.

## Channel Matching

Used when no template in `channels/` matches the video's channel. A channel template overrides this one entirely — it does not merge with it.

## Scope

This file describes **output shape** and declarative settings only. It never sequences tool calls — fetching, cleaning and writing belong to `notes:clip`, `notes:clean-transcript` and `notes:create`. If a rule here starts saying "then run X", it has outgrown the format and belongs in a skill.

## Frontmatter

```yaml
---
title: "{{title}}"
author:
  - "[[@{{speaker}}]]"  # Repeat for each speaker
duration: "{{duration}}"
published: {{published_date}}
source: {{url}}
image: {{thumbnail_url}}
created: {{created_date}}
channel: {{channel}}
tags:
  - videos
  - youtube
  - inbox
  - clippings
categories:
  - "[[Clippings]]"
---
```

## Summary Structure

### Core Themes
Identify 3-5 main themes/topics discussed. For each theme:
- Use H3 heading with theme title
- Add 2-4 bullet points summarizing key insights

Example:
```markdown
## Core Themes

### Theme 1: [Title]
- Key insight 1
- Key insight 2

### Theme 2: [Title]
- Key insight 1
- Key insight 2
```

### Key Data Points
Create a markdown table with important data mentioned:

```markdown
## Key Data Points

| Metric | Value | Context |
|--------|-------|---------|
| Example | $100K | Bitcoin price target |
```

### Notable Quotes
Extract 3-5 significant quotes:

```markdown
## Notable Quotes

> "Quote text here" — Speaker Name

> "Another quote" — Other Speaker
```

### Predictions/Takeaways
List actionable insights or forward-looking statements:

```markdown
## Predictions/Takeaways

1. Takeaway 1
2. Takeaway 2
3. Takeaway 3
```

## Body Structure

```markdown
# Summary: {{title}}

**Speakers:** Speaker 1, Speaker 2
**Event/Context:** [If mentioned in description]

---

[Summary sections as defined above]

---

# About

![{{title}}]({{url}})

# Description

[Description from YouTube - strip hashtag lines but preserve chapter timestamps]

---

# Transcript

[FULL VERBATIM TRANSCRIPT - cleaned and formatted, NOT summarized]

## Chapter 1: Introduction

**Speaker Name:** Complete cleaned transcript content...

## Chapter 2: Main Topic

**Speaker Name:** Full content continues here...
```

## Tags

Default tags applied:
- videos
- youtube
- inbox
- clippings

## Post-Processing

- Ensure all speaker names are linked as `[[@Speaker Name]]`
- Preserve chapter structure from video
- Keep full transcript verbatim (cleaned but not condensed)
