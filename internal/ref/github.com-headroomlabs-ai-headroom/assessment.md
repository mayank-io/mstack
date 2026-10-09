---
title: Headroom (headroomlabs-ai/headroom) — egress and dependency assessment
source: https://github.com/headroomlabs-ai/headroom
commit: 17abee2 (committed 2026-10-08 14:22:21 -0500)
researched: 2026-10-09
status: reference
---

# Headroom — egress and dependency assessment

## 1. Objective

Answer two questions about Headroom, a context-compression layer for AI agents (library, local proxy, `headroom wrap claude`, MCP server): does it send data off the machine to the publisher, and what models and helper programs does it download and run? Every finding below was verified against the source at commit `17abee2`, not just the README.

## 2. Key Findings

- **Prompt and file content stays local.** Compression runs on-device. No prompt, completion, code, tool result or file path appears in any payload sent to Headroom Labs (§4.2).
- **An anonymous telemetry beacon is ON by default (opt-out).** It POSTs session counters to `https://headroom-beacon.headroom-beacon.workers.dev/v1/logs`, a Cloudflare Worker run by Headroom Labs (§4.1).
- **The opt-out fails open.** An unrecognised `HEADROOM_BEACON` value (e.g. `none`) still uploads. Use an exact off value, `DO_NOT_TRACK=1`, or `HEADROOM_OFFLINE=1` (§4.3).
- **Kompress, the AI text compressor, is on by default in the proxy.** It is a model trained by the author (`chopratejas/kompress-v2-base`), downloaded from Hugging Face on first use, and it is the lossy step that drops detail (§5.1).
- **Supply-chain hygiene is decent.** Hugging Face models are pinned to commit SHAs, and downloaded programs are checked against SHA-256 hashes in `tools.json` (§5.1, §5.2).
- **The main trust cost is placement.** `wrap claude` puts a fast-moving proxy in the path of every request, with your API token and all your content, and it rewrites requests (§6).

## 3. Recommendation

1. If you try it, start small: use the library or MCP server on one heavy workflow (large logs, JSON tool output), not `wrap claude` across the board.
2. Run with `HEADROOM_OFFLINE=1` and a pinned package version, with the models downloaded ahead of time (§5.1).
3. To avoid the opaque lossy step, add `--disable-kompress` (`HEADROOM_DISABLE_KOMPRESS=1`). This keeps the rule-based compressors (JSON, logs, diffs, search results), which have no model.
4. Compare token counts and answer quality before any wider rollout.

## 4. Network egress

### 4.1 Egress table

Beyond your configured LLM providers:

| Destination | What is sent / fetched | Default | Disable |
|---|---|---|---|
| `headroom-beacon.headroom-beacon.workers.dev` | Anonymous session counters (§4.2) | **On** | `HEADROOM_BEACON=off`, `DO_NOT_TRACK=1`, `HEADROOM_OFFLINE=1` |
| `pypi.org` | Daily version check | On | `HEADROOM_UPDATE_CHECK=off`. Also skipped in `--stateless`, in CI, and from source checkouts |
| `huggingface.co` | Model downloads (§5.1) | First use of an ML feature | Download ahead of time, then `HEADROOM_OFFLINE=1` |
| `github.com` | Helper program downloads (§5.2) | Only with opt-in features | `HEADROOM_BINARIES_MIRROR`, or don't enable them |
| `app.headroomlabs.ai` | License validation and usage reporting | Only when a license key is set | Omit the license key |
| `api.headroomlabs.ai` | Paid cloud compression (ASGI / LiteLLM integrations) | Only when `HEADROOM_API_KEY` is set | Don't set it |

Sources: `sources/security-model.mdx` ("Network egress"), `headroom/telemetry/session.py:131` (`DEFAULT_ENDPOINT`), `session.py:1714` (`HEADROOM_TELEMETRY_ENDPOINT` override), `headroom/integrations/asgi.py:41,81-84`, `headroom/proxy/models.py:479`.

### 4.2 Beacon payload

Each report is a cumulative snapshot of the session:

- **Session:** a random ID, a sequence number, duration, turn count, and a final-report flag.
- **Tokens:** original, attempted, input, output, saved, cache read/write and uncached counts, plus derived percentages.
- **Compression:** counts per transform and per skipped transform, a per-strategy breakdown, latency and overhead in ms, pass-through turns, and response-cache hits.
- **Context:** request source (`proxy`/`mcp`), the provider and model names seen, and failure counts by HTTP status code.
- **Resource attributes:** a random per-install UUID (in `<config dir>/install_id`; delete it to reset), Headroom version, OS, CPU architecture, install mode and detected stack.
- **Config values:** a fixed list of 15 `HEADROOM_*` settings with small closed value sets, such as mode, profile and CCR backend (`session.py:346-372`). Each value passes through `_safe_slug`, so a value that holds a path or URL is reported as `"other"`.

The receiver's code is in `deploy/beacon/worker.js` in the upstream repo. `headroom telemetry --show` prints the exact payload.

### 4.3 Switch semantics

From `sources/beacon.py`:

- `BEACON_DEFAULT_ON = True` is a single constant that sets the policy.
- Order of checks: offline mode → `DO_NOT_TRACK` (any value except an off value disables) → `HEADROOM_BEACON` off values (`off/false/0/no/disable/disabled`) → on values → the default.
- **Fails open:** a `HEADROOM_BEACON` value that is neither on nor off falls through to `True` and uploads.
- `HEADROOM_TELEMETRY` is a separate switch. It is opt-in, fails closed, and is local only: it powers `/stats` and the dashboard and sends nothing outside the machine. Turning it on does not enable the beacon, and turning it off does not stop the beacon.
- A startup notice discloses the beacon unless `HEADROOM_TELEMETRY_WARN=off`.

