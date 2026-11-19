"""Long posts cut at "Show more".

X renders a post longer than about 280 characters in full only as the focal
post of its own status page. In a thread view every long reply is cut, with a
"Show more" button after the text. The cut text is ordinary prose, so a thread
captured from one page read as a complete note while ten of its twelve posts
held their opening lines only.

The fixture below is a 12-post long-form thread shaped like the page measured
on 2026-11-15: posts 1 and 12 are short and whole, posts 2-11 are cut at 276-280
characters and carry a <button data-testid="tweet-text-show-more-link"> that is
a sibling AFTER tweetText, and clicking it expands the post in place.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import x_extract  # noqa: E402
import x_render  # noqa: E402
import xpost_download  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
EXTRACTION_JS = SCRIPTS.parent / "skills" / "x-post" / "references" / "extraction.js"

HANDLE = "longform"
ROOT_ID = 2000000000000000000
IDS = [str(ROOT_ID + i * 50_000_000_000) for i in range(12)]     # seconds apart
FULL = {sid: (f"Post {i + 1} of the thread. " + "A complete sentence that carries the argument. " * 30).strip()
        for i, sid in enumerate(IDS)}
FULL[IDS[0]] = "Everything you need to know about the subject - 1/N"
FULL[IDS[11]] = "That is the whole of it. Hope it helps."
CUT_IDS = IDS[1:11]


def cut(text: str) -> str:
    return text[:278].rstrip(" .")


# ============================================================ extraction.js

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is required to execute extraction.js")

# A DOM just deep enough for extraction.js: articles in document order, each
# with an author link, a permalink, a tweetText and (when cut) a Show more
# control placed after the text. `quoted` adds a quote card with its own text
# and its own control, after the post's.
DOM_JS = r"""
function makeDocument(posts) {
  let pos = 0;
  const articles = posts.map((p) => {
    const node = (extra) => Object.assign({ pos: pos++,
      compareDocumentPosition(o) { return o.pos > this.pos ? 4 : 2; } }, extra);
    const text = node({ innerText: p.shown });
    const kids = { text: [text], more: [] };
    const control = (onClick) => node({ tagName: p.tag || 'BUTTON', click: onClick });
    if (p.cut) kids.more.push(control(() => {
      if (p.dead) return;
      text.innerText = p.full; kids.more.shift(); clicks.push(p.id); }));
    if (p.quoted) { kids.text.push(node({ innerText: 'quoted text, cut' })); kids.more.push(control(() => {})); }
    const author = { getAttribute: () => '/' + p.handle, textContent: p.handle };
    const time = { getAttribute: () => '2026-06-15T10:00:00.000Z',
                   closest: () => ({ getAttribute: () => '/' + p.handle + '/status/' + p.id }) };
    const all = (sel) => sel.includes('tweet-text-show-more-link') ? kids.more
      : sel.includes('tweetText') ? kids.text
      : sel === 'a[role="link"]' ? [author] : [];
    return { innerText: p.shown, querySelectorAll: all,
             querySelector: (sel) => sel === 'time' ? time : (all(sel)[0] || null) };
  });
  return { querySelectorAll: (sel) => sel === 'article' ? articles : [],
           querySelector: (sel) => sel === 'article' ? (articles[0] || null) : null };
}
const clicks = [];
"""


def run_js(posts, body: str):
    script = (
        "const fs = require('fs');\n"
        "global.window = {};\n"
        f"eval(fs.readFileSync({json.dumps(str(EXTRACTION_JS))}, 'utf8'));\n"
        "const X = window.__xExtract;\n"
        + DOM_JS +
        f"global.document = makeDocument({json.dumps(posts)});\n"
        f"console.log(JSON.stringify({body}));\n"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def thread_view(**overrides):
    """The 12-post thread as its root's status page shows it."""
    posts = []
    for sid in IDS:
        is_cut = sid in CUT_IDS
        posts.append({"id": sid, "handle": HANDLE, "full": FULL[sid], "cut": is_cut,
                      "shown": cut(FULL[sid]) if is_cut else FULL[sid], **overrides.get(sid, {})})
    return posts


@needs_node
def test_thread_view_reports_exactly_the_cut_posts_as_truncated():
    posts = run_js(thread_view(), f"X.extractAllByAuthor({json.dumps(HANDLE)})")
    assert [p["statusId"] for p in posts] == IDS
    assert [p["statusId"] for p in posts if p["truncated"]] == CUT_IDS
    assert all(len(p["content"]) <= 280 for p in posts if p["truncated"])


