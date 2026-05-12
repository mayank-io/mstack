# WA Secretary of State — Business Entity Name Search Playbook

**Last verified:** 2026-05-12 (headed-mode procedure verified end-to-end)
**Purpose:** Check whether a proposed LLC/corp name is distinguishable from existing active WA entities before filing.

---

## Direct URLs

| Resource | URL |
| --- | --- |
| WA SoS CCFS home (Quick Search) | https://ccfs.sos.wa.gov/#/ |
| WA SoS CCFS Advanced Search | https://ccfs.sos.wa.gov/#/AdvancedSearch |
| WA SoS CCFS Business Search results | https://ccfs.sos.wa.gov/#/BusinessSearch |
| WA SoS CCFS underlying API | https://ccfs-api.prod.sos.wa.gov/api/BusinessSearch/GetBusinessSearchList |
| WA DOR Business Lookup (fallback) | https://secure.dor.wa.gov/gteunauth/_/ → "Business Lookup" |
| OpenCorporates WA (third-party mirror, can be stale) | https://opencorporates.com/companies/us_wa?q={name} |
| WA naming-rule statute | https://app.leg.wa.gov/RCW/default.aspx?cite=23.95.305 |
| Permitted-names statute | https://app.leg.wa.gov/RCW/default.aspx?cite=23.95.300 |
| Direct UBI lookup URL | https://ccfs.sos.wa.gov/#/BusinessSearch/BusinessInformation/{UBI} |

The CCFS routes use hash-based SPA routing — the URL does NOT carry per-query state. Search criteria lives in Angular scope. Deep-link per query is not possible; you must drive the UI.

---

## Critical gotcha — Cloudflare Turnstile + AWS WAF

The CCFS search API is gated by **both** Cloudflare Turnstile (`cf-turnstile-response` token) **and** AWS WAF (`AwsWafIntegration` token).

**In headless mode**, both challenges fail to resolve. Symptoms:
- `input[name="cf-turnstile-response"]` stays empty
- `POST .../GetBusinessSearchList` returns HTTP 400 with body `"System verification in progress, please wait."`
- The UI displays "No Value Found" — **indistinguishable from a real zero-results match**
- The Search button shows `[disabled]` in the ARIA tree forever

**In headed mode**, Turnstile auto-resolves within ~5 seconds. The Search button enables. The API returns real data.

**Conclusion: always use headed mode for this site.** The headless path is a trap that produces silent false negatives.

---

## Primary procedure — headed mode via gstack `browse`

```bash
B="/Users/mayank/.claude/skills/gstack/browse/dist/browse"

# 1. Disconnect any existing headless daemon (idempotent)
$B disconnect 2>/dev/null

# 2. Launch headed server (a real Chromium window opens on screen)
$B --headed status   # confirms Mode: headed

# 3. Navigate
$B --headed goto "https://ccfs.sos.wa.gov/"
$B --headed wait --networkidle
sleep 3   # allow Turnstile background resolve

# 4. Find the Business Name textbox + Search button (refs change per session)
$B --headed snapshot -i | grep -E "Business Name|Search"
# Typical refs:  @e8 = Business Name textbox, @e10 = Search button

# 5. Fill and wait for Turnstile to enable the button
$B --headed fill @e8 "<candidate-name>"
sleep 5    # Turnstile resolution takes a few seconds
$B --headed snapshot -i | grep "@e10"     # confirm Search no longer shows [disabled]

# 6. Verify the Turnstile token (optional sanity check)
$B --headed js "document.querySelector('input[name=\"cf-turnstile-response\"]')?.value?.length"
# > 0 means token resolved

# 7. Submit
$B --headed click @e10
$B --headed wait --networkidle 2>&1 || true   # may timeout — that's OK
sleep 3

# 8. Read result count from Angular scope
$B --headed js "(function(){var s=angular.element(document.querySelector('[ng-init=\"initBusinessSearch()\"]')).scope(); return JSON.stringify({total: s?.totalCount, page: s?.page, pages: s?.pagesCount});})()"
# → {"total":10,"page":0,"pages":1}

# 9. Read entity records (key fields only)
$B --headed js "(function(){var s=angular.element(document.querySelector('[ng-init=\"initBusinessSearch()\"]')).scope(); return JSON.stringify(s.businessList.map(b=>({Name:b.BusinessName||b.Name||b.EntityName, UBI:b.UBINumber||b.UBI||b.UBIID, Type:b.BusinessType, Status:b.BusinessStatus||b.Status, City:b.PrincipalOffice?.PrincipalStreetAddress?.City})));})()"
```

**Note:** `--headed` flag must be passed on **every** subsequent command — the daemon will refuse if the global flag mismatches its launch mode.

---

## Sanity check protocol

Before trusting any 0-result match, run:

