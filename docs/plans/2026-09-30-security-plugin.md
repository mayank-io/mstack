---
title: Security plugin — agent-config lock, commit gate, checklist audit, live probe
status: draft
created: 2026-09-30
source: "saed (Senior Security Engineer, Google) — '30 doors I'd try first on your vibe-coded app', LinkedIn, 2026-09-29"
---

# Security plugin — agent-config lock, commit gate, checklist audit, live probe

## 1. Objective

Decide what mstack should add so that apps and agent setups built with Claude Code pass saed's 30-item pre-launch checklist ("Securitymaxxxing", §8.1) — without duplicating the security-review skills already installed on this machine.

## 2. Key findings

1. **gstack `cso` already covers most of the static checklist.** Its 14 phases include Secrets Archaeology (2), Dependency Supply Chain (3), Webhook & Integration Audit (6), LLM & AI Security (7), Skill Supply Chain (8) and OWASP Top 10 (9). It is an LLM-driven, point-in-time audit. A second static LLM auditor in mstack would be redundant.
2. **`cso` deliberately makes no live requests** — Phase 6 reads "code-tracing only — NO live requests". Items that can only be proven against a running app (ID swapping, unauthenticated routes, rate limits, error leakage) are covered by nobody.
3. **Nothing detects *change* in agent config.** `cso` Phase 8 pattern-scans skills once. No tool records what the agent config looked like yesterday and flags what moved — the gap a commenter on the source post named: "Is there tooling yet that diffs a SKILL.md or MCP config against its last-known version, the way a lockfile diff catches a changed dependency?"
4. **The surface is large and unreviewed.** Measured 2026-09-30 on this machine: 307 `SKILL.md` files and 110 hook scripts (23 `hooks.json`) under `~/.claude/plugins/`, 54 enabled plugins, 10 MCP servers (3 user-scoped, 7 project-scoped). 7 plugin hook scripts reference `curl`, `wget`, `nc`, `ssh` or `eval` — not evidence of malice, but exactly the set a reviewer should see first. Plugins auto-update (`autoUpdate: true`), so any of these can change without a human reading the diff.
5. **Nothing prevents a secret reaching a commit.** `gitleaks` is not installed; no mstack hook inspects staged content. `cso` finds secrets after the fact, in history, where item 3 of the checklist says the key is already burned.
6. **The permission allow list grants broad reach.** 97 entries; 3 give unscoped network or deploy reach: `Bash(curl:*)`, `Bash(gh api:*)`, `Bash(vercel:*)`. `ccimprove:clean-permissions` removes cruft but does not assess reach. Note this session ran in bypass-permissions mode, where the allow list is not consulted at all — the audit must say so when it detects it.

## 3. Recommendation

Add a `security` plugin to mstack that does only what `cso` does not — **change detection, prevention, and live verification** — and let `cso` remain the deep static audit.

| # | Component | Checklist items | Why it is not `cso` |
|---|---|---|---|
| 1 | `security:agent-config-lock` skill + SessionStart hook | 25, 26 | Baseline + diff over time; `cso` is point-in-time |
| 2 | `ccimprove:clean-permissions` — reach assessment | 26 | Extends an existing skill; `cso` does not read the allow list's reach |
| 3 | `dev` pre-commit secret gate (PreToolUse hook on `git commit`) | 1, 2, 3 | Prevention before the commit exists; `cso` finds it afterwards |
| 4 | `security:checklist` skill | all 30 | Deterministic PASS / FAIL / MANUAL gate mapped to the checklist; delegates depth to `cso` |
| 5 | `security:probe-app` skill | 6, 7, 11, 12, 16, 21, 27 | Live requests against the user's own app; `cso` forbids them |

**Not built:** a static vulnerability scanner (that is `cso`), cloud-account posture checks for RLS, buckets and spend caps (provider-specific; items 8, 17, 20 surface as MANUAL in `security:checklist` with a one-line verification each).

## 4. Next steps

1. Approve or amend the scope in §3 — in particular whether §5.4 `security:checklist` earns its place given `cso` (§7.1).
2. Write the TDD-tight implementation plan for Milestone M1 (§6).
3. Install `gitleaks` (`brew install gitleaks`) — M2 depends on it.

