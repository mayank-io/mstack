"""Video detection in the canonical extraction.js.

An X video post used to extract as a caption and nothing else, because the
extractor had no concept of video at all. The caption is the hook; the video is
the content, so a capture holding only the caption is not a capture.

These run the real extraction.js under node with a minimal DOM stub. The file is
a bare IIFE that only defines functions and assigns window.__xExtract, so it
loads with no document present — which is what makes the pure parsers testable
without a browser.

The duration parser earns its own tests because the play button's aria-label is
the ONLY place X renders a duration. There is no data attribute and no visible
text carrying it. Misparsing it silently turns a 53-minute lecture into a post
that looks like a clip not worth transcribing.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
EXTRACTION_JS = SCRIPTS.parent / "skills" / "x-post" / "references" / "extraction.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is required to execute extraction.js")


def run_js(body: str):
    """Load extraction.js under node and evaluate `body`, returning its JSON."""
    script = (
        "const fs = require('fs');\n"
        "global.window = {};\n"
        f"eval(fs.readFileSync({json.dumps(str(EXTRACTION_JS))}, 'utf8'));\n"
        "const X = window.__xExtract;\n"
        f"console.log(JSON.stringify({body}));\n"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ----------------------------------------------------- duration parsing

@pytest.mark.parametrize("label,expected", [
    # The label on the post that motivated this work. yt-dlp reports 3214.71s
    # for the same video, so X is ceiling the duration — the two agree.
    ("Play Video. 53 minutes 35 seconds long", 3215),
    ("Play Video. 1 hour 2 minutes 5 seconds long", 3725),
    ("Play Video. 2 hours 1 minute 1 second long", 7261),
    ("Play Video. 45 seconds long", 45),
    ("Play Video. 2 minutes long", 120),
])
def test_duration_parses_from_the_aria_label(label, expected):
    assert run_js(f"X.parseVideoDuration({json.dumps(label)})") == expected


@pytest.mark.parametrize("label", ["Play Video", "", None, "Embedded video"])
def test_a_label_with_no_duration_yields_null_not_zero(label):
    # Zero would read as a real duration of zero seconds and mark a genuine
    # video as nothing worth transcribing.
    assert run_js(f"X.parseVideoDuration({json.dumps(label)})") is None


# ----------------------------------------------------- presence detection

def _article_stub(js_matches: str) -> str:
    """An <article>-shaped stub whose querySelector answers from a lookup table."""
    return (
        "(() => { const table = " + js_matches + ";"
        " const find = (sel) => { for (const k of Object.keys(table))"
        "   if (sel.includes(k)) return table[k]; return null; };"
        " return { querySelector: find, querySelectorAll: () => [] }; })()"
    )


def test_a_post_with_no_video_returns_null():
    assert run_js(f"X.extractVideo({_article_stub('{}')})") is None


def test_video_player_alone_is_enough_to_detect_presence():
    # Duration is unknown when the play button has not mounted, but presence
    # must still be reported: "no duration" is not "no video".
    stub = _article_stub('{"videoPlayer": {getAttribute: () => null}}')
    result = run_js(f"X.extractVideo({stub})")
    assert result["present"] is True
    assert result["seconds"] is None


def test_duration_and_poster_are_carried_off_the_dom():
    stub = _article_stub(
        '{"Play Video": {getAttribute: () => "Play Video. 53 minutes 35 seconds long"},'
        ' "video": {getAttribute: (a) => a === "poster"'
        '   ? "https://pbs.twimg.com/ext_tw_video_thumb/1/img/x.jpg" : null}}')
    result = run_js(f"X.extractVideo({stub})")
    assert result["seconds"] == 3215
    assert result["isGif"] is False
    # The poster lives on ext_tw_video_thumb, not the /media path the image
    # extractor filters for, so it is only ever reachable this way.
    assert "ext_tw_video_thumb" in result["poster"]


def test_a_gif_is_flagged_so_it_is_not_sent_for_transcription():
    stub = _article_stub('{"Play Video": {getAttribute: () => "Play Video. GIF"}}')
    result = run_js(f"X.extractVideo({stub})")
    assert result["present"] is True
    assert result["isGif"] is True


# ----------------------------------------------------- export surface

def test_video_helpers_are_exported():
    # x_extract.py drives these by name from the injected script; an unexported
    # helper fails at runtime in the page, where nothing reports it.
    names = run_js("Object.keys(X)")
    assert "extractVideo" in names
    assert "parseVideoDuration" in names


# ----------------------------------------------------- note frontmatter

import sys  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import x_render  # noqa: E402
import xpost_download  # noqa: E402


def _post(**over):
    base = {
        "status_id": "2099165993834799124", "handle": "alokkumarzz",
        "author_name": "Alok Kumar", "date": "2026-09-14", "date_captured": "2026-09-14",
        "post_type": "post", "metrics": {"likes": 1, "reposts": 2, "views": 3},
        "media": 0, "content": "A Stanford professor.", "image_files": [],
    }
    base.update(over)
    return base


def _frontmatter(note):
    return note.split("---")[1]


def test_a_text_post_gains_no_video_keys():
    fm = _frontmatter(x_render.render_note(_post()))
    assert "media_type:" not in fm
    assert "transcript:" not in fm


def test_a_video_post_declares_its_type_duration_and_transcript_debt():
    fm = _frontmatter(x_render.render_note(_post(
        video={"present": True, "isGif": False, "seconds": 3215})))
    # `media:` is already an integer image count, so the KIND of media has to
    # live under its own key rather than overloading that one.
    assert "media_type: video" in fm
    assert "media: 0" in fm
    assert "video_seconds: 3215" in fm
    assert "video_duration: 53:35" in fm
    # Present-and-pending is what makes an untranscribed video visible. Absent
    # would be indistinguishable from a text post.
    assert "transcript: pending" in fm


def test_an_unread_duration_is_omitted_not_written_as_zero():
    # 0 reads as "too short to bother transcribing", which is the opposite of
    # what an unread duration means.
    fm = _frontmatter(x_render.render_note(_post(
        video={"present": True, "isGif": False, "seconds": None})))
    assert "media_type: video" in fm
    assert "video_seconds:" not in fm
    assert "video_duration:" not in fm


def test_a_gif_owes_no_transcript():
    fm = _frontmatter(x_render.render_note(_post(
        video={"present": True, "isGif": True, "seconds": None})))
    assert "media_type: gif" in fm
    assert "transcript:" not in fm


def test_hour_long_durations_format_with_an_hours_field():
    fm = _frontmatter(x_render.render_note(_post(
        video={"present": True, "isGif": False, "seconds": 3725})))
    assert "video_duration: 1:02:05" in fm


# ----------------------------------------------------- the stderr marker

class _FakePage:
    url = "https://x.com/alokkumarzz/status/2099165993834799124"


def _capture(monkeypatch, tmp_path, video):
    monkeypatch.setattr(xpost_download.x_extract, "extract_thread_here",
                        lambda *a, **k: {"is_thread": False,
                                         "root_id": "2099165993834799124", "posts": [{
                            "status_id": "2099165993834799124", "handle": "alokkumarzz",
                            "author_name": "Alok Kumar", "content": "A Stanford professor.",
                            "timestamp": "2026-09-14T00:00:00.000Z",
                            "metrics": {"likes": 1, "reposts": 2, "views": 3},
                            "images": [], "expected_images": 0, "video": video}]})
    return xpost_download.download_open_post(
        _FakePage(), "alokkumarzz", str(tmp_path), "2026-09-14", download_media=False)


def test_a_video_post_announces_itself_on_stderr(monkeypatch, tmp_path, capsys):
    _capture(monkeypatch, tmp_path, {"present": True, "isGif": False, "seconds": 3215})
    err = capsys.readouterr().err
    assert "VIDEO_DETECTED:https://x.com/alokkumarzz/status/2099165993834799124\t3215" in err


def test_the_marker_never_reaches_stdout(monkeypatch, tmp_path, capsys):
    # OUTPUT_FILE: must stay the sole machine-parseable line on stdout. A
    # second marker there breaks every caller that reads the last stdout line.
    _capture(monkeypatch, tmp_path, {"present": True, "isGif": False, "seconds": 3215})
    assert "VIDEO_DETECTED" not in capsys.readouterr().out


def test_a_gif_is_not_announced_for_transcription(monkeypatch, tmp_path, capsys):
    _capture(monkeypatch, tmp_path, {"present": True, "isGif": True, "seconds": None})
    assert "VIDEO_DETECTED" not in capsys.readouterr().err


def test_a_text_post_is_not_announced(monkeypatch, tmp_path, capsys):
    _capture(monkeypatch, tmp_path, None)
    assert "VIDEO_DETECTED" not in capsys.readouterr().err
