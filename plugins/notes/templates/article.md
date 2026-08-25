# Article Template

Output shape for a general web article, and for Scribd documents. Selected by `notes:clip` for the fallback route.

## Scope

Output shape and declarative settings only. Never sequences tool calls.

## Frontmatter

```yaml
---
tags:
  - clippings
  - article
  - inbox
source: {{url}}
title: "{{title}}"
author: "{{author}}"
site: {{site_name}}
published: {{published_date}}
date_captured: {{today}}
---
```

## Body

```markdown
# {{title}}

> {{author}} · {{site_name}} · {{published_date}}

{{article body — headings, lists and inline images preserved in source order}}
```

**Images belong where they appeared.** `fetch:blog-post` returns each image with an anchor (its nearest preceding heading) precisely so order survives; a note with every image dumped at the end has lost information the fetcher preserved.

## Required sections

```markdown
## Initial Take

- 2–4 bullets: the argument, the evidence offered, what is asserted without support.

## Related

- [[$TICKER]] · [[@Person]]
```

## Rules

- **Filename:** `{{Author or Site}} - {{title}}.md`, sanitised, ~60 chars.
- **Paywalled or partial captures must say so.** A truncated article that reads as complete is the failure mode here.
- For a Scribd document, the pages are images — embed them in order and state the page count.
