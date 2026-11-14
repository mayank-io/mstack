"""Tests for the Tabroom results download unit and its extraction.js.

The extractor is exercised under jsdom against `fixtures/tabroom_history.html`
and `fixtures/tabroom_tournament.html`, which reproduce the structure of the
live pages read on 2026-11-13 with invented names and comments.

What these pin, each of which produces a capture that looks fine:

1. Hidden feedback. A ballot's comments sit in a display:none row; a text
   extraction of the visible page returns the scores and none of the feedback.
2. The sticky-header clone. tablesorter duplicates the table; counting it
   doubles the entries or yields one with no rounds.
3. Empty scores. An elimination round has a Points span with no value; it must
   not become a score of "".
4. Line breaks. Judges type one thought per line inside a single list item;
   collapsing them fuses "delivery:" into the sentence after it.
5. Dates. The page prints "Sat 5:30 PM" and no date; the date is resolved from
   the tournament's range and left unknown when the weekday is ambiguous.
6. An empty page. The wrong account sees the tournament header and no table;
   that must fail, not write an empty note.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tabroom_results as tr  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
EXTRACTION_JS = SCRIPTS.parent / "skills" / "tabroom-results" / "references" / "extraction.js"
FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.tabroom.com/user/student/history.mhtml?tourn_id=90001&student_id=7000001"


# ------------------------------------------------------------------ URL parse

@pytest.mark.parametrize("url", [
    URL,
    "https://tabroom.com/user/student/history.mhtml?student_id=7000001&tourn_id=90001",
    "www.tabroom.com/user/student/history.mhtml?tourn_id=90001&student_id=7000001",
    "  " + URL + "#top  ",
])
def test_history_urls_parse_to_canonical(url):
    assert tr.parse_history_url(url) == (URL, "90001", "7000001")


@pytest.mark.parametrize("url", [
    "https://www.tabroom.com/user/student/history.mhtml?tourn_id=90001",
    "https://www.tabroom.com/user/student/history.mhtml?tourn_id=abc&student_id=7000001",
    "https://www.tabroom.com/user/judge/history.mhtml?tourn_id=90001&student_id=7000001",
    "https://www.tabroom.com/index/tourn/main.mhtml?tourn_id=90001",
    "https://evil.example/user/student/history.mhtml?tourn_id=90001&student_id=7000001",
    "",
    None,
])
def test_other_urls_are_refused(url):
    with pytest.raises(ValueError):
        tr.parse_history_url(url)


def test_tournament_url():
    assert tr.tournament_url("90001") == "https://www.tabroom.com/index/tourn/main.mhtml?tourn_id=90001"


# ------------------------------------------------------------------ dates

@pytest.mark.parametrize("label,expected", [
    ("Mar 6 to Mar 8 2026", ("2026-03-06", "2026-03-08")),
    ("Mar 7 2026", ("2026-03-07", "2026-03-07")),
    ("March 6, 2026 to March 8, 2026", ("2026-03-06", "2026-03-08")),
    ("Dec 30 to Jan 2 2027", ("2026-12-30", "2027-01-02")),
    ("Dec 30 2026 to Jan 2 2027", ("2026-12-30", "2027-01-02")),
    ("  Feb 28 - Mar 1 2026 ", ("2026-02-28", "2026-03-01")),
])
def test_tournament_dates_parse(label, expected):
    assert tr.parse_tournament_dates(label) == expected


@pytest.mark.parametrize("label", [
    "", None, "Mar 6 to Mar 8", "Octember 16 2026", "Feb 30 2026",
    "Mar 8 2026 to Mar 6 2026", "Mar 6 to Mar 7 to Mar 8 2026", "TBA",
])
def test_unparseable_tournament_dates_are_none_not_a_guess(label):
    assert tr.parse_tournament_dates(label) == (None, None)


@pytest.mark.parametrize("start_label,expected", [
    ("Sat 5:30 PM", "2026-03-07"),
    ("Fri 4:00 PM", "2026-03-06"),
    ("sun 9:00 AM", "2026-03-08"),
    ("Mon 9:00 AM", None),      # not a day of the tournament
    ("6:00 PM", None),
    ("", None),
    (None, None),
])
def test_round_date_resolves_a_weekday_inside_the_range(start_label, expected):
    assert tr.round_date(start_label, "2026-03-06", "2026-03-08") == expected


def test_round_date_is_unknown_when_the_weekday_occurs_twice():
    assert tr.round_date("Sat 9:00 AM", "2026-03-07", "2026-03-14") is None   # two Saturdays
    assert tr.round_date("Sat 9:00 AM", "2026-03-07", "2026-03-13") == "2026-03-07"


def test_round_date_without_tournament_dates():
    assert tr.round_date("Sat 9:00 AM", None, None) is None


# ------------------------------------------------------------------ extractor under jsdom

def _jsdom_path():
    """A node_modules directory holding jsdom, or None."""
    cands = [os.environ.get("MSTACK_JSDOM_NODE_PATH", "")]
    npm = shutil.which("npm")
    if npm:
        root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip()
        cands += [root, os.path.join(root, "defuddle-cli", "node_modules")]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "jsdom")):
            return c
    return None


_HARNESS = r"""
const {JSDOM} = require('jsdom'); const fs = require('fs');
const [htmlPath, jsPath, fn] = process.argv.slice(1);
const dom = new JSDOM(fs.readFileSync(htmlPath, 'utf8'),
                      {url: 'https://www.tabroom.com/', runScripts: 'outside-only'});