@needs_node
def test_expand_show_more_opens_every_cut_post_in_place():
    result = run_js(thread_view(),
                    f"(() => {{ const r = X.expandShowMore({json.dumps(HANDLE)});"
                    f" return {{ r, clicks, posts: X.extractAllByAuthor({json.dumps(HANDLE)}) }}; }})()")
    assert result["r"] == {"clicked": 10, "links": 0}
    assert result["clicks"] == CUT_IDS
    assert {p["statusId"]: p["content"] for p in result["posts"]} == FULL
    assert not any(p["truncated"] for p in result["posts"])


@needs_node
def test_a_link_control_is_counted_not_clicked():
    """An <a> would navigate away from the conversation mid-collection."""
    view = thread_view(**{IDS[1]: {"tag": "A"}})
    result = run_js(view, f"(() => ({{ r: X.expandShowMore({json.dumps(HANDLE)}), clicks }}))()")
    assert result["r"] == {"clicked": 9, "links": 1}
    assert IDS[1] not in result["clicks"]


@needs_node
def test_other_authors_posts_are_not_expanded():
    view = thread_view() + [{"id": "2999", "handle": "someone_else", "full": "f" * 900,
                             "shown": "f" * 278, "cut": True}]
    result = run_js(view, f"(() => ({{ r: X.expandShowMore({json.dumps(HANDLE)}), clicks }}))()")
    assert result["r"]["clicked"] == 10
    assert "2999" not in result["clicks"]


@needs_node
def test_a_quote_cards_show_more_does_not_mark_the_quoting_post():
    view = [{"id": IDS[0], "handle": HANDLE, "full": "short and whole", "shown": "short and whole",
             "cut": False, "quoted": True}]
    assert run_js(view, "X.extractFocal().truncated") is False
    assert run_js(view, f"X.expandShowMore({json.dumps(HANDLE)})") == {"clicked": 0, "links": 0}


@needs_node
def test_extract_by_id_returns_the_named_post_not_the_first_article():
    """On a reply's status page the ancestors render above it."""
    got = run_js(thread_view(), f"X.extractById({json.dumps(IDS[3])})")
    assert got["statusId"] == IDS[3]
    assert "error" in run_js(thread_view(), 'X.extractById("1")')


# ================================================================ x_extract

class FakePage:
    """The conversation page, as x_extract drives it.

    `dead` posts ignore the in-place click (they open only on their own status
    page); `sealed` posts are cut everywhere.
    """

    def __init__(self, dead=(), sealed=(), control_renamed=False):
        self.dead, self.sealed = set(dead), set(sealed)
        self.control_renamed = control_renamed
        self.expanded, self.visited = set(), []
        self.url = f"https://x.com/{HANDLE}/status/{IDS[0]}"

    def _post(self, sid, whole):
        return {"statusId": sid, "handle": HANDLE, "displayName": "Long Form",
                "content": FULL[sid] if whole else cut(FULL[sid]),
                "truncated": not whole and not self.control_renamed,
                "timestamp": "2026-06-15T10:00:00.000Z", "images": [], "video": None,
                "isReplyToOther": False}

    def evaluate(self, expression, *args):
        if expression.startswith("typeof"):
            return "object"
        if "expandShowMore" in expression:
            openable = set(CUT_IDS) - self.dead - self.sealed - self.expanded
            if self.control_renamed:
                openable = set()
            self.expanded |= openable
            return {"clicked": len(openable), "links": 0}
        if "extractAllByAuthor" in expression:
            return [self._post(sid, sid not in CUT_IDS or sid in self.expanded) for sid in IDS]
        if "extractById" in expression:
            return self._post(args[0], args[0] not in self.sealed)
        if "findRoot" in expression:
            return {"rootId": IDS[0]}
        if "mediaReady" in expression:
            return True
        if expression == "window.scrollY":
            return 0
        return None

    def goto(self, url, **_):
        self.url = url
        self.visited.append(url.rsplit("/", 1)[1])

    def wait_for_selector(self, *_a, **_k):
        return True


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(x_extract.time, "sleep", lambda _s: None)


def test_long_thread_is_captured_whole_without_leaving_the_page():
    page = FakePage()
    th = x_extract.extract_thread_here(page, HANDLE, IDS[0])
    assert {p["status_id"]: p["content"] for p in th["posts"]} == FULL
    assert not any(p["truncated"] for p in th["posts"])
    assert page.visited == []


def test_a_post_the_click_did_not_open_is_read_from_its_own_status_page():
    page = FakePage(dead=[IDS[4], IDS[7]])
    th = x_extract.extract_thread_here(page, HANDLE, IDS[0])
    assert page.visited == [IDS[4], IDS[7]]
    assert {p["status_id"]: p["content"] for p in th["posts"]} == FULL
    assert not any(p["truncated"] for p in th["posts"])