## 5. Components

### 5.1 `security:agent-config-lock`

**Purpose:** a lockfile for everything that tells an agent what to do or runs on its behalf. Answers "what changed in my agent's instructions and executables since I last looked?"

**Locked surfaces:**

| Surface | Path(s) | Why it matters |
|---|---|---|
| Instructions | `~/.claude/CLAUDE.md`, every project `CLAUDE.md` / `AGENTS.md` on the session's cwd ancestry | Silently steers every action |
| Skills | `SKILL.md` + sibling `scripts/` under `~/.claude/plugins/{cache,marketplaces}/`, `~/.claude/skills/`, project `.claude/skills/` | Loaded on trigger words; scripts executed |
| Hooks | `hooks.json` + referenced scripts in every enabled plugin; `hooks` in `~/.claude/settings.json` and project settings | Run automatically, no model in the loop |
| MCP | `mcpServers` in `~/.claude.json` (user + per-project), project `.mcp.json` | New tools and new network egress |
| Plugins | `enabledPlugins`, `~/.claude/plugins/installed_plugins.json`, `known_marketplaces.json` | New code sources |
| Permissions | `permissions.allow` / `deny`, `defaultMode` | What runs without a prompt |

**Lockfile:** `~/.claude/security/agent-config.lock.json` — one record per file: `{path, surface, sha256, size, mtime_utc, plugin, marketplace, version}`. MCP entries are hashed as the canonical JSON of their server block, so key reordering is not a change. Absolute times are stored and printed as UTC with an explicit `Z`.

**Commands:**

- `lock` — write the baseline. Refuses to overwrite an existing lock without `--accept`, so a compromised session cannot silently re-baseline.
- `diff` — compare the live tree to the lock; print added / removed / modified per surface to stdout, exit 1 on any change. Modified text files show a unified diff.
- `accept <path…>` — move reviewed changes into the lock.

**Risk ranking of a diff (highest first):** new or changed hook script; new MCP server or changed `command` / `url`; new plugin or marketplace; hook or skill script newly containing `curl|wget|nc|ssh|scp|eval|base64 -d|/dev/tcp`, or reads of `~/.ssh`, `~/.aws`, `.env`, keychain; instruction text newly containing "ignore previous", "do not tell the user", or out-of-band URLs; plain SKILL.md prose edits.

**SessionStart hook:** runs `diff`; silent when nothing changed (no log noise). On change, prints one stderr line per surface with counts, and the top-ranked item, and tells the user to run `/security:agent-config-lock` to review. It never blocks the session and never auto-accepts.

**Plugin auto-update interplay:** a marketplace version bump legitimately changes many files at once. The diff groups changes by `plugin@version` so a reviewer sees "fetch 0.17.6 → 0.17.7: 3 SKILL.md modified, 0 scripts" rather than 3 unrelated lines, and can accept a whole plugin version after reading it.

### 5.2 `ccimprove:clean-permissions` — reach assessment

Adds a fourth category to the existing skill's report: **reach**. Entries are classified, not removed:

| Class | Examples | Report |
|---|---|---|
| Unscoped network | `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch(domain:*)` | Suggest domain-scoped variants |
| Deploy / cloud control | `Bash(vercel:*)`, `Bash(aws:*)`, `Bash(gcloud:*)`, `Bash(kubectl:*)`, `Bash(terraform:*)`, `Bash(fly:*)` | Suggest read-only subcommands, or removal |
| Credential stores | anything reading `~/.ssh`, `~/.aws`, `.env*`, `security find-*`, `op ` | Flag as item 26 violation |
| Unscoped API | `Bash(gh api:*)` | Suggest `gh api` GET-only patterns |

It also reports `defaultMode` and whether bypass-permissions is enabled — the allow list is irrelevant in that mode, and the report says so rather than grading entries that are never consulted.

### 5.3 `dev` pre-commit secret gate