dom.window.eval(fs.readFileSync(jsPath, 'utf8'));
process.stdout.write(JSON.stringify(dom.window.__tabroom[fn]()));
"""


def _run_extractor(html_path, fn):
    node, path = shutil.which("node"), _jsdom_path()
    if not node or not path:
        pytest.skip("node + jsdom not found; set MSTACK_JSDOM_NODE_PATH to a node_modules dir with jsdom")
    r = subprocess.run([node, "-e", _HARNESS, str(html_path), str(EXTRACTION_JS), fn],
                       capture_output=True, text=True, env={**os.environ, "NODE_PATH": path}, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture(scope="module")
def extracted():
    return _run_extractor(FIXTURES / "tabroom_history.html", "extract")


def test_header_fields(extracted):
    assert extracted["student"] == "Avery Quinn"
    assert extracted["tournament"] == "Cedar Ridge Invitational"
    assert extracted["tourn_id"] == "90001"
    assert extracted["account"] == "student1@example.org"


def test_one_entry_despite_the_sticky_header_clone(extracted):
    assert len(extracted["entries"]) == 1
    e = extracted["entries"][0]
    assert e["event"] == "Informative Speaking (INF)"
    assert e["code"] == "CedRid Avery Quinn"
    assert e["columns"] == ["Round", "Start", "Room", "Section", "Speak", "Judges & Results"]


def test_round_fields_exclude_the_judges_column(extracted):
    rounds = extracted["entries"][0]["rounds"]
    assert [r["fields"] for r in rounds] == [
        {"Round": "FINALS", "Start": "Sat 5:30 PM", "Room": "104", "Section": "1", "Speak": "3rd"},
        {"Round": "Round 1", "Start": "Sat 9:30 AM", "Room": "220", "Section": "2", "Speak": "2nd"},
    ]


def test_judges_and_scores_drop_an_empty_points_value(extracted):
    finals, round1 = extracted["entries"][0]["rounds"]
    assert finals["judges"] == [
        {"judge": "Okafor, Ngozi", "scores": [{"label": "Rank", "value": "2"}]},
        {"judge": "Lindqvist, Per", "scores": [{"label": "Rank", "value": "3"}]},
    ]
    assert round1["judges"] == [
        {"judge": "Haddad, Rania", "scores": [{"label": "Rank", "value": "1"},
                                              {"label": "Points", "value": "24"}]},
    ]


def test_hidden_feedback_is_read_per_judge_and_per_comment_box(extracted):
    fb = extracted["entries"][0]["rounds"][0]["feedback"]
    assert [(f["judge"], f["label"]) for f in fb] == [
        ("Okafor, Ngozi", "FINALS Feedback"), ("Lindqvist, Per", "FINALS Feedback")]
    assert fb[0]["sections"] == [{"heading": "Comments for you", "blocks": [
        {"type": "paragraph", "text": "Clear structure and pacing. Cite more sources."}]}]
    assert [s["heading"] for s in fb[1]["sections"]] == ["Reason for Rank/Decision", "Comments for you"]
    assert fb[1]["sections"][0]["blocks"] == [
        {"type": "paragraph", "text": "Close round."},
        {"type": "paragraph", "text": "Came down to structure."}]


def test_lists_keep_their_kind_and_position_and_empty_paragraphs_vanish(extracted):
    blocks = extracted["entries"][0]["rounds"][0]["feedback"][1]["sections"][1]["blocks"]
    assert blocks == [
        {"type": "paragraph", "text": "notes:"},
        {"type": "ordered", "items": ["hook lands", "transitions abrupt"]},
        {"type": "paragraph", "text": "time: 8:40"},
    ]


def test_line_breaks_inside_a_list_item_survive(extracted):
    blocks = extracted["entries"][0]["rounds"][1]["feedback"][0]["sections"][0]["blocks"]
    assert blocks == [{"type": "bullets", "items": [
        "delivery:\nsteady, good volume",
        "content:\nstrong opening\nadd a preview"]}]


def test_every_feedback_character_on_the_page_is_extracted(extracted):
    """The extractor against the raw fixture: no ballot text may be dropped."""
    import re
    html = (FIXTURES / "tabroom_history.html").read_text(encoding="utf-8")
    rows = re.findall(r'<tr class="feedback".*?</tr>', html, re.S)
    assert len(rows) == 2
    source = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", "".join(rows)).replace("&nbsp;", ""))
    got = ""
    for r in extracted["entries"][0]["rounds"]:
        for f in r["feedback"]:
            got += f["judge"] + f["label"]
            for s in f["sections"]:
                got += s["heading"] + "".join(tr._block_text(b) for b in s["blocks"])
    assert re.sub(r"\s+", "", got) == source


def test_tournament_info():
    info = _run_extractor(FIXTURES / "tabroom_tournament.html", "tournamentInfo")
    assert info == {"dates_label": "Mar 6 to Mar 8 2026", "location": "Lakeview, OR/US"}


def test_a_page_with_no_results_table_extracts_no_entries(tmp_path):
    """What the wrong account sees: the tournament header and nothing under it."""
    page = tmp_path / "empty.html"
    page.write_text('<html><body><span>parent@example.org</span><div class="main">'
                    '<h4>Avery Quinn</h4><h6>Cedar Ridge Invitational</h6>'
                    '<span>Informative Speaking (INF)</span><span>Your Code: CedRid Avery Quinn</span>'
                    '</div></body></html>', encoding="utf-8")
    data = _run_extractor(page, "extract")
    assert data["entries"] == []
    assert data["account"] == "parent@example.org"
    assert "parent@example.org" in tr.validate(data)[0]


# ------------------------------------------------------------------ validate, record, render

def _data():
    return {
        "student": "Avery Quinn", "tournament": "Cedar Ridge Invitational", "tourn_id": "90001",
        "account": "student1@example.org",
        "entries": [{
            "event": "Informative Speaking (INF)", "code": "CedRid Avery Quinn",
            "columns": ["Round", "Start", "Room", "Judges & Results"],
            "rounds": [
                {"fields": {"Round": "FINALS", "Start": "Sat 5:30 PM", "Room": "104"},
                 "judges": [{"judge": "Okafor, Ngozi", "scores": [{"label": "Rank", "value": "2"}]},
                            {"judge": "Lindqvist, Per", "scores": [{"label": "Rank", "value": "3"}]}],
                 "feedback": [{"judge": "Okafor, Ngozi", "label": "FINALS Feedback", "sections": [
                     {"heading": "Comments for you", "blocks": [
                         {"type": "paragraph", "text": "Good | poise.\n# not a heading"},
                         {"type": "ordered", "items": ["hook lands", "delivery:\n- polished"]}]}]}]},
                {"fields": {"Round": "Round 1", "Start": "Sat 9:30 AM", "Room": "220"},
                 "judges": [{"judge": "Haddad, Rania", "scores": [
                     {"label": "Rank", "value": "1"}, {"label": "Points", "value": "24"}]}],
                 "feedback": []},
            ],
        }],
    }


def test_validate_accepts_a_real_capture():
    assert tr.validate(_data()) == []


@pytest.mark.parametrize("data,needle", [
    (None, "no object"),
    ({"student": "A", "account": "x@example.org", "entries": []}, "no rounds on the page for x@example.org"),
    ({"student": "A", "entries": [{"rounds": []}]}, "an unknown account"),
    ({"student": "", "entries": [{"rounds": [{"judges": [{"judge": "J", "scores": []}]}]}]}, "no student name"),
    ({"student": "A", "entries": [{"rounds": [{"judges": []}]}]}, "no judge in any of them"),
])
def test_validate_names_what_is_wrong(data, needle):
    assert needle in "; ".join(tr.validate(data))


def test_feedback_chars_ignores_whitespace():
    # "Good|poise.#notaheading" (23) + "hooklands" (9) + "delivery:-polished" (18)
    assert tr.feedback_chars(_data()) == 50


def test_record_resolves_round_dates_and_counts():
    rec = tr.build_record(_data(), URL, {"dates_label": "Mar 6 to Mar 8 2026", "location": "Lakeview, OR/US"})
    assert rec["source"] == URL and rec["tourn_id"] == "90001" and rec["student_id"] == "7000001"
    assert (rec["tournament_start"], rec["tournament_end"]) == ("2026-03-06", "2026-03-08")
    assert rec["location"] == "Lakeview, OR/US"
    assert [r["date"] for r in rec["entries"][0]["rounds"]] == ["2026-03-07", "2026-03-07"]
    assert (rec["rounds_count"], rec["ballots_count"], rec["feedback_count"]) == (2, 3, 1)
    assert rec["captured_utc"].endswith("+00:00")


def test_record_without_tournament_info_leaves_dates_unknown():
    rec = tr.build_record(_data(), URL)
    assert rec["tournament_start"] is None and rec["location"] is None
    assert [r["date"] for r in rec["entries"][0]["rounds"]] == [None, None]


def test_score_labels_are_the_union_in_first_seen_order():
    assert tr.score_labels(_data()["entries"][0]) == ["Rank", "Points"]


def test_markdown_table_has_one_row_per_ballot():
    rec = tr.build_record(_data(), URL, {"dates_label": "Mar 6 to Mar 8 2026", "location": "Lakeview, OR/US"})
    md = tr.render_markdown(rec)
    assert "# Avery Quinn: Cedar Ridge Invitational" in md
    assert "- Tournament dates: 2026-03-06 to 2026-03-08" in md
    assert "| Round | Start | Room | Date | Judge | Rank | Points |" in md
    assert "| FINALS | Sat 5:30 PM | 104 | 2026-03-07 | Okafor, Ngozi | 2 |  |" in md
    assert "|  |  |  |  | Lindqvist, Per | 3 |  |" in md
    assert "| Round 1 | Sat 9:30 AM | 220 | 2026-03-07 | Haddad, Rania | 1 | 24 |" in md


def test_markdown_omits_the_date_column_when_no_date_resolved():
    md = tr.render_markdown(tr.build_record(_data(), URL))
    assert "| Round | Start | Room | Judge | Rank | Points |" in md
    assert "Tournament dates" not in md


def test_markdown_keeps_feedback_verbatim_and_neutralises_structure_characters():
    md = tr.render_markdown(tr.build_record(_data(), URL))
    assert "##### Okafor, Ngozi (Rank 2)" in md
    assert "**Comments for you**" in md
    assert "Good | poise.  \n\\# not a heading" in md          # the pipe is prose here, not a cell
    assert "1. hook lands\n2. delivery:  \n   \\- polished" in md
    assert "#### Round 1\n\nNo written feedback on the page for this round." in md


# ------------------------------------------------------------------ CLI

def test_cli_refuses_a_non_history_url_before_touching_the_browser(capsys):
    assert tr.main(["https://www.tabroom.com/index/tourn/main.mhtml?tourn_id=90001"]) == 2
    out, err = capsys.readouterr()
    assert "OUTPUT_DIR:" not in out
    assert "not a Tabroom competitor history URL" in err


def test_cli_usage_without_arguments(capsys):
    assert tr.main([]) == 2
    assert "OUTPUT_DIR:" not in capsys.readouterr().out


def test_cli_from_an_extracted_file_writes_both_outputs_and_the_marker(tmp_path, capsys):
    src = tmp_path / "extracted.json"
    src.write_text(json.dumps({**_data(), "tournament_info": {
        "dates_label": "Mar 6 to Mar 8 2026", "location": "Lakeview, OR/US"}}), encoding="utf-8")
    out_dir = tmp_path / "out"
    assert tr.main(["--extracted", str(src), URL, str(out_dir)]) == 0
    out, err = capsys.readouterr()
    assert out.strip().splitlines()[-1] == f"OUTPUT_DIR:{out_dir}"
    assert "2 round(s), 3 ballot(s), 1 with feedback" in err
    assert "2 of 3 ballot(s) have no written feedback" in err
    rec = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert rec["type"] == "tabroom-results" and rec["tournament_start"] == "2026-03-06"
    assert "tournament_info" not in rec
    assert (out_dir / "results.md").read_text(encoding="utf-8").startswith("# Avery Quinn: Cedar Ridge")


def test_cli_fails_without_a_marker_on_an_empty_page(tmp_path, capsys):
    src = tmp_path / "extracted.json"
    src.write_text(json.dumps({"student": "Avery Quinn", "account": "parent@example.org",
                               "entries": []}), encoding="utf-8")
    assert tr.main(["--extracted", str(src), URL, str(tmp_path / "out")]) == 1
    out, err = capsys.readouterr()
    assert "OUTPUT_DIR:" not in out
    assert "no rounds on the page for parent@example.org" in err
    assert not (tmp_path / "out").exists()


def test_cli_reports_an_unreadable_extracted_file(tmp_path, capsys):
    assert tr.main(["--extracted", str(tmp_path / "missing.json"), URL]) == 2
    assert "cannot read --extracted file" in capsys.readouterr().err
