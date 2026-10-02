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

### Notable comments

- **{{commenter}}** ({{commenter headline, short}}): "{{comment text, verbatim}}"
```

**`### Notable comments` is optional but usually worth it on list and advice posts** — commenters routinely add the items the author missed. Quote verbatim and keep the commenter's name; drop reactions-only replies ("Saving to dive in"), tags of other users, and self-promotion. Omit the section when no comment adds substance.

## Article — `linkedin.com/pulse/…`

`fetch:linkedin-post` returns `type: article` with ordered `blocks`. An article is an essay, not a post: swap `linkedin-post` for `linkedin-article` in `tags`, and use the printed `published` date as `date` (it is a real date, not a relative age; leave it empty when the fetcher returns `null`).

```yaml
tags:
  - clippings
  - linkedin-article
  - inbox
source: {{source}}
author: "{{author_name}}"
author_headline: "{{author_headline}}"
author_url: {{author_url}}
date: {{published}}
date_captured: {{today}}
likes: {{metrics.reactions}}
comments: {{metrics.comments}}
```

```markdown
# {{title}}

> **{{author_name}}**, {{author_headline}} · LinkedIn article · {{reactions}} reactions · {{comments}} comments
> Published [[{{published}}]] · captured [[{{today}}]]

## Summary

[paraphrase of the argument, no evaluation]

## Article

{{blocks, in document order — article.md minus its title and byline, every heading demoted one level}}

---

**Engagement:** {{reactions}} reactions · {{comments}} comments (at capture)
**Published:** [[{{published}}]]
```

- **The title is the note's only `#`.** Article `h2` → `###`, `h3` → `####` under `## Article`, so the source's sections nest under it and never collide with `## Summary` or `# Analysis`.
- **Images stay where the article put them.** An image block between two paragraphs is embedded between those paragraphs, not collected at the end. Embed the cover above the body only when it is not a crop of an inline image.
- **Bold run-ins are the author's.** Keep `**label:**` from the blocks; do not add emphasis the source lacks.
- **Filename:** `{{Author Name}} - {{title}}.md`, colons and parentheses folded into commas or dashes.
- `# Analysis` replaces `## Initial Take` for articles, as in `x.md`: an `h1` after the source, so the boundary between the author's voice and yours is visible in the outline.

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
