#!/usr/bin/env python3
"""
Extract the on-screen slides of a video: prediction tables, charts, decks.

A transcript says "this is my screenshot" and the note ends up without it. This
script downloads the video, samples small grey frames at a fixed interval,
keeps the frames that look like slides, and exports the most complete copy of
each distinct slide at source resolution.

Three properties of real videos decide the design (measured on a Chariot
Palmistry video; docs/plans/2026-10-10-youtube-slides.md §5):

- Slides are flat. On a 160x90 grey thumbnail, the most common of 16 luminance
  bins covers 0.64-0.94 of a slide frame and 0.28-0.34 of a talking head.
- Slides build up. Lines are revealed one at a time and annotations are drawn
  on, so the best copy is the one with the most ink, not the first frame.
- Slides come back. A slide shown three times is one slide with three
  appearances, decided by whether the sparser frame's ink lies inside the
  denser one's.

Scene-change detection is not used: it misses dissolves and a slide that is on
screen from the first second, because there is no cut to detect.

Usage:
    youtube_slides.py <url> [output_dir] [--interval 1.0]
    youtube_slides.py --video local.mp4 [output_dir]

Output: <output_dir>/slides/NN-mmss.png, contact_sheet.png, slides.json.
The final stdout line is OUTPUT_DIR:<path>, also when no slides were found.
Nothing is printed on stdout on failure.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from whisper_transcriber import resolve_source, source_ident  # noqa: E402

ANALYSIS_WIDTH = 160
ANALYSIS_HEIGHT = 90
FLAT_MIN = 0.50    # dominant-bin share at or above which a frame is slide-like
INK_MIN = 0.01     # below this the frame is blank (a white fade), not a slide
INK_DELTA = 48     # a pixel is ink when it differs from the background by MORE than this
SAME_MIN = 0.80    # containment at or above which two frames are the same slide
MIN_RUN_SECONDS = 2.0  # shorter runs are dissolves between a talking head and a slide
BINS = 16

# Tried in order. The default clients are often refused by YouTube's SABR
# experiment (HTTP 403); android still serves a plain stream, at 360p.
CLIENTS = ("web_safari", "tv", "android")
VIDEO_FORMAT = "bv*[height<=1080]/b[height<=1080]/b"

_CUE_PATTERNS = [
    ("screenshot", re.compile(r"\bscreenshots?\b", re.I)),
    ("on screen", re.compile(r"\bon (?:the |my |your |this )?screen\b", re.I)),
    ("slide", re.compile(r"\b(?:this|next|the|my|that|previous) slides?\b", re.I)),
    ("as you can see", re.compile(r"\bas you can see\b", re.I)),
    ("chart", re.compile(r"\b(?:this|the|my|that|a) (?:chart|graph|table|diagram)s?\b", re.I)),
    ("you'll notice", re.compile(r"\byou(?:'ll| will) notice\b", re.I)),
    ("let me show you", re.compile(r"\blet me show you\b", re.I)),
]
_TS_LINE = re.compile(r"^\s*(\d{1,2}(?::\d{2}){1,2})\s+(.*)$")


@dataclass(frozen=True)
class FrameFeatures:
    flat: float        # share of pixels in the dominant luminance bin
    ink: float         # share of pixels more than INK_DELTA from the background
    background: int    # centre of the dominant bin


@dataclass(frozen=True)
class Sample:
    t: float
    frame: bytes
    features: FrameFeatures


@dataclass(frozen=True)
class Run:
    samples: tuple[Sample, ...]


@dataclass(frozen=True)
class Slide:
    best: Sample
    appearances: tuple[tuple[float, float], ...]


# --- transcript cues ------------------------------------------------------

def parse_timestamp(token: str) -> int | None:
    """Seconds for `m:ss` or `h:mm:ss`; None for anything else."""
    parts = token.strip().split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + int(p)
    return seconds


def find_slide_cues(transcript: str) -> list[dict]:
    """Transcript lines that point at something on screen, one entry per line.

    Auto-captions break lines mid-phrase ("as you can" / "see"), so each line is
    searched together with the next one. A match belongs to the line it starts in.
    """
    lines = []
    for raw in (transcript or "").splitlines():
        m = _TS_LINE.match(raw)
        seconds = parse_timestamp(m.group(1)) if m else None
        if seconds is not None:
            lines.append((seconds, m.group(2).strip()))
    cues = []
    for i, (seconds, text) in enumerate(lines):
        window = text + (" " + lines[i + 1][1] if i + 1 < len(lines) else "")
        for phrase, pattern in _CUE_PATTERNS:
            hit = pattern.search(window)
            if hit and hit.start() < len(text):
                cues.append({"seconds": seconds, "phrase": phrase, "line": text})
                break
    return cues


# --- frame analysis -------------------------------------------------------

def frame_features(frame: bytes, width: int) -> FrameFeatures:
    if not frame or len(frame) % width:
        raise ValueError(f"frame of {len(frame)} bytes is not a whole number of {width}-pixel rows")
    hist = Counter(p // (256 // BINS) for p in frame)
    dominant, count = max(hist.items(), key=lambda kv: (kv[1], kv[0]))
    background = dominant * (256 // BINS) + (256 // BINS) // 2
    values = Counter(frame)
    ink = sum(c for v, c in values.items() if abs(v - background) > INK_DELTA)
    return FrameFeatures(flat=count / len(frame), ink=ink / len(frame), background=background)


def is_slide(f: FrameFeatures) -> bool:
    return f.flat >= FLAT_MIN and f.ink >= INK_MIN


def ink_mask(frame: bytes, background: int) -> frozenset[int]:
    return frozenset(i for i, p in enumerate(frame) if abs(p - background) > INK_DELTA)


def containment(small: frozenset[int], big: frozenset[int], width: int) -> float:
    """Share of `small` lying within one pixel (8-neighbourhood) of `big`."""
    if not small:
        return 1.0
    near = set()
    for i in big:
        row, col = divmod(i, width)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                c = col + dc
                if 0 <= c < width:
                    near.add((row + dr) * width + c)
    return sum(1 for i in small if i in near) / len(small)


def same_slide(a: Sample, b: Sample, width: int) -> bool:
    ma = ink_mask(a.frame, a.features.background)
    mb = ink_mask(b.frame, b.features.background)
    small, big = (ma, mb) if len(ma) <= len(mb) else (mb, ma)
    return containment(small, big, width) >= SAME_MIN


def group_runs(samples: list[Sample], width: int) -> list[Run]:
    runs: list[list[Sample]] = []
    current: list[Sample] = []
    for s in samples:
        if not is_slide(s.features):
            if current:
                runs.append(current)
            current = []
        elif current and not same_slide(current[-1], s, width):
            runs.append(current)
            current = [s]
        else:
            current.append(s)
    if current:
        runs.append(current)
    return [Run(samples=tuple(r)) for r in runs]


def drop_transients(runs: list[Run], interval: float) -> list[Run]:
    """Drop runs shorter than MIN_RUN_SECONDS (inclusive keep at exactly the minimum).

    A dissolve from a talking head into a slide blends both, so for one sample it
    looks like a slide with extra ink. Real slides stay on screen for seconds.
    """
    return [r for r in runs if len(r.samples) * interval >= MIN_RUN_SECONDS]


def best_sample(run: Run) -> Sample:
    """The interior sample with the most ink; a tie goes to the later sample.

    The first and last samples of a run of three or more are skipped: they are
    where dissolves sit, and a blend of slide and talking head has more ink
    than the slide alone.
    """
    pool = run.samples[1:-1] if len(run.samples) >= 3 else run.samples
    best = pool[0]
    for s in pool[1:]:
        if s.features.ink >= best.features.ink:
            best = s
    return best


def merge_repeats(runs: list[Run], width: int, interval: float) -> list[Slide]:
    """One Slide per distinct slide, in first-appearance order."""
    slides: list[tuple[Sample, list[tuple[float, float]]]] = []
    for run in runs:
        rep = best_sample(run)
        span = (run.samples[0].t, run.samples[-1].t + interval)
        for i, (best, spans) in enumerate(slides):
            if same_slide(best, rep, width):
                spans.append(span)
                if rep.features.ink >= best.features.ink:
                    slides[i] = (rep, spans)
                break
        else:
            slides.append((rep, [span]))
    return [Slide(best=b, appearances=tuple(s)) for b, s in slides]


# --- download and sampling ------------------------------------------------

def build_download_argv(url: str, client: str, out: Path) -> list[str]:
    return [
        "yt-dlp", "--no-playlist", "--quiet", "--no-warnings",
        "--remote-components", "ejs:github",
        "--extractor-args", f"youtube:player_client={client}",
        "-f", VIDEO_FORMAT,
        "-o", str(out),
        url,
    ]


def download_video(url: str, out_dir: Path, run=subprocess.run) -> Path:
    """Download the video with the first client that produces a file."""
    errors = []
    for client in CLIENTS:
        argv = build_download_argv(url, client, out_dir / f"video-{client}.%(ext)s")
        result = run(argv, capture_output=True, text=True)
        produced = [p for p in out_dir.glob(f"video-{client}.*")
                    if p.suffix not in (".part", ".ytdl")]
        if result.returncode == 0 and produced:
            print(f"Downloaded with the {client} client: {produced[0].name}", file=sys.stderr)
            return produced[0]
        last = (result.stderr or "").strip().splitlines()[-1:] or ["no file written"]
        errors.append(f"{client}: {last[0]}")
    raise RuntimeError("every client failed — " + "; ".join(errors))


def sample_frames(video: Path, interval: float, run=subprocess.run) -> list[Sample]:
    """One grey analysis frame every `interval` seconds, from a single ffmpeg pass."""
    argv = [
        "ffmpeg", "-v", "error", "-i", str(video),
        "-vf", f"fps=1/{interval},scale={ANALYSIS_WIDTH}:{ANALYSIS_HEIGHT}:flags=area,format=gray",
        "-f", "rawvideo", "-",
    ]
    result = run(argv, capture_output=True)
    if result.returncode != 0:
        tail = (result.stderr or b"").decode("utf-8", "replace")[-500:]
        raise RuntimeError(f"ffmpeg sampling failed: {tail}")
    size = ANALYSIS_WIDTH * ANALYSIS_HEIGHT
    raw = result.stdout
    samples = []
    for k in range(len(raw) // size):
        frame = raw[k * size:(k + 1) * size]
        samples.append(Sample(t=k * interval, frame=frame,
                              features=frame_features(frame, ANALYSIS_WIDTH)))
    return samples


def probe_height(video: Path, run=subprocess.run) -> int | None:
    result = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=height", "-of", "csv=p=0", str(video)],
                 capture_output=True, text=True)
    value = (result.stdout or "").strip().splitlines()[:1]
    return int(value[0]) if result.returncode == 0 and value and value[0].isdigit() else None


# --- export ---------------------------------------------------------------

def _mmss(t: float) -> str:
    whole = int(t)
    return f"{whole // 60:02d}{whole % 60:02d}"


def export_slides(video: Path, slides: list[Slide], out_dir: Path,
                  run=subprocess.run) -> list[dict]:
    """Write one full-resolution PNG per slide and a contact sheet."""
    slide_dir = out_dir / "slides"
    slide_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for n, slide in enumerate(slides, 1):
        name = f"{n:02d}-{_mmss(slide.best.t)}.png"
        result = run(["ffmpeg", "-v", "error", "-y", "-ss", f"{slide.best.t:.3f}",
                      "-i", str(video), "-frames:v", "1", str(slide_dir / name)],
                     capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg frame export failed at {slide.best.t}s: {result.stderr[-300:]}")
        entries.append({
            "index": n,
            "file": f"slides/{name}",
            "t": slide.best.t,
            "appearances": [list(a) for a in slide.appearances],
            "ink": round(slide.best.features.ink, 4),
        })
    if entries:
        columns = min(3, len(entries))
        rows = -(-len(entries) // columns)
        result = run(["ffmpeg", "-v", "error", "-y", "-pattern_type", "glob",
                      "-i", str(slide_dir / "*.png"),
                      "-vf", f"scale=480:-2,tile={columns}x{rows}", "-frames:v", "1",
                      str(out_dir / "contact_sheet.png")],
                     capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg contact sheet failed: {result.stderr[-300:]}")
    return entries


def extract_slides(video: Path, out_dir: Path, interval: float = 1.0,
                   video_id: str | None = None) -> dict:
    """Offline pipeline over a local video. Writes slides.json and returns it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = sample_frames(video, interval)
    runs = drop_transients(group_runs(samples, ANALYSIS_WIDTH), interval)
    slides = merge_repeats(runs, ANALYSIS_WIDTH, interval)
    doc = {
        "video_id": video_id or video.stem,
        "source_height": probe_height(video),
        "interval": interval,
        "samples": len(samples),
        "slides": export_slides(video, slides, out_dir),
    }
    (out_dir / "slides.json").write_text(json.dumps(doc, indent=2))
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract on-screen slides from a video.")
    ap.add_argument("url", nargs="?", help="YouTube (or other yt-dlp) URL")
    ap.add_argument("output_dir", nargs="?", help="output directory (default: a temp dir)")
    ap.add_argument("--video", help="use a local video file instead of downloading")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between samples (default 1.0)")
    args = ap.parse_args()

    if not args.url and not args.video:
        ap.print_usage(sys.stderr)
        print("error: give a URL or --video", file=sys.stderr)
        sys.exit(2)
    if args.interval <= 0:
        print("error: --interval must be positive", file=sys.stderr)
        sys.exit(2)

    if args.video:
        video, video_id = Path(args.video), Path(args.video).stem
        out_dir = Path(args.output_dir or args.url or tempfile.mkdtemp(prefix=f"slides_{video_id}_"))
    else:
        kind, url = resolve_source(args.url)
        video_id = source_ident(kind, url)
        out_dir = Path(args.output_dir or tempfile.mkdtemp(prefix=f"slides_{video_id}_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            video = download_video(url, out_dir)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    doc = extract_slides(video, out_dir.resolve(), args.interval, video_id)
    height = doc["source_height"]
    print(f"slides: {len(doc['slides'])} from {doc['samples']} samples, "
          f"source {height}p" + (" (low resolution: small text may be unreadable)"
                                 if height and height < 720 else ""), file=sys.stderr)
    print(f"OUTPUT_DIR:{out_dir.resolve()}")


if __name__ == "__main__":
    main()