A PreToolUse hook on `Bash` that matches `git commit` (and `git push` for already-committed content). It runs `gitleaks protect --staged --redact` against the repo; on a finding it exits 2 with the rule id, file and line (secret redacted) so Claude Code blocks the command and shows why. Absent `gitleaks`, it prints one stderr line saying the gate is inactive — never a silent pass. It also fails when `.env` is tracked or not ignored (item 1). It does not replace the user's own git pre-commit hooks; it covers commits the agent makes.

### 5.4 `security:checklist`

A deterministic script that walks a repo and emits one row per checklist item: `PASS`, `FAIL` (with evidence path:line), `MANUAL` (with the exact check to perform), or `N/A` (with the reason, e.g. "no webhook routes found"). Output is JSON to stdout plus a Markdown table; exit 1 on any FAIL.

| Mechanism | Items |
|---|---|
| File and git inspection | 1 `.env` ignored and never committed (`git log --all -- '*.env*'`), 3 keys in history (gitleaks `detect`), 5 lockfile committed and versions pinned |
| Bundle inspection | 4 build output grepped for key-shaped strings (`sk-`, `AKIA`, `ghp_`, `xox`, Stripe/Supabase service keys) |
| Semgrep (installed) | 13 server validation, 14 string-built SQL, 15 unescaped render, 16 `Access-Control-Allow-Origin: *`, 19 webhook routes without signature verification, 27 stack traces in responses, 28 secrets/PII in log calls |
| Registry lookup | 24 every imported package resolves on its registry (npm / PyPI) — catches hallucinated and slopsquatted names |
| Delegation | 25 and 26 → §5.1 and §5.2 results; 6, 7, 11, 12, 21 → §5.5 when a target is given |
| MANUAL with one-line check | 8 RLS, 9 auth provider, 10 token lifetimes, 17 bucket privacy, 18 upload sandboxing, 20 spend caps, 22 untrusted model input, 23 tool limits, 29 audit log, 30 restore tested |

Every FAIL links the `cso` phase that covers it in depth, so the checklist is the gate and `cso` is the investigation.

### 5.5 `security:probe-app`

Live checks against **the user's own app only**. Requires an explicit `--target` URL; refuses anything not `localhost`, `127.0.0.1`, a `*.local` / `*.internal` host, or a host listed in the repo's `.security/targets` file. Two test accounts are supplied by the user (`--user-a`, `--user-b` credential files); the skill never creates accounts or brute-forces.

| Check | Method | Item |
|---|---|---|
| Unauthenticated routes | Enumerate routes from the framework's route table; call each without a session; any 2xx on a non-public route is FAIL | 6 |
| ID swapping (IDOR) | As A, capture resource ids; as B, request A's ids; any 2xx returning A's data is FAIL | 7 |
| Admin checks | As a non-admin, call admin routes | 11 |
| Rate limits | Bounded burst (default 30 requests) at login, signup, reset and AI endpoints; no 429 or backoff is FAIL | 12, 21 |
| CORS | `Origin: https://evil.example` preflight; reflected or `*` with credentials is FAIL | 16 |
| Error leakage | Malformed bodies; stack frames, file paths or framework banners in the response are FAIL | 27 |

Request volume is capped and printed before the run; there is no fuzzing and no payload library.

## 6. Milestones and streams

| Milestone | Ships | Acceptance |
|---|---|---|
| **M1 — Agent config is locked** | §5.1 skill, script and SessionStart hook; §5.2 reach category | `lock` on this machine records all surfaces in §5.1; editing one SKILL.md, adding one dummy MCP server and adding one hook script each produce exactly one ranked diff entry; the SessionStart hook prints nothing on an unchanged tree; clean-permissions reports the 3 reach entries in §2.6 |
| **M2 — Secrets cannot be committed by the agent** | §5.3 hook | A staged fake AWS key blocks `git commit` with exit 2 and a redacted finding; a tracked `.env` blocks; a clean commit passes; missing `gitleaks` prints the inactive warning |
| **M3 — The checklist is a gate** | §5.4 | On a seeded fixture repo with one planted defect per automatable item, every planted item is FAIL with the right path:line and every other automatable item is PASS; items listed as MANUAL are MANUAL |
| **M4 — The app is probed** | §5.5 | Against a fixture app with a planted IDOR, an unauthenticated route, no rate limit, wildcard CORS and a leaking error handler, each is FAIL; the fixed variant is all PASS; a non-allowlisted target is refused |

