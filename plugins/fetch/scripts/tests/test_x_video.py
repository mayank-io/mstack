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
