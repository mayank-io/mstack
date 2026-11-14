"""Tabroom competitor-history download unit: judges' scores and feedback.

Page: `tabroom.com/user/student/history.mhtml?tourn_id=<n>&student_id=<n>`, the
per-tournament history a competitor (or a linked parent) sees once ballots are
released. Each round carries every judge's rank and points, and a hidden row
holding that judge's written feedback.

The DOM logic is `skills/tabroom-results/references/extraction.js`, tested under
jsdom. This file owns URL parsing, validation, date resolution and writing.

    python3 tabroom_results.py <history-url> [out_dir]
    python3 tabroom_results.py --extracted <file.json> <history-url> [out_dir]

The first form drives the gstack browser. The second takes the object returned
by `__tabroom.extract()` (optionally with a `tournament_info` key holding
`__tabroom.tournamentInfo()`), for when the page was read through another
browser driver: Tabroom results are visible only to the account they belong to,
which is often signed in on a different Chrome profile than gstack's.

Writes `results.json` and `results.md` (plain Markdown, no vault syntax) into
`out_dir` (a temp directory when omitted). The final stdout line is
`OUTPUT_DIR:<abs path>`; on failure the script exits non-zero with no marker.
"""
import argparse
import datetime
import json
import os
import re
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_EXTRACTION_JS_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "skills", "tabroom-results", "references", "extraction.js"))

_HISTORY_PATH = "/user/student/history.mhtml"
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DATE_PART = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?$")

# A line a judge typed that Markdown would read as structure: a heading, a
# quote, a list item, or a numbered item.
_MD_LEADER = re.compile(r"^(#{1,6}\s|>|[-+*]\s|\d+[.)]\s)")


def parse_history_url(url):
    """Return (canonical_url, tourn_id, student_id), or raise ValueError.

    Anything that is not a competitor history page is refused before a browser
    moves: a judge's history or a public results page has a different layout
    and would extract nothing, which reads as "no ballots released".
    """
    u = urlparse((url or "").strip() if "://" in (url or "") else "https://" + (url or "").strip())
    host = (u.hostname or "").lower()
    q = parse_qs(u.query)
    tourn, student = q.get("tourn_id", [""])[0], q.get("student_id", [""])[0]
    if host not in ("tabroom.com", "www.tabroom.com") or u.path != _HISTORY_PATH \
            or not tourn.isdigit() or not student.isdigit():
        raise ValueError(
            "not a Tabroom competitor history URL "
            f"(tabroom.com{_HISTORY_PATH}?tourn_id=<n>&student_id=<n>): {url!r}")
    return (f"https://www.tabroom.com{_HISTORY_PATH}?tourn_id={tourn}&student_id={student}",
            tourn, student)


def tournament_url(tourn_id):
    return f"https://www.tabroom.com/index/tourn/main.mhtml?tourn_id={tourn_id}"


def _month_number(name):
    """'Oct', 'Sept', 'October' -> 10. None for anything that is not a month's name or prefix."""
    name = name.lower()
    hits = [i for i, full in enumerate(_MONTHS, 1) if len(name) >= 3 and full.startswith(name)]
    return hits[0] if len(hits) == 1 else None


def parse_tournament_dates(label):
    """'Mar 6 to Mar 8 2026' -> ('2026-03-06', '2026-03-08'). (None, None) when unparseable.

    A one-day tournament prints a single date. A start with no year takes the
    end's; a start that would then fall after the end crossed New Year and
    belongs to the year before. Never guess beyond that.
    """
    parts = [p.strip() for p in re.split(r"\s+(?:to|-|–|—)\s+", (label or "").strip()) if p.strip()]
    if not 1 <= len(parts) <= 2:
        return None, None
    parsed = []
    for p in parts:
        m = _DATE_PART.match(p)
        if not m:
            return None, None
        month = _month_number(m.group(1))
        if not month:
            return None, None
        parsed.append((month, int(m.group(2)), int(m.group(3)) if m.group(3) else None))
    end_year = parsed[-1][2]
    if end_year is None:
        return None, None
    try:
        end = datetime.date(end_year, parsed[-1][0], parsed[-1][1])
        month, day, year = parsed[0]
        start = datetime.date(year or end_year, month, day)
        if year is None and start > end:
            start = datetime.date(end_year - 1, month, day)
    except ValueError:
        return None, None
    if start > end:
        return None, None
    return start.isoformat(), end.isoformat()