**Streams:** M1 and M2 are independent and can run in parallel. M3 consumes M1's and M2's outputs for items 1–3, 25 and 26 but can start its semgrep and registry streams immediately. M4 is independent of M3 except for the delegation rows in §5.4.

## 7. Open questions

1. **Does §5.4 earn its place next to `cso`?** Argument for: deterministic, fast, CI-able, maps 1:1 to a checklist people share. Argument against: overlaps `cso` Phases 2, 3, 6, 9 in substance. Deferring it to after M4 costs nothing, since M1, M2 and M4 are the parts nothing else covers.
2. **Where does the lockfile live for project-scoped config?** User-level (§5.1) catches everything but mixes projects; a per-repo `.claude/agent-config.lock.json` could be committed and reviewed in PRs. Possibly both.
3. **Plugin placement.** A new `security` plugin versus folding §5.1 into `ccimprove` (which already owns plugin-cache hygiene). Recommendation: new plugin — security findings should not share a namespace with cache pruning.

## 8. Appendix

### 8.1 The source checklist

saed, "My job at Google is thinking like an attacker…", LinkedIn, posted 2026-09-29 10:10 UTC; vault clipping `Clippings/@saedf - 30 security doors to check in a vibe-coded app.md`.

| Group | Items |
|---|---|
| Before you push | 1 `.env` in `.gitignore` · 2 Gitleaks pre-commit · 3 rotate any key that touched GitHub · 4 no API keys in the frontend bundle · 5 pin versions, commit lockfile |
| Auth & access | 6 auth on every API route · 7 change the ID in the URL · 8 RLS on every table · 9 real auth provider · 10 short-lived tokens, revoke refresh on logout · 11 admin checks server-side · 12 rate-limit login, signup, reset |
| Input & data | 13 server-side validation · 14 parameterised queries · 15 escape user content · 16 CORS locked to own domains · 17 private buckets · 18 sandboxed upload processing · 19 verify webhook signatures |
| AI & agents | 20 hard spend caps · 21 rate-limit AI endpoints · 22 model input is untrusted · 23 limit tools, SQL, shell · 24 check suggested packages exist · 25 read every CLAUDE.md, SKILL.md, MCP config like code · 26 keep prod credentials out of the agent's reach |
| When it breaks | 27 generic errors, no stack traces · 28 strip secrets and PII from logs · 29 audit trail · 30 test a restore |

Additions raised in the post's comments: treat anything ever committed as public forever; egress / SSRF controls on agent tools; honeypot keys that alert on use.

### 8.2 Measurement commands (2026-09-30)

```bash
find ~/.claude/plugins -name SKILL.md | wc -l                                # 307
find ~/.claude/plugins -name hooks.json | wc -l                              # 23
find ~/.claude/plugins -path '*/hooks/*' -type f \( -name '*.sh' -o -name '*.py' -o -name '*.js' -o -name '*.ts' \) | wc -l   # 110
find ~/.claude/plugins -path '*/hooks/*' -name '*.sh' | xargs grep -lE "curl|wget|nc |ssh |eval " | wc -l                   # 7
# MCP servers: ~/.claude.json mcpServers (3) + projects.*.mcpServers (7); enabledPlugins in ~/.claude/settings.json (54)
```

### 8.3 `cso` coverage map

Read from `~/.claude/skills/gstack/cso/SKILL.md` and `sections/audit-phases.md`: Phase 0 architecture, 1 attack surface, 2 secrets archaeology, 3 dependency supply chain, 4 CI/CD, 5 infrastructure, 6 webhooks (code-tracing only), 7 LLM & AI, 8 skill supply chain (point-in-time pattern scan, global scope opt-in), 9 OWASP Top 10, 10 STRIDE, 11 data classification, 12 false-positive filtering, 13 report, 14 save.
