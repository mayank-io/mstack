# Paper Template

Output shape for an arXiv / alphaXiv paper. Selected by `notes:clip`.

## Scope

Output shape and declarative settings only. Never sequences tool calls.

## Frontmatter

```yaml
---
tags:
  - clippings
  - paper
  - inbox
source: {{url}}
arxiv_id: {{arxiv_id}}
title: "{{title}}"
authors:
  - "{{author}}"
published: {{published_date}}
date_captured: {{today}}
---
```

## Body

```markdown
# {{title}}

> {{authors}} · arXiv:{{arxiv_id}} · {{published_date}}

## Abstract

{{abstract, verbatim}}

## Overview

{{the structured overview from fetch:alphaxiv-paper}}
```

**Mark generated content as generated.** alphaXiv's overview is AI-written. Say so where it appears — it is a reading aid, not the paper, and a claim traced back to it is not a claim traced to the authors.

## Required sections

```markdown
## Initial Take

- 2–4 bullets: the contribution, the method, the stated limitations.

## Related

- [[@Author]] where a note exists
```

## Rules

- **Filename:** `{{first author}} et al - {{short title}}.md`.
- Keep the abstract verbatim; do not paraphrase it into the summary.
- If the paper is only reachable as a PDF, route to `notes:save-local-file` instead so the PDF is archived.