def round_date(start_label, start, end):
    """'Sat 5:30 PM' within 2026-03-06..08 -> '2026-03-07'. None unless exactly one day matches.

    A tournament longer than a week has two Saturdays; picking the first would
    be a guess, so the date is left unknown.
    """
    m = re.match(r"\s*([A-Za-z]{3})", start_label or "")
    if not (m and start and end) or m.group(1).lower() not in _WEEKDAYS:
        return None
    want = _WEEKDAYS.index(m.group(1).lower())
    first, last = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    days = [first + datetime.timedelta(n) for n in range((last - first).days + 1)]
    hits = [d for d in days if d.weekday() == want]
    return hits[0].isoformat() if len(hits) == 1 else None


def _block_text(block):
    return block.get("text") or "\n".join(block.get("items") or [])


def feedback_chars(data):
    """Characters of judge-written feedback, whitespace excluded."""
    return sum(len(re.sub(r"\s+", "", _block_text(b)))
               for e in data.get("entries") or [] for r in e.get("rounds") or []
               for f in r.get("feedback") or [] for s in f.get("sections") or []
               for b in s.get("blocks") or [])


def validate(data):
    """Problems that make the capture unusable. An empty list means usable."""
    if not isinstance(data, dict):
        return ["extraction returned no object (extraction.js did not run on the page)"]
    rounds = [r for e in data.get("entries") or [] for r in e.get("rounds") or []]
    if not rounds:
        who = data.get("account") or "an unknown account"
        return [f"no rounds on the page for {who}: that Tabroom account has no results for "
                "this student (wrong browser profile or login), or ballots are not released"]
    problems = []
    if not data.get("student"):
        problems.append("no student name on the page")
    if not any(r.get("judges") for r in rounds):
        problems.append("rounds were found but no judge in any of them (page layout changed)")
    return problems


def score_labels(entry):
    """Score columns in first-seen order: speech prints Rank and Points, debate prints others."""
    labels = []
    for r in entry.get("rounds") or []:
        for j in r.get("judges") or []:
            for s in j.get("scores") or []:
                if s["label"] not in labels:
                    labels.append(s["label"])
    return labels


