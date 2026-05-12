# USPTO trademark search playbook (new search UI)

- **Last verified:** 2026-05-12
- **System:** USPTO TM Search (beta / new search experience), not the legacy TESS
- **Direct URL:** https://tmsearch.uspto.gov/
- **Search results URL pattern:** https://tmsearch.uspto.gov/search/search-results

This playbook documents how to drive the new USPTO trademark search SPA from
the `browse` Playwright CLI. It captures the exact element semantics, the
default filter state, and the gotchas that bit me on first contact.

---

## Why this exists

The legacy USPTO search (TESS) was retired. The replacement is a JavaScript
SPA at `tmsearch.uspto.gov`. `curl` and `WebFetch` return shell HTML with no
results — only a JS-driven browser session can return data.

Additionally:
- USPTO returns **403** to default Playwright user-agents. The `browse` server
  is pre-warmed with a Chrome UA. **Never run `$B useragent` to reset it** —
  a fresh session reverts to Playwright UA and the next `goto` returns 403.
- Element refs (`@e14`, `@e18`, etc.) **invalidate after every navigation,
  filter toggle, or re-render**. Always `$B snapshot -i` to get fresh refs
  before each interaction.
- The browse server is shared across subagents. Always work in a dedicated
  tab and re-focus before each command.

---

## Environment setup

```bash
B="/Users/mayank/.claude/skills/gstack/browse/dist/browse"

# Open USPTO in a dedicated tab and record the tab id
$B newtab "https://tmsearch.uspto.gov/"
# → "Opened tab N → https://tmsearch.uspto.gov/"  (remember N)

# Before EVERY subsequent command:
$B tab N >/dev/null
$B wait --networkidle   # after goto/click/tab
```

---

## Page anatomy (refs reflect a fresh load; re-snapshot to confirm)

### Landing page (https://tmsearch.uspto.gov/)
- `[combobox] "Search refinment": Wordmark`   ← search-type dropdown, default
  is **Wordmark** which is what we want. Other options include Owner, Serial,
  Goods/Services, etc.
- `[combobox] "Search trademarks"`   ← the actual search input (yes, combobox
  not textbox — autocomplete)
- `[button] "search"`                ← submit

### Search results page (https://tmsearch.uspto.gov/search/search-results)
Same search controls at top, plus a left rail with filters:

- **Status filter** (button, defaults to expanded). Six checkboxes:
  - `Live` (parent) — `Registered`, `Pending` (children)
  - `Dead` (parent) — `Cancelled`, `Abandoned` (children)
  - **All six are checked by default.** This is what you want for an
    availability sweep — Live captures current blockers, Dead captures
    recently abandoned marks worth knowing about.
- **Class filter** (button, defaults to expanded). All 45 NICE classes plus
  certification + collective membership. Plus a leading `Coordinated`
  checkbox.
  - `Coordinated` defaults **ON**. When you check one class while
    `Coordinated` is on, the system auto-selects USPTO-coordinated classes
    too (e.g., checking 035 auto-checks 042, and vice versa).
  - To filter to a single class exactly, uncheck `Coordinated` first, then
    check the desired class.
  - **Gotcha:** with one or more class boxes checked, the header text may
    still say "0 results for X" even though results are clearly listed
    below. Trust the result rows (look for `Serial<digits>` markers), not
    the header.
- `Sort` button — Relevance (default), Wordmark A-Z/Z-A, Class, Serial.
- `Configure` button — toggle thumbnail "Show image", view modes
  (grid / list / compact).
- Pagination bar at bottom with 10 / 25 / 50 / 100 per page.

### Result row format
Each row in the result text contains, in order:
```
Wordmark <NAME>
Status <Live|Dead>  <Registered|Pending|Cancelled|Abandoned>
Goods & services IC <NN>: <first part of description, truncated with "...">
Class<NN, NN, NN>
Serial<8-digit-serial>
Owners<OWNER NAME> (<ENTITY TYPE>; <JURISDICTION>)
```

The result text is enough for first-pass clearance triage — no need to drill
into TSDR detail pages unless you want full goods/services prose, prosecution
history, or filing dates beyond live/dead.

---

## Worked example: search "solidus"