```bash
$B --headed goto "https://ccfs.sos.wa.gov/"
sleep 3
$B --headed snapshot -i | grep -E "Business Name"
$B --headed fill @e8 "MICROSOFT"
sleep 5
$B --headed click @e10
sleep 3
$B --headed js "(function(){var s=angular.element(document.querySelector('[ng-init=\"initBusinessSearch()\"]')).scope(); return s?.totalCount;})()"
# expect ≥ 30
```

If `MICROSOFT` returns 0, the Turnstile didn't resolve — close the window, disconnect, relaunch.

---

## Worked example — searching "Solidus" on 2026-05-12

Full 10-result list (post headed-mode rerun):

| # | Entity Name | UBI | Type | Status | City |
| --- | --- | --- | --- | --- | --- |
| 1 | SOLIDUS DEVELOPMENTS, LLC | 603 093 207 | WA LLC | Administratively Dissolved | Mercer Island |
| 2 | SOLIDUS FABRICATION AND DESIGN LLC | 605 022 472 | WA LLC | Active | Carnation |
| 3 | SOLIDUS GROUP, LLC | 603 298 877 | Foreign LLC | Terminated | Buffalo NY |
| 4 | SOLIDUS HOLDINGS LLC | 605 617 718 | WA LLC | Active | Nine Mile Falls |
| 5 | SOLIDUS LLC | 603 009 388 | WA LLC | Inactive (2011) | Redmond |
| 6 | SOLIDUS SALES LLC | 605 614 797 | WA LLC | Administratively Dissolved | Spokane |
| 7 | SOLIDUS SOFTWARE, INC. | 602 768 500 | WA Corp | Administratively Dissolved | Bothell |
| 8 | SOLIDUS TECHNICAL SOLUTIONS, INC. | 603 148 189 | Foreign Corp | Terminated | (n/a) |
| 9 | SOLIDUS TECHNICAL SOLUTIONS, LLC | 604 976 262 | Foreign LLC | **Active** | Leominster MA |
| 10 | SOLIDUS, LLC | 604 675 709 | WA LLC | **Active** | Spokane |

Variant searches:

| Query | totalCount | Active matches |
| --- | --- | --- |
| `Solidus` | 10 | 4 |
| `Solidus Tech` | 2 | 1 (SOLIDUS TECHNICAL SOLUTIONS, LLC) |
| `Solidus Tech Advisory` | 0 | — |
| `Solidus Advisory` | 0 | — |
| `Solidus CTO` | 0 | — |

The Quick Search match type is **Contains** (substring match). For exact match, use Advanced Search.

---

## WA naming rules (RCW 23.95.305)

A name is **NOT distinguishable** from an existing active entity merely by:
- Different entity designator (LLC vs L.L.C. vs Corp vs Inc)
- Articles or conjunctions ("The", "and", "&")
- Punctuation, capitalization, or special characters
- Numerals vs spelled-out numbers ("3" vs "Three")
- Pluralization or possessive ("s", "'s")

A name **IS distinguishable** if it adds substantive, meaningful words.

**Concrete implication for "Solidus":**
- Bare "Solidus LLC" is BLOCKED — collides with active "SOLIDUS, LLC" (the comma is punctuation, not a distinguisher).
- "Solidus Tech Advisory LLC" likely passes distinguishability — adds two substantive words.
- "Solidus Tech LLC" alone is too close to active SOLIDUS TECHNICAL SOLUTIONS, LLC and Solidus Technical Solutions's federal Class 042 trademark.

LLC name must contain one of: "Limited Liability Company", "Limited Liability Co.", "L.L.C.", "LLC".

---

## Advanced Search workflow

Use when you need filters for Business Type, Status, formation date range, or registered agent. Same headed-mode requirement.

```bash
$B --headed goto "https://ccfs.sos.wa.gov/#/AdvancedSearch"
$B --headed wait --networkidle
sleep 3
$B --headed snapshot -i
# Field map (refs from 2026-05-12 — re-snapshot each session):
#   @e1   Business Type dropdown  (leave blank for ALL)
#   @e50  Business Name textbox   (fill the candidate)
#   @e51  Expiration Date         (leave blank)
#   @e52  Business Status         (leave blank for ALL)
#   @e68  Formation Start Date    (leave blank)
#   @e69  Formation End Date      (leave blank)
#   @e70  Registered Agent radio  (default checked)
#   @e71  Governor radio
#   @e79  Search button
#   @e80  Clear
#   @e81  Return to Home

$B --headed fill @e50 "<candidate-name>"
sleep 5   # Turnstile
$B --headed click @e79
sleep 3
# Read scope as in Quick Search
```

