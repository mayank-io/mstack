---
name: check-name
description: "Check whether a candidate company name is available across USPTO trademarks, WA Secretary of State, and major domain TLDs. Use when the user asks to check, verify, clear, or sweep a name for an LLC, corp, brand, trademark, or domain — anything that needs to be unique before filing."
---

# Check Name Availability

Run an aggregated availability sweep on a candidate company name across three sources and produce a single markdown report. The report drives a real filing decision — accuracy over speed.

## When to invoke

The user asks any of:
- "Is `<name>` available?"
- "Can I file `<name>` as an LLC?"
- "Check trademark on `<name>`"
- "Is `<name>.com` taken?"
- "Run availability checks on `<name>`"
- "Clear `<name>` for me"

## Arguments

Parse from `$ARGUMENTS`:

- **Candidate name** (positional, required) — the bare candidate. Can be one or more words. Quote if it contains spaces.
- `--systems <csv>` (optional) — subset of `uspto,wa-sos,domain`. Default: all three.
- `--class <csv>` (optional) — USPTO class filter, e.g. `35,42`. Default: no class filter (all classes).
- `--json` (optional) — emit machine-readable JSON instead of markdown.
- `--refresh` (optional) — bypass cache.

If the candidate name is missing or ambiguous, ask the user before invoking.

## Prerequisites

This skill delegates all browser interactions to **gstack `browse`** — a single shared browser daemon that handles Cloudflare Turnstile, stealth, and headed/headless mode. No `npm install` is required.

Verify gstack is installed:

```bash
ls "$HOME/.claude/skills/gstack/browse/dist/browse" && echo READY || echo MISSING
```

If `MISSING`, tell the user: "This skill requires gstack to be installed. Install it from https://github.com/garryslist/gstack and run its setup." STOP.

## Run

```bash
cd "${CLAUDE_PLUGIN_ROOT}/scripts"
node cli.mjs "<candidate-name>" [flags...]
```

The CLI writes:
- **stdout**: the markdown report (or JSON if `--json`)
- **stderr**: progress notes (one line per source)

Show the stdout report verbatim to the user.

## Interpreting the result

The report ends with an `Overall verdict` line — one of:

| Verdict | What to recommend |
| --- | --- |
| `available` | Encourage the user to file. Flag any caveats from the per-source notes. |
| `crowded` | Show the table and the specific collisions. Ask the user whether they want to proceed despite the noise or try alternates. |
| `blocked` | Recommend dropping this candidate. Show the blocking entry. Offer to run the same check on alternates. |
| `inconclusive` | Some source returned a block (e.g., WAF). Explain which one and what manual step would resolve it. Do NOT treat as available. |

## Headed-mode requirement

The WA SoS check launches a **visible Chromium window** during its run because Cloudflare Turnstile won't auto-resolve in headless mode. This is by design — the script returns silent false negatives without it. If the user objects to the visible window, suggest running `--systems uspto,domain` only.

## When the script fails

If a source returns `status: error`, read the matching playbook in `${CLAUDE_PLUGIN_ROOT}/playbooks/<source>.md` and re-derive the working procedure by hand. The playbook documents element semantics, gotchas, and the Angular scope keys / API response shapes. Once the manual procedure works again, patch the script in `${CLAUDE_PLUGIN_ROOT}/scripts/sources/<source>.mjs` and bump its `LAST_VERIFIED` constant.

## Output paper trail

If the user is doing this for a real filing decision (not casual exploration), offer to save the report to `internal/research/name-checks/<slug>-<YYYY-MM-DD>.md` in the current project for later reference.
