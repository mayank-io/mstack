"""Tests for the Tabroom event-results download and break analysis.

The tournament JSON is generated here in the shape of what
`/api/download_data.mhtml` returned on 2026-11-15, with invented names. No
test touches the network or a browser: `main` takes its fetcher and its
results-page reader as arguments.

What these pin, each of which yields output that looks fine:

1. Any tournament link. Every tab carries `tourn_id`; only some name the event.
2. Rank-only ballots. One tournament publishes points on ballots, another only
   inside a result row's per-round string; a final has no points at all.
3. Entries missing from schools. The public data leaves some events' entries
   out, so the school has to come from the entry code.
4. Seeding. Rank total, then reciprocals, then points, in Tabroom's priority.
5. The zero. "0 totals differ" and "0 seeds differ" must be able to come out
   non-zero.
6. Search. A tournament name repeats every year; the wrong year parses fine.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tabroom_event_results as ter   # noqa: E402

NAMES = ["Ada Quill", "Ben Rook", "Cy Marsh", "Di Frost", "Eli Stone", "Fay Wren", "Gus Pike", "Hal Dove"]
SCHOOLS = {"Ada Quill": "Ald", "Ben Rook": "Bir", "Cy Marsh": "Ced", "Di Frost": "Ald",
           "Eli Stone": "Bir", "Fay Wren": "Ced", "Gus Pike": "Ald", "Hal Dove": "Bir"}
SCHOOL_NAMES = {"Ald": "Alder High School", "Bir": "Birch High School", "Ced": "Cedar High School"}
ENTRY_ID = {name: 1000 + i for i, name in enumerate(NAMES)}
# round number -> [(section, judge, [(name, rank, points)])]
PRELIMS = {
    1: [("1", "Avery North", [("Ada Quill", 1, 20), ("Ben Rook", 2, 19), ("Cy Marsh", 3, 18), ("Di Frost", 4, 17)]),
        ("2", "Blake South", [("Eli Stone", 1, 18), ("Fay Wren", 2, 17), ("Gus Pike", 3, 16), ("Hal Dove", 4, 15)])],
    2: [("1", "Casey East", [("Ada Quill", 1, 20), ("Eli Stone", 2, 19), ("Gus Pike", 3, 18), ("Hal Dove", 4, 17)]),
        ("2", "Drew West", [("Ben Rook", 1, 20), ("Cy Marsh", 2, 19), ("Fay Wren", 3, 18), ("Di Frost", 4, 16)])],
    3: [("1", "Emery Vale", [("Gus Pike", 1, 20), ("Ada Quill", 2, 19), ("Ben Rook", 3, 18), ("Eli Stone", 4, 16)]),
        ("2", "Finley Moor", [("Cy Marsh", 1, 19), ("Fay Wren", 2, 19), ("Hal Dove", 3, 17), ("Di Frost", 4, 15)])],
}
FINAL_JUDGES = ["Gray Holt", "Harper Lund", "Indigo Peña"]
FINAL = [("Ada Quill", [1, 1, 2]), ("Ben Rook", [2, 3, 1]), ("Cy Marsh", [3, 2, 4]), ("Eli Stone", [4, 4, 3])]
PLACES = {"Ada Quill": "1st", "Ben Rook": "2nd", "Cy Marsh": "3rd", "Eli Stone": "4th"}
# Prelim totals as Tabroom prints them: reciprocals truncated, not rounded.
TOTALS = {"Ada Quill": ("4", "2.5", "59"), "Ben Rook": ("6", "1.83", "57"), "Cy Marsh": ("6", "1.83", "56"),
          "Eli Stone": ("7", "1.75", "53"), "Gus Pike": ("7", "1.66", "54"), "Fay Wren": ("7", "1.33", "54"),
          "Hal Dove": ("11", "0.83", "49"), "Di Frost": ("12", "0.75", "48")}
SEED_ORDER = ["Ada Quill", "Ben Rook", "Cy Marsh", "Eli Stone", "Gus Pike", "Fay Wren", "Hal Dove", "Di Frost"]
KEYS = [("k1", "RkLst", "Ranks in this round"), ("k2", "RcpLst", "Reciprocals in this round"),
        ("k4", "Ballots", "Unadjusted Raw Scores"), ("k5", "RkPm", "Ranks in Prelims"),
        ("k6", "RcpPm", "Reciprocals in Prelims"), ("k7", "PtsPm", " Points in Prelims")]


def ballot(name, judge, order, rank, points=None):
    first, last = judge.split(" ", 1)
    scores = ([{"tag": "point", "value": points}] if points is not None else []) + [{"tag": "rank", "value": rank}]
    return {"entry": ENTRY_ID[name], "entry_code": f"{SCHOOLS[name]} {name}", "entry_name": name,
            "judge_first": first, "judge_last": last, "speakerorder": order, "scores": scores}


def ballots_string(name):
    lines = []
    for number, rooms in PRELIMS.items():
        for _, _, room in rooms:
            for who, rank, points in room:
                if who == name:
                    lines.append(f"R{number}  {rank}  {points} |")
    if name in PLACES:
        lines.append("R4  " + " |".join(str(r) for r in dict(FINAL)[name]) + " | (9)")
    return "\n" + "\n".join(lines)


def prelim_row(name, place, totals=None):
    rk, rcp, pts = totals or TOTALS[name]
    return {"place": place, "entry": ENTRY_ID[name], "values": [
        {"result_key": "k5", "value": rk, "priority": 1}, {"result_key": "k6", "value": rcp, "priority": 2},
        {"result_key": "k7", "value": pts, "priority": 3},
        {"result_key": "k4", "value": ballots_string(name), "priority": 999}]}


def result_sets(with_seeds=True, overrides=None, seed_places=None, third="Points in Prelims"):
    overrides, seed_places = overrides or {}, seed_places or {}
    keys = [{"id": i, "tag": tag, "description": third if tag == "PtsPm" else text} for i, tag, text in KEYS]
    final = [{"place": PLACES[name], "entry": ENTRY_ID[name], "round": 14, "values": [
        {"result_key": "k1", "value": str(sum(ranks)), "priority": 1}, {"result_key": "k2", "priority": 2},
        {"result_key": "k4", "value": ballots_string(name), "priority": 999}]} for name, ranks in FINAL]
    final += [prelim_row(name, "Prelim", overrides.get(name)) for name in SEED_ORDER if name not in PLACES]
    sets = [{"label": "Final Places", "tag": "final", "result_keys": keys, "results": final}]
    if with_seeds:
        seeds = [prelim_row(name, seed_places.get(name, str(i)), overrides.get(name))
                 for i, name in enumerate(SEED_ORDER, 1)]
        sets.append({"label": "Prelim Seeds", "tag": "seed", "result_keys": keys, "results": seeds})
    return sets


def tournament(points_on_ballots=True, entries_in_schools=True, **sets):
    rounds = []
    for number, rooms in PRELIMS.items():
        sections = [{"letter": section, "room": f"R{section}", "ballots": [
            ballot(name, judge, i, rank, points if points_on_ballots else None)
            for i, (name, rank, points) in enumerate(room, 1)]} for section, judge, room in rooms]
        rounds.append({"id": str(10 + number), "name": number, "type": "prelim", "sections": sections})
    final = [ballot(name, judge, i, rank) for i, (name, ranks) in enumerate(FINAL, 1)
             for judge, rank in zip(FINAL_JUDGES, ranks)]
    rounds.append({"id": "14", "name": 4, "label": "FINALS", "type": "final",
                   "sections": [{"letter": "1", "room": "Hall", "ballots": final}]})
    oratory = {"id": "500", "abbr": "NTO", "name": "Novice Test Oratory", "type": "speech",
               "rounds": rounds, "result_sets": result_sets(**sets)}
    other = {"id": "700", "abbr": "OTO", "name": "Open Test Oratory", "type": "speech", "result_sets": [], "rounds": [
        {"id": "71", "name": 1, "type": "prelim", "sections": [{"letter": "1", "room": "A", "ballots": [
            {"entry": 2001, "entry_code": "Ald Ada Quill", "entry_name": "Ada Quill", "judge_first": "Jo", "judge_last": "Reed",
             "speakerorder": 1, "scores": [{"tag": "rank", "value": 1}]},
            {"entry": 2002, "entry_code": "Bir Zed Lark", "entry_name": "Zed Lark", "judge_first": "Jo", "judge_last": "Reed",
             "speakerorder": 2, "scores": [{"tag": "rank", "value": 2}]}]}]}]}
    debate = {"id": "600", "abbr": "TD", "name": "Test Debate", "type": "debate", "result_sets": [], "rounds": [
        {"id": "61", "name": 1, "type": "prelim", "sections": [{"letter": "1", "ballots": [
            {"entry": 3001, "entry_code": "Ald QR", "entry_name": "Quill & Rook", "scores": [{"tag": "winloss", "value": 1}]}]}]}]}
    schools = [{"id": str(i), "code": code, "name": SCHOOL_NAMES[code], "entries": [
        {"id": str(ENTRY_ID[n]), "name": n, "code": f"{code} {n}", "event": 500}
        for n in NAMES if SCHOOLS[n] == code and entries_in_schools]} for i, code in enumerate(SCHOOL_NAMES)]
    return {"id": 900, "name": "Testville Invitational", "start": "2026-10-16 15:00:00", "end": "2026-10-19 03:00:00",
            "timezone": "America/Los_Angeles", "city": "Testville", "state": "WA", "schools": schools,
            "categories": [{"abbr": "IE", "events": [oratory, other]}, {"abbr": "DB", "events": [debate]}]}


def event_from(data):
    return ter.build_event(data, ter.pick_event(ter.list_events(data), "NTO"))


@pytest.fixture
def event():
    return event_from(tournament())


@pytest.fixture
def standings(event):
    return ter.build_standings(event)


# -- start --------------------------------------------------------------------

@pytest.mark.parametrize("path,ids", [
    ("index/tourn/main.mhtml?tourn_id=900", {}),                                    # Invite
    ("index/tourn/fields.mhtml?tourn_id=900", {}),                                  # Entries
    ("index/tourn/judges.mhtml?tourn_id=900", {}),                                  # Judges
    ("index/tourn/postings/index.mhtml?tourn_id=900", {}),                          # Pairings
    ("index/tourn/updates/index.mhtml?tourn_id=900", {}),                           # Live Updates
    ("index/tourn/results/index.mhtml?tourn_id=900", {}),                           # Results
    ("index/tourn/results/index.mhtml?tourn_id=900&event_id=500", {"event_id": "500"}),
    ("index/tourn/results/round_results.mhtml?tourn_id=900&round_id=13", {"round_id": "13"}),
    ("index/tourn/results/event_results.mhtml?tourn_id=900&result_id=77", {"result_id": "77"}),
    ("user/student/history.mhtml?tourn_id=900&student_id=5", {}),
])
def test_every_tournament_page_is_a_start(path, ids):
    start = ter.parse_start(f"https://www.tabroom.com/{path}")
    assert (start["kind"], start["tourn_id"]) == ("tournament", "900")
    assert {k: start[k] for k in ("round_id", "event_id", "result_id")} == {"round_id": "", "event_id": "", "result_id": "", **ids}


def test_a_bare_host_and_a_name_are_told_apart():
    assert ter.parse_start("tabroom.com/index/tourn/main.mhtml?tourn_id=900")["tourn_id"] == "900"
    assert ter.parse_start("  Testville Invitational ") == {"kind": "search", "query": "Testville Invitational"}


@pytest.mark.parametrize("text", ["", "https://example.com/index/tourn/main.mhtml?tourn_id=900",
                                  "https://www.tabroom.com/index/index.mhtml", "https://www.tabroom.com/x?tourn_id=abc"])
def test_starts_that_name_no_tournament_are_refused(text):
    with pytest.raises(ValueError):
        ter.parse_start(text)


# -- search -------------------------------------------------------------------

def search_page(rows):
    body = ""
    for tourn_id, name, place, start, dates in rows:
        body += (f'<tr class="small"> <td class="nospace"> <a class = "bluetext"\n href = "/index/tourn/main.mhtml?tourn_id={tourn_id}" '
                 f'target= "_blank" > {name} </a> </td> <td class="limitsmall"> {place} </td> '
                 f'<td data-text="{start} 08:00:00" class="nowrap"> {dates} </td> <td><span>Oratory</span></td> </tr>')
    return f"<html><table><tr><th>Name</th></tr>{body}</table></html>"


SEARCH = [("905", "Testville Invitational", "Testville, WA", "2027-10-15", "Oct 15&ndash;17, 2027"),
          ("900", "Testville Invitational", "Testville, WA", "2026-10-16", "Oct 16&ndash;18, 2026"),
          ("880", "Testville Invitational", "Testville, WA", "2025-10-17", "Oct 17&ndash;19, 2025"),
          ("910", "Testville Novice Scrimmage", "Testville, WA", "2026-09-01", "Sep 1, 2026")]


def test_search_results_are_parsed():
    found = ter.parse_search_results(search_page(SEARCH))
    assert len(found) == 4
    assert found[1] == {"tourn_id": "900", "name": "Testville Invitational", "location": "Testville, WA",
                        "dates": "Oct 16–18, 2026", "start": "2026-10-16"}


def test_a_repeated_name_resolves_to_the_latest_that_has_started():
    found = ter.parse_search_results(search_page(SEARCH))
    assert ter.pick_tournament(found, "testville invitational", today="2026-11-15")["tourn_id"] == "900"
    assert ter.pick_tournament(found, "Testville Novice Scrimmage")["tourn_id"] == "910"


def test_a_loose_search_lists_its_candidates():
    found = ter.parse_search_results(search_page(SEARCH))
    with pytest.raises(ter.ResultsError, match=r"matches 4 tournaments.*tourn_id 910"):
        ter.pick_tournament(found, "testville")
    with pytest.raises(ter.ResultsError, match="found no tournament"):
        ter.pick_tournament([], "nowhere")
    assert ter.pick_tournament(found[3:], "scrimmage")["tourn_id"] == "910"     # a single result needs no exact name


# -- event --------------------------------------------------------------------

def test_pick_event_by_abbreviation_name_or_words():
    events = ter.list_events(tournament())
    assert ter.pick_event(events, "nto")["id"] == "500"
    assert ter.pick_event(events, "Novice Test Oratory")["id"] == "500"
    assert ter.pick_event(events, "open oratory")["id"] == "700"
    with pytest.raises(ter.ResultsError, match="matches 2 events"):
        ter.pick_event(events, "oratory")
    with pytest.raises(ter.ResultsError, match="no event matches"):
        ter.pick_event(events, "poetry")


def start(**ids):
    return {"kind": "tournament", "url": "https://www.tabroom.com/x", "tourn_id": "900",
            "round_id": "", "event_id": "", "result_id": "", **ids}


def test_the_event_comes_from_the_link_when_it_names_one():
    data = tournament()
    assert ter.resolve_event(data, start(event_id="500"))["abbr"] == "NTO"
    assert ter.resolve_event(data, start(round_id="12"))["abbr"] == "NTO"
    assert ter.resolve_event(data, start(), event="NTO")["abbr"] == "NTO"
    assert ter.resolve_event(data, start(result_id="77"), page_abbr=lambda url: "nto")["abbr"] == "NTO"


def test_the_event_comes_from_the_competitor_when_only_one_fits():
    data = tournament(entries_in_schools=False)      # found from ballots, not the entry lists
    assert ter.resolve_event(data, start(), competitor="fay")["abbr"] == "NTO"
    with pytest.raises(ter.ResultsError, match="entered in 2 speech events"):
        ter.resolve_event(data, start(), competitor="Ada")


def test_an_unnamed_event_lists_the_speech_events():
    with pytest.raises(ter.ResultsError, match=r"Name one with --event.*Novice Test Oratory \(NTO\), Open Test Oratory \(OTO\)$"):
        ter.resolve_event(tournament(), start(result_id="77"), page_abbr=lambda url: "")


def test_a_debate_event_is_refused():
    with pytest.raises(ter.ResultsError, match="is a debate event"):
        ter.resolve_event(tournament(), start(), event="TD")


def test_rounds_ballots_and_metadata(event):
    assert [(r["label"], r["stage"], r["key"], len(r["ballots"])) for r in event["rounds"]] == [
        ("Round 1", "prelim", "r1", 8), ("Round 2", "prelim", "r2", 8), ("Round 3", "prelim", "r3", 8),
        ("FINALS", "elim", "finals", 12)]
    fay = next(b for b in event["rounds"][1]["ballots"] if b["name"] == "Fay Wren")
    assert fay == {"section": "2", "room": "R2", "order": 3, "entry": "1005", "code": "Ced Fay Wren", "name": "Fay Wren",
                   "school": "Cedar High School", "judge": "Drew West", "rank": 3, "points": 18}
    cy = [b for b in event["rounds"][3]["ballots"] if b["name"] == "Cy Marsh"]
    assert sorted((b["judge"], b["rank"], b["points"]) for b in cy) == [
        ("Gray Holt", 3, None), ("Harper Lund", 2, None), ("Indigo Peña", 4, None)]
    assert (event["tournament"], event["event"], event["event_abbr"]) == ("Testville Invitational", "Novice Test Oratory", "NTO")
    # 15:00 UTC on the 16th and 03:00 UTC on the 19th, in the tournament's own zone.
    assert event["dates"] == "2026-10-16 to 2026-10-18 (America/Los_Angeles)"
    assert event["tiebreakers"] == ["ranks", "reciprocals", "points"] and event["tiebreakers_known"]
    assert (event["points_on_ballots"], event["points_from_result_sets"], event["rounds_missing"]) == (24, 0, [])


def test_points_missing_from_ballots_are_read_from_the_result_sets():
    event = event_from(tournament(points_on_ballots=False))
    assert (event["points_on_ballots"], event["points_from_result_sets"]) == (0, 24)
    assert [e["points_total"] for e in ter.build_standings(event)] == [59, 57, 56, 53, 54, 54, 49, 48]
    bare = event_from(tournament(points_on_ballots=False, with_seeds=False))
    assert bare["points_from_result_sets"] == 24        # Final Places alone carries every entry's string


def test_school_comes_from_the_entry_code_when_entries_are_left_out():
    event = event_from(tournament(entries_in_schools=False))
    assert {b["school"] for b in event["rounds"][0]["ballots"]} == set(SCHOOL_NAMES.values())


def test_an_unknown_tiebreaker_falls_back_to_the_default_order():
    event = event_from(tournament(third="Judge Variance in Prelims"))
    assert (event["tiebreakers"], event["tiebreakers_known"]) == (["ranks", "reciprocals", "points"], False)
    assert event["tiebreakers_printed"][-1] == "Judge Variance in Prelims"


def test_an_event_with_no_scored_ballots_is_an_error():
    data = tournament()
    for r in data["categories"][0]["events"][0]["rounds"]:
        for s in r["sections"]:
            for b in s["ballots"]:
                b["scores"] = []
    with pytest.raises(ter.ResultsError, match="no scored ballots"):
        ter.build_event(data, data["categories"][0]["events"][0])


# -- standings ----------------------------------------------------------------

def test_seeding_uses_rank_total_then_reciprocals_then_points(standings):
    # Ben and Cy tie on rank total 6 and reciprocals 1.83; Ben has 57 points to 56.
    # Eli, Gus and Fay tie on rank total 7; reciprocals 1.75, 1.67, 1.33 split them.
    assert [e["name"] for e in standings] == SEED_ORDER
    fay = standings[5]
    assert (fay["seed"], fay["rank_total"], fay["points_total"], fay["firsts"], fay["tabroom_seed"]) == (6, 7, 54, 0, "6")
    assert fay["reciprocals"] == pytest.approx(4 / 3)


def test_break_and_final_places(standings):
    assert [e["name"] for e in standings if e["broke"]] == ["Ada Quill", "Ben Rook", "Cy Marsh", "Eli Stone"]
    brk = ter.break_summary(standings)
    assert (brk["size"], brk["cut"]["name"], brk["by_seed"], brk["first_out"]["name"]) == (4, "Eli Stone", True, "Gus Pike")
    assert [e["final_place"] for e in standings[:5]] == ["1st", "2nd", "3rd", "4th", None]
    assert sorted(standings[2]["elim"]["finals"]) == [2, 3, 4]


def test_a_missed_round_is_seeded_after_complete_entries():
    data = tournament()
    room = data["categories"][0]["events"][0]["rounds"][2]["sections"][0]["ballots"]
    room[:] = [b for b in room if b["entry_name"] != "Ada Quill"]
    last = ter.build_standings(event_from(data))[-1]
    assert (last["name"], last["prelim_ballots"], last["complete"], last["rank_total"]) == ("Ada Quill", 2, False, 2)


def test_no_prelims_is_an_error():
    data = tournament()
    ev = data["categories"][0]["events"][0]
    ev["rounds"] = ev["rounds"][3:]
    with pytest.raises(ter.ResultsError, match="no preliminary round"):
        ter.build_standings(ter.build_event(data, ev))


# -- checks -------------------------------------------------------------------

def test_totals_and_seeds_match_tabroom(event, standings):
    # 1.66 for 1.6667: Tabroom truncates reciprocals.
    assert ter.check_against_tabroom(standings, event["result_sets"]) == {
        "checked": 8, "mismatches": [], "unmatched": [], "seeds_compared": 8, "seed_differs": []}


def test_without_prelim_seeds_only_non_finalists_are_checked():
    event = event_from(tournament(with_seeds=False))
    check = ter.check_against_tabroom(ter.build_standings(event), event["result_sets"])
    assert (check["checked"], check["seeds_compared"], check["mismatches"]) == (4, 0, [])


def test_a_wrong_total_is_reported():
    event = event_from(tournament(overrides={"Gus Pike": ("8", "1.66", "54")}))
    check = ter.check_against_tabroom(ter.build_standings(event), event["result_sets"])
    assert check["checked"] == 8
    assert check["mismatches"] == [{"entry": "Gus Pike", "tiebreaker": "ranks", "rebuilt": 7, "tabroom": 8.0}]


def test_a_wrong_seed_is_reported_and_a_tied_seed_is_not():
    event = event_from(tournament(seed_places={"Gus Pike": "6", "Fay Wren": "5", "Ben Rook": "2-T", "Cy Marsh": "2-T"}))
    check = ter.check_against_tabroom(ter.build_standings(event), event["result_sets"])
    assert check["seed_differs"] == [{"entry": "Gus Pike", "rebuilt": 5, "tabroom": "6"},
                                     {"entry": "Fay Wren", "rebuilt": 6, "tabroom": "5"}]


def test_a_result_row_with_no_ballots_is_reported():
    data = tournament()
    rows = data["categories"][0]["events"][0]["result_sets"][1]["results"]
    rows.append({"place": "9", "entry": 4242, "values": [{"result_key": "k5", "value": "9", "priority": 1}]})
    event = event_from(data)
    assert ter.check_against_tabroom(ter.build_standings(event), event["result_sets"])["unmatched"] == ["4242"]


# -- competitor ---------------------------------------------------------------

def test_find_competitor(standings):
    assert ter.find_competitor(standings, "fay")["name"] == "Fay Wren"
    with pytest.raises(ter.ResultsError, match="no entry"):
        ter.find_competitor(standings, "Zed")
    with pytest.raises(ter.ResultsError, match="matches 2 entries"):
        ter.find_competitor(standings, "st")      # Di Frost, Eli Stone


def test_one_rank_better_reseeds_the_event(event, standings):
    fay = ter.find_competitor(standings, "Fay Wren")
    sims = ter.simulate_one_rank_better(event, fay["entry"], 4)
    assert [(s["round"], s["from"], s["to"], s["swapped_with"], s["rank_total"], s["seed"], s["would_break"]) for s in sims] == [
        ("Round 1", 2, 1, "Eli Stone", 6, 4, True),      # ties Ben and Cy on 6 and 1.83, fewest points of the three
        ("Round 2", 3, 2, "Cy Marsh", 6, 3, True),
        ("Round 3", 2, 1, "Cy Marsh", 6, 3, True)]       # Cy drops to 7; Fay ties Ben on 6 and 1.83, behind on points
    assert ter.build_standings(event)[5]["name"] == "Fay Wren"      # the event itself is untouched


def test_a_rank_that_is_not_enough(event, standings):
    hal = ter.find_competitor(standings, "Hal")
    assert not any(s["would_break"] for s in ter.simulate_one_rank_better(event, hal["entry"], 4))


# -- end to end ---------------------------------------------------------------

class Web:
    """Stands in for Tabroom: answers the two URLs the script may request."""

    def __init__(self, data=None, search=SEARCH):
        self.data, self.search, self.requested = data or tournament(), search, []

    def get(self, url):
        self.requested.append(url)
        if "/api/download_data.mhtml" in url:
            return json.dumps(self.data)
        if "/index/search.mhtml" in url:
            return search_page(self.search)
        raise AssertionError(f"unexpected request: {url}")


def no_browser(url):
    raise AssertionError("the browser must not be used here")


def test_main_from_a_round_link_writes_everything(tmp_path, capsys):
    web, out = Web(), tmp_path / "out"
    url = "https://www.tabroom.com/index/tourn/results/round_results.mhtml?tourn_id=900&round_id=13"
    assert ter.main([url, str(out), "--competitor", "fay"], get=web.get, page_abbr=no_browser) == 0
    assert web.requested == ["https://www.tabroom.com/api/download_data.mhtml?tourn_id=900"]
    assert capsys.readouterr().out.strip().splitlines()[-1] == f"OUTPUT_DIR:{out}"
    assert sorted(p.name for p in out.iterdir()) == ["analysis.md", "ballots.csv", "ballots.json", "event.json",
                                                    "raw", "result_sets.json", "standings.csv"]
    assert json.loads((out / "raw" / "tournament_900.json").read_text(encoding="utf-8"))["id"] == 900
    assert len(list(csv.DictReader((out / "ballots.csv").open(encoding="utf-8")))) == 24 + 12
    rows = list(csv.DictReader((out / "standings.csv").open(encoding="utf-8")))
    assert (rows[5]["name"], rows[5]["r2_rank"], rows[5]["r2_points"], rows[5]["broke"], rows[5]["tabroom_seed"]) == (
        "Fay Wren", "3", "18", "no", "6")
    assert (rows[0]["final_place"], sorted(rows[0]["finals_ranks"].split("/"))) == ("1st", ["1", "1", "2"])
    meta = json.loads((out / "event.json").read_text(encoding="utf-8"))
    assert (meta["entries"], meta["ballots"], meta["break_size"], meta["break_by_seed"]) == (8, 36, 4, True)
    assert meta["check"]["checked"] == 8 and meta["captured_utc"].endswith("Z")

    analysis = (out / "analysis.md").read_text(encoding="utf-8")
    assert [line for line in analysis.splitlines() if line.startswith("## ")] == [
        "## 1. Objective", "## 2. Key findings", "## 3. How the break worked", "## 4. Fay Wren's rooms",
        "## 5. What one rank better would have changed", "## 6. Who broke", "## 7. Judge point scales",
        "## 8. Data and checks"]
    assert "4 of 8 entries broke to FINALS. The last one in was seed 4, Eli Stone" in analysis
    assert "Fay Wren seeded 6th of 8 after prelims on ranks 2, 3, 2" in analysis
    assert "That is 2 places below the cut. They tied the cut on rank total and lost on reciprocals: 1.33 against 1.75." in analysis
    assert "checked against Tabroom's for 8 of 8 entries: all match." in analysis
    assert "Prelim Seeds list covers 8 entries: every untied seed matches the rebuilt order." in analysis
    assert "| Round 2 | 2 | Drew West | 3 of 4 | 18 | Ben Rook (20) | 16 to 20 | 18.2 |" in analysis


@pytest.mark.parametrize("tab", ["main.mhtml", "fields.mhtml", "judges.mhtml", "postings/index.mhtml",
                                 "updates/index.mhtml", "results/index.mhtml"])
def test_main_from_any_tab_with_an_event(tab, tmp_path):
    web, out = Web(), tmp_path / "out"
    assert ter.main([f"https://www.tabroom.com/index/tourn/{tab}?tourn_id=900", str(out), "--event", "NTO"],
                    get=web.get, page_abbr=no_browser) == 0
    headings = [line for line in (out / "analysis.md").read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
    assert headings == ["## 1. Objective", "## 2. Key findings", "## 3. How the break worked", "## 4. Who broke",
                        "## 5. Judge point scales", "## 6. Data and checks"]


def test_main_from_a_final_places_link_reads_the_event_off_the_page(tmp_path):
    web, out, asked = Web(), tmp_path / "out", []
    url = "https://www.tabroom.com/index/tourn/results/event_results.mhtml?tourn_id=900&result_id=77"
    assert ter.main([url, str(out)], get=web.get, page_abbr=lambda u: asked.append(u) or "NTO") == 0
    assert asked == [url]
    assert json.loads((out / "event.json").read_text(encoding="utf-8"))["event_abbr"] == "NTO"


def test_main_from_a_final_places_link_without_a_browser_asks_for_the_event(tmp_path, capsys):
    url = "https://www.tabroom.com/index/tourn/results/event_results.mhtml?tourn_id=900&result_id=77"
    assert ter.main([url, str(tmp_path / "out")], get=Web().get, page_abbr=lambda u: "") == 1
    captured = capsys.readouterr()
    assert "Name one with --event" in captured.err and "OUTPUT_DIR:" not in captured.out
    assert not (tmp_path / "out").exists()


def test_main_from_a_tournament_name(tmp_path, capsys):
    web, out = Web(), tmp_path / "out"
    assert ter.main(["Testville Novice Scrimmage", str(out), "--event", "NTO"], get=web.get, page_abbr=no_browser) == 0
    assert web.requested == ["https://www.tabroom.com/index/search.mhtml?search=Testville+Novice+Scrimmage",
                             "https://www.tabroom.com/api/download_data.mhtml?tourn_id=910"]
    assert "tournament: Testville Novice Scrimmage (Sep 1, 2026, Testville, WA; tourn_id 910)" in capsys.readouterr().err


def test_main_from_raw_needs_no_network(tmp_path, capsys):
    first, again = tmp_path / "first", tmp_path / "again"
    assert ter.main(["https://www.tabroom.com/index/tourn/main.mhtml?tourn_id=900", str(first), "--event", "NTO"],
                    get=Web().get, page_abbr=no_browser) == 0
    assert ter.main(["--from-raw", str(first), str(again), "--competitor", "gus"], get=no_browser, page_abbr=no_browser) == 0
    assert "Gus Pike seeded 5th of 8" in (again / "analysis.md").read_text(encoding="utf-8")
    assert (again / "raw" / "tournament_900.json").exists()
    assert ter.main(["--from-raw", str(first), "--event", "NTO"], get=no_browser, page_abbr=no_browser) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith("OUTPUT_DIR:")


def test_main_with_an_unknown_competitor_keeps_the_data_and_emits_no_marker(tmp_path, capsys):
    out = tmp_path / "out"
    assert ter.main(["https://www.tabroom.com/index/tourn/main.mhtml?tourn_id=900", str(out), "--event", "NTO",
                     "--competitor", "Zed"], get=Web().get, page_abbr=no_browser) == 1
    captured = capsys.readouterr()
    assert "OUTPUT_DIR:" not in captured.out
    assert 'no entry in this event matches "Zed"' in captured.err
    assert (out / "standings.csv").exists()


@pytest.mark.parametrize("argv,code", [
    ([], 2),
    (["https://example.com/index/tourn/main.mhtml?tourn_id=900"], 2),
    (["https://www.tabroom.com/index/index.mhtml"], 2),
    (["--from-raw", "a", "b", "c"], 2),
])
def test_main_usage_errors_make_no_request(argv, code, capsys):
    assert ter.main(argv, get=no_browser, page_abbr=no_browser) == code
    assert "OUTPUT_DIR:" not in capsys.readouterr().out


def test_main_reports_a_tournament_with_no_data(tmp_path, capsys):
    assert ter.main(["https://www.tabroom.com/index/tourn/main.mhtml?tourn_id=1", str(tmp_path / "out")],
                    get=lambda url: "<html>Log In to Tabroom</html>", page_abbr=no_browser) == 1
    assert "returned no tournament data for tourn_id 1" in capsys.readouterr().err


def test_cells_that_start_like_a_formula_are_written_as_text(tmp_path):
    data = tournament()
    for r in data["categories"][0]["events"][0]["rounds"]:
        for s in r["sections"]:
            for b in s["ballots"]:
                if b["entry_name"] == "Hal Dove":
                    b["entry_name"], b["judge_first"] = "=HYPERLINK(1)", "@Blake"
    out = tmp_path / "out"
    assert ter.main(["https://www.tabroom.com/index/tourn/main.mhtml?tourn_id=900", str(out), "--event", "NTO"],
                    get=Web(data).get, page_abbr=no_browser) == 0
    ballots = list(csv.DictReader((out / "ballots.csv").open(encoding="utf-8")))
    assert {b["name"] for b in ballots if "HYPERLINK" in b["name"]} == {"'=HYPERLINK(1)"}
    assert "'@Blake South" in {b["judge"] for b in ballots}
    assert not any(v[:1] in "=+-@" for b in ballots for v in b.values() if v)
    names = [r["name"] for r in csv.DictReader((out / "standings.csv").open(encoding="utf-8"))]
    assert "'=HYPERLINK(1)" in names and "=HYPERLINK(1)" not in names


def test_a_tournament_id_that_is_not_a_number_is_refused(tmp_path, capsys):
    data = tournament()
    data["id"] = "../../evil"
    assert ter.main(["https://www.tabroom.com/index/tourn/main.mhtml?tourn_id=900", str(tmp_path / "out"), "--event", "NTO"],
                    get=Web(data).get, page_abbr=no_browser) == 1
    assert "no numeric id" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_main_says_how_the_event_was_chosen(tmp_path, capsys):
    url = "https://www.tabroom.com/index/tourn/results/round_results.mhtml?tourn_id=900&round_id=13"
    assert ter.main([url, str(tmp_path / "out")], get=Web().get, page_abbr=no_browser) == 0
    assert "event: Novice Test Oratory (NTO), from the link's round_id" in capsys.readouterr().err


def test_main_from_raw_with_no_file_fails(tmp_path, capsys):
    assert ter.main(["--from-raw", str(tmp_path)], get=no_browser, page_abbr=no_browser) == 1
    assert "no tournament_*.json" in capsys.readouterr().err
