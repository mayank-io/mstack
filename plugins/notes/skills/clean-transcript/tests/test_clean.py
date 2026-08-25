"""Tests for the deterministic transcript cleaner.

Spec: docs/plans/2026-08-24-orchestrator-collapse.md §11.

The load-bearing test is test_verbatim_invariant. Everything else guards a
boundary that has produced a real bad capture at some point.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "clean.py"
sys.path.insert(0, str(SCRIPT.parent))

import clean  # noqa: E402


# ---------------------------------------------------------------- helpers

def run(tmp_path, raw_text, meta=None, extra=()):
    raw = tmp_path / "raw.txt"
    raw.write_text(raw_text, encoding="utf-8")
    out = tmp_path / "out.md"
    argv = [str(raw), str(out)]
    if meta is not None:
        m = tmp_path / "meta.json"
        m.write_text(meta if isinstance(meta, str) else json.dumps(meta), encoding="utf-8")
        argv.append(str(m))
    argv += list(extra)
    proc = subprocess.run([sys.executable, str(SCRIPT), *argv],
                          capture_output=True, text=True)
    return proc, out


def words(text):
    """Token stream, ignoring markup this script is allowed to insert."""
    text = re.sub(r"^##\s+.*$", " ", text, flags=re.M)   # chapter headings
    text = text.replace("**", "")                         # speaker bolding
    return re.findall(r"\S+", text)


# ---------------------------------------------------------------- §11.2 smoke

def test_parse_mmss():
    assert clean.parse("0:15 the market has been volatile") == \
        [(15, "the market has been volatile")]


def test_parse_hhmmss():
    assert clean.parse("1:02:33 and then it turned") == [(3753, "and then it turned")]


def test_group_count_not_magnitude_decides():
    """62:33 is mm:ss (3753s) and 1:02:33 is hh:mm:ss (3753s) — same value,
    different shape. Magnitude must never be used to guess."""
    assert clean.parse("62:33 x")[0][0] == 3753
    assert clean.parse("1:02:33 x")[0][0] == 3753
    assert clean.parse("1:02 x")[0][0] == 62


def test_noise_inline_removed():
    assert clean.parse("12:04 [Music] back to the charts") == [(724, "back to the charts")]


def test_continuation_line():
    """An untimestamped line continues the prior segment; it must not become
    a new segment at t=0, which would reorder it against the chapters."""
    assert clean.parse("0:00 first\ncontinued here") == [(0, "first continued here")]


# ---------------------------------------------------------------- §11.3 boundaries

def test_noise_case_insensitive_all_markers():
    for marker in ("[Music]", "[APPLAUSE]", "[laughter]", "[Inaudible]"):
        assert clean.parse(f"0:01 {marker} words") == [(1, "words")]


def test_noise_only_line_dropped(tmp_path):
    """A line that is nothing but a marker must vanish — not survive as an
    empty segment, not leave an empty paragraph, and not swallow the next one.

    Assert on the exact body, not just the token stream: an empty segment
    joins as a double space, which a \\S+ tokeniser silently normalises away.
    """
    assert clean.parse("0:00 alpha\n0:05 [Music]\n0:10 beta\n") == \
        [(0, "alpha"), (10, "beta")]

    proc, out = run(tmp_path, "0:00 alpha\n0:05 [Music]\n0:10 beta\n")
    body = out.read_text()
    assert body == "alpha beta\n"      # exact — no double space, no blank run
    assert "\n\n\n" not in body


def test_chapter_boundary_inclusive(tmp_path):
    """A segment at exactly chapters[i].start belongs UNDER that heading."""
    meta = {"chapters": [{"start_time": 0, "title": "One"},
                         {"start_time": 330, "title": "Two"}]}
    proc, out = run(tmp_path, "0:00 alpha\n5:30 beta\n", meta)
    body = out.read_text()
    assert body.index("## Two") < body.index("beta")
    assert body.index("alpha") < body.index("## Two")


def test_chapter_before_first_emits_without_heading(tmp_path):
    meta = {"chapters": [{"start_time": 100, "title": "Later"}]}
    proc, out = run(tmp_path, "0:00 early words\n2:00 after\n", meta)
    body = out.read_text()
    assert body.index("early words") < body.index("## Later")


def test_no_chapters(tmp_path):
    proc, out = run(tmp_path, "0:00 alpha\n0:05 beta\n")
    assert proc.returncode == 0
    assert "##" not in out.read_text()


def test_long_run_without_terminator_stays_one_paragraph(tmp_path):
    """Flush needs BOTH the length threshold and a sentence terminator. A long
    run with neither must not be cut mid-sentence."""
    line = "0:{:02d} " + "word " * 40  # no '.' anywhere
    raw = "\n".join(line.format(i) for i in range(1, 20))
    proc, out = run(tmp_path, raw)
    assert out.read_text().strip().count("\n\n") == 0


# ---------------------------------------------------------------- §11.4 invariant

def test_verbatim_invariant(tmp_path):
    """THE load-bearing test. Output tokens == input tokens minus timestamps
    and noise markers. Nothing rewritten, nothing dropped, nothing added."""
    raw_lines, expected = [], []
    for i in range(1200):
        secs = i * 3
        sentence = f"segment {i} says something worth keeping."
        if i % 37 == 0:
            raw_lines.append(f"{secs // 60}:{secs % 60:02d} [Music] {sentence}")
        else:
            raw_lines.append(f"{secs // 60}:{secs % 60:02d} {sentence}")
        expected += sentence.split()
    raw = "\n".join(raw_lines)
    assert len(raw) > 50_000, f"fixture too small: {len(raw)}"

    proc, out = run(tmp_path, raw)
    assert proc.returncode == 0
    assert words(out.read_text()) == expected


def test_verbatim_invariant_with_chapters(tmp_path):
    """Chapter headings are inserted text; they must not perturb the body."""
    raw = "\n".join(f"0:{i:02d} word{i} here." for i in range(1, 40))
    meta = {"chapters": [{"start_time": 0, "title": "A"},
                         {"start_time": 20, "title": "B"}]}
    proc, out = run(tmp_path, raw, meta)
    expected = [w for i in range(1, 40) for w in (f"word{i}", "here.")]
    assert words(out.read_text()) == expected


# ---------------------------------------------------------------- §11.4 corruption

@pytest.mark.parametrize("bad", ["$und00", "a,50", "the % of revenue"])
def test_corruption_scan_flags(bad):
    assert clean.scan_corruption(bad), f"should have flagged: {bad}"


@pytest.mark.parametrize("good", ["$1,050", "60%", "up 12.5% today", "$42"])
def test_corruption_scan_ignores_valid(good):
    assert not clean.scan_corruption(good), f"false positive on: {good}"


# ---------------------------------------------------------------- speakers

def test_speaker_labels_only_when_present(tmp_path):
    proc, out = run(tmp_path, "0:00 DAVID: hello there\n0:05 unlabelled speech\n",
                    extra=["--speakers", "David"])
    body = out.read_text()
    assert "**DAVID:**" in body
    assert "unlabelled speech" in body
    assert body.count("**") == 2  # exactly one label bolded, none invented


def test_no_speakers_flag_leaves_text_alone(tmp_path):
    proc, out = run(tmp_path, "0:00 DAVID: hello there\n")
    assert "**" not in out.read_text()


# ---------------------------------------------------------------- §11.4 output

def test_output_marker_is_final_stdout_line(tmp_path):
    proc, out = run(tmp_path, "0:00 alpha\n")
    last = proc.stdout.strip().splitlines()[-1]
    assert last.startswith("OUTPUT_FILE:")
    assert Path(last[len("OUTPUT_FILE:"):]).is_absolute()
    assert Path(last[len("OUTPUT_FILE:"):]).exists()


def test_no_trailing_blank_run(tmp_path):
    proc, out = run(tmp_path, "0:00 alpha.\n0:05 beta.\n")
    assert not out.read_text().endswith("\n\n\n")


# ---------------------------------------------------------------- §11.5 errors

def test_missing_raw_file(tmp_path):
    out = tmp_path / "out.md"
    proc = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "nope.txt"), str(out)],
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "no such file" in proc.stderr.lower()
    assert not out.exists()


def test_empty_raw_file(tmp_path):
    proc, out = run(tmp_path, "")
    assert proc.returncode == 0
    assert out.read_text() == ""
    assert "segments: 0" in proc.stderr


def test_malformed_meta_is_fatal(tmp_path):
    """Must NOT silently proceed with zero chapters — that looks like success
    while dropping the whole chapter structure."""
    proc, out = run(tmp_path, "0:00 alpha\n", meta="{not json")
    assert proc.returncode != 0
    assert "cannot read chapters" in proc.stderr


def test_chapter_missing_start_is_fatal(tmp_path):
    proc, out = run(tmp_path, "0:00 alpha\n", meta={"chapters": [{"title": "Orphan"}]})
    assert proc.returncode != 0
    assert "Orphan" in proc.stderr


def test_no_timestamps_anywhere(tmp_path):
    proc, out = run(tmp_path, "just prose with no timings at all\n")
    assert proc.returncode == 0
    assert words(out.read_text()) == "just prose with no timings at all".split()
