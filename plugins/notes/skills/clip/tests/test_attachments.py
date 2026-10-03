"""Tests for attachments.py: localize a note's images, then verify every embed.

No network and no Obsidian: the downloader and the Obsidian runner are injected.
Each test pins a way a clipping has looked complete while its images lived
somewhere else, or nowhere.
"""
import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import attachments as att  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
B64 = base64.b64encode(PNG).decode()


@pytest.fixture
def vault(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / "Clippings" / "attachments").mkdir(parents=True)
    return tmp_path


def note(vault, body, name="My Note.md"):
    p = vault / "Clippings" / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def run(path, fetcher=lambda u: b"", **kw):
    return att.process(path, fetcher=fetcher, **kw)


# ------------------------------------------------------------------ sniff

@pytest.mark.parametrize("data,ext", [
    (PNG, "png"), (JPG, "jpg"), (b"GIF89a....", "gif"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
    (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "svg"),
    (b'<?xml version="1.0"?>\n<svg></svg>', "svg"),
    (b"<!doctype html><html>", None), (b"", None),
])
def test_sniff_by_magic_bytes(data, ext):
    assert att.sniff(data) == ext


# ------------------------------------------------------------------ localize

def test_data_uri_becomes_a_file_and_a_relative_embed(vault):
    p = note(vault, f"Intro\n\n![chart](data:image/png;base64,{B64})\n\nOutro\n")
    r = run(p)
    text = Path(p).read_text()
    assert "data:" not in text
    assert "![chart](attachments/my-note-01.png)" in text
    assert (vault / "Clippings/attachments/my-note-01.png").read_bytes() == PNG
    assert r["ok"] and r["saved"] == ["my-note-01.png"]


def test_html_img_data_uri_is_localized(vault):
    p = note(vault, f'<img alt="x" src="data:image/png;base64,{B64}" width="10">\n')
    assert run(p)["ok"]
    assert Path(p).read_text().strip() == "![](attachments/my-note-01.png)"


def test_remote_image_is_downloaded_and_named_by_content_not_url(vault):
    p = note(vault, "![a](https://cdn.example.com/img?id=7)\n")
    r = run(p, fetcher=lambda u: JPG)
    assert Path(p).read_text() == "![a](attachments/my-note-01.jpg)\n"
    assert r["ok"] and r["remote_embeds"] == []


def test_failed_image_download_fails_the_run_and_keeps_the_link(vault):
    body = "![a](https://cdn.example.com/chart.png)\n"
    p = note(vault, body)
    r = run(p, fetcher=lambda u: b"")
    assert not r["ok"]
    assert r["failed"] == [{"what": "image download failed", "at": "https://cdn.example.com/chart.png"}]
    assert Path(p).read_text() == body
    assert r["remote_embeds"] == ["https://cdn.example.com/chart.png"]


def test_remote_non_image_embed_is_left_alone_and_is_not_an_error(vault):
    body = "![Talk](https://www.youtube.com/watch?v=abc)\n"
    p = note(vault, body)
    r = run(p, fetcher=lambda u: b"<!doctype html><html>player</html>")
    assert r["ok"] and Path(p).read_text() == body
    assert r["skipped"] == [{"what": "remote embed is not an image", "at": "https://www.youtube.com/watch?v=abc"}]


def test_inline_svg_is_saved_repaired_and_embedded(vault):
    p = note(vault, 'Before\n\n<svg width="10" style viewBox="0 0 1 1"><text>a&nbsp;b</text></svg>\n\nAfter\n')
    r = run(p)
    saved = (vault / "Clippings/attachments/my-note-01.svg").read_text()
    assert 'xmlns="http://www.w3.org/2000/svg"' in saved and 'style=""' in saved and "&#160;" in saved
    assert "<svg" not in Path(p).read_text() and "![](attachments/my-note-01.svg)" in Path(p).read_text()
    assert r["ok"]


def test_fenced_code_is_never_rewritten(vault):
    body = f"```html\n<svg><rect/></svg>\n![x](data:image/png;base64,{B64})\n```\n"
    p = note(vault, body)
    r = run(p)
    assert Path(p).read_text() == body and r["saved"] == [] and r["ok"]


def test_numbering_continues_and_never_reuses_a_number(vault):
    (vault / "Clippings/attachments/my-note-01.jpg").write_bytes(JPG)
    p = note(vault, f"![a](attachments/my-note-01.jpg)\n![b](data:image/png;base64,{B64})\n")
    run(p)
    assert "![b](attachments/my-note-02.png)" in Path(p).read_text()


def test_second_run_changes_nothing(vault):
    p = note(vault, f"![c](data:image/png;base64,{B64})\n")
    run(p)
    once = Path(p).read_text()
    r = run(p)
    assert Path(p).read_text() == once and r["saved"] == [] and r["ok"]


def test_prefix_override(vault):
    p = note(vault, f"![c](data:image/png;base64,{B64})\n")
    assert run(p, prefix="karpathy-123")["saved"] == ["karpathy-123-01.png"]


# ------------------------------------------------------------------ verify

def test_missing_local_embed_is_a_problem(vault):
    p = note(vault, "![x](attachments/nope.png)\n")
    r = run(p, check_only=True)
    assert not r["ok"] and r["problems"] == [{"embed": "attachments/nope.png", "problem": "missing"}]


def test_empty_file_is_a_problem(vault):
    (vault / "Clippings/attachments/z.png").write_bytes(b"")
    r = run(note(vault, "![x](attachments/z.png)\n"), check_only=True)
    assert r["problems"] == [{"embed": "attachments/z.png", "problem": "empty file"}]


def test_icloud_placeholder_is_named_as_such(vault):
    (vault / "Clippings/attachments/.pic.png.icloud").write_bytes(b"x")
    r = run(note(vault, "![x](attachments/pic.png)\n"), check_only=True)
    assert r["problems"] == [{"embed": "attachments/pic.png", "problem": "iCloud placeholder, not downloaded"}]


def test_url_encoded_path_resolves(vault):
    (vault / "Clippings/attachments/my pic.png").write_bytes(PNG)
    r = run(note(vault, "![x](attachments/my%20pic.png)\n"), check_only=True)
    assert r["ok"] and r["local_ok"] == ["Clippings/attachments/my pic.png"]


def test_wikilink_embed_resolves_by_basename_across_the_vault(vault):
    (vault / "Elsewhere").mkdir()
    (vault / "Elsewhere/deck.pdf").write_bytes(b"%PDF-1.7")
    r = run(note(vault, "![[deck.pdf]]\n![[attachments/gone.jpg]]\n![[Daily.base]]\n![[Some Note]]\n"), check_only=True)
    assert r["local_ok"] == ["Elsewhere/deck.pdf"]
    assert r["problems"] == [{"embed": "attachments/gone.jpg", "problem": "missing"}]   # .base and notes are not attachments


def test_markdown_embed_falls_back_to_basename_like_obsidian_does(vault):
    # the note says `deck.pdf`; the file lives in attachments/. Obsidian shows it.
    (vault / "Clippings/attachments/deck.pdf").write_bytes(b"%PDF-1.4")
    r = run(note(vault, "![](deck.pdf)\n![](nowhere.pdf)\n"), check_only=True)
    assert r["local_ok"] == ["Clippings/attachments/deck.pdf"]
    assert r["problems"] == [{"embed": "nowhere.pdf", "problem": "missing"}]


def test_icloud_placeholder_still_detected_at_the_stated_path(vault):
    (vault / "Clippings/attachments/.pic.png.icloud").write_bytes(b"x")
    (vault / "Elsewhere").mkdir()
    r = run(note(vault, "![x](attachments/pic.png)\n"), check_only=True)
    assert r["problems"][0]["problem"] == "iCloud placeholder, not downloaded"


def test_linked_local_files_are_checked_like_embeds(vault):
    (vault / "Clippings/attachments/supp 1.pdf").write_bytes(b"%PDF-1.4")
    body = ("[Additional file 1](attachments/supp%201.pdf)\n[Table](attachments/gone.xls)\n"
            "[web](https://example.com/a.pdf)\n[section](#Results)\n[note](Other%20Note.md)\n")
    r = run(note(vault, body), check_only=True)
    assert r["local_ok"] == ["Clippings/attachments/supp 1.pdf"]
    assert r["problems"] == [{"embed": "attachments/gone.xls", "problem": "missing"}]


def test_malformed_svg_file_is_a_problem(vault):
    (vault / "Clippings/attachments/d.svg").write_text("<svg style><g></svg>")
    r = run(note(vault, "![x](attachments/d.svg)\n"), check_only=True)
    assert r["problems"][0]["problem"].startswith("SVG does not parse")


def test_check_only_reports_inline_data_without_touching_the_note(vault):
    body = f"![c](data:image/png;base64,{B64})\n\n<svg><g/></svg>\n"
    p = note(vault, body)
    r = run(p, check_only=True)
    assert Path(p).read_text() == body and not r["ok"]
    assert {x["problem"] for x in r["problems"]} == {"data left in the note, not an attachment",
                                                     "inline-svg left in the note, not an attachment"}


def test_note_with_no_embeds_is_ok(vault):
    r = run(note(vault, "Just text.\n"))
    assert r["ok"] and r["local_ok"] == [] and r["problems"] == []


# ------------------------------------------------------------------ obsidian

class FakeRun:
    def __init__(self, reply=None, raise_=None, rc=0):
        self.reply, self.raise_, self.rc, self.calls = reply, raise_, rc, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if self.raise_:
            raise self.raise_
        out = "=> 1" if len(self.calls) == 1 else "=> " + json.dumps(self.reply)
        return subprocess.CompletedProcess(cmd, self.rc, out, "")


def test_obsidian_ok_and_uses_vault_relative_path(vault):
    p = note(vault, "![x](attachments/a.png)\n")
    fake = FakeRun({"embeds": 1, "unresolved": []})
    r = att.obsidian_check(p, wait=0, run=fake)
    assert r == {"status": "ok", "embeds": 1, "unresolved": []}
    assert fake.calls[0][1] == f"vault={vault.name}" and '"Clippings/My Note.md"' in fake.calls[0][3]


def test_obsidian_unresolved_fails_the_run(vault, monkeypatch):
    (vault / "Clippings/attachments/a.png").write_bytes(PNG)
    p = note(vault, "![x](attachments/a.png)\n")
    monkeypatch.setattr(att, "obsidian_check", lambda path: {"status": "failed", "embeds": 1, "unresolved": ["attachments/a.png"]})
    assert not run(p, check_only=True, obsidian=True)["ok"]


def test_obsidian_unavailable_is_skipped_not_passed(vault, monkeypatch):
    p = note(vault, "text\n")
    r = att.obsidian_check(p, wait=0, run=FakeRun(raise_=FileNotFoundError("obsidian")))
    assert r["status"] == "skipped" and "unavailable" in r["reason"]
    monkeypatch.setattr(att, "obsidian_check", lambda path: r)
    assert run(p, obsidian=True)["ok"]            # local checks still decide


def test_obsidian_outside_a_vault_is_skipped(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("x")
    assert att.obsidian_check(str(p), wait=0, run=FakeRun({}))["status"] == "skipped"


# ------------------------------------------------------------------ CLI

def test_cli_exit_codes_and_json(vault, capsys):
    (vault / "Clippings/attachments/a.png").write_bytes(PNG)
    good = note(vault, "![x](attachments/a.png)\n", "Good.md")
    bad = note(vault, "![x](attachments/missing.png)\n", "Bad.md")
    assert att.main([good, "--check-only"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert att.main([bad, "--check-only"]) == 1
    cap = capsys.readouterr()
    assert json.loads(cap.out)["ok"] is False and "PROBLEM: attachments/missing.png: missing" in cap.err
    assert att.main([str(vault / "nope.md")]) == 2