### Business Status options
ACTIVE, ACTIVE PENDING, ADMINISTRATIVELY DISSOLVED, CONSOLIDATED, CONVERTED, DELINQUENT, DOMESTICATED, EXPIRED, INACTIVE, JUDICIALLY DISSOLVED, MERGED, TERMINATED, VOLUNTARILY DISSOLVED, WITHDRAWN.

### Business Type options (relevant subset)
- WA LIMITED LIABILITY COMPANY (the target for a fractional CTO LLC)
- WA PROFESSIONAL LIMITED LIABILITY COMPANY
- WA PROFIT CORPORATION
- WA SOCIAL PURPOSE CORPORATION
- WA NONPROFIT CORPORATION
- FOREIGN LIMITED LIABILITY COMPANY (out-of-state LLC registered in WA)

---

## Reading pagination + total counts

```bash
$B --headed js "(function(){var s=angular.element(document.querySelector('[ng-init=\"initBusinessSearch()\"]')).scope(); return JSON.stringify({total: s?.totalCount, pages: s?.pagesCount, page: s?.page});})()"
```

Pagination controls in UI: `«` first, `‹` prev, `›` next, `»` last. Default sort by Entity Name ASC. Sortable columns: Entity Name, UBI, Entity Type, Address, Registered Agent Name, Status.

CSV export (Quick Search results only, not Advanced): the small CSV icon POSTs to `BusinessSearch/GetBusinessSearchListOnlineCSVExport`.

---

## Drilling into an entity

Each result row's Business Name is clickable → entity detail at `/#/BusinessInformation` showing Filing History, Governors, Registered Agent, Principal Office, name history, downloadable PDFs of all filings.

Direct UBI lookup (no search required):
```
https://ccfs.sos.wa.gov/#/BusinessSearch/BusinessInformation/{UBI}
```

---

## Phonetic / soundalike matching

WA SoS does NOT publish a phonetic-match rule (unlike CA). Distinguishability follows RCW 23.95.305 bright-line rules (above). The clerk reviews on filing; ambiguous cases can be rejected at the reviewer's discretion.

Risk reduction:
- Add at least one substantive word beyond the base term
- Avoid plurals/possessives of an existing active name
- Use the $30 / 180-day name reservation if any doubt — file at https://ccfs.sos.wa.gov via "Name Reservation"

---

## Dissolution / re-use window

- **Voluntarily or administratively dissolved**: name typically becomes available after dissolution, BUT the dissolved entity has reinstatement rights (5 years for admin dissolution under RCW 23.95.615). During that window the SoS may refuse a new filing on the same exact name.
- **In practice for our case**: SOLIDUS LLC dissolved 2011-11-01 — ~15 years past, well beyond any reinstatement window. The bare name "Solidus LLC" should be available *on dissolution grounds*, BUT it's still blocked by the active SOLIDUS, LLC (Spokane) under distinguishability rules.

---

## Known gotchas

1. **Headless mode is a silent-failure trap.** Always run with `--headed`. Do not trust 0-result counts from headless sessions.
2. **`--headed` flag is sticky and must be repeated.** Once you launch the daemon with `--headed`, every subsequent browse invocation must also include `--headed`, or the daemon will refuse with `"existing daemon has different config (proxy/headed mismatch)"`. Use `$B disconnect` to flip modes.
3. **Search button stays `[disabled]` until Turnstile resolves** — wait 5+ seconds after filling the input before clicking. Verify by checking `cf-turnstile-response` length is > 0.
4. **`wait --networkidle` may time out after click** — that's harmless. The Angular scope updates regardless. Just `sleep 3` and read.
5. **Hash routing means no URL deep-linking** for queries. Bookmark the search page, not the result.
6. **Element refs invalidate after navigation, filter change, or re-render.** Re-snapshot every time.
7. **WA DOR Business Lookup caps at 10,000 results** — for a substring like "Solidus" you may hit the cap because it matches anywhere in the business name including DBAs and trade names. Refine with City/County.
8. **OpenCorporates and Bizapedia** are third-party mirrors with unknown lag. Useful for triangulation, not authority.
9. **For final filing decisions**, always do one human-driven session in a real Chrome to confirm — or call WA SoS Corporations Division at (360) 725-0377.

---

## Recommended verification protocol for a new LLC name

1. **Headed `browse` Quick Search** for the base substantive word (Contains match, broadest).
2. **Headed `browse` Quick Search** for each candidate full name (e.g., "Solidus Tech Advisory") — confirm 0 exact matches.
3. **Headed `browse` Advanced Search** with the candidate full name across ALL statuses — confirms no dissolved-but-recently entity could block on reinstatement grounds.
4. If any **Active** entity contains the same substantive word AND a related industry suffix, file a $30 name reservation (180-day) as a hedge while you firm up the filing.
5. File via CCFS online "Start a Domestic LLC" workflow. Rejections (if any) return in 7–14 days; expedited review available for $50 (2-day) or $100 (same-day).
