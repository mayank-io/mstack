"""Tests for the LinkedIn ARTICLE download unit and its extraction.js.

The extractor is exercised under jsdom against `fixtures/linkedin_pulse_gokul_rajaram.html`,
the <article> and social-count bar saved from the live page
https://www.linkedin.com/pulse/defensibility-ai-data-lessons-from-ads-gokul-rajaram-6vsuc
on 2026-10-02. Every expected value below was read off that page by hand.

What these pin, each of which produced (or would produce) a capture that looks fine:

1. Inline images. Post mode's filter rejects `article-cover_image` and does not
   know `article-inline_image`; the article's only body image would vanish.
2. Image position. The image sits between the closing paragraph and the PS;
   flattening the body to one string loses where it goes.
3. Bold run-ins. LinkedIn puts the separating space INSIDE <strong>, so naive
   wrapping yields `**workflow:**Doubleclick` — unrendered and fused.
4. Reactions. The visible text is a bare "37"; only the aria-label carries the unit.
5. Dates. Pulse slugs carry no activity id, so the date comes from the printed
   label, corroborated by the CDN upload time in the image URLs.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import linkedin_article_download as lad  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
EXTRACTION_JS = SCRIPTS.parent / "skills" / "linkedin-post" / "references" / "article_extraction.js"
FIXTURE = Path(__file__).parent / "fixtures" / "linkedin_pulse_gokul_rajaram.html"
URL = "https://www.linkedin.com/pulse/defensibility-ai-data-lessons-from-ads-gokul-rajaram-6vsuc"


# ------------------------------------------------------------------ URL parse

@pytest.mark.parametrize("url,slug", [
    (URL, "defensibility-ai-data-lessons-from-ads-gokul-rajaram-6vsuc"),
    (URL + "/", "defensibility-ai-data-lessons-from-ads-gokul-rajaram-6vsuc"),
    ("linkedin.com/pulse/defensibility-ai-data-lessons-from-ads-gokul-rajaram-6vsuc",
     "defensibility-ai-data-lessons-from-ads-gokul-rajaram-6vsuc"),
    ("https://in.linkedin.com/pulse/abc-def-1x2y?trackingId=z", "abc-def-1x2y"),
    ("  https://www.linkedin.com/pulse/a-b/#comments  ", "a-b"),
])
def test_pulse_urls_parse_to_canonical(url, slug):
    canonical, got = lad.parse_pulse_url(url)
    assert got == slug
    assert canonical == f"https://www.linkedin.com/pulse/{slug}/"


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/posts/gokulrajaram_x-activity-7311234567890123456-abcd",
    "https://www.linkedin.com/feed/update/urn:li:activity:7311234567890123456/",
    "https://www.linkedin.com/in/gokulrajaram1/",
    "https://www.linkedin.com/pulse/",
    "https://example.com/pulse/some-article",
    "",
    None,
])
def test_non_article_urls_are_refused(url):
    with pytest.raises(ValueError):
        lad.parse_pulse_url(url)


def test_cli_refuses_a_post_url_before_touching_the_browser(capsys):
    assert lad.main(["https://www.linkedin.com/posts/someone_x-activity-1-abc"]) == 2
    out, err = capsys.readouterr()
    assert "OUTPUT_DIR:" not in out
    assert "not a LinkedIn article URL" in err


def test_cli_usage_without_arguments(capsys):
    assert lad.main([]) == 2
    assert "OUTPUT_DIR:" not in capsys.readouterr().out


# ------------------------------------------------------------------ dates

@pytest.mark.parametrize("label,iso", [
    ("October 2, 2026", "2026-10-02"),
    ("Oct 2, 2026", "2026-10-02"),
    ("December 31, 2025", "2025-12-31"),
    ("  March 1, 2024 ", "2024-03-01"),
])
def test_published_label_parses(label, iso):
    assert lad.parse_published_label(label) == iso


@pytest.mark.parametrize("label", ["2w", "1d • Edited", "", None, "2026-10-02", "Octember 2, 2026"])
def test_unparseable_label_is_none_not_a_guess(label):
    assert lad.parse_published_label(label) is None


def test_cdn_upload_time_decodes_epoch_ms_in_utc():
    u = ("https://media.licdn.com/dms/image/v2/D5612AQFZg47sX2nA7w/article-inline_image-"
         "shrink_1000_1488/B56aD6VyBuJMAM-/0/1790906409754?e=1792627200&v=beta&t=x")
    t = lad.cdn_upload_time(u)
    assert t.isoformat() == "2026-10-02T02:00:09.754000+00:00"


@pytest.mark.parametrize("u", ["", None, "https://media.licdn.com/x/0/123?e=1",
                               "https://static.licdn.com/aero-v1/sc/h/8ekq8gho1ruaf8i7f86vd1ftt"])
def test_cdn_upload_time_none_without_a_13_digit_stamp(u):
    assert lad.cdn_upload_time(u) is None


def test_date_check_agrees_within_skew():
    u = "https://media.licdn.com/a/article-inline_image-shrink_1/b/0/1790906409754?e=1"
    first, warning = lad.date_check("2026-10-02", [u])
    assert first.startswith("2026-10-02T02:00:09")
    assert warning is None


def test_date_check_boundary_two_days_ok_three_days_warns():
    u = "https://media.licdn.com/a/article-inline_image-shrink_1/b/0/1790906409754?e=1"  # 2026-10-02
    assert lad.date_check("2026-10-04", [u])[1] is None          # exactly MAX_DATE_SKEW_DAYS
    assert "3 days" in lad.date_check("2026-10-05", [u])[1]      # one past it


def test_date_check_without_images_or_date():
    assert lad.date_check("2026-10-02", []) == (None, None)
    u = "https://media.licdn.com/a/b/0/1790906409754?e=1"
    first, warning = lad.date_check(None, [u])
    assert first and warning is None


# ------------------------------------------------------------------ images

@pytest.mark.parametrize("u,role", [
    ("https://media.licdn.com/dms/image/v2/X/article-cover_image-shrink_720_1280/Y/0/1?e=1", "cover"),
    ("https://media.licdn.com/dms/image/v2/X/article-inline_image-shrink_1000_1488/Y/0/1?e=1", "inline"),
    ("https://media.licdn.com/dms/image/v2/X/profile-displayphoto-shrink_200_200/Y/0/1?e=1", None),
    ("https://media.licdn.com/dms/image/v2/X/feedshare-shrink_800/Y/0/1?e=1", None),
    ("", None),
])
def test_image_role(u, role):
    assert lad.image_role(u) == role


def test_image_filenames_are_stable_and_safe():
    assert lad.image_filename("Defensibility-AI_Data-6vsuc", "cover", 0) == \
        "linkedin-defensibility-ai-data-6vsuc-cover.jpg"
    assert lad.image_filename("a-b", "inline", 2) == "linkedin-a-b-2.jpg"


# ------------------------------------------------------------------ validate

def test_validate_rejects_error_empty_and_short_bodies():
    assert lad.validate(None) == ["extractor returned nothing"]
    assert lad.validate({"error": "no <article> on page"}) == ["no <article> on page"]
    short = {"title": "T", "blocks": [{"type": "paragraph", "text": "Sign in to view"}]}
    assert "likely a login wall" in lad.validate(short)[0]
    untitled = {"title": "", "blocks": [{"type": "paragraph", "text": "x" * 400}]}
    assert lad.validate(untitled) == ["no article title (<h1>) found"]


def test_validate_boundary_min_body_chars():
    ok = {"title": "T", "blocks": [{"type": "paragraph", "text": "x" * lad.MIN_BODY_CHARS}]}
    short = {"title": "T", "blocks": [{"type": "paragraph", "text": "x" * (lad.MIN_BODY_CHARS - 1)}]}
    assert lad.validate(ok) == []
    assert lad.validate(short)


def test_body_chars_counts_list_items():
    assert lad.body_chars([{"type": "list", "items": ["ab", "cde"]},
                           {"type": "paragraph", "text": "f"}, {"type": "image", "src": "u"}]) == 6


# ------------------------------------------------------------------ render

def test_render_keeps_order_levels_and_falls_back_to_url_for_failed_images():
    data = {"title": "T", "author_name": "A", "author_headline": "H", "published_label": "Oct 2, 2026",
            "cover": "C", "blocks": [
                {"type": "heading", "level": 2, "text": "Intro"},
                {"type": "paragraph", "text": "p1"},
                {"type": "image", "src": "I1", "alt": "chart", "caption": "Fig 1"},
                {"type": "list", "ordered": True, "items": ["one", "two"]},
                {"type": "list", "ordered": False, "items": ["x"]},
                {"type": "quote", "text": "q1\nq2"},
                {"type": "heading", "level": 3, "text": "Sub"},
                {"type": "image", "src": "I2", "alt": "", "caption": ""},
            ]}
    md = lad.render_markdown(data, {"C": "c.jpg", "I1": "1.jpg"})
    assert md.startswith("# T\n\n*A · H · Oct 2, 2026*\n\n![cover](c.jpg)\n")
    assert md.count("\n# ") == 0                      # the title is the only h1
    order = ["## Intro", "p1", "![chart](1.jpg)", "*Fig 1*", "1. one\n2. two", "- x",
             "> q1\n> q2", "### Sub", "![image](I2)"]
    pos = [md.index(s) for s in order]
    assert pos == sorted(pos)
    assert "[[" not in md                             # no vault syntax in a fetch layer


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
const [html, js] = process.argv.slice(1).map(p => fs.readFileSync(p, 'utf8'));
const dom = new JSDOM(html, {url: 'https://www.linkedin.com/pulse/x/', runScripts: 'outside-only'});
dom.window.eval(js);
process.stdout.write(JSON.stringify({
  data: dom.window.__liArticle.extract(),
  pending: dom.window.__liArticle.imagesPending(),
  unwrap: [
    dom.window.__liArticle.unwrapLink('https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fskool.com%2Ftec%2Fabout&urlhash=x'),
    dom.window.__liArticle.unwrapLink('https://www.linkedin.com/safety/go/?url=http%3A%2F%2FCLAUDE.md'),
    dom.window.__liArticle.unwrapLink('http://'),
  ],
}));
"""


