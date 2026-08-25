#!/usr/bin/env python3
"""Deterministic transcript cleaner.

Verbatim by construction: this script only DELETES timestamps and noise
markers and INSERTS whitespace, chapter headings, and (when speaker names are
supplied) bold markers around labels already present in the text. It never
rewrites a word, so the output is provably the same token stream as the input
minus deliberate deletions.

That guarantee is the whole point. Prose instructions asking a model to "be
verbatim" cannot be checked; this can — see tests/test_clean.py.

Usage:
    clean.py RAW.txt OUT.md [META.json] [--speakers "Name One,Name Two"]

Prints progress to stderr and OUTPUT_FILE:<path> as the final stdout line.
"""

import argparse
import json
import os
import re
import sys

# A timestamp opening a line: mm:ss or hh:mm:ss. Group count decides which —
# never magnitude, so 62:33 is 3753s (mm:ss) and 1:02:33 is also 3753s.
TS = re.compile(r"^(\d{1,3}):(\d{2})(?::(\d{2}))?\s*")

NOISE = re.compile(
    r"\[(music|laughter|applause|snorts|inaudible|silence|crosstalk|"
    r"side conversation)\]\s*",
    re.I,
)

PARA_MIN_CHARS = 700
SENT_END = (".", "?", "!", '"', "”")

# Corruption signatures. caption_warnings (in fetch:youtube-transcript) detects
# figures the caption OMITTED; it cannot see one it MANGLED. These do.
# Real cases seen: "$und00" for "$1,050", "a,50" for "1,050".
CORRUPTION = [
    (re.compile(r"[$€£¥](?!\s*[\d.])"), "currency symbol not followed by a digit"),
    (re.compile(r"\b[A-Za-z]+,\d"), "letters immediately before a comma-number"),
    (re.compile(r"\d,[A-Za-z]"), "digits immediately before comma-letters"),
]


def parse(raw):
    """Raw text -> [(seconds, text)], noise stripped, empties dropped."""
    segs = []
    for line in raw.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        m = TS.match(line)
        if m:
            a, mm, ss = m.groups()
            secs = int(a) * 60 + int(mm) if ss is None else int(a) * 3600 + int(mm) * 60 + int(ss)
            segs.append([secs, line[m.end():].strip()])
        elif segs:
            # Continuation of the previous timed segment, not a new one.
            segs[-1][1] += " " + line.strip()
        else:
            # Text before any timestamp: one segment at t=0.
            segs.append([0, line.strip()])

    out = []
    for secs, text in segs:
        text = re.sub(r"\s+", " ", NOISE.sub("", text)).strip()
        if text:  # a noise-only line leaves nothing; drop it rather than
            out.append((secs, text))  # emitting an empty paragraph
    return out


def label_speakers(text, speakers):
    """Bold speaker labels that are ALREADY in the text. Never add one."""
    if not speakers:
        return text
    for name in speakers:
        # Match the name followed by a colon, at a segment or sentence start.
        pat = re.compile(
            r"(?<![*\w])(" + re.escape(name) + r")\s*:",
            re.I,
        )
        text = pat.sub(lambda m: f"**{m.group(1)}:**", text)
    return text


def scan_corruption(text):
    """Return [(signature, snippet)] for mangled-looking numeric tokens."""
    hits = []
    for pat, why in CORRUPTION:
        for m in pat.finditer(text):
            s = max(0, m.start() - 30)
            hits.append((why, text[s:m.end() + 30].replace("\n", " ")))

    # '%' whose nearest preceding non-space character is not a digit.
    for m in re.finditer(r"%", text):
        before = text[:m.start()].rstrip()
        if not before or not before[-1].isdigit():
            s = max(0, m.start() - 30)
            hits.append(("percent sign with no preceding digit",
                         text[s:m.end() + 30].replace("\n", " ")))
    return hits


def emit(segs, chapters, speakers=None):
    chapters = sorted(chapters, key=lambda c: c["start"])
    ci = 0
    parts, buf, buf_len = [], [], 0

    def flush():
        nonlocal buf, buf_len
        if buf:
            parts.append(" ".join(buf))
            buf, buf_len = [], 0

    for secs, text in segs:
        # start-inclusive: a segment exactly at chapters[ci].start falls UNDER
        # that heading, not the one before it.
        while ci < len(chapters) and secs >= chapters[ci]["start"]:
            flush()
            parts.append("## " + chapters[ci]["title"])
            ci += 1
        buf.append(text)
        buf_len += len(text) + 1
        # Both conditions required: a long run with no sentence terminator
        # stays one paragraph rather than being cut mid-sentence.
        if buf_len >= PARA_MIN_CHARS and text.endswith(SENT_END):
            flush()
    flush()

    body = "\n\n".join(p.strip("\n") for p in parts if p.strip())
    body = label_speakers(body, speakers)
    return body + "\n" if body else ""


def load_chapters(path):
    try:
        meta = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        # Do NOT fall back to zero chapters — that looks like success while
        # silently dropping the entire chapter structure.
        sys.exit(f"clean.py: cannot read chapters from {path}: {e}")

    chapters = []
    for i, c in enumerate(meta.get("chapters") or []):
        if "start_time" not in c and "seconds" not in c:
            sys.exit(
                f"clean.py: chapter {i} ({c.get('title', '<untitled>')!r}) "
                f"has neither 'start_time' nor 'seconds'"
            )
        chapters.append({
            "start": int(c.get("start_time", c.get("seconds"))),
            "title": c.get("title", f"Chapter {i + 1}"),
        })
    return chapters


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw", help="raw transcript text file")
    ap.add_argument("out", help="cleaned markdown output path")
    ap.add_argument("meta", nargs="?", help="JSON with a 'chapters' array")
    ap.add_argument("--speakers", default="",
                    help="comma-separated names whose existing labels to bold")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.raw):
        sys.exit(f"clean.py: no such file: {args.raw}")

    raw = open(args.raw, encoding="utf-8").read()
    chapters = load_chapters(args.meta) if args.meta else []
    speakers = [s.strip() for s in args.speakers.split(",") if s.strip()]

    segs = parse(raw)
    body = emit(segs, chapters, speakers)

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(body)

    print(f"segments: {len(segs)}", file=sys.stderr)
    print(f"chapters inserted: {len(chapters)}", file=sys.stderr)
    print(f"chars out: {len(body)}", file=sys.stderr)

    hits = scan_corruption(body)
    if hits:
        print(f"\n⚠ Corruption scan: {len(hits)} suspect token(s). A figure may "
              f"have been MANGLED, which caption_warnings cannot detect. "
              f"Re-transcribe these windows before quoting them:", file=sys.stderr)
        for why, snippet in hits[:10]:
            print(f"   {why}: …{snippet}…", file=sys.stderr)

    print(f"OUTPUT_FILE:{os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
