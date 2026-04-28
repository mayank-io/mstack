---
name: setup-doc-conventions
description: "Bootstrap doc-conventions in the current project: creates docs/templates/ (including dashboard.base), docs/dashboard.md, configures Obsidian, and appends a workflow section to CLAUDE.md. Use when the user says \"set up doc conventions\", \"bootstrap docs\", \"install doc-conventions\", or \"set up the docs folder\"."
---

Set up the doc-conventions system in this project. Follow these steps exactly:

## 1. Create directory structure

```bash
mkdir -p docs/templates
```

## 2. Copy templates

Copy all 10 doc type templates and dashboard.base from the dev plugin cache into `docs/templates/`:
- design.md, impl-plan.md, cutover-plan.md, analysis.md, report.md, postmortem.md, kb.md, ops-guide.md, playbook.md, experiment.md
- dashboard.base (Obsidian Bases views definition — stays in templates/)

Then copy dashboard.md into `docs/dashboard.md` (the entry point that transcludes named views from templates/dashboard.base).

Find the plugin cache at: `~/.claude/plugins/cache/mstack/dev/*/templates/`

```bash
PLUGIN_DIR=$(ls -d ~/.claude/plugins/cache/mstack/dev/*/templates/ 2>/dev/null | head -1)
if [[ -n "$PLUGIN_DIR" ]]; then
  cp "$PLUGIN_DIR"/{design,impl-plan,experiment,cutover-plan,analysis,report,postmortem,kb,ops-guide,playbook}.md docs/templates/
  cp "$PLUGIN_DIR/dashboard.base" docs/templates/dashboard.base
  cp "$PLUGIN_DIR/dashboard.md" docs/dashboard.md
else
  echo "Plugin cache not found. Copy templates manually."
fi
```

## 3. Configure Obsidian

If `docs/.obsidian/` exists, update `docs/.obsidian/app.json` to include:
```json
{
  "templateFolder": "templates"
}
```

If `docs/.obsidian/` doesn't exist, create it:
```bash
mkdir -p docs/.obsidian
echo '{"templateFolder": "templates"}' > docs/.obsidian/app.json
```

Ensure the Templates core plugin is enabled in `docs/.obsidian/core-plugins.json`.

## 4. Update CLAUDE.md

Read the workflow section template from:
```bash
TMPL_DIR=$(ls -d ~/.claude/plugins/cache/mstack/dev/*/templates/ 2>/dev/null | head -1)
```

Append the contents of `$TMPL_DIR/claude-md-workflow-section.md` to the project's `CLAUDE.md`.

If CLAUDE.md doesn't exist, create it with just the workflow section.

## 5. Commit

```bash
git add docs/ CLAUDE.md
git commit -m "feat: set up doc-conventions (templates, dashboard, workflow)"
```

## 6. Verify

- Run `ls docs/templates/` — should show 10 template files + dashboard.base
- Run `cat docs/dashboard.md` — should show Obsidian transclusion links to dashboard.base views
- Run `cat docs/templates/dashboard.base` — should show Obsidian Bases view definitions
- Open docs/ in Obsidian — dashboard.md should render with tabbed views, templates should be available

Note: Hooks are registered automatically by the dev plugin via `hooks.json`. No project-level hook configuration is needed.