@pytest.fixture(scope="module")
def extracted():
    node, path = shutil.which("node"), _jsdom_path()
    if not node or not path:
        pytest.skip("node + jsdom not found; set MSTACK_JSDOM_NODE_PATH to a node_modules dir with jsdom")
    r = subprocess.run([node, "-e", _HARNESS, str(FIXTURE), str(EXTRACTION_JS)],
                       capture_output=True, text=True, env={**os.environ, "NODE_PATH": path}, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_header_fields(extracted):
    d = extracted["data"]
    assert d["title"] == "Defensibility in AI Data: Lessons from Ads"
    assert d["author_name"] == "Gokul Rajaram"
    assert d["author_headline"] == "Investor and Company Helper"
    assert d["author_url"] == "https://www.linkedin.com/in/gokulrajaram1"
    assert d["published_label"] == "October 2, 2026"
    assert "/article-cover_image-" in d["cover"]


def test_metrics_come_from_aria_labels(extracted):
    assert extracted["data"]["metrics"] == {"reactions": 37, "comments": 4, "reposts": None}


def test_body_is_17_ordered_blocks_with_the_image_before_the_ps(extracted):
    blocks = extracted["data"]["blocks"]
    assert [b["type"] for b in blocks] == ["paragraph"] * 15 + ["image", "paragraph"]
    assert blocks[0]["text"].startswith("Companies selling data / expertise / RL environments")
    assert blocks[14]["text"].endswith("(inevitably) commoditized.")
    assert blocks[16]["text"].startswith("PS: If you're a founder")


def test_inline_image_is_kept_and_cover_is_not_a_body_block(extracted):
    imgs = [b for b in extracted["data"]["blocks"] if b["type"] == "image"]
    assert len(imgs) == 1
    assert "/article-inline_image-" in imgs[0]["src"]
    assert imgs[0]["alt"] == "Article content"
    assert extracted["pending"] == 0


def test_bold_run_ins_keep_their_separating_space(extracted):
    texts = [b.get("text", "") for b in extracted["data"]["blocks"]]
    assert texts[10].startswith("1. **Own differentiated supply:** Google and Facebook")
    assert texts[11].startswith("2. **Become part of the customer’s workflow:** Doubleclick")
    assert texts[12].startswith("3. **Build self-improving environments:** Invest in technology")
    import re
    assert not re.search(r":\*\*\S", " ".join(texts))  # no `**label:**Word` fusion anywhere


def test_body_text_matches_the_live_page_verbatim(extracted):
    # 6,119 characters of body text, whitespace-normalised, as measured on the live page
    import re
    joined = " ".join(b["text"] for b in extracted["data"]["blocks"] if b["type"] == "paragraph")
    plain = re.sub(r"\s+", " ", joined.replace("**", "")).strip()
    assert len(plain) == 6119


def test_article_with_no_links_returns_empty_and_unwrap_works(extracted):
    assert extracted["data"]["links"] == []
    ok, filename_host, junk = extracted["unwrap"]
    assert ok == "https://skool.com/tec/about"       # proves an empty list is not a dead path
    assert filename_host == ""
    assert junk == ""                                 # unparseable -> dropped, not thrown
