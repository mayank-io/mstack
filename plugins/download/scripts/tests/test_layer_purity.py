"""download:x-account must emit NO Obsidian/vault syntax. Grep the render
output surface. See design §10.4."""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_no_wikilinks_in_render_module_output():
    from x_render import render_note
    md = render_note({
        "status_id": "1", "handle": "h", "author_name": "H",
        "date": "2026-01-01", "date_captured": "2026-08-16",
        "post_type": "post", "metrics": {"likes": 0, "reposts": 0, "views": 0},
        "media": 1, "content": "$AAPL to the moon", "image_files": ["h-1-1.jpg"],
    })
    # even ticker-looking content must not become a wikilink here
    assert "[[" not in md and "]]" not in md

def test_render_source_has_no_daily_note_pattern():
    src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "x_render.py")).read()
    assert "[[" not in src  # no wikilink templating anywhere in the layer
