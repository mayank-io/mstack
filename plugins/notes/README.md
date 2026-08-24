# Notes Plugin

Capture external sources into a notes vault.

## Skills

### `clip`

Routes a URL to the right extractor and note-writer, so you type one thing regardless of source.

**Usage:**

```
clip https://x.com/user/status/123
clip https://youtube.com/watch?v=abc
/notes:clip https://example.com/article  tag it to project X
```

**Routing:**

| Source | Routes to | Writes the note? |
|--------|-----------|------------------|
| X / Twitter | `x-to-obsidian:save` | yes |
| YouTube | `youtube-to-obsidian:process` | yes |
| LinkedIn | `linkedin-to-obsidian:save` | yes |
| Notion site | `fetch:notion-public-site` | extract only |
| Scribd | `fetch:scribd-document` | extract only |
| arXiv / alphaXiv | `fetch:alphaxiv-paper` | extract only |
| PDF (incl. Drive) | `curl` + Read | extract only |
| anything else | `obsidian:defuddle` | extract only |

Extract-only routes are followed by `notes:create` to write the note.

## Design

**The clip skill is a router.** It deliberately does not know vault conventions — folder layout, frontmatter, tags, daily-note updates all belong to the downstream skill. That keeps the routing table stable while vaults differ.

What the router *does* own is the set of source-specific traps that have produced bad captures:

- **Browser sources use gstack browse, never a fresh Playwright session** — otherwise you silently capture logged-out content.
- **X virtualises its DOM** — a single pass loses posts; harvest across a scroll loop.
- **YouTube caption warnings catch omitted numbers, not corrupted ones** — run a corruption scan and re-transcribe any figure a summary will quote.
- **Notion hides content in collapsed toggles** — a page that is all headings with empty bodies is not a short page, it is an unexpanded one.
- **Screenshot-heavy pages carry their content in the images** — download *and read* them.
- **PDFs get archived locally**, because the link will rot.

## Dependencies

Note-writing lives in this plugin (`notes:create`, `notes:save-local-file`). Source-specific formatters live in the `mk-claude-code-plugins` marketplace (`x-to-obsidian`, `youtube-to-obsidian`, `linkedin-to-obsidian`); extraction lives in this marketplace's `fetch` plugin, plus `obsidian:defuddle`.

If a required skill is missing the clip skill reports it and stops, rather than half-finishing.
