# mstack

Claude Code plugin marketplace for development and continuous-improvement workflows.

## Install

```
/plugin marketplace add mayank-io/mstack
```

Then enable individual plugins:

```
/plugin install ccimprove@mstack
/plugin install dev@mstack
/plugin install download@mstack
```

## Plugins

### `ccimprove` — meta improvement

Analyze your Claude Code usage and turn one-off work into reusable patterns.

| Command | What it does |
|---|---|
| `/ccimprove:surface-usage-patterns` | Scan all sessions in `~/.claude/projects/` and surface candidates for skills, plugins, agents, and CLAUDE.md additions |
| `/ccimprove:make-repeatable` | Analyze the current conversation and recommend whether to codify it as a skill or a plugin, then build it |
| `/ccimprove:clean-permissions` | Prune one-off pastes, redundant entries, and dead MCP refs from `~/.claude/settings.json` |

### `dev` — development workflow

Iterative reviews, doc conventions, and feedback loops for serious engineering work.

| Command | What it does |
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

### `download` — pull content into local Markdown

Save what you read so it stays searchable, summarizable, and yours.

| Command | What it does |
|---|---|
| `/download:youtube-transcript` | Transcript + metadata + chapters + speakers from a YouTube URL (persistent Chrome profile) |
| `/download:x-post` | Single tweet, full thread, or X Article — auto-detects threads and downloads images |
| `/download:notion-public-site` | Crawl a public Notion site, save every page as Markdown with wikilinks and embedded images |
| `/download:scribd-document` | Pull every page of a Scribd document as zero-padded `.jpg` files via embed view |
| `/download:alphaxiv-paper` | Structured AI-generated overview of any arXiv paper from alphaxiv.org |

## Conventions

- **Wrapper → SKILL pattern.** Every command is a thin wrapper that invokes its `<plugin>:<skill-name>` skill via the Skill tool. The skill holds the implementation. This means natural-language triggers ("clean up these permissions", "make this repeatable") activate the same flow as the explicit `/command`.
- **No Claude attribution in commits.** See `~/.claude/CLAUDE.md`.
- **Docs live elsewhere.** Design docs and implementation plans for this marketplace live in the sibling repo `mstack-docs/`, not in this repo.

## Layout

```
mstack/
├── .claude-plugin/
│   └── marketplace.json    # marketplace manifest
└── plugins/
    ├── ccimprove/
    ├── dev/
    └── download/
```

Each plugin follows the standard layout:

```
<plugin>/
├── .claude-plugin/plugin.json
├── commands/<name>.md      # thin wrappers
├── skills/<name>/SKILL.md  # implementations
├── hooks/                  # (dev only)
├── scripts/                # (dev, download)
└── templates/              # (dev only)
```

## License

MIT
