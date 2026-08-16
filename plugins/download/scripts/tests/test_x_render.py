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
