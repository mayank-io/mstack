import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_state import ArchiveState, FORMAT_VERSION

def test_manifest_roundtrip_injects_format_version(tmp_path):
    s = ArchiveState(str(tmp_path))
    s.write_manifest({"handle": "vedanjanam"})
    m = s.read_manifest()
    assert m["handle"] == "vedanjanam"
    assert m["format_version"] == FORMAT_VERSION

def test_read_manifest_none_when_absent(tmp_path):
    assert ArchiveState(str(tmp_path)).read_manifest() is None

def test_append_and_replay_posts(tmp_path):
    s = ArchiveState(str(tmp_path))
    s.append_post({"status_id": "1", "status": "rendered"})
    s.append_post({"status_id": "2", "status": "rendered"})
    assert [p["status_id"] for p in s.read_posts()] == ["1", "2"]

def test_torn_final_line_is_discarded(tmp_path):
    s = ArchiveState(str(tmp_path))
    s.append_post({"status_id": "1"})
    # simulate a crash mid-write: append a truncated JSON line
    with open(os.path.join(str(tmp_path), ".x-archive", "posts.jsonl"), "a") as f:
        f.write('{"status_id": "2", "st')  # no newline, invalid
    assert [p["status_id"] for p in s.read_posts()] == ["1"]

def test_manifest_write_is_atomic_no_tmp_left(tmp_path):
    s = ArchiveState(str(tmp_path))
    s.write_manifest({"a": 1})
    archive = os.path.join(str(tmp_path), ".x-archive")
    assert not any(n.endswith(".tmp") for n in os.listdir(archive))

def test_budget_counter_persists(tmp_path):
    s = ArchiveState(str(tmp_path))
    assert s.rendered_today("2026-08-16") == 0
    s.bump_rendered("2026-08-16", 3)
    # a fresh handle to the same dir must see the persisted count
    assert ArchiveState(str(tmp_path)).rendered_today("2026-08-16") == 3

def test_budget_counter_is_per_day(tmp_path):
    s = ArchiveState(str(tmp_path))
    s.bump_rendered("2026-08-16", 5)
    assert s.rendered_today("2026-08-17") == 0
