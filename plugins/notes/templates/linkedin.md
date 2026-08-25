# LinkedIn Template

Output shape for a note captured from `linkedin.com`. Selected by `notes:clip`.

## Scope

Output shape and declarative settings only. Never sequences tool calls.

## Frontmatter

```yaml
---
tags:
  - clippings
  - linkedin-post
  - inbox
source: {{url}}
author: "{{author_name}}"
author_headline: "{{author_headline}}"
date: {{post_date}}
date_captured: {{today}}
likes: {{likes}}
comments: {{comments}}
reposts: {{reposts}}
---
```

LinkedIn shows a relative age ("2w"), not a date. Resolve it where you can; **where you cannot, leave `date` empty rather than guessing** — a wrong date is worse than a missing one because it silently sorts wrong.

## Body

```markdown
# {{author_name}}: {{first ~60 chars of the post}}

> **{{author_name}}** — {{author_headline}}
> {{post_date}}

{{full post text, line breaks preserved}}

![{{description}}](attachments/{{filename}}.jpg)

---

**Engagement:** {{likes}} likes · {{comments}} comments · {{reposts}} reposts
**Posted:** [[{{post_date}}]]
**Source:** [LinkedIn]({{url}})
```

## Required sections

```markdown
## Linked Content

- [[{{child note}}]] — for each URL `notes:clip` followed
- {{inline summary}} — for a preview card that was not clipped

## Initial Take

- 2–3 bullets: the thesis, why it was shared, what context is missing.

## Related

- [[$TICKER]] · [[@Person]]
```

**`## Linked Content` is not optional when the post shares a URL.** The whole point of a shared post is often the thing it shares; a note that drops it captures the wrapper and loses the content. If a link was deliberately not followed, say so there.

## Rules

- **Verify the post was expanded.** LinkedIn truncates behind "…see more", and a truncated capture reads as a complete short post.
- **Filename:** `{{Author Name}} - {{short description}}.md`.
- If an image was screenshotted rather than downloaded, note it — a re-encode is not the original asset.
