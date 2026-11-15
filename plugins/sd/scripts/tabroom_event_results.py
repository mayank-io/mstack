#!/usr/bin/env python3
"""Download one Tabroom tournament's data and analyse the break of one speech event.

The data comes from Tabroom's documented backup endpoint,
`/api/download_data.mhtml?tourn_id=<n>`, which returns a tournament's public
data as JSON to a plain GET with no login: every round, section, ballot, rank,
judge and result set. One request covers the whole tournament.

`start` is one of:

- any Tabroom URL that carries a `tourn_id`: a results page, or the Invite,
  Entries, Judges, Pairings, Live Updates or Results tab;
- a tournament name, looked up with Tabroom's search.

The event is taken, in this order, from: `event_id` or `round_id` in the URL;
`--event` (name or abbreviation); the page a `result_id` URL points at (read
through the signed-in gstack browser, because that page needs a login and the
JSON carries no result ids); the one speech event `--competitor` is entered in.

Written to the output directory:

    raw/tournament_<id>.json   the tournament data as served
    event.json                 tournament, event, rounds, tiebreakers, checks
    ballots.csv/.json          one row per ballot
    standings.csv              one row per entry, in prelim seed order
    result_sets.json           Tabroom's own result sets for the event
    analysis.md                how the break worked, and one competitor's path to it

Final stdout line on success: `OUTPUT_DIR:<abs path>`. On failure the script
exits non-zero and prints no marker.

`--from-raw PATH` rebuilds everything from an earlier download with no network.
"""

import argparse
import copy
import csv
import datetime
import glob
import html
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import parse_qs, quote_plus, urlparse
from zoneinfo import ZoneInfo

HOST = "www.tabroom.com"
DATA_URL = "https://" + HOST + "/api/download_data.mhtml?tourn_id={}"
SEARCH_URL = "https://" + HOST + "/index/search.mhtml?search={}"
USER_AGENT = "Mozilla/5.0 (compatible; tabroom-event-results)"   # a generic client name; nothing personal
DEFAULT_TIEBREAKERS = ["ranks", "reciprocals", "points"]
TIEBREAKER_NAMES = {
    "ranks": "rank total (lower is better)",
    "reciprocals": "reciprocals (higher is better)",
    "points": "points (higher is better)",
}
ELIM_TYPES = {"elim", "final", "runoff"}


class ResultsError(RuntimeError):
    """Input that cannot be turned into results; the message says which and why."""


# -- input --------------------------------------------------------------------

def parse_start(text):
    """What the caller handed over: a page of a tournament, or a name to search for.

    Any Tabroom URL with a `tourn_id` is accepted. `round_id`, `event_id` and
    `result_id` are kept when present, because each can name the event.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("give a Tabroom URL or a tournament name")
    if not re.match(r"(?i)(https?://|www\.|tabroom\.com)", text):
        return {"kind": "search", "query": text}
    url = text if "://" in text else f"https://{text}"
    parts = urlparse(url)
    if parts.netloc.lower() not in (HOST, "tabroom.com"):
        raise ValueError(f"not a Tabroom URL: {text}")
    query = parse_qs(parts.query)

    def ident(name):
        value = (query.get(name) or [""])[0]
        return value if value.isdigit() else ""

    if not ident("tourn_id"):
        raise ValueError(f"no tourn_id in the URL; give a page of the tournament, or its name: {text}")
    return {"kind": "tournament", "url": url, "tourn_id": ident("tourn_id"), "round_id": ident("round_id"),
            "event_id": ident("event_id"), "result_id": ident("result_id")}


def clean_text(fragment):
    """Tag-free, entity-decoded, whitespace-collapsed text of an HTML fragment."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_search_results(page):
    """Tournaments listed by Tabroom's search: [{tourn_id, name, location, dates, start}]."""
    found, seen = [], set()
    for tr in re.split(r"<tr\b", page)[1:]:
        link = re.search(r'href\s*=\s*"[^"]*/index/tourn/(?:main|index)\.mhtml\?tourn_id=(\d+)"[^>]*>(.*?)</a>',
                         tr, flags=re.S)
        if not link or link.group(1) in seen:
            continue
        seen.add(link.group(1))
        cells = [clean_text(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, flags=re.S)]
        start = re.search(r'data-text\s*=\s*"(\d{4}-\d{2}-\d{2})', tr)
        found.append({"tourn_id": link.group(1), "name": clean_text(link.group(2)),
                      "location": cells[1] if len(cells) > 1 else "", "dates": cells[2] if len(cells) > 2 else "",
                      "start": start.group(1) if start else ""})
    return found


def describe_tournament(t):
    detail = ", ".join(x for x in (t["dates"], t["location"]) if x)
    return f"{t['name']} ({detail}; tourn_id {t['tourn_id']})" if detail else f"{t['name']} (tourn_id {t['tourn_id']})"


def pick_tournament(results, query, today=None):
    """The one tournament a search means.

    A name is often reused every year. When several results carry exactly the
    searched name, the latest one that has started is taken; anything looser
    than an exact name must be unique, or the caller is shown the candidates.
    """
    if not results:
        raise ResultsError(f"Tabroom's search found no tournament for \"{query}\"")
    exact = [t for t in results if t["name"].casefold() == query.strip().casefold()]
    if len(exact) == 1 or (not exact and len(results) == 1):
        return (exact or results)[0]
    if exact:
        today = today or datetime.date.today().isoformat()
        started = sorted((t for t in exact if t["start"] and t["start"] <= today), key=lambda t: t["start"])
        if started:
            return started[-1]
    pool = exact or results
    listed = "; ".join(describe_tournament(t) for t in pool[:12])
    return _raise(f"\"{query}\" matches {len(pool)} tournaments. Give the full name or a tournament URL. "
                  f"Candidates: {listed}" + (f"; and {len(pool) - 12} more" if len(pool) > 12 else ""))


