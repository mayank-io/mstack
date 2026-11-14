---
name: tabroom-results
description: "Download a competitor's judges' scores and written feedback for one tournament from Tabroom — every round's rank, points and ballot comments. Use when the user shares a tabroom.com/user/student/history.mhtml URL, or says \"get the tabroom feedback\", \"download the judges' scores\", \"save the ballots from this tournament\". Returns JSON and Markdown to a directory; it does not write notes."
---

# Fetch Tabroom Results

Pull one competitor's results for one tournament into a directory: each round's judges, their ranks and points, and each judge's written feedback. **This skill knows nothing about vaults.** It retrieves, and stops. `notes:clip` turns the result into a note.

## Input

`$ARGUMENTS`:

- **First argument**: the history URL (required), `tabroom.com/user/student/history.mhtml?tourn_id=<n>&student_id=<n>`. Any other Tabroom page is refused.
- **Second argument**: output directory (optional). Omitted, a temp directory is used. Created if missing. **Never write outside it.**

## The page is only visible to the account it belongs to

A competitor's ballots show for the competitor's own Tabroom login (and an account linked to that student). Every other signed-in account gets the same URL with the tournament name, the event and the entry code, **and no results table**. That reads as "ballots not released yet", and it is usually the wrong account.

Verified 2026-11-13 on one URL in two Chrome profiles: an account that did not own the entry got a header and no table; the competitor's account got every round, ballot and comment.

**So settle which browser holds the right login before fetching.** The script reports the account it saw (`account` in `results.json`, and in the error when it finds no rounds). If that is not the competitor's account, switch browsers; do not conclude the feedback is missing.

## This skill owns no extraction code

The DOM logic is [`references/extraction.js`](references/extraction.js), tested under jsdom. URL parsing, validation, date resolution and writing are `${CLAUDE_PLUGIN_ROOT}/scripts/tabroom_results.py`. Do not re-implement either by hand.

### Route A: the login is in the gstack browser

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/tabroom_results.py "<history-url>" [out_dir]
```

Run it via the Bash tool **outside the sandbox** (it drives `$B`). It goes through `_browse.sync_browse_page()`, so the headed-mode check is automatic. It reads the history page, then the tournament's own page for its dates.

### Route B: the login is in another Chrome profile

gstack attaches to one Chrome session. When the competitor's login lives in a different profile, read the page with a driver connected to that profile (Claude in Chrome, selected with `list_connected_browsers` and `select_browser`), then hand the result to the same script.

1. Open the history URL in that browser. Check the account in the site header before going further.
2. Evaluate the whole of `references/extraction.js` in the page, then `window.__tabroom.extract()`. It is synchronous and needs no clicks: the feedback rows are already in the DOM, hidden.
3. Open `https://www.tabroom.com/index/tourn/main.mhtml?tourn_id=<n>`, evaluate `extraction.js` again, and call `window.__tabroom.tournamentInfo()`.
4. Save the `extract()` object as a JSON file, with the `tournamentInfo()` object under a `tournament_info` key.
5. Run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/tabroom_results.py --extracted <file.json> "<history-url>" [out_dir]
```

**Getting the object out of the page intact is the hard part of Route B.** Measured with Claude in Chrome on 2026-11-13:

| What you return from the page | What arrives |
|---|---|
| the `extract()` object itself | everything below five levels of nesting replaced by `[TRUNCATED: Max depth exceeded]` |
| one long string | cut at roughly 1,000 characters |
| raw `outerHTML`, or a string containing a URL with a query | `[BLOCKED: Cookie/query string data]` |
| an array of 850-character slices of `JSON.stringify(extract())`, four slices per call | intact |

So stash the JSON on `window`, read it out in slices, and **prove the reassembled file is the page's string** before using it:

```javascript
const s = JSON.stringify(window.__tabroom.extract()); window.__s = s;
let h = 5381; for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
({len: s.length, djb2: h})                        // then: [0,1,2,3].map(i => window.__s.slice(i*850, (i+1)*850))
```

```python
s = json.dumps(json.load(open(path)), separators=(",", ":"), ensure_ascii=False)
h = 5381
for ch in s:
    h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF          # must equal the page's len and djb2
```

A reassembled file whose length or hash differs has a dropped or altered character in a judge's words. Fix it before running the script; do not ship it.

## What it writes

| File | Contents |
|---|---|
| `results.json` | `type: tabroom-results`, `source`, `tourn_id`, `student_id`, `student`, `tournament`, `tournament_url`, `tournament_dates_label`, `tournament_start`, `tournament_end`, `location`, `account`, `entries`, `rounds_count`, `ballots_count`, `feedback_count`, `feedback_chars`, `captured_utc` |
| `results.md` | plain Markdown, no vault syntax: a results table with one row per ballot, then every ballot's feedback under round and judge headings |

Each entry (one per event entered) has `event`, `code`, `columns` and `rounds`. Each round has `fields` (the page's own columns: Round, Start, Room, Section, Speak), `date`, `judges` (`judge` plus `scores` as `{label, value}` pairs) and `feedback` (per judge: `label` and `sections`, each a `heading` such as "Reason for Rank/Decision" or "Comments for you" with ordered `blocks`).

**Output contract:** final stdout line `OUTPUT_DIR:<abs path>`. On failure (a non-history URL, no rounds on the page, no student name, no judge in any round) it exits non-zero with **no** marker. Warnings go to stderr: tournament dates unknown, or ballots with no written feedback.

## How the page is handled

| Trait of the page | Handled in |
|---|---|
| Feedback sits in a `display:none` row (`tr.feedback`) that a button reveals; visible-text extraction returns scores and no comments | `extraction.js feedbackOf()` reads `textContent`, paired to its round by the button's `toggleView('<id>')` |
| tablesorter clones the table into an empty sticky-header copy | `resultTables()` skips it |
| A judge's scores are leaf spans titled by role ("Rank", "Points"); an elimination round has an empty Points span | `judgesOf()` keeps the label and drops empty values |
| Comments mix paragraphs, numbered lists and bullets, and judges type several lines into one list item | `blocksOf()` keeps block order and kind; `textOf()` keeps `<br>` as a line break |
| The page prints "Sat 5:30 PM" with no date | `round_date()` resolves the weekday inside the tournament's date range, and leaves it `null` when that weekday occurs twice |
| A judge's line can start with `#`, `-` or `1.` | `render_markdown()` escapes the leading character so the words stay words |

## Verify before reporting

- **`account` is the competitor's login**, not whoever happened to be signed in.
- **`feedback_count` against `ballots_count`.** A ballot without feedback is reported on stderr. That is the source lacking it (the judge wrote nothing, or the tournament has not released comments), not an extraction failure, and the report should say which ballots.
- **`rounds_count` matches the rounds visible on the page**, elimination rounds included.

## Limits

- **Verified on one speech event** (2026-11-13): ranks, points, and two comment boxes per ballot. Debate events print other columns and score labels (side, opponent, win or loss). `fields` and `scores` carry whatever labels the page uses, so they should come through, but that has not been checked against a live debate page. Read `results.md` against the page the first time.
- **Two events at one tournament** produce two tables and two `entries`. The fixture covers one.
- One tournament per run. The list of a student's tournaments (`/user/student/index.mhtml`) is not crawled.
