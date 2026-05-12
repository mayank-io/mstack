# company-setup

Tools for forming a company. The first skill — `check-name` — runs an availability sweep on a candidate company name across:

- **USPTO trademark database** (tmsearch.uspto.gov) — federal trademarks in your target classes
- **Washington State Secretary of State** (ccfs.sos.wa.gov) — registered LLCs and corps
- **Domain registrars** (.com, .io, .co, .ai) — via RDAP

Output is a single markdown report with per-source findings and an overall verdict (`available` / `crowded` / `blocked` / `inconclusive`).

## Why this exists

Name availability checks are slow and easy to do wrong. Both target sites are JavaScript SPAs over JSON APIs — naive `curl` or `WebFetch` returns shell HTML with no data. The WA SoS specifically gates its API with Cloudflare Turnstile + AWS WAF, which silently returns 0 results in headless mode (false negatives).

This skill encodes the procedures that actually work — headed Chromium where required, network-response interception for the USPTO SPA, RDAP for domains — and bundles the human-readable playbooks alongside the scripts so the procedures can be re-derived when site selectors break.

## Install

This plugin lives in [mstack](https://github.com/mayank-io/mstack). Install via the mstack marketplace:

```
/plugin install mstack:company-setup
```

First run will install Playwright + the Chromium browser (~150MB, one-time).

## Usage

```
/check-name solidus
/check-name "solidus tech advisory"
/check-name solidus --systems uspto,wa-sos       # subset
/check-name solidus --class 42                    # USPTO class filter
/check-name solidus --json                        # machine-readable output
```

## Output

A markdown table with per-source results, a risk summary, and a recommendation. When a source comes back `inconclusive` (e.g., WAF block), it's flagged honestly — the skill never silently treats a block as a clean result.

## How it works

| Source | Approach | Mode |
| --- | --- | --- |
| USPTO | Playwright + network response interception | Headless OK (Chrome UA) |
| WA SoS | Playwright + Angular scope read | **Headed required** (Turnstile auto-resolves only with a visible window) |
| Domain | RDAP HTTP fetch | No browser |

See `playbooks/` for the human-readable procedures the scripts encode. When selectors break, an agent can re-drive the playbook manually and patch the script.

## License

MIT