def test_a_post_cut_everywhere_stays_flagged():
    page = FakePage(sealed=[IDS[5]])
    th = x_extract.extract_thread_here(page, HANDLE, IDS[0])
    assert [p["status_id"] for p in th["posts"] if p["truncated"]] == [IDS[5]]
    assert len(th["posts"]) == 12


def test_a_status_page_that_fails_to_load_leaves_the_post_flagged(capsys):
    page = FakePage(dead=[IDS[2]])

    def timeout(*_a, **_k):
        raise RuntimeError("waitFor: Timeout 15000ms exceeded")
    page.wait_for_selector = timeout
    th = x_extract.extract_thread_here(page, HANDLE, IDS[0])
    assert [p["status_id"] for p in th["posts"] if p["truncated"]] == [IDS[2]]
    assert IDS[2] in capsys.readouterr().err


@pytest.mark.parametrize("content, expected", [
    (cut(FULL[IDS[1]]), True),                                   # the measured shape: a bare word
    ("x" * 250 + " and then, after all of that,", True),
    ("x" * 250 + " as the text says…", True),
    (FULL[IDS[1]], False),                                       # ends on a full stop
    ("x" * 250 + " is that so?", False),
    ("x" * 250 + " read it here example.com/a/long/pa…", False),
    ("x" * 250 + " more tomorrow #threads", False),
    ("x" * 250 + " the subject - 3/12", False),
    ("x" * 250 + " the subject - 1/N", False),
    ("short and unpunctuated", False),
    ("", False),
    (None, False),
])
def test_ends_mid_sentence(content, expected):
    assert x_extract.ends_mid_sentence(content) is expected


# =========================================================== xpost_download

def test_download_reports_cut_posts_and_marks_the_note(tmp_path, capsys):
    page = FakePage(sealed=[IDS[5], IDS[6]])
    result = xpost_download.download_open_post(page, HANDLE, str(tmp_path), "2026-11-15")
    err = capsys.readouterr().err
    assert result["truncated_ids"] == [IDS[5], IDS[6]]
    assert err.count("TRUNCATED_POST:") == 2
    assert f"TRUNCATED_POST:https://x.com/{HANDLE}/status/{IDS[5]}" in err
    note = (tmp_path / HANDLE / result["note"]).read_text()
    assert "incomplete_posts: 2" in note
    assert note.count(x_render.INCOMPLETE_MARKER) == 2


def test_download_of_a_whole_thread_carries_no_incomplete_marks(tmp_path, capsys):
    result = xpost_download.download_open_post(FakePage(), HANDLE, str(tmp_path), "2026-11-15")
    assert result["truncated_ids"] == [] and result["suspect_ids"] == []
    note = (tmp_path / HANDLE / result["note"]).read_text()
    assert "incomplete" not in note.lower()
    assert all(FULL[sid] in note for sid in IDS)
    assert "TRUNCATED" not in capsys.readouterr().err


def test_download_warns_when_text_looks_cut_but_no_control_was_found(tmp_path, capsys):
    """The backstop for X renaming the control: nothing is flagged truncated."""
    result = xpost_download.download_open_post(
        FakePage(control_renamed=True), HANDLE, str(tmp_path), "2026-11-15")
    assert result["truncated_ids"] == []
    assert result["suspect_ids"] == CUT_IDS
    assert capsys.readouterr().err.count("POSSIBLY_TRUNCATED:") == 10


class _Session:
    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False


def test_cli_exits_4_without_output_file_when_posts_are_cut(monkeypatch, capsys, tmp_path):
    import _browse
    monkeypatch.setattr(_browse, "sync_browse_page", _Session)
    monkeypatch.setattr(xpost_download, "download_url", lambda *a, **k: {
        "note": "posts/n.md", "is_thread": True, "post_count": 12, "media": 0,
        "truncated_ids": ["5", "6"], "suspect_ids": []})
    rc = xpost_download.main([f"https://x.com/{HANDLE}/status/1", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == xpost_download.EXIT_INCOMPLETE == 4
    assert "OUTPUT_FILE" not in captured.out
    assert "2 of 12 post(s) are cut" in captured.err


def test_single_cut_post_is_marked_in_the_note():
    note = x_render.render_note({
        "status_id": "1", "handle": "h", "author_name": "H", "date": "2026-01-01",
        "date_captured": "2026-11-15", "post_type": "post", "metrics": {}, "media": 0,
        "content": "cut text", "image_files": [], "truncated": True, "incomplete_posts": 1})
    assert "incomplete_posts: 1" in note
    assert x_render.INCOMPLETE_MARKER in note