def build_record(data, url, tournament_info=None):
    canonical, tourn_id, student_id = parse_history_url(url)
    info = tournament_info or {}
    start, end = parse_tournament_dates(info.get("dates_label"))
    entries = []
    for e in data["entries"]:
        rounds = [{**r, "date": round_date(r["fields"].get("Start"), start, end)}
                  for r in e["rounds"]]
        entries.append({**e, "rounds": rounds})
    return {
        "type": "tabroom-results",
        "source": canonical,
        "tourn_id": tourn_id,
        "student_id": student_id,
        "student": data.get("student"),
        "tournament": data.get("tournament"),
        "tournament_url": tournament_url(tourn_id),
        "tournament_dates_label": info.get("dates_label") or None,
        "tournament_start": start,
        "tournament_end": end,
        "location": info.get("location") or None,
        "account": data.get("account") or None,
        "entries": entries,
        "rounds_count": sum(len(e["rounds"]) for e in entries),
        "ballots_count": sum(len(r["judges"]) for e in entries for r in e["rounds"]),
        "feedback_count": sum(len(r["feedback"]) for e in entries for r in e["rounds"]),
        "feedback_chars": feedback_chars(data),
        "captured_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }


def _cell(text):
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _md_lines(text, indent=""):
    """A judge's text as Markdown lines, verbatim, with structure characters neutralised."""
    out = []
    for n, line in enumerate(text.split("\n")):
        if _MD_LEADER.match(line):
            line = "\\" + line
        out.append((indent if n else "") + line)
    return out


def _render_block(block):
    if block["type"] == "paragraph":
        # Two trailing spaces: a line break the judge typed stays a line break.
        return ["  \n".join(_md_lines(block["text"])), ""]
    lines = []
    for n, item in enumerate(block["items"], 1):
        lead = f"{n}. " if block["type"] == "ordered" else "- "
        body = _md_lines(item, indent=" " * len(lead))
        lines.append(lead + "  \n".join(body))
    return lines + [""]


def _scores_text(judge):
    return ", ".join(f"{s['label']} {s['value']}" for s in judge.get("scores") or [])


def render_markdown(record):
    """Plain Markdown of the whole capture: a results table, then every ballot verbatim."""
    lines = [f"# {record['student']}: {record['tournament']}", ""]
    if record["tournament_start"]:
        when = record["tournament_start"] if record["tournament_start"] == record["tournament_end"] \
            else f"{record['tournament_start']} to {record['tournament_end']}"
        lines.append(f"- Tournament dates: {when}")
    if record["location"]:
        lines.append(f"- Location: {record['location']}")
    lines += [f"- Source: {record['source']}", ""]

    for entry in record["entries"]:
        labels = score_labels(entry)
        cols = [c for c in entry["columns"] if not re.search("judge", c, re.I)]
        dated = any(r["date"] for r in entry["rounds"])
        lines += [f"## {entry['event'] or 'Entry'}", ""]
        if entry["code"]:
            lines += [f"Code: {entry['code']}", ""]
        head = cols + (["Date"] if dated else []) + ["Judge"] + labels
        lines += ["### Results", "", "| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
        for r in entry["rounds"]:
            # A round with no judge listed still gets its row.
            ballots = [(j["judge"], {s["label"]: s["value"] for s in j["scores"]})
                       for j in r["judges"]] or [("", {})]
            for n, (judge, by_label) in enumerate(ballots):
                first = n == 0
                row = [_cell(r["fields"].get(c)) if first else "" for c in cols]
                if dated:
                    row.append((r["date"] or "") if first else "")
                row += [_cell(judge)] + [_cell(by_label.get(lb, "")) for lb in labels]
                lines.append("| " + " | ".join(row) + " |")
        lines += ["", "### Feedback", ""]
        for r in entry["rounds"]:
            name = r["fields"].get("Round") or "Round"
            lines += [f"#### {name}", ""]
            if not r["feedback"]:
                lines += ["No written feedback on the page for this round.", ""]
            scores = {j["judge"]: _scores_text(j) for j in r["judges"]}
            for f in r["feedback"]:
                got = scores.get(f["judge"])
                lines += [f"##### {f['judge']}" + (f" ({got})" if got else ""), ""]
                for s in f["sections"]:
                    if s["heading"]:
                        lines += [f"**{s['heading']}**", ""]
                    for b in s["blocks"]:
                        lines += _render_block(b)
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(record, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "results.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(record))


def _inject(page):
    src = open(_EXTRACTION_JS_PATH, encoding="utf-8").read()
    kind = page.evaluate("() => {\n" + src + "\nreturn typeof window.__tabroom;\n}")
    if kind != "object":
        raise RuntimeError(f"extraction.js did not install (typeof = {kind!r})")


def capture(page, url):
    """Read the history page, then the tournament page, through a gstack page."""
    canonical, tourn_id, _ = parse_history_url(url)
    page.goto(canonical)
    page.wait_for_selector(".main", timeout=20000)
    _inject(page)
    data = page.evaluate("() => window.__tabroom.extract()")
    if validate(data):
        return data, None          # no second navigation for a page that failed
    page.goto(tournament_url(tourn_id))
    page.wait_for_selector("h2", timeout=20000)
    _inject(page)
    return data, page.evaluate("() => window.__tabroom.tournamentInfo()")


def main(argv):
    ap = argparse.ArgumentParser(
        prog="tabroom_results.py",
        description="Download a competitor's judges' scores and feedback from Tabroom.")
    ap.add_argument("url", help="tabroom.com/user/student/history.mhtml?tourn_id=<n>&student_id=<n>")
    ap.add_argument("out_dir", nargs="?", help="output directory (default: a temp directory)")
    ap.add_argument("--extracted", metavar="FILE",
                    help="JSON from __tabroom.extract(), read through another browser driver")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    try:
        parse_history_url(args.url)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.extracted:
        try:
            with open(args.extracted, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"ERROR: cannot read --extracted file: {e}", file=sys.stderr)
            return 2
        info = data.pop("tournament_info", None) if isinstance(data, dict) else None
    else:
        from _browse import sync_browse_page   # imported here so usage errors need no browser
        with sync_browse_page() as page:
            data, info = capture(page, args.url)

    # No OUTPUT_DIR marker on failure: a caller chaining on it would write a
    # note from an empty page.
    problems = validate(data)
    if problems:
        print(f"ERROR: {'; '.join(problems)}", file=sys.stderr)
        return 1

    record = build_record(data, args.url, info)
    out_dir = os.path.abspath(args.out_dir) if args.out_dir else tempfile.mkdtemp(prefix="tabroom-")
    write_outputs(record, out_dir)

    if not record["tournament_start"]:
        print("WARNING: tournament dates unknown; rounds carry a weekday and time only",
              file=sys.stderr)
    if record["feedback_count"] < record["ballots_count"]:
        print(f"WARNING: {record['ballots_count'] - record['feedback_count']} of "
              f"{record['ballots_count']} ballot(s) have no written feedback on the page",
              file=sys.stderr)
    print(f"captured {record['rounds_count']} round(s), {record['ballots_count']} ballot(s), "
          f"{record['feedback_count']} with feedback, {record['feedback_chars']} feedback chars "
          f"-> {out_dir}", file=sys.stderr)
    print(f"OUTPUT_DIR:{out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
