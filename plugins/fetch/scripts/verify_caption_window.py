#!/usr/bin/env python3
"""
Verify (re-transcribe) specific time windows of a YouTube video with Whisper.

YouTube auto-captions silently drop words — especially numbers in Q&A — which
produces confidently-wrong summaries. youtube_transcript_extractor.py flags the
suspect windows in its `caption_warnings`; this script recovers the real words
for just those windows from the audio, instead of re-transcribing the whole
video.

Audio is downloaded ONCE (via the android client, which bypasses YouTube's
SABR/DRM/PO-token wall), then each window is clipped with ffmpeg and Whispered.

Usage:
    verify_caption_window.py <url> --windows 670-730,1100-1140 [--model small]

    # windows may also be given as M:SS-M:SS
    verify_caption_window.py <url> --windows 11:10-12:10

Output (stdout): JSON
    {"windows": [{"start": 670, "end": 730, "text": "..."}], ...}
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Reuse the extractor's video-id parsing and the (android-client) audio download.
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from whisper_transcriber import extract_video_id, download_audio  # noqa: E402


def _parse_window(token: str) -> tuple[int, int]:
    """Parse 'START-END' where each side is seconds (670) or M:SS (11:10)."""
    def to_seconds(s: str) -> int:
        s = s.strip()
        if ':' in s:
            m, sec = s.split(':', 1)
            return int(m) * 60 + int(sec)
        return int(s)

    start_s, end_s = token.split('-', 1)
    start, end = to_seconds(start_s), to_seconds(end_s)
    if end <= start:
        raise ValueError(f"window end must be after start: {token!r}")
    return start, end


def clip_audio(audio_path: Path, start: int, end: int, out_dir: Path) -> Path:
    """Extract [start, end) from audio as 16 kHz mono WAV (Whisper-friendly)."""
    out = out_dir / f"clip_{start}_{end}.wav"
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-t", str(end - start),
        "-i", str(audio_path),
        "-ar", "16000", "-ac", "1",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"ffmpeg clip failed: {result.stderr[-500:]}")
    return out


def whisper_clip(clip_path: Path, model: str, language: str, out_dir: Path) -> str:
    """Transcribe a clip to plain text."""
    cmd = [
        "whisper", str(clip_path),
        "--model", model,
        "--language", language,
        "--output_format", "txt",
        "--output_dir", str(out_dir),
        "--fp16", "False",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"whisper failed: {result.stderr[-500:]}")
    txt_path = out_dir / (clip_path.stem + ".txt")
    if not txt_path.exists():
        raise RuntimeError("whisper produced no text output")
    # Collapse to a single clean paragraph.
    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    return re.sub(r'\s+', ' ', text).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-transcribe specific YouTube time windows with Whisper.")
    ap.add_argument("url", help="YouTube URL or video ID")
    ap.add_argument("--windows", required=True,
                    help="Comma-separated START-END windows (seconds or M:SS), e.g. 670-730,11:10-12:10")
    ap.add_argument("--model", default="small", help="Whisper model (tiny/base/small/medium/large)")
    ap.add_argument("--language", default="en", help="Language code (default: en)")
    ap.add_argument("--cookies", help="Netscape-format cookies file (optional)")
    args = ap.parse_args()

    try:
        windows = [_parse_window(w) for w in args.windows.split(",") if w.strip()]
    except ValueError as e:
        print(f"Invalid --windows: {e}", file=sys.stderr)
        sys.exit(2)
    if not windows:
        print("No windows given", file=sys.stderr)
        sys.exit(2)

    video_id = extract_video_id(args.url)

    with tempfile.TemporaryDirectory(prefix=f"verify_{video_id}_") as td:
        tmp = Path(td)
        print(f"Downloading audio for {video_id} (android client)...", file=sys.stderr)
        audio = download_audio(video_id, tmp, args.cookies)

        out_windows = []
        for start, end in windows:
            print(f"Re-transcribing {start // 60}:{start % 60:02d}-{end // 60}:{end % 60:02d} "
                  f"with Whisper ({args.model})...", file=sys.stderr)
            clip = clip_audio(audio, start, end, tmp)
            text = whisper_clip(clip, args.model, args.language, tmp)
            out_windows.append({"start": start, "end": end, "text": text})

    print(json.dumps({"video_id": video_id, "windows": out_windows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