def _raise(message):
    raise ResultsError(message)


def http_get(url, timeout=180):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise ResultsError(f"Tabroom answered {e.code} for {url}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ResultsError(f"could not reach Tabroom: {e}") from e


def parse_tournament_data(text, tourn_id=""):
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or "categories" not in data:
        raise ResultsError(f"Tabroom returned no tournament data for tourn_id {tourn_id}".rstrip()
                           + "; the tournament may be hidden or the id wrong")
    if not str(data.get("id") or "").isdigit():
        # The id names the raw file; anything but digits is not a tournament id.
        raise ResultsError("the tournament data carries no numeric id")
    return data


# -- events -------------------------------------------------------------------

def list_events(data):
    return [e for c in data.get("categories", []) for e in c.get("events", [])]


def describe_events(events):
    return ", ".join(f"{e['name']} ({e['abbr']})" for e in events)


def scored_rounds(ev):
    return [r for r in ev.get("rounds", [])
            if any(s.get("tag") == "rank" for sec in r.get("sections", []) for b in sec.get("ballots", [])
                   for s in b.get("scores", []))]


def pick_event(events, query):
    """The one event `query` names: its abbreviation, its name, or words of its name."""
    q = query.strip().casefold()
    for test in (lambda e: e["abbr"].casefold() == q, lambda e: e["name"].casefold() == q,
                 lambda e: all(word in e["name"].casefold() for word in q.split())):
        hits = [e for e in events if test(e)]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise ResultsError(f"\"{query}\" matches {len(hits)} events: {describe_events(hits)}")
    raise ResultsError(f"no event matches \"{query}\". Events: {describe_events(events)}")


def event_entries(data, ev):
    """{entry id: {name, code, school}} for one event."""
    entries = {}
    for school in data.get("schools", []):
        for entry in school.get("entries", []):
            if str(entry.get("event")) == str(ev["id"]):
                entries[str(entry["id"])] = {"name": entry.get("name") or "", "code": entry.get("code") or "",
                                             "school": school.get("name") or ""}
    return entries


def school_of(code, name, school_codes):
    """School from an entry code such as "TesSTE First Last": the prefix is the
    school's code. Used when the public data leaves the entry out of its school."""
    prefix = code[:-len(name)].strip() if name and code.endswith(name) else ""
    return school_codes.get(prefix, prefix)


def events_with_competitor(events, query):
    """Events with a ballot for a name containing `query`. Ballots, not the
    entry lists: the public data omits some events' entries from the schools."""
    q = query.strip().casefold()
    return [e for e in events if any(q in (b.get("entry_name") or "").casefold()
                                     for r in e.get("rounds", []) for s in r.get("sections", [])
                                     for b in s.get("ballots", []))]


def resolve_event(data, start, event=None, competitor=None, page_abbr=None):
    """The event to analyse. `page_abbr` reads the event abbreviation off a
    `result_id` page; it is passed in so that nothing here opens a browser."""
    events = list_events(data)
    speech = [e for e in events if e.get("type") == "speech" and scored_rounds(e)]
    chosen, how = None, ""
    if start.get("event_id"):
        chosen, how = next((e for e in events if str(e["id"]) == start["event_id"]), None), "the link's event_id"
    if not chosen and start.get("round_id"):
        chosen = next((e for e in events if any(str(r["id"]) == start["round_id"] for r in e.get("rounds", []))), None)
        how = "the link's round_id"
    if not chosen and event:
        chosen, how = pick_event(events, event), "--event"
    if not chosen and start.get("result_id") and page_abbr:
        abbr = page_abbr(start["url"])
        chosen = next((e for e in events if abbr and e["abbr"].casefold() == abbr.casefold()), None)
        how = "the results page the link points at, read in the browser"
    if not chosen and competitor:
        entered = events_with_competitor(speech, competitor)
        if len(entered) == 1:
            chosen, how = entered[0], "the one speech event the competitor is in"
        elif entered:
            raise ResultsError(f"\"{competitor}\" is entered in {len(entered)} speech events; name one with --event: "
                               + describe_events(entered))
    if not chosen:
        if not speech:
            raise ResultsError("this tournament has no speech event with scored rounds in its public data")
        raise ResultsError(f"which event? Name one with --event. Speech events with results: {describe_events(speech)}")
    if chosen.get("type") != "speech":
        raise ResultsError(f"{chosen['name']} is a {chosen.get('type')} event; this script handles speech events "
                           "(ranks and points), not win/loss events")
    print(f"event: {chosen['name']} ({chosen['abbr']}), from {how}", file=sys.stderr)
    return chosen


def slug(label):
    return re.sub(r"[^a-z0-9]+", "_", str(label).lower()).strip("_")


def local_dates(data):
    """The tournament's dates in its own timezone, e.g. '2026-10-16 to 2026-10-18 (America/Los_Angeles)'."""
    zone = data.get("timezone") or "UTC"
    try:
        tz = ZoneInfo(zone)
        days = [datetime.datetime.strptime(data[k], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
                .astimezone(tz).date().isoformat() for k in ("start", "end")]
    except (KeyError, ValueError, TypeError):
        return ""
    return (days[0] if days[0] == days[1] else f"{days[0]} to {days[1]}") + f" ({zone})"


def parse_result_sets(ev, entries):
    """Tabroom's own result sets: [{label, tag, keys: [{tag, description}], rows: [...]}]."""
    sets = []
    for rs in ev.get("result_sets", []):
        keys = {str(k["id"]): {"tag": k.get("tag") or "", "description": (k.get("description") or "").strip()}
                for k in rs.get("result_keys", [])}
        rows = []
        for r in rs.get("results", []):
            entry_id = str(r.get("entry"))
            values, priority = {}, {}
            for v in r.get("values", []):
                key = keys.get(str(v.get("result_key")))
                if key and v.get("value") is not None:
                    values[key["tag"]] = str(v["value"]).strip()
                    priority[key["tag"]] = v.get("priority") or 0
            rows.append({"place": str(r.get("place") or ""), "entry": entry_id,
                         "name": entries.get(entry_id, {}).get("name", ""), "values": values, "priority": priority})
        sets.append({"label": rs.get("label") or "", "tag": rs.get("tag") or "", "keys": list(keys.values()), "rows": rows})
    return sets


def tiebreaker_of(description):
    d = description.strip().lower()
    if "in prelims" not in d:
        return None
    for name in DEFAULT_TIEBREAKERS:
        if d.startswith(name):
            return name
    return "unknown"


def prelim_values(result_set, row):
    """{tiebreaker: value} for the prelim totals a result row carries."""
    out = {}
    for key in result_set["keys"]:
        name = tiebreaker_of(key["description"])
        if name and name != "unknown" and key["tag"] in row["values"]:
            out[name] = row["values"][key["tag"]]
    return out


def tiebreakers_from(result_sets):
    """(order, as_printed, known): the prelim tiebreakers Tabroom applied, in priority order.

    `known` is False when no result row carries prelim totals, or one of the
    tiebreakers is not one this script computes; the default order is used and
    the analysis says so.
    """
    for rs in sorted(result_sets, key=lambda s: s["label"] != "Prelim Seeds"):
        described = {k["tag"]: k["description"] for k in rs["keys"] if tiebreaker_of(k["description"])}
        for row in rs["rows"]:
            tags = sorted((t for t in row["values"] if t in described), key=lambda t: row["priority"].get(t, 0))
            if not tags:
                continue
            printed = [described[t] for t in tags]
            order = [tiebreaker_of(d) for d in printed]
            if "unknown" in order:
                return list(DEFAULT_TIEBREAKERS), printed, False
            return order, printed, True
    return list(DEFAULT_TIEBREAKERS), [], False


def backfill_points(rounds, result_sets):
    """Fill missing ballot points from the per-round strings in a result set.

    Some tournaments publish ranks on ballots and points only inside the
    `Ballots` value of a result row ("R1  2  19 |"). A round line is used only
    when the entry has exactly one ballot in that round and the rank agrees.
    """
    filled = 0
    by_number = {r["number"]: r for r in rounds}
    for rs in result_sets:
        for row in rs["rows"]:
            for line in (row["values"].get("Ballots") or "").splitlines():
                m = re.match(r"\s*R(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s*\|\s*$", line)
                if not m or int(m.group(1)) not in by_number:
                    continue
                rnd = by_number[int(m.group(1))]
                mine = [b for b in rnd["ballots"] if b["entry"] == row["entry"]]
                if len(mine) == 1 and mine[0]["points"] is None and mine[0]["rank"] == int(m.group(2)):
                    mine[0]["points"] = parse_number(m.group(3))
                    filled += 1
    return filled


def parse_number(text):
    value = float(text)
    return int(value) if value == int(value) else value


def build_event(data, ev):
    """One event's rounds, ballots and result sets, from the tournament data."""
    entries = event_entries(data, ev)
    school_codes = {s.get("code"): s.get("name") or "" for s in data.get("schools", []) if s.get("code")}
    rounds, missing = [], []
    for r in sorted(ev.get("rounds", []), key=lambda r: int(r.get("name") or 0)):
        number = int(r.get("name") or 0)
        stage = "elim" if r.get("type") in ELIM_TYPES else "prelim"
        label = r.get("label") or f"Round {number}"
        ballots = []
        for section in r.get("sections", []):
            for b in section.get("ballots", []):
                scores = {s.get("tag"): s.get("value") for s in b.get("scores", [])}
                if scores.get("rank") is None:
                    continue    # not scored, or not published
                entry_id = str(b.get("entry"))
                known = entries.get(entry_id, {})
                code = b.get("entry_code") or known.get("code", "")
                name = b.get("entry_name") or known.get("name", "")
                ballots.append({
                    "section": str(section.get("letter") or ""), "room": str(section.get("room") or ""),
                    "order": b.get("speakerorder"), "entry": entry_id, "code": code, "name": name,
                    "school": known.get("school") or school_of(code, name, school_codes),
                    "judge": " ".join(x for x in (b.get("judge_first"), b.get("judge_last")) if x),
                    "rank": int(scores["rank"]),
                    "points": parse_number(str(scores["point"])) if scores.get("point") is not None else None,
                })
        if not ballots:
            missing.append(label)
            continue
        ballots.sort(key=lambda b: (b["section"], b["judge"], b["order"] or 0))
        rounds.append({"id": str(r.get("id")), "label": label, "number": number, "stage": stage,
                       "key": f"r{number}" if stage == "prelim" else slug(label),
                       "judges": sorted({b["judge"] for b in ballots}), "ballots": ballots})
    if not rounds:
        raise ResultsError(f"{ev['name']} has no scored ballots in the tournament's public data")
    result_sets = parse_result_sets(ev, entries)
    direct = sum(1 for r in rounds for b in r["ballots"] if b["points"] is not None)
    filled = backfill_points(rounds, result_sets)
    order, printed, known = tiebreakers_from(result_sets)
    return {"tournament": data.get("name") or "", "tourn_id": str(data.get("id") or ""), "dates": local_dates(data),
            "location": ", ".join(x for x in (data.get("city"), data.get("state")) if x),
            "event": ev["name"], "event_abbr": ev["abbr"], "event_id": str(ev["id"]),
            "rounds": rounds, "rounds_missing": missing, "result_sets": result_sets,
            "points_on_ballots": direct, "points_from_result_sets": filled,
            "tiebreakers": order, "tiebreakers_printed": printed, "tiebreakers_known": known}


# -- standings ----------------------------------------------------------------

def seed_key(entry, order):
    parts = {"ranks": entry["rank_total"], "reciprocals": -round(entry["reciprocals"], 6),
             "points": -entry["points_total"]}
    return tuple(parts[name] for name in order)


def seed_entries(prelims, order):
    """Entries built from prelim rounds and sorted into seed order.

    An entry with fewer prelim ballots than the fullest entry has an
    incomparable rank total, so it is seeded after every complete entry.
    """
    entries = {}
    for rnd in prelims:
        for b in rnd["ballots"]:
            e = entries.setdefault(b["entry"], {"entry": b["entry"], "code": b["code"], "name": b["name"],
                                                "school": b["school"], "prelim": [], "elim": {},
                                                "final_place": None, "tabroom_seed": None})
            e["prelim"].append({"round": rnd["key"], "label": rnd["label"], "section": b["section"],
                                "judge": b["judge"], "rank": b["rank"], "points": b["points"]})
    full = max((len(e["prelim"]) for e in entries.values()), default=0)
    for e in entries.values():
        e["rank_total"] = sum(p["rank"] for p in e["prelim"])
        e["reciprocals"] = sum(1 / p["rank"] for p in e["prelim"])
        e["points_total"] = sum(p["points"] or 0 for p in e["prelim"])
        e["firsts"] = sum(1 for p in e["prelim"] if p["rank"] == 1)
        e["prelim_ballots"] = len(e["prelim"])
        e["complete"] = len(e["prelim"]) == full
    ranked = sorted(entries.values(), key=lambda e: (not e["complete"], seed_key(e, order), e["name"]))
    for i, e in enumerate(ranked, 1):
        e["seed"] = i
    return ranked


def build_standings(event):
    prelims = [r for r in event["rounds"] if r["stage"] == "prelim"]
    elims = [r for r in event["rounds"] if r["stage"] == "elim"]
    if not prelims:
        raise ResultsError("no preliminary round with ballots was found, so there is nothing to seed")
    standings = seed_entries(prelims, event["tiebreakers"])
    by_entry = {e["entry"]: e for e in standings}
    for rnd in elims:
        for b in rnd["ballots"]:
            if b["entry"] in by_entry:
                by_entry[b["entry"]]["elim"].setdefault(rnd["key"], []).append(b["rank"])
    first_elim = elims[0]["key"] if elims else None
    for e in standings:
        e["broke"] = bool(first_elim and first_elim in e["elim"])
    for rs in event["result_sets"]:
        for row in rs["rows"]:
            e = by_entry.get(row["entry"])
            if not e or not re.match(r"\d", row["place"]):
                continue
            if rs["label"] == "Prelim Seeds":
                e["tabroom_seed"] = row["place"]       # "3", or "1-T" for a tie
            elif rs["label"] == "Final Places":
                e["final_place"] = row["place"]
    return standings


def break_summary(standings):
    broke = [e for e in standings if e["broke"]]
    size = len(broke)
    return {"size": size, "cut": max(broke, key=lambda e: e["seed"]) if broke else None,
            "by_seed": bool(broke) and all(e["seed"] <= size for e in broke),
            "first_out": next((e for e in standings if not e["broke"]), None)}


def check_against_tabroom(standings, result_sets):
    """Compare rebuilt prelim totals and seeds with the ones in Tabroom's result sets.

    Reciprocals are printed truncated to two decimals, hence the tolerance. A
    tied seed ("1-T") names a group, so only untied seeds are compared.
    """
    by_entry = {e["entry"]: e for e in standings}
    checked, mismatches, unmatched = set(), [], []
    for rs in result_sets:
        for row in rs["rows"]:
            theirs = prelim_values(rs, row)
            if not theirs:
                continue
            e = by_entry.get(row["entry"])
            if not e:
                label = row["name"] or row["entry"]
                if label not in unmatched:
                    unmatched.append(label)
                continue
            if e["entry"] in checked:
                continue        # listed in both Final Places and Prelim Seeds
            checked.add(e["entry"])
            ours = {"ranks": e["rank_total"], "reciprocals": e["reciprocals"], "points": e["points_total"]}
            for name, value in theirs.items():
                try:
                    value = float(value)
                except ValueError:
                    continue
                if abs(ours[name] - value) > (0.011 if name == "reciprocals" else 1e-9):
                    mismatches.append({"entry": e["name"], "tiebreaker": name,
                                       "rebuilt": round(ours[name], 2), "tabroom": value})
    seeded = [e for e in standings if e["tabroom_seed"]]
    seed_differs = [{"entry": e["name"], "rebuilt": e["seed"], "tabroom": e["tabroom_seed"]}
                    for e in seeded if e["tabroom_seed"].isdigit() and int(e["tabroom_seed"]) != e["seed"]]
    return {"checked": len(checked), "mismatches": mismatches, "unmatched": unmatched,
            "seeds_compared": len(seeded), "seed_differs": seed_differs}


def find_competitor(standings, query):
    """The one entry whose name contains `query`, case-insensitively."""
    q = query.strip().lower()
    hits = [e for e in standings if q in e["name"].lower()]
    hits = [e for e in hits if e["name"].lower() == q] or hits
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ResultsError(f"no entry in this event matches \"{query}\"")
    raise ResultsError(f"\"{query}\" matches {len(hits)} entries: " + ", ".join(e["name"] for e in hits))


def simulate_one_rank_better(event, entry_id, break_size):
    """For each prelim ballot of the entry ranked below 1st: swap ranks with the
    room-mate one place above and re-seed. Points are left as the judges gave them."""
    prelims = [r for r in event["rounds"] if r["stage"] == "prelim"]
    results = []
    for i, rnd in enumerate(prelims):
        for b in rnd["ballots"]:
            if b["entry"] != entry_id or b["rank"] == 1:
                continue
            trial = copy.deepcopy(prelims)
            room = [x for x in trial[i]["ballots"] if x["section"] == b["section"] and x["judge"] == b["judge"]]
            mine = next(x for x in room if x["entry"] == entry_id)
            above = next((x for x in room if x["rank"] == b["rank"] - 1), None)
            mine["rank"] -= 1
            if above:
                above["rank"] += 1
            new = next(e for e in seed_entries(trial, event["tiebreakers"]) if e["entry"] == entry_id)
            results.append({"round": rnd["label"], "judge": b["judge"], "from": b["rank"], "to": b["rank"] - 1,
                            "swapped_with": above["name"] if above else None, "seed": new["seed"],
                            "rank_total": new["rank_total"], "reciprocals": new["reciprocals"],
                            "would_break": new["seed"] <= break_size})
    return results


# -- output -------------------------------------------------------------------

def num(value):
    if value is None:
        return ""
    return str(int(value)) if float(value) == int(value) else f"{value:.2f}"


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def ranks_text(entry):
    return ", ".join(str(p["rank"]) for p in entry["prelim"])


def totals_text(entry):
    return (f"rank total {entry['rank_total']}, reciprocals {num(entry['reciprocals'])}, "
            f"points {num(entry['points_total'])}")


def deciding_tiebreaker(entry, other, order):
    for name, a, b in zip(order, seed_key(entry, order), seed_key(other, order)):
        if a != b:
            return name
    return None


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(lines)


def standing_row(e):
    return [e["seed"], e["name"], e["school"], ranks_text(e), e["rank_total"], num(e["reciprocals"]),
            num(e["points_total"]), e["firsts"], "yes" if e["broke"] else "no", e["final_place"] or ""]


STANDING_HEADER = ["Seed", "Entry", "School", "Prelim ranks", "Rank total", "Reciprocals", "Points", "1sts",
                   "Broke", "Final place"]


def room_of(rnd, ballot):
    return [b for b in rnd["ballots"] if b["section"] == ballot["section"] and b["judge"] == ballot["judge"]]


def render_analysis(event, standings, check, competitor=None, simulation=None):
    brk = break_summary(standings)
    order = event["tiebreakers"]
    prelims = [r for r in event["rounds"] if r["stage"] == "prelim"]
    elims = [r for r in event["rounds"] if r["stage"] == "elim"]
    title = ", ".join(x for x in (event["tournament"], event["event"]) if x) or "Tabroom event"
    order_text = ", then ".join(TIEBREAKER_NAMES[n] for n in order)
    cut = brk["cut"]

    findings = []
    if cut:
        findings.append(
            f"{brk['size']} of {len(standings)} entries broke to {elims[0]['label']}. The last one in was seed "
            f"{cut['seed']}, {cut['name']} (ranks {ranks_text(cut)}; {totals_text(cut)})."
            + ("" if brk["by_seed"] else " The entries that broke are not the top seeds as rebuilt here; see the checks section."))
    else:
        findings.append(f"{len(standings)} entries; no elimination round has ballots, so no break can be read off.")
    if competitor:
        c = competitor
        line = (f"{c['name']} seeded {ordinal(c['seed'])} of {len(standings)} after prelims on ranks "
                f"{ranks_text(c)} ({totals_text(c)}).")
        if c["broke"]:
            line += " They broke" + (f" and placed {c['final_place']}." if c["final_place"] else ".")
        elif cut:
            decider = deciding_tiebreaker(c, cut, order)
            places_out = c["seed"] - brk["size"]
            line += f" That is {places_out} place{'s' if places_out != 1 else ''} below the cut."
            if decider == "ranks":
                line += f" The gap to the cut is rank total: {c['rank_total']} against {cut['rank_total']}."
            elif decider:
                tied = " and ".join("rank total" if n == "ranks" else n for n in order[:order.index(decider)])
                shown = {"reciprocals": lambda e: num(e["reciprocals"]), "points": lambda e: num(e["points_total"])}[decider]
                line += f" They tied the cut on {tied} and lost on {decider}: {shown(c)} against {shown(cut)}."
        findings.append(line)
        if simulation is not None and not c["broke"] and cut:
            enough = [s for s in simulation if s["would_break"]]
            if enough:
                findings.append("One rank better in a single prelim would have been enough in: "
                                + "; ".join(f"{s['round']} ({s['from']} to {s['to']}, seed {s['seed']})" for s in enough) + ".")
            else:
                findings.append("One rank better in any single prelim would not have been enough to break.")
    if check["checked"]:
        findings.append(
            f"Rebuilt prelim totals were checked against Tabroom's for {check['checked']} of {len(standings)} entries: "
            + ("all match." if not check["mismatches"] else f"{len(check['mismatches'])} differ; see the checks section."))
    else:
        findings.append("Rebuilt totals could not be checked against Tabroom's: no result set with prelim totals is published.")
    if check["seeds_compared"]:
        findings.append(
            f"Tabroom's own Prelim Seeds list covers {check['seeds_compared']} entries: "
            + ("every untied seed matches the rebuilt order." if not check["seed_differs"]
               else f"{len(check['seed_differs'])} seed(s) differ from the rebuilt order; see the checks section."))

    where = ", ".join(x for x in (event["dates"], event["location"]) if x)
    sections = [("Objective",
                 f"How the break in {title} was decided"
                 + (f", and how close {competitor['name']} came to it." if competitor else ".")
                 + (f" Tournament: {where}." if where else "")
                 + f" Built from {sum(len(r['ballots']) for r in event['rounds'])} ballots across "
                   f"{len(prelims)} prelim and {len(elims)} elimination round(s)."),
                ("Key findings", "\n".join(f"- {f}" for f in findings))]

    how = [f"Entries are seeded on prelims by {order_text}."
           + ("" if event["tiebreakers_known"] else
              " This order is assumed: no result set with prelim totals is published, or it names a tiebreaker this script does not compute"
              + (f" ({'; '.join(event['tiebreakers_printed'])})." if event["tiebreakers_printed"] else "."))]
    if cut:
        last = min(len(standings), brk["size"] + 5)
        how.append(f"Seeds 1 to {last} (the cut falls after seed {brk['size']}):")
        how.append(table(STANDING_HEADER, [standing_row(e) for e in standings[:last]]))
        level = [e for e in standings if e["rank_total"] == cut["rank_total"]]
        if len(level) > 1:
            how.append(f"{len(level)} entries share the cut's rank total of {cut['rank_total']}: "
                       + ", ".join(f"{e['name']} (seed {e['seed']}, reciprocals {num(e['reciprocals'])}, "
                                   f"points {num(e['points_total'])}, {'broke' if e['broke'] else 'out'})" for e in level) + ".")
    else:
        how.append(table(STANDING_HEADER, [standing_row(e) for e in standings]))
    sections.append(("How the break worked", "\n\n".join(how)))

    if competitor:
        rows = []
        for rnd in prelims:
            for b in (x for x in rnd["ballots"] if x["entry"] == competitor["entry"]):
                room = room_of(rnd, b)
                pts = [x["points"] for x in room if x["points"] is not None]
                winners = [x for x in room if x["rank"] == 1]
                rows.append([rnd["label"], b["section"], b["judge"], f"{b['rank']} of {len(room)}", num(b["points"]),
                             ", ".join(f"{w['name']} ({num(w['points'])})" if w["points"] is not None else w["name"]
                                       for w in winners),
                             f"{num(min(pts))} to {num(max(pts))}" if pts else "",
                             f"{sum(pts) / len(pts):.1f}" if pts else ""])
        sections.append((f"{competitor['name']}'s rooms",
                         table(["Round", "Section", "Judge", "Rank", "Points", "Room winner (points)",
                                "Room points range", "Room points average"], rows)))
        if simulation is not None:
            if simulation:
                body = ("Each row moves one prelim rank up by one, swapping with the room-mate who held that rank, "
                        "and re-seeds the whole event. Points are left as given.\n\n"
                        + table(["Round", "Judge", "Rank change", "Swapped with", "New rank total", "New reciprocals",
                                 "New seed", f"Inside the top {brk['size']}" if cut else "Breaks"],
                                [[s["round"], s["judge"], f"{s['from']} to {s['to']}", s["swapped_with"] or "",
                                  s["rank_total"], num(s["reciprocals"]), s["seed"],
                                  ("yes" if s["would_break"] else "no") if cut else ""] for s in simulation]))
            else:
                body = "Every prelim rank was already a 1st; there is no single rank to improve."
            sections.append(("What one rank better would have changed", body))

    broke = [e for e in standings if e["broke"]]
    if broke:
        worst = max(max(p["rank"] for p in e["prelim"]) for e in broke)
        facts = [f"{sum(1 for e in broke if e['firsts'])} of {len(broke)} had at least one 1st in prelims.",
                 f"Their rank totals run from {min(e['rank_total'] for e in broke)} to {max(e['rank_total'] for e in broke)}.",
                 f"The worst single prelim rank carried into the break was a {worst}."]
        out_with_first = [e for e in standings if not e["broke"] and e["firsts"]]
        if out_with_first:
            facts.append(f"{len(out_with_first)} entr{'y' if len(out_with_first) == 1 else 'ies'} with a 1st did not break: "
                         + ", ".join(f"{e['name']} ({ranks_text(e)})" for e in out_with_first) + ".")
        sections.append(("Who broke", "\n".join(f"- {f}" for f in facts) + "\n\n"
                         + table(STANDING_HEADER, [standing_row(e) for e in broke])))

    scale_rows = []
    for rnd in prelims:
        rooms = {}
        for b in rnd["ballots"]:
            rooms.setdefault((b["section"], b["judge"]), []).append(b)
        for (section, judge), room in sorted(rooms.items()):
            pts = [b["points"] for b in room if b["points"] is not None]
            if pts:
                scale_rows.append([rnd["label"], section, judge, len(room), num(min(pts)), num(max(pts)),
                                   f"{sum(pts) / len(pts):.1f}"])
    if scale_rows:
        sections.append(("Judge point scales",
                         "Points are comparable only inside one room: each judge uses their own range, which is why "
                         "points come last among the tiebreakers.\n\n"
                         + table(["Round", "Section", "Judge", "Entries", "Lowest", "Highest", "Average"], scale_rows)))

    checks = []
    if check["mismatches"]:
        checks.append("Totals that differ from Tabroom's:\n\n" + table(
            ["Entry", "Tiebreaker", "Rebuilt", "Tabroom"],
            [[m["entry"], m["tiebreaker"], num(m["rebuilt"]), num(m["tabroom"])] for m in check["mismatches"]]))
    if check["seed_differs"]:
        checks.append("Seeds that differ from Tabroom's Prelim Seeds list:\n\n" + table(
            ["Entry", "Rebuilt seed", "Tabroom seed"],
            [[m["entry"], m["rebuilt"], m["tabroom"]] for m in check["seed_differs"]]))
    if check["unmatched"]:
        checks.append("Result rows for entries with no prelim ballot: " + ", ".join(check["unmatched"]) + ".")
    if event["rounds_missing"]:
        checks.append("Rounds with no scored ballots in the public data: " + ", ".join(event["rounds_missing"]) + ".")
    if event["points_from_result_sets"]:
        checks.append(f"Points for {event['points_from_result_sets']} prelim ballots are not on the ballots in the public "
                      "data; they were read from the per-round strings in Tabroom's result sets.")
    prelim_ballots = sum(len(r["ballots"]) for r in prelims)
    pointless = sum(1 for r in prelims for b in r["ballots"] if b["points"] is None)
    if pointless:
        checks.append(f"{pointless} of {prelim_ballots} prelim ballots carry no points in the public data; "
                      "point totals count them as 0, so the points tiebreaker is unreliable here.")
    incomplete = [e for e in standings if not e["complete"]]
    if incomplete:
        checks.append("Entries with fewer prelim ballots than the rest, seeded after every complete entry: "
                      + ", ".join(f"{e['name']} ({e['prelim_ballots']})" for e in incomplete) + ".")
    level = {}
    for e in standings:
        level.setdefault(seed_key(e, order), []).append(e)
    for group in (g for g in level.values() if len(g) > 1):
        checks.append("Level on every tiebreaker, so listed alphabetically between seeds "
                      f"{group[0]['seed']} and {group[-1]['seed']}: " + ", ".join(e["name"] for e in group) + ".")
    if cut and not brk["by_seed"]:
        outside = [e for e in broke if e["seed"] > brk["size"]]
        checks.append("Entries in the first elimination round from outside the top seeds: "
                      + ", ".join(f"{e['name']} (seed {e['seed']})" for e in outside)
                      + ". The tournament may break on something other than these tiebreakers.")
    checks.append("Ballot comments are not in this data; each competitor's are visible only to their own Tabroom login. "
                  "Ranks and points show where the places were lost, not why.")
    sections.append(("Data and checks", "\n\n".join(checks)))

    out = [f"# {title}: results analysis", ""]
    for i, (heading, body) in enumerate(sections, 1):
        out += [f"## {i}. {heading}", "", body, ""]
    return "\n".join(out)


def csv_safe(row):
    """Names, codes, schools and judges come from Tabroom as typed by users. A
    cell that starts like a formula is prefixed with a quote, so a spreadsheet
    opens it as text."""
    return {k: ("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v)
            for k, v in row.items()}


def ballot_rows(event):
    return [{"round": r["label"], "stage": r["stage"], **b} for r in event["rounds"] for b in r["ballots"]]


def write_outputs(event, standings, check, analysis, out_dir, source):
    os.makedirs(out_dir, exist_ok=True)
    prelims = [r for r in event["rounds"] if r["stage"] == "prelim"]
    elims = [r for r in event["rounds"] if r["stage"] == "elim"]
    ballots = ballot_rows(event)

    def dump(name, value):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)

    dump("ballots.json", ballots)
    dump("result_sets.json", event["result_sets"])
    brk = break_summary(standings)
    dump("event.json", {
        "type": "tabroom-event-results", "source": source,
        **{k: event[k] for k in ("tournament", "tourn_id", "dates", "location", "event", "event_abbr", "event_id")},
        "rounds": [{"id": r["id"], "label": r["label"], "stage": r["stage"], "judges": r["judges"],
                    "ballots": len(r["ballots"])} for r in event["rounds"]],
        "rounds_missing": event["rounds_missing"], "entries": len(standings), "ballots": len(ballots),
        "points_on_ballots": event["points_on_ballots"], "points_from_result_sets": event["points_from_result_sets"],
        "tiebreakers": event["tiebreakers"], "tiebreakers_printed": event["tiebreakers_printed"],
        "tiebreakers_known": event["tiebreakers_known"], "break_size": brk["size"],
        "break_by_seed": brk["by_seed"], "check": check,
        "captured_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    with open(os.path.join(out_dir, "ballots.csv"), "w", encoding="utf-8", newline="") as f:
        cols = ["round", "stage", "section", "room", "order", "entry", "code", "name", "school", "judge", "rank", "points"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(csv_safe(b) for b in ballots)
    with open(os.path.join(out_dir, "standings.csv"), "w", encoding="utf-8", newline="") as f:
        cols = (["seed", "name", "school", "code"]
                + [f"{r['key']}_{x}" for r in prelims for x in ("rank", "points")]
                + ["rank_total", "reciprocals", "points_total", "firsts", "prelim_ballots", "broke"]
                + [f"{r['key']}_ranks" for r in elims] + ["final_place", "tabroom_seed"])
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for e in standings:
            row = {k: e[k] for k in ("seed", "name", "school", "code", "rank_total", "points_total", "firsts",
                                     "prelim_ballots")}
            row["reciprocals"] = f"{e['reciprocals']:.4f}"
            row["broke"] = "yes" if e["broke"] else "no"
            row["final_place"] = e["final_place"] or ""
            row["tabroom_seed"] = e["tabroom_seed"] or ""
            for r in prelims:
                mine = [p for p in e["prelim"] if p["round"] == r["key"]]
                row[f"{r['key']}_rank"] = "/".join(str(p["rank"]) for p in mine)
                row[f"{r['key']}_points"] = "/".join(num(p["points"]) for p in mine)
            for r in elims:
                row[f"{r['key']}_ranks"] = "/".join(str(x) for x in e["elim"].get(r["key"], []))
            w.writerow(csv_safe(row))
    with open(os.path.join(out_dir, "analysis.md"), "w", encoding="utf-8") as f:
        f.write(analysis)


# -- sources ------------------------------------------------------------------

def load_raw(path):
    """(text, file path) of a saved tournament JSON: a file, a directory, or a directory with raw/."""
    candidates = [path] if os.path.isfile(path) else sorted(
        glob.glob(os.path.join(path, "raw", "tournament_*.json")) + glob.glob(os.path.join(path, "tournament_*.json")))
    if not candidates:
        raise ResultsError(f"no tournament_*.json in {path} or {os.path.join(path, 'raw')}")
    if len(candidates) > 1:
        raise ResultsError("more than one tournament file; give one: " + ", ".join(candidates))
    with open(candidates[0], encoding="utf-8") as f:
        return f.read(), candidates[0]


def browser_page_abbr(url):
    """The event abbreviation printed on a results page ("NOO Results"), or "".

    Result pages need a login, so this goes through the gstack browser by way
    of the `fetch` plugin's adapter. Any failure returns "": the caller then
    asks for --event instead.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    plugin = os.path.dirname(here)
    candidates = [os.path.join(os.path.dirname(plugin), "fetch", "scripts")]               # repo layout
    candidates += sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(plugin)), "fetch", "*", "scripts")),
                         key=os.path.getmtime, reverse=True)                              # plugin cache layout
    scripts = next((p for p in candidates if os.path.isfile(os.path.join(p, "_browse.py"))), None)
    if not scripts:
        return ""
    try:
        sys.path.insert(0, scripts)
        from _browse import sync_browse_page
        with sync_browse_page(quiet=True) as page:
            page.goto(url)
            found = page.evaluate("() => Array.from(document.querySelectorAll('h4')).map(h => h.innerText.trim())")
    except Exception as e:      # noqa: BLE001 - the browser is optional here; every failure means "ask for --event"
        print(f"NOTE: could not read the results page in the browser ({type(e).__name__})", file=sys.stderr)
        return ""
    for text in found or []:
        m = re.match(r"(.+) Results$", str(text))
        if m and m.group(1) != "Event":
            return m.group(1)
    return ""


def main(argv, get=http_get, page_abbr=browser_page_abbr):
    ap = argparse.ArgumentParser(
        prog="tabroom_event_results.py",
        description="Download a Tabroom tournament's public data and analyse the break of one speech event.")
    ap.add_argument("start", nargs="?", help="any Tabroom URL of the tournament, or a tournament name to search for")
    ap.add_argument("out_dir", nargs="?", help="output directory (default: a temp directory)")
    ap.add_argument("--event", metavar="NAME", help="the event: its name or abbreviation (e.g. \"Novice Oratory\", NOO)")
    ap.add_argument("--competitor", metavar="NAME", help="entry to analyse against the break (part of the name is enough)")
    ap.add_argument("--from-raw", metavar="PATH", help="rebuild from an earlier download (its directory or JSON file)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    positional = [a for a in (args.start, args.out_dir) if a]
    if args.from_raw:
        if len(positional) > 1:
            print("ERROR: with --from-raw, give at most an output directory", file=sys.stderr)
            return 2
        args.start, args.out_dir = None, (positional[0] if positional else None)   # `--from-raw PATH [out_dir]`
    elif not positional:
        print("ERROR: give a Tabroom URL or a tournament name, or --from-raw PATH", file=sys.stderr)
        return 2

    try:
        if args.from_raw:
            text, source = load_raw(args.from_raw)
            start = {"kind": "tournament"}
        else:
            try:
                start = parse_start(args.start)
            except ValueError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 2
            if start["kind"] == "search":
                chosen = pick_tournament(parse_search_results(get(SEARCH_URL.format(quote_plus(start["query"])))),
                                         start["query"])
                print(f"tournament: {describe_tournament(chosen)}", file=sys.stderr)
                start = {"kind": "tournament", "tourn_id": chosen["tourn_id"]}
            text, source = get(DATA_URL.format(start["tourn_id"])), args.start
        data = parse_tournament_data(text, start.get("tourn_id", ""))
        chosen_event = resolve_event(data, start, args.event, args.competitor, page_abbr)
        event = build_event(data, chosen_event)
        standings = build_standings(event)
    except ResultsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out_dir = os.path.abspath(args.out_dir) if args.out_dir else tempfile.mkdtemp(prefix="tabroom-event-")
    raw_path = os.path.join(out_dir, "raw", f"tournament_{event['tourn_id']}.json")
    os.makedirs(os.path.dirname(raw_path), exist_ok=True)
    if not (args.from_raw and os.path.exists(raw_path) and os.path.samefile(raw_path, str(source))):
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(text)

    check = check_against_tabroom(standings, event["result_sets"])
    brk = break_summary(standings)
    competitor, simulation, failed = None, None, None
    if args.competitor:
        try:
            competitor = find_competitor(standings, args.competitor)
            simulation = simulate_one_rank_better(event, competitor["entry"], brk["size"])
        except ResultsError as e:
            failed = e
    write_outputs(event, standings, check, render_analysis(event, standings, check, competitor, simulation),
                  out_dir, source)

    if not event["tiebreakers_known"]:
        print("WARNING: prelim tiebreakers not read from Tabroom's result sets; seeded by ranks, reciprocals, points",
              file=sys.stderr)
    if event["rounds_missing"]:
        print(f"WARNING: no scored ballots for: {', '.join(event['rounds_missing'])}", file=sys.stderr)
    if check["mismatches"]:
        print(f"WARNING: {len(check['mismatches'])} rebuilt total(s) differ from Tabroom's; see analysis.md",
              file=sys.stderr)
    if check["seed_differs"]:
        print(f"WARNING: {len(check['seed_differs'])} rebuilt seed(s) differ from Tabroom's Prelim Seeds; see analysis.md",
              file=sys.stderr)
    if not check["checked"]:
        print("WARNING: rebuilt totals were not checked against Tabroom's (no prelim totals in its result sets)",
              file=sys.stderr)
    if brk["size"] and not brk["by_seed"]:
        print("WARNING: the entries that broke are not the top seeds as rebuilt", file=sys.stderr)
    print(f"{event['tournament']}, {event['event']}: {len(standings)} entries, "
          f"{sum(len(r['ballots']) for r in event['rounds'])} ballots, {len(event['rounds'])} round(s), "
          f"break of {brk['size']}, {check['checked']} totals checked -> {out_dir}", file=sys.stderr)
    if failed:
        # The data is on disk, but a chained caller asked about one competitor
        # and must not get an analysis that silently leaves them out.
        print(f"ERROR: {failed}. Data written to {out_dir}; rerun with --from-raw and a name from standings.csv",
              file=sys.stderr)
        return 1
    print(f"OUTPUT_DIR:{out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
