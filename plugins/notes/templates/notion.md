# Notion Template

Output shape for a public Notion site. Selected by `notes:clip`.

## Scope

Output shape and declarative settings only. Never sequences tool calls.

## Frontmatter

```yaml
---
tags:
  - clippings
  - notion
  - inbox
source: {{url}}
title: "{{site_title}}"
pages: {{page_count}}
date_captured: {{today}}
---
```

## Body

A Notion site is a *set* of pages. Write an index note whose body links each captured page, and keep the pages as separate notes beneath it:

```markdown
# {{site_title}}

{{page_count}} pages captured from [{{url}}]({{url}}).

- [[{{page 1 title}}]]
- [[{{page 2 title}}]]
```

## Rules

- **Report the byte count per page.** The characteristic Notion failure is a page of headings with empty bodies — collapsed toggle blocks the crawler never expanded. It looks like a valid short page.
- **A page that is almost all headings is a failed capture, not a short page.** Re-extract it with toggles expanded and compare sizes before accepting it.
- Some Notion *database group headers* will not expand at all. Try, then **say what is still missing** rather than presenting the capture as complete.
- **Filename:** the page title, sanitised.
