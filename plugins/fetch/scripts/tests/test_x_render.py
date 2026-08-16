import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_render import slugify, note_filename

def test_filename_format():
    assert note_filename("2026-02-08", "vedanjanam", "Saturn transit") \
        == "2026-02-08 @vedanjanam - Saturn transit.md"

def test_slug_strips_forbidden_chars():
    assert slugify('Saturn: "transit" / retrograde?') == "Saturn transit retrograde"

def test_slug_capped_at_60():
    assert len(slugify("word " * 40, max_len=60)) <= 60

def test_filename_never_contains_status_id():
    fn = note_filename("2026-02-08", "vedanjanam", "Saturn transit")
    assert "2020489596505592084" not in fn


def test_render_note_has_frontmatter_and_status_id():
    from x_render import render_note
    md = render_note({
        "status_id": "2020489596505592084", "handle": "vedanjanam",
        "author_name": "Vedanjanam", "date": "2026-02-08",
        "date_captured": "2026-08-16", "post_type": "post",
        "metrics": {"likes": 1240, "reposts": 312, "views": 88400},
        "media": 0, "content": "Saturn transits Purva Bhadrapada.",
        "image_files": [],
    })
    assert 'status_id: "2020489596505592084"' in md
    assert "Saturn transits Purva Bhadrapada." in md
    assert "author: \"@vedanjanam\"" in md

def test_render_note_emits_no_vault_syntax():
    from x_render import render_note
    md = render_note({
        "status_id": "1", "handle": "h", "author_name": "H",
        "date": "2026-01-01", "date_captured": "2026-08-16",
        "post_type": "post", "metrics": {"likes": 0, "reposts": 0, "views": 0},
        "media": 0, "content": "text", "image_files": [],
    })
    assert "[[" not in md   # download layer must never emit wikilinks

def test_render_thread_numbers_sections():
    from x_render import render_note
    md = render_note({
        "status_id": "1", "handle": "h", "author_name": "H",
        "date": "2026-01-01", "date_captured": "2026-08-16",
        "post_type": "thread", "thread_length": 2,
        "metrics": {"likes": 0, "reposts": 0, "views": 0}, "media": 0,
        "sections": [{"content": "first"}, {"content": "second"}],
        "image_files": [],
    })
    assert "## 1." in md and "## 2." in md
