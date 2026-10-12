---
name: explain-flows
description: "Generate an interactive, single-page HTML map of how an application's packages and components collaborate to complete its workflows, driven by a flows.json document. Clicking a flow (\"Invite new user\", \"todesktop build\", \"POST /v1/invites\", \"/notes:clip <url>\") highlights the path through the components and annotates what is passed at each hop. Works for UI/monorepo apps, API-first apps invoked via REST or CLI, and apps built from Claude Code skills/plugins. Use when the user says \"explain the flows\", \"map the workflows\", \"document how the packages talk to each other\", \"flow diagram of the app\", \"how does X travel through the system\", or wants an onboarding map of an unfamiliar codebase."
---

# Explain Flows

Produce two artifacts for the current repository:

- `flows.json` — the source of truth: every component and every documented workflow, each step backed by a code reference.
- `index.html` — a single self-contained page that renders `flows.json`. All components are always on screen; choosing a flow highlights the participating components, draws the path, and annotates each hop with what is passed.

Default location is `docs/flows/` (use the repo's existing docs folder if it has a different name). If `flows.json` already exists, run in **update mode** (§6).

## 1. Detect the application kind

Classify the repo before inventorying anything. A repo can be more than one kind (a monorepo with a web app *and* a public REST API *and* a CLI); record every kind that applies in `app.kinds`.

| Kind | Signals | What a "flow" is |
|---|---|---|
| `ui-app` | `package.json` workspaces, `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `apps/` + `packages/`, Electron / ToDesktop / Tauri / React Native config | A user action in the UI ("Invite new user"), or a build/release pipeline ("todesktop build", "deploy web") |
| `api` | OpenAPI/Swagger spec, route registrations (Express/Fastify/FastAPI/Rails/axum), CLI parser definitions (clap, click/typer, cobra, commander, argparse), `[project.scripts]` / `bin` entries | One endpoint (`POST /v1/invites`) or one CLI command (`acme invite --email`) end to end, including its error paths |
| `plugin` | `.claude-plugin/plugin.json`, `marketplace.json`, `skills/*/SKILL.md`, `commands/`, `agents/`, `hooks/hooks.json`, `.mcp.json` | One slash command, one skill trigger phrase, or one hook event, from the user's prompt to the final output |

## 2. Inventory the components (nodes)

Read manifests first, then code. Every node gets a `path` that exists in the repo.

- **ui-app** — node types: `app`, `package`, `component`, `worker`, `build-tool`, `datastore`, `external`. Layers, in order: `client` → `server` → `shared` → `data` → `external`, plus `build` when build/release flows exist. Pick the granularity that makes flows legible: packages by default; promote a component (a modal, a store, a route handler) to its own node only when a flow needs to show it.
- **api** — node types: `entrypoint` (HTTP router, CLI parser), `middleware` (auth, validation, rate limiting), `handler`, `service`, `datastore`, `queue`, `worker`, `external`. Layers: `entry` → `middleware` → `domain` → `data` → `external`. When REST and CLI front the same service layer, give each its own `entrypoint` node so their convergence is visible.
- **plugin** — node types: `actor` (the user), `host` (Claude Code), `plugin`, `command`, `skill`, `agent`, `hook`, `mcp-server`, `script`, `config` (e.g. `~/.mstack/<plugin>/*.json`), `external` (web services, other CLIs, the vault/filesystem). Layers: `user` → `host` → `plugin` (skills, commands, agents, hooks) → `runtime` (scripts, MCP servers, tools) → `external`. Cross-plugin calls (one skill invoking another plugin's skill) are edges between `skill` nodes in different plugins; group nodes by plugin with `group`.

## 3. Discover candidate flows, then ask

Build a candidate list from evidence, not imagination:

- **ui-app**: UI actions that cross a package boundary (buttons, forms, routes with mutations), plus `package.json` scripts, CI workflows and release config for build flows.
- **api**: every route in the spec or router, every CLI subcommand. Collapse trivial CRUD into one representative flow per resource.
- **plugin**: every slash command and skill, every hook event that has a handler, every agent that a skill dispatches.

Then stop and ask the user, in one message, before tracing anything:

1. The detected kind(s) and the node count per layer.
2. The candidate flows grouped by `category`, marked **recommended** for the 6–12 that best explain the system (cross the most layers, touch the most-shared nodes, include at least one build/deploy or error-heavy flow).
3. Anything ambiguous that changes the map: granularity (packages vs components), whether to include external SaaS as separate nodes, output location.

Trace only the flows the user confirms.

## 4. Trace each flow and write `flows.json`

Follow the call path in code, hop by hop. Each step is one hop between two nodes and carries a `source` (`path:line`) where the hop happens. If you cannot find the line, keep the step, set `"confidence": "inferred"`, and say why in `note` — the page renders inferred steps dashed. Never present a guess as traced.

### 4.1 Schema

```json
{
  "schemaVersion": 1,
  "app": {
    "name": "acme",
    "kinds": ["ui-app", "api"],
    "commit": "<git rev-parse --short HEAD>",
    "generatedAt": "YYYY-MM-DD"
  },
  "layers": [{ "id": "client", "label": "Client" }],
  "nodes": [
    {
      "id": "web",
      "label": "apps/web",
      "type": "app",
      "layer": "client",
      "group": "optional grouping, e.g. plugin name",
      "path": "apps/web",
      "description": "One line: what this component is responsible for."
    }
  ],
  "flows": [
    {
      "id": "invite-user",
      "title": "Invite new user",
      "category": "Users",
      "trigger": { "kind": "ui", "value": "Settings → Members → Invite" },
      "summary": "One or two sentences: what the flow achieves and its end state.",
      "steps": [
        {
          "from": "web",
          "to": "api",
          "kind": "http",
          "label": "POST /api/invites",
          "payload": { "name": "InviteRequest", "example": { "email": "a@b.co", "role": "member" } },
          "async": false,
          "source": "apps/web/src/members/invite.ts:42",
          "confidence": "traced",
          "note": "Optional: anything a reader would get wrong without being told."
        }
      ],
      "branches": [
        {
          "atStep": 3,
          "label": "Email already invited",
          "steps": [{ "from": "api", "to": "web", "kind": "return", "label": "409 Conflict", "source": "..." }]
        }
      ],
      "outcome": "Invite row exists; email queued; UI shows pending member."
    }
  ]
}
```

Field rules:

- `trigger.kind`: `ui` | `http` | `cli` | `slash-command` | `skill-phrase` | `hook` | `schedule` | `build` | `event`.
- `step.kind`: `call` (in-process function/import), `http`, `cli` (process spawn / subcommand), `ipc` (Electron main↔renderer, worker messages), `event` (emitter/pub-sub), `queue`, `db`, `file`, `build` (bundler/packager stage), `prompt` (text loaded into the model's context — a SKILL.md, a reference file, a command body), `tool-call` (the model invokes Bash/Read/MCP/Skill), `model-decision` (the model chooses — a skill selected from its description, a branch taken from judgment), `hook` (harness-run, deterministic), `return`.
- `payload` names the real type, schema, file or argument list where one exists, and gives a small realistic `example`. For `cli`, the example is the argv; for `return` from a CLI, it is the exit code plus what goes to stdout vs stderr; for `prompt`, it is the file loaded; for `http`, method, path, body shape and status.
- Steps are ordered. Add an explicit `return` step only when the returned data matters to a later step or to the user.
- `branches` hold error paths and alternates. Every `api` flow documents at least its main failure modes (auth failure, validation failure, not found) with HTTP status / CLI exit code. Every `plugin` flow documents what happens when a precondition fails (missing config, tool denied, network blocked).

### 4.2 Kind-specific tracing guidance

- **ui-app** — Show where data changes shape (form state → DTO → DB row → event → email). For build flows, nodes are the packages being built and the tools doing it (`turbo`, `vite`, `todesktop`, signing/notarization, the CDN or update server); steps are stages and the payload is the artifact (`dist/`, `.dmg`, `latest-mac.yml`).
- **api** — Show the middleware chain explicitly; it is where most surprises live. When a REST flow and a CLI flow reach the same service, make them two flows in the same `category` with matching titles (`Invite user (REST)`, `Invite user (CLI)`) so a reader can switch between them and watch only the entry differ. Note auth context propagation (token → principal → tenant) on the step where it happens.
- **plugin** — Make the deterministic/non-deterministic boundary visible: `hook` and `tool-call` → `script` edges are deterministic; skill selection and most branching are `model-decision`. Show every `prompt` edge that loads instructions (SKILL.md, `references/*.md`, templates) because that is the "code" of a skill. Show where state persists (config files, vault writes, caches) and which external services are reached, and through what (gstack browse, `curl`, an MCP server).

## 5. Build `index.html`

One file, no build step, no network dependencies (no CDN). Requirements:

1. **Data loading.** Embed the JSON in `<script type="application/json" id="flows-data">`. On load, try `fetch('flows.json')` and fall back to the embedded copy, so the page works both when served and when opened from `file://`. Show `app.commit` and `generatedAt` in the header.
2. **Layout.** All nodes visible at all times, arranged in columns (or rows on narrow screens) by `layers` order, grouped by `group` within a layer. Node cards show `label`, `type` and a one-line `description` on hover. Edges are SVG paths between cards.
3. **Flow picker.** A sidebar listing flows grouped by `category`, with a text filter. Selecting a flow: dims nodes and edges not in the flow, draws its steps as numbered arrows, and shows the trigger and summary.
4. **Step annotations.** A step panel lists each step: number, `from → to`, `kind`, `label`, `payload` (name plus collapsible pretty-printed `example`), `note`, and `source` as `path:line`. Hovering or selecting a step highlights its arrow. Prev/next buttons and ←/→ keys step through; a play button animates the path.
5. **Branches.** Branch steps render in a distinct style off the step they hang from, with their `label`; toggling a branch shows its path.
6. **Visual encoding with a legend.** One colour per edge `kind`; `async` edges dashed-animated; `confidence: "inferred"` edges dashed grey; `model-decision` edges visibly different from deterministic ones.
7. **Node → flows.** Clicking a node lists every flow that touches it; clicking one selects it.
8. **Deep links.** URL hash reflects state (`#flow=invite-user&step=3`) and is restored on load.
9. **Light and dark** via `prefers-color-scheme`; usable at 1280px wide and readable on a phone.

## 6. Update mode

When `flows.json` exists: read it, keep hand-written `note`s and flows, refresh `app.commit`, re-check every `source` path and line (mark ones that moved or vanished as `inferred` with a note), add the newly requested flows, and regenerate `index.html` from the template already in the folder rather than rewriting its design.

## 7. Verify before reporting

Run this check and fix everything it reports. Adjust `D` to the output folder.

```bash
set -euo pipefail
D="docs/flows"
python3 - "${D:?}" <<'EOF'
import json, os, re, sys
d = sys.argv[1]
data = json.load(open(os.path.join(d, "flows.json")))
html = open(os.path.join(d, "index.html")).read()
m = re.search(r'<script type="application/json" id="flows-data">(.*?)</script>', html, re.S)
errs = []
if not m or json.loads(m.group(1)) != data:
    errs.append("embedded JSON in index.html does not match flows.json")
layers = {l["id"] for l in data["layers"]}
nodes = {n["id"]: n for n in data["nodes"]}
for n in nodes.values():
    if n["layer"] not in layers: errs.append(f"node {n['id']}: unknown layer {n['layer']}")
    if not os.path.exists(n["path"]): errs.append(f"node {n['id']}: path missing {n['path']}")
used = set()
for f in data["flows"]:
    steps = f["steps"] + [s for b in f.get("branches", []) for s in b["steps"]]
    for b in f.get("branches", []):
        if not 1 <= b["atStep"] <= len(f["steps"]): errs.append(f"{f['id']}: branch atStep out of range")
    for i, s in enumerate(steps, 1):
        for end in ("from", "to"):
            if s[end] not in nodes: errs.append(f"{f['id']} step {i}: unknown node {s[end]}")
            used.add(s[end])
        if s.get("confidence", "traced") == "traced":
            p, _, line = s.get("source", "").rpartition(":")
            if not p or not os.path.exists(p): errs.append(f"{f['id']} step {i}: source missing {s.get('source')}")
            elif not line.isdigit() or int(line) > sum(1 for _ in open(p, errors="ignore")): errs.append(f"{f['id']} step {i}: bad line {s.get('source')}")
for n in sorted(set(nodes) - used):
    print(f"warning: node {n} appears in no flow")
print("\n".join(errs) or f"ok: {len(nodes)} nodes, {len(data['flows'])} flows")
sys.exit(1 if errs else 0)
EOF
```

Then, if a headless browser is available (gstack `/browse`, Playwright MCP), open `index.html`, select every flow and step through one end to end, and confirm there are no console errors and every step arrow lands on the right cards. If no browser is available, say so in the report instead of claiming the page was checked.

## 8. Report

State: output paths, detected kind(s), node and flow counts, the number of `inferred` steps (and which flows hold them), and the command to open the page (`open docs/flows/index.html`).