## 5. Downloaded models and programs

### 5.1 Hugging Face models

| Model | Purpose | When it is downloaded |
|---|---|---|
| `chopratejas/kompress-v2-base` (ONNX: `kompress-int8.onnx`, `-fp32`, etc.) + `answerdotai/ModernBERT-base` (its tokenizer) | **Kompress:** decides which tokens to keep or drop in prose and logs. **Lossy.** | **On by default** in the proxy (`proxy/models.py:238`, `disable_kompress: bool = False`). It is the fallback for text no rule-based compressor handles |
| `chopratejas/technique-router-onnx` (~100 MB) + `chopratejas/siglip-image-encoder-onnx` (~95 MB) | Image compression: classifies an image and picks how to shrink it | Only when image compression is enabled |
| `BAAI/bge-small-en-v1.5` (~30 MB; fastembed uses `qdrant/bge-small-en-v1.5-onnx-q`) | Embeddings for relevance ranking | When relevance ranking is used |
| `Qdrant/all-MiniLM-L6-v2-onnx` | Local embeddings for cross-agent memory | When memory is used |
| Tokenizer files for Qwen, Gemma, Phi-3, etc. (`tokenizers/huggingface.py`) | Token counting for those model families | Only when routing to those families. Tokenizer files only, not model weights |

`chopratejas` is the author's personal Hugging Face account, so the default compressor is a model trained by one person, not a widely reviewed one.

Pinning: `headroom/onnx_runtime.py:68-83` pins Kompress, ModernBERT, technique-router, SigLIP and MiniLM to commit SHAs (`sources/onnx_runtime.py-hf-pins.excerpt`). `relevance/embedding.py:116-125` pins the default bge model. Repos not in the list fall back to the latest version. `HEADROOM_HF_PIN=off` turns pinning off; keep it unset.

### 5.2 GitHub programs (`headroom/tools.json`, SHA-256 hashed per platform)

| Tool | Version | What it is |
|---|---|---|
| `difft` (difftastic) | 0.64.0 | Diff tool that understands code structure |
| `scc` | 3.5.0 | Line counts and code complexity |
| `codebase-memory-mcp` (DeusData) | v0.8.1 | MCP server that builds a code graph. Installs to `~/.local/bin`. Hash-checked via `binaries.verify_download_bytes` (`graph/installer.py:119`) |
| `ast-grep` | PyPI (`ast-grep-cli`) | Code search that understands syntax. Never fetched from GitHub; Headroom only checks your PATH |

All three GitHub tools have macOS builds (`darwin-aarch64`, `darwin-x86_64`) in the registry.

**When they are fetched:** the docstring of `ensure_tools()` (`binaries.py:636-640`) says it runs "at proxy startup and on first `headroom` CLI invocation". The only call found is behind the opt-in `--intercept-tool-results` flag (`cli/proxy.py:1275`). `ensure_cbm()` has no caller in `headroom/` beyond its definition. With default settings, a plain proxy run does not appear to download any programs.

## 6. Usage risks (beyond egress)

- **Placement:** `headroom wrap claude` routes every Claude Code request through a local proxy. That proxy holds your API token, sees all content, and rewrites requests. Some rewrites are on by default, such as tool search on Anthropic requests.
- **Pace of change:** the project changes fast (last commit 2026-10-08), which is a large trust surface for something in that position.
- **Lossy compression:** CCR keeps originals locally and lets the model retrieve them, but Kompress and the output trimming drop detail. When the model misses something, it is hard to trace back to compression.
- **Limited savings on a subscription:** on a Claude subscription the main gain is rate-limit headroom, not cost. Claude Code already uses prompt caching and compacts long sessions.
- **Config edits:** `wrap` changes agent settings (undo with `headroom unwrap <tool>`). `headroom learn` writes to `CLAUDE.local.md` by default, or to `CLAUDE.md`/`AGENTS.md` with `--target`. Either can clash with a hand-managed `~/.claude` setup.

## 7. Appendix

### 7.1 Method

1. Shallow-cloned the repo at `17abee2`.
2. Searched for telemetry keywords and hard-coded URLs across `headroom/`, `crates/*/src` and `sdk`.
3. Listed every outbound HTTP call in `headroom/` that is not the proxy forwarding to your LLM.
4. Read `telemetry/beacon.py` in full, plus the endpoint and settings-list sections of `telemetry/session.py`.
5. Traced each Hugging Face model ID and each `tools.json` entry to the code that uses it.

### 7.2 Local source snapshots (`sources/`)

| File | Content |
|---|---|
| `security-model.mdx` | Upstream security model doc, including the network egress table and beacon section |
| `SECURITY.md` | Upstream security policy |
| `beacon.py` | Full beacon and telemetry switch logic |
| `session.py-endpoint.excerpt` | `DEFAULT_ENDPOINT` (lines 120-140) and the settings allowlist `_CONFIG_ENV_KEYS` (lines 340-372) |
| `onnx_runtime.py-hf-pins.excerpt` | Hugging Face commit-SHA pin table (lines 60-90) |
| `tools.json` | Program registry with versions and per-platform SHA-256 hashes |

### 7.3 Not verified

- What the receiver (`deploy/beacon/worker.js`) keeps or stores server-side.
- The Rust proxy crate (`crates/headroom-proxy`) was keyword-searched only, not audited line by line.
- Kompress model size and accuracy claims.
- Whether the `api.headroomlabs.ai` cloud mode sends content. Presumably it does, since it is a managed compression service, but it is off without an API key.
