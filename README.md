# mstack

Claude Code plugin marketplace for development and continuous-improvement workflows.

## Install

```
/plugin marketplace add mayank-io/mstack
```

Then enable individual plugins:

```
/plugin install notes@mstack
/plugin install fetch@mstack
/plugin install dev@mstack
/plugin install ccimprove@mstack
/plugin install company-setup@mstack
/plugin install think@mstack
```

`notes` and `fetch` are a pair — `notes:clip` routes to `fetch:*` for everything it captures, so installing `notes` alone leaves most routes dead.

## Plugins

### `ccimprove` — meta improvement

Analyze your Claude Code usage and turn one-off work into reusable patterns.

| Skill | What it does |
|---|---|
| `/ccimprove:surface-usage-patterns` | Scan all sessions in `~/.claude/projects/` and surface candidates for skills, plugins, agents, and CLAUDE.md additions |
| `/ccimprove:make-repeatable` | Analyze the current conversation and recommend whether to codify it as a skill or a plugin, then build it |
| `/ccimprove:clean-permissions` | Prune one-off pastes, redundant entries, and dead MCP refs from `~/.claude/settings.json` |

### `dev` — development workflow

Iterative reviews, doc conventions, and feedback loops for serious engineering work.

| Skill | What it does |
|---|---|
| `/dev:code-review-iterative` | Up to 4 review-fix iterations with 3 parallel reviewer agents (PE, Sr SDE, QA), diminishing fix thresholds |
| `/dev:design-review-iterative` | Same shape, applied to design documents (PE, Sr SDE, Domain Expert) |
| `/dev:ml-design-review-iterative` | ML-specific variant (Principal ML Engineer, Sr Applied Scientist, ML Ops Engineer) |
| `/dev:apply-feedback` | Apply tagged comments (`[MK]`, `[REV]`, etc.) in the current document immediately, no questions asked |
| `/dev:review-feedback` | Same input, but plan-then-apply with approval gate |
| `/dev:setup-doc-conventions` | Bootstrap `docs/templates/`, dashboard, Obsidian config, and CLAUDE.md workflow section |
| `/dev:finish-work-on-local-worktree` | Squash-merge a worktree into main, update doc statuses, refresh the project plan, recommend next work |
| `/dev:summarize-this-session` | Two-section conversation recap: ongoing task + continuous-improvement insights |

Bundled assets:
- 10 doc-type templates (`design`, `impl-plan`, `cutover-plan`, `analysis`, `report`, `postmortem`, `kb`, `ops-guide`, `playbook`, `experiment`)
- Obsidian Bases dashboard (`dashboard.base` + `dashboard.md`)
- CLAUDE.md workflow section snippet
- PreToolUse / PostToolUse / SessionStart hooks for doc workflow enforcement

#### Configuration: feedback tags

`apply-feedback` and `review-feedback` look for tagged comments (e.g., `[MK]`, `[REV]`) in the current document. The set of tags and how each one should be interpreted is configured per user at:

```
~/.mstack/dev/feedback-tags.json
```

The file is **auto-created on first run** with a default `MK` entry. To add, modify, or delete tags, edit this file directly. Changes are picked up on the next skill invocation — no restart required.

Schema:

```json
{
  "tags": [
    {
      "tag": "MK",
      "from": "Document author (initials = MK for Mayank)",
      "content": "Direct edit instructions, factual corrections, rephrasing requests",
      "action": "Apply edits as written; treat as imperative; only push back if ambiguous"
    },
    {
      "tag": "REV",
      "from": "External reviewer",
      "content": "Suggestions, open questions, alternative phrasings",
      "action": "Treat as suggestions; flag for discussion before applying"
    }
  ]
}
```

Field semantics:
- `tag` — short uppercase prefix that appears bracketed in documents (matched case-insensitively).
- `from` / `content` — context to help Claude calibrate trust and tone for these comments.
- `action` — interpretation guidance. Does **not** override the skill's posture (`apply-feedback` still applies immediately, `review-feedback` still gates on approval), but informs *how* matched comments are treated within that posture.

### `notes` — capture a source into your vault

**Start here.** `clip` is the single entry point: hand it a URL and it routes to the right fetcher, then files the result into whichever Obsidian vault you are running in.

| Skill | What it does |
|---|---|
| `notes:clip` | URL in, note out — routes by host, chains on the fetcher's result line |
| `notes:create` | Write a note into the current vault; owns frontmatter, folder, filename, collisions |
| `notes:save-local-file` | File already on disk → note, archiving the file into the vault's attachments |

The vault is wherever the session is — found by walking up for a `.obsidian/` directory. There is no `vault_path` config.

### `fetch` — pull content from a source into a directory

The layer beneath `notes`. Each skill gets content out of one source and knows nothing about vaults. Useful directly when you want the raw material somewhere of your choosing.

| Skill | What it does |
|---|---|
| `fetch:youtube-transcript` | Transcript + metadata + chapters + speakers from a YouTube URL (persistent Chrome profile, Whisper fallback, caption-integrity verification) |
| `fetch:x-post` | Single tweet, full thread, or X Article — auto-detects threads, walks back to the thread root, downloads images at original resolution |
| `fetch:linkedin-post` | Post text, author, metrics, comments and attachments — expands the "… more" control and filters attachments from page furniture |
| `fetch:blog-post` | Article to self-contained Markdown + images, recovering the lazy-loaded ones Defuddle drops |
| `fetch:notion-public-site` | Crawl a public Notion site, save every page as Markdown with wikilinks and embedded images |
| `fetch:scribd-document` | Pull every page of a Scribd document as zero-padded `.jpg` files via embed view |
| `fetch:alphaxiv-paper` | Structured AI-generated overview of any arXiv paper from alphaxiv.org |
| `fetch:vedic-chart` | Digitize a Vedic astrology chart image into structured data |

**Contract.** Every `fetch:*` skill takes `<url-or-path> [output_dir]` — a temp directory when omitted — never writes outside it, and prints `OUTPUT_FILE:<path>` or `OUTPUT_DIR:<path>` as its final stdout line. Chain on that line; never reconstruct the path.

## Conventions

- **Skills only — no command wrappers.** A skill is both slash-invocable (`/notes:clip`) and naturally triggered by its description, so it needs no companion command. Until 0.9.0 every skill had a same-named wrapper in `commands/` whose entire body was *"Invoke the `<plugin>:<name>` skill via the Skill tool."* Both registered the same `/plugin:name`, so all 23 appeared **twice** in the slash menu — and the two descriptions drifted apart. Removing them cut the menu from 74 entries to 51 and, because the skill's own description is longer than the wrapper's, made the remaining entries more informative rather than less.
- **No Claude attribution in commits.** See `~/.claude/CLAUDE.md`.
- **Docs live elsewhere.** Design docs and implementation plans for this marketplace live in the sibling repo `mstack-docs/`, not in this repo.

## Layout

```
mstack/
├── .claude-plugin/
│   └── marketplace.json    # marketplace manifest
└── plugins/
    ├── ccimprove/
    ├── company-setup/
    ├── dev/
    ├── fetch/
    ├── notes/
    └── think/
```

Each plugin follows the standard layout:

```
<plugin>/
├── .claude-plugin/plugin.json
├── skills/<name>/SKILL.md  # implementations
├── hooks/                  # (dev only)
├── scripts/                # (dev, fetch)
└── templates/              # (dev only)
```

## License

MIT
