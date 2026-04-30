## Development Workflow

Before writing or modifying source code, determine work size:
- Small: single file or function change → create a lightweight impl plan
- Medium: >3 files OR >50 lines changed OR new module/refactor/rename/behavior change → impl plan required, design recommended
- Large: new system, cross-cutting, production deploy → design + impl plan required

If no plan exists for the current work, prompt:
"This looks like [size] work. Should I create a [plan / design + plan] first?"

If work crosses the medium/large threshold mid-implementation, stop and create missing docs before continuing.

After writing a design doc or impl plan, invoke domain-specific review agents before proceeding.
After completing implementation, invoke domain-specific code review agents.

At session start, read docs/dashboard.md (or docs/templates/dashboard.base) to understand active work and current stages.
Filter by the current git branch to find docs relevant to this session's work.

When creating a new doc, copy from docs/templates/ and fill in frontmatter (work = current branch, created = today, status = draft).

When a doc is ready for the next stage, update its status frontmatter before proceeding.

### Status Lifecycle

Two terminal states, depending on doc shape:

**Workflow artifacts** (impl-plans, designs, audits, postmortems, cutover-plans, analyses, reports, reconciliations) drive a discrete piece of work. Lifecycle:
`draft → active → review → completed → archived`

**Reference specifications** (kb, ops-guide, playbook, `type: reference`, catalogs, strategy docs) ARE the live spec. Lifecycle:
`draft → review → active` — and `active` is the terminal state. Reference docs do not flip to `completed`; they live at `active` until deleted or replaced.

This split matters for the dashboard: the "Active Work" view filters out reference-shape types (`kb`, `ops-guide`, `playbook`, `reference`, `checklist`) so terminal-active references don't appear as in-flight work. If you introduce a new reference-shape type, add it to the filter in `docs/templates/dashboard.base`.

### Document Naming Convention

Workflow artifacts (date-prefixed): `YYYY-MM-DD-<topic>-{suffix}.md`
- Suffixes: `-design`, `-impl-plan`, `-cutover-plan`, `-analysis`, `-experiment`, `-report`, `-postmortem`

Evergreen reference (no date prefix): `<topic>.md`, `<topic>-guide.md`, `<topic>-playbook.md`

All docs live in `docs/` (flat, no subdirectories except `templates/`).
