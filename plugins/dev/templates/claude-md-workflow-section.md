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
Status lifecycle: draft → active → review → completed → archived.

### Document Naming Convention

Workflow artifacts (date-prefixed): `YYYY-MM-DD-<topic>-{suffix}.md`
- Suffixes: `-design`, `-impl-plan`, `-cutover-plan`, `-analysis`, `-experiment`, `-report`, `-postmortem`

Evergreen reference (no date prefix): `<topic>.md`, `<topic>-guide.md`, `<topic>-playbook.md`

All docs live in `docs/` (flat, no subdirectories except `templates/`).
