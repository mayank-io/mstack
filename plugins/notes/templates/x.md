# X / Twitter Template

Output shape for a note captured from `x.com` or `twitter.com`. Selected by `notes:clip`.

## Scope

Output shape and declarative settings only. Never sequences tool calls — fetching, cleaning and writing belong to `notes:clip`, `fetch:x-post` and `notes:create`.

## Frontmatter

```yaml
---
tags:
  - clippings
  - x-post
  - inbox
source: {{url}}
author: "@{{handle}}"
author_name: {{display_name}}
date: {{post_date}}
date_captured: {{today}}
likes: {{likes}}
reposts: {{reposts}}
views: {{views}}
---
```

Add `x-thread` to `tags` for a multi-post thread, `x-article` for long-form. Omit a metric entirely rather than writing `0` when it could not be read — a real zero and an unread value are different facts.

## Body — single post

Post text verbatim, preserving line breaks. Then embedded images, then:

```markdown
---

**Engagement:** {{likes}} likes · {{reposts}} reposts · {{views}} views
**Posted:** [[{{post_date}}]]
```

## Body — thread

```markdown
# {{title derived from the first post}}

## 1. {{short summary of post 1}}

{{post 1 text}}

![{{descriptive-name}}](attachments/{{filename}}.jpg)

---

## 2. {{short summary of post 2}}
```

Number every post. **Start from the thread root, not the shared link** — `fetch:x-post` walks backward to find it, and the note must begin where the thread does.

## Body — X Article

`# {{Article Title}}`, header image, then the article body with its own headings, paragraphs and inline images preserved in order.

## Required sections

Both at the end, in this order:

```markdown
## Initial Take

- 2–4 bullets: the key claim, what is notable, what is unsupported.

## Related

- [[$TICKER]] for each ticker mentioned
- [[@Person]] for each person with a note
```

## Rules

- **Images at original resolution.** `fetch:x-post` requests `name=orig`; embed those. A downscaled chart is unreadable at the point it matters.
- **Tickers as wikilinks** — `[[$AAPL]]`, never bare `$AAPL`. `notes:create` applies the vault's convention; do not fight it.
- **Filename:** `@{{handle}} - {{short description}}.md`. Never include the status ID.
- **Quote what was said, flag what was not.** If replies ask something the author never answered, record that as a gap in the source rather than inferring an answer.
