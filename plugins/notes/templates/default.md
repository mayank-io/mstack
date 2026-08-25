# Default Template

Fallback shape when no source template applies. If `notes:clip` is reaching for this often, the missing source deserves its own template.

## Scope

Output shape and declarative settings only. Never sequences tool calls.

## Frontmatter

```yaml
---
tags:
  - clippings
  - inbox
source: {{url}}
title: "{{title}}"
date_captured: {{today}}
---
```

## Body

```markdown
# {{title}}

> {{source attribution}}

{{content}}
```

## Required sections

```markdown
## Initial Take

- 2–4 bullets on what this is and why it was captured.

## Related
```

## Rules

- **Filename:** `{{title}}.md`, sanitised.
- Say plainly what could not be captured, and distinguish *"the extractor failed"* from *"the source does not have this"* — they call for different follow-ups.