```bash
B="/Users/mayank/.claude/skills/gstack/browse/dist/browse"

# 1. Open in own tab
$B newtab "https://tmsearch.uspto.gov/"
# → Tab 3
$B tab 3 >/dev/null
$B wait --networkidle

# 2. Snapshot to get current refs (do this fresh — refs change)
$B snapshot -i | grep -E "Search trademarks|button.*search"
# →  @e14 [combobox] "Search trademarks"
# →  @e15 [button] "search"

# 3. Fill and submit
$B fill @e14 "solidus"
$B click @e15
$B wait --networkidle

# 4. Read result count from text
$B text | grep -oE "[0-9]+ results for solidus" | head -1
# → "42 results for solidus"

# 5. Read status counts (left rail shows them inline)
# Look for "Live ... 29" and "Dead ... 13" in the text dump.

# 6. Iterate over rows
$B text | sed 's/Check to tag for /\n=== /g' | grep -E "^=== [0-9]"
# Each line is one result with wordmark, status, IC, class list, serial, owner.

# 7. Re-snapshot, then class filter to 042 only
$B snapshot -i | grep -E "Coordinated|\(042\)"
# Uncheck Coordinated (so coordinated classes aren't auto-added)
$B click <coordinated-ref>
$B wait --networkidle
# Check 042
$B snapshot -i | grep "\(042\)"
$B click <042-ref>
$B wait --networkidle
$B text | sed 's/Check to tag for /\n=== /g' | grep -E "^=== [0-9]"
```

---

## Search behavior notes

- **Default token matching** is permissive. `solidus tech` returned 936
  matches (anything containing "solidus" OR "tech"). Use quoted phrases for
  exact matches: `"solidus tech"`, `"solidus advisory"`.
- **Quoted phrases** treat the input as a literal compound wordmark — so
  `"solidus labs"` returns 0 even though the mark SOLIDUS LABS exists,
  because it's not stored as the literal string "solidus labs" as a single
  token-string match. The unquoted single token `solidus` already surfaces
  all `SOLIDUS *` compound marks because they begin with the token.
- **Recommended practice for clearance:** run the unquoted base word search
  (`solidus`) with all Live + Dead checked, no class filter. The full
  candidate set will be ≤ a few hundred for distinctive words and fits on
  one or two pages at 50 per page. Then drill by class.

---

## Gotchas (read these before debugging)

1. **403 on goto** — UA was reset. Restart the browse server with the
   pre-warmed Chrome UA. Do NOT manually run `$B useragent <anything>`.
2. **Stale refs** — After `goto`, `click` (that triggers nav), `fill` (that
   triggers autocomplete that redraws), or `tab <id>`, refs may shift.
   Always re-snapshot before the next interactive command.
3. **"0 results for X" header but rows below** — Class filter was clicked
   and the header is showing a stale count. Trust the row content
   (`Serial<digits>` markers) over the header text.
4. **Coordinated classes auto-check** — Checking class 035 with
   `Coordinated` on auto-checks 042, and vice versa. To get exact class
   isolation, uncheck Coordinated first.
5. **Truncated goods/services** — Result rows truncate the IC description
   with "...". For full prose, click the wordmark to open the detail panel
   or use TSDR: `https://tsdr.uspto.gov/#caseNumber=<serial>&caseType=SERIAL_NO&searchType=statusSearch`.
6. **Shared browse session** — Always `$B tab <id> >/dev/null` before
   every command. Another agent can switch focus between your commands.
7. **`text` dump is one giant line** — Pipe through `sed
   's/Check to tag for /\n=== /g'` to split rows on the tag-checkbox
   delimiter, then grep for what you need.

---

## Drilling into a single mark

The result page itself contains owner, status, primary IC, and serial. For
full prosecution history and complete goods/services prose, fetch TSDR
directly:

```bash
$B newtab "https://tsdr.uspto.gov/#caseNumber=88491943&caseType=SERIAL_NO&searchType=statusSearch"
$B wait --networkidle
$B text
```

TSDR is more reliable for detail extraction than trying to click into the
search-results panel (which is also JS-rendered and slow).

---

## Recommended search sweep for clearance

Given a candidate mark `<NAME>`:

1. `<name>` unquoted → baseline count, status distribution, all variants.
2. Filter to Class 035 (uncheck Coordinated first) → consulting/advertising/business.
3. Filter to Class 042 (uncheck Coordinated first) → tech/SaaS/software.
4. `"<name> <suffix>"` quoted for each full candidate name you're considering
   → confirms the exact full mark is unregistered.
5. For each Live mark in your target classes, capture: serial, owner,
   status, full class list, first line of goods/services.
6. Phonetic/semantic neighbors are out of scope here — use a paid
   clearance vendor (Corsearch, Compumark) before filing.
