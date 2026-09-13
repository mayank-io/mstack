#!/usr/bin/env python3
"""
Whisper Transcriber

Downloads audio with yt-dlp and transcribes it with Whisper. Used standalone, or
as the last-resort tier when a native YouTube transcript is unavailable.

Host-agnostic. yt-dlp carries several hundred extractors, so any page it can
pull audio from can be transcribed here: YouTube, x.com, Vimeo. YouTube needs
two workarounds (see download_audio) that must NOT follow a generic URL, which
is what resolve_source() classifies for.

No browser: yt-dlp fetches the audio directly. Member-only videos need a cookie
jar, which youtube_downloader.py exports from the headed gstack
session and passes in via --cookies. There was never a --chrome-profile option;
the docstring advertised one for months.

Usage:
    python3 whisper_transcriber.py <url_or_youtube_id> [--model medium]
        [--backend whisper|mlx] [--language auto] [--cookies PATH] [--audio PATH]

Output:
    Prints path to JSON file with transcript in same format as youtube_downloader.py
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


_YOUTUBE_ID = re.compile(r'^[a-zA-Z0-9_-]{11}$')
_YOUTUBE_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be", "www.youtu.be",
})
_YOUTUBE_ID_IN_URL = (
    r'[?&]v=([a-zA-Z0-9_-]{11})',
    r'youtu\.be/([a-zA-Z0-9_-]{11})',
    r'embed/([a-zA-Z0-9_-]{11})',
    r'/shorts/([a-zA-Z0-9_-]{11})',
)


def resolve_source(url_or_id: str) -> tuple[str, str]:
    """Classify a video source and return (kind, url).

    kind is "youtube" for YouTube hosts and for a bare 11-character video id;
    "generic" for every other host, whose URL is handed to yt-dlp untouched.

    This exists so the YouTube-only workarounds in download_audio() do not
    follow a non-YouTube URL. Passing --extractor-args youtube:... to an x.com
    URL is not merely useless: it is the kind of silent mismatch that makes a
    failed fetch look like a source with no audio.
    """
    raw = url_or_id.strip()
    if not raw:
        raise ValueError("Empty video source")

    # A bare YouTube id — 11 chars, no scheme, no path.
    if "/" not in raw and _YOUTUBE_ID.match(raw):
        return "youtube", f"https://www.youtube.com/watch?v={raw}"

    url = raw if "://" in raw else f"https://{raw}"
    host = urlparse(url).hostname or ""
    kind = "youtube" if host.lower() in _YOUTUBE_HOSTS else "generic"
    return kind, url


def source_ident(kind: str, url: str) -> str:
    """A filesystem-safe identifier for a source, for temp and output filenames.

    YouTube keeps its real 11-character video id so existing output paths and
    the caption-verification workflow stay recognisable. Everything else is
    derived from host plus the last meaningful path segment, which for
    x.com/<handle>/status/<id> is the status id.
    """
    if kind == "youtube":
        for pattern in _YOUTUBE_ID_IN_URL:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

    parsed = urlparse(url)
    host = (parsed.hostname or "source").replace(".", "_")
    segments = [seg for seg in parsed.path.split("/") if seg]
    tail = segments[-1] if segments else ""
    ident = f"{host}_{tail}" if tail else host
    return re.sub(r'[^A-Za-z0-9_-]', '_', ident)[:80]


def download_audio(source: str, output_dir: Path, cookies_file: str | None = None) -> Path:
    """Download audio for any yt-dlp-supported URL (or bare YouTube id)."""
    kind, url = resolve_source(source)
    ident = source_ident(kind, url)
    output_path = output_dir / f"{ident}.%(ext)s"

    print(f"Downloading audio for {ident} ({kind})...", file=sys.stderr)

    cmd = [
        "yt-dlp",
        "-x",  # Extract audio
        "--audio-format", "mp3",
        "--audio-quality", "0",  # Best quality
        "-o", str(output_path),
        "--no-playlist",
        "--quiet",
        "--progress",
    ]

    if kind == "youtube":
        cmd += [
            "--remote-components", "ejs:github",  # Required for YouTube JS challenges
            # The default/web/ios/tv clients are blocked by YouTube's SABR/DRM and
            # PO-token experiments ("DRM protected" / "Requested format is not
            # available"). The android client still serves a plain audio stream and
            # needs no n-challenge solving, so prefer it first.
            "--extractor-args", "youtube:player_client=android,web,tv",
        ]

    # Use cookies file if provided (Netscape format)
    if cookies_file:
        cookies_path = Path(cookies_file).expanduser()
        if cookies_path.exists():
            print(f"Using cookies file: {cookies_path}", file=sys.stderr)
            cmd.extend(["--cookies", str(cookies_path)])

    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr}")

    # Find the downloaded file
    audio_file = output_dir / f"{ident}.mp3"
    if not audio_file.exists():
        # Try to find any audio file with the source identifier
        for ext in ['mp3', 'm4a', 'opus', 'webm']:
            candidate = output_dir / f"{ident}.{ext}"
            if candidate.exists():
                audio_file = candidate
                break

    if not audio_file.exists():
        raise RuntimeError(f"Audio file not found after download")

    print(f"Downloaded: {audio_file}", file=sys.stderr)
    return audio_file


BACKENDS = ("whisper", "mlx")


def detect_repetition_loops(transcript: str, threshold: float = 0.6) -> list[dict]:
    """Find segments where the decoder looped instead of transcribing speech.

    Whisper's best-known failure on long audio: it conditions on its own output,
    catches a phrase, and emits it for the rest of the file. The transcript
    still runs to the full duration and still reads as English, so every
    coverage check passes while the content is gone. One 53-minute lecture lost
    its last 11 minutes this way and looked complete.

    A loop takes two shapes and BOTH must be checked:

    1. Within one segment — "the crash of 1929" forty times in a single line.
       Measured as the fraction of repeated 4-grams.
    2. Across consecutive segments — "So this is a good question." emitted as
       24 separate short lines. Each line on its own is unremarkable prose and
       is far too short to measure 4-gram repetition on, so shape 1 misses it
       entirely. This was found the hard way: a transcript passed the per-line
       check and still had 24 duplicate segments in the middle of it.
    """
    lines = transcript.splitlines()
    suspects = []

    for line in lines:
        timestamp, _, text = line.partition(" ")
        words = text.split()
        if len(words) < 12:
            continue
        grams = [tuple(words[i:i + 4]) for i in range(len(words) - 3)]
        repeated = 1 - len(set(grams)) / len(grams)
        if repeated > threshold:
            suspects.append({"timestamp": timestamp, "repeated_fraction": round(repeated, 3),
                             "text": text[:120], "kind": "within-segment"})

    def norm(line):
        return re.sub(r"[^a-z0-9 ]", "", line.partition(" ")[2].lower()).strip()

    run_start, run_len = 0, 1
    for i in range(1, len(lines) + 1):
        same = (i < len(lines) and norm(lines[i]) and norm(lines[i]) == norm(lines[i - 1]))
        if same:
            run_len += 1
            continue
        if run_len >= 3:
            head = lines[run_start]
            suspects.append({"timestamp": head.partition(" ")[0], "repeated_fraction": 1.0,
                             "text": head.partition(" ")[2][:120],
                             "kind": "repeated-segment", "segments": run_len})
        run_start, run_len = i, 1

    suspects.sort(key=lambda s: lines.index(next(
        l for l in lines if l.startswith(s["timestamp"]))))
    return suspects


def mlx_model_repo(model: str) -> str:
    """Map a plain Whisper model name to its mlx-community Hugging Face repo.

    `--model medium` means the same size on both backends; only the address
    differs. A value that already names a repo or a local directory is passed
    through, so `--model mlx-community/whisper-large-v3-turbo` still works.
    """
    if "/" in model or os.path.isdir(model):
        return model
    name = model if model.startswith("whisper-") else f"whisper-{model}"
    return f"mlx-community/{name}"


def build_whisper_argv(audio_path: Path, model: str, language: str, output_dir: Path,
                       condition_on_previous_text: bool = True) -> list[str]:
    """argv for the reference openai-whisper CLI (underscored flag names)."""
    cmd = [
        "whisper",
        str(audio_path),
        "--model", model,
        "--output_format", "json",
        "--output_dir", str(output_dir),
        "--verbose", "False",
    ]

    if not condition_on_previous_text:
        cmd.extend(["--condition_on_previous_text", "False"])

    # Add language if not auto-detect
    if language and language != "auto":
        cmd.extend(["--language", language])

    return cmd


def build_mlx_argv(audio_path: Path, model: str, language: str, output_dir: Path,
                   condition_on_previous_text: bool = True) -> list[str]:
    """argv for mlx-whisper, run through uvx so nothing has to be installed.

    Two incompatibilities with the reference CLI, both silent if got wrong:
    flags are hyphenated (--output-format, not --output_format), and
    --language has no "auto" choice — auto-detection means omitting the flag,
    so passing our "auto" default through would be an argparse error.
    """
    cmd = [
        "uvx", "--from", "mlx-whisper", "mlx_whisper",
        str(audio_path),
        "--model", mlx_model_repo(model),
        "--output-format", "json",
        "--output-dir", str(output_dir),
        "--output-name", audio_path.stem,
        "--verbose", "False",
    ]

    if not condition_on_previous_text:
        cmd.extend(["--condition-on-previous-text", "False"])

    if language and language != "auto":
        cmd.extend(["--language", language])

    return cmd


def transcribe_with_whisper(audio_path: Path, model: str, language: str,
                            output_dir: Path, backend: str = "whisper",
                            condition_on_previous_text: bool = True) -> tuple[str, str]:
    """Transcribe audio with Whisper, via the reference CLI or mlx-whisper.

    Both backends write the same JSON schema, so the segment formatting below
    is shared rather than duplicated per backend.
    """
    if backend not in BACKENDS:
        raise ValueError(f"Unknown backend {backend!r}; expected one of {', '.join(BACKENDS)}")

    if backend == "mlx":
        if not shutil.which("uvx"):
            raise RuntimeError(
                "--backend mlx needs uvx (https://docs.astral.sh/uv/) on PATH. "
                "Refusing to fall back to a smaller model: a quieter transcript "
                "of a figures-dense source is worse than no transcript."
            )
        cmd = build_mlx_argv(audio_path, model, language, output_dir,
                             condition_on_previous_text)
    else:
        cmd = build_whisper_argv(audio_path, model, language, output_dir,
                                 condition_on_previous_text)

    print(f"Transcribing with Whisper (backend={backend}, model={model}, "
          f"language={language})...", file=sys.stderr)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Whisper failed ({backend}): {result.stderr}")

    # Find the output JSON file
    json_file = output_dir / f"{audio_path.stem}.json"
    if not json_file.exists():
        raise RuntimeError(f"Whisper output not found: {json_file}")

    # Read and parse the Whisper output
    with open(json_file) as f:
        whisper_data = json.load(f)

    return format_segments(whisper_data)


def format_segments(whisper_data: dict) -> tuple[str, str]:
    """Render Whisper segments as timestamped lines; return (transcript, language)."""
    # Convert Whisper format to our transcript format (with timestamps)
    transcript_lines = []
    for segment in whisper_data.get("segments", []):
        start_time = segment.get("start", 0)
        text = segment.get("text", "").strip()
        if text:
            # Format timestamp as M:SS or H:MM:SS
            hours = int(start_time // 3600)
            minutes = int((start_time % 3600) // 60)
            seconds = int(start_time % 60)

            if hours > 0:
                timestamp = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                timestamp = f"{minutes}:{seconds:02d}"

            transcript_lines.append(f"{timestamp} {text}")

    detected_language = whisper_data.get("language", "unknown")
    print(f"Detected language: {detected_language}", file=sys.stderr)
    print(f"Transcribed {len(transcript_lines)} segments", file=sys.stderr)

    return "\n".join(transcript_lines), detected_language


def get_video_metadata(url: str) -> dict:
    """Get video metadata using yt-dlp, for any supported host."""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {}

    try:
        data = json.loads(result.stdout)

        # Format duration
        duration_secs = data.get("duration", 0)
        hours = int(duration_secs // 3600)
        minutes = int((duration_secs % 3600) // 60)
        seconds = int(duration_secs % 60)

        if hours > 0:
            duration = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            duration = f"{minutes}:{seconds:02d}"

        return {
            "title": data.get("title", "Unknown Title"),
            "channel": data.get("channel", data.get("uploader", "Unknown Channel")),
            "duration": duration,
            "description": data.get("description", ""),
            "published_date": data.get("upload_date", ""),
            "thumbnail_url": data.get("thumbnail", ""),
            # Non-YouTube sources carry their author here; x.com gives the handle.
            "uploader_id": data.get("uploader_id", ""),
            "webpage_url": data.get("webpage_url", url),
            "source_id": data.get("id", ""),
            "duration_seconds": data.get("duration"),
        }
    except json.JSONDecodeError:
        return {}


def extract_chapters(description: str) -> list:
    """Extract chapter timestamps from description."""
    chapters = []
    patterns = [
        r'^(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]?\s*(.+)$',
        r'^\((\d{1,2}:\d{2}(?::\d{2})?)\)\s*(.+)$',
    ]

    for line in description.split('\n'):
        line = line.strip()
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                timestamp, title = match.groups()
                parts = timestamp.split(':')
                if len(parts) == 2:
                    seconds = int(parts[0]) * 60 + int(parts[1])
                else:
                    seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                chapters.append({
                    'timestamp': timestamp,
                    'seconds': seconds,
                    'title': title.strip()
                })
                break

    chapters.sort(key=lambda x: x['seconds'])
    return chapters


def main():
    parser = argparse.ArgumentParser(
        description='Transcribe any yt-dlp-supported video using Whisper')
    parser.add_argument('video',
                       help='Video URL (YouTube, x.com, Vimeo, …) or a bare YouTube ID')
    parser.add_argument('--model', default='medium',
                       help='Whisper model (tiny, base, small, medium, large, large-v3-turbo)')
    parser.add_argument('--backend', default='whisper', choices=list(BACKENDS),
                       help='whisper = reference CLI; mlx = mlx-whisper via uvx (Apple Silicon)')
    parser.add_argument('--language', default='auto',
                       help='Language code (e.g., en, hi, es) or "auto" for detection')
    parser.add_argument('--output', '-o', help='Output JSON file path')
    parser.add_argument('--audio',
                       help='Transcribe this local audio file instead of downloading. '
                            'Metadata is still read from the URL.')
    parser.add_argument('--no-condition-on-previous-text', action='store_true',
                       help='Disable decoder conditioning. The fix when a transcript '
                            'degenerates into a repeated phrase (see --help output of '
                            'the repetition warnings this script emits on stderr).')
    parser.add_argument('--keep-audio', action='store_true',
                       help='Keep the downloaded audio file')
    parser.add_argument('--cookies',
                       help='Path to Netscape format cookies file for YouTube (for member-only videos)')

    args = parser.parse_args()

    try:
        kind, url = resolve_source(args.video)
        ident = source_ident(kind, url)
        print(f"Source: {ident} ({kind}) -> {url}", file=sys.stderr)

        # Create temp directory for working files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Get metadata first
            print("Fetching video metadata...", file=sys.stderr)
            metadata = get_video_metadata(url)

            if metadata:
                print(f"Title: {metadata.get('title')}", file=sys.stderr)
                print(f"Channel: {metadata.get('channel')}", file=sys.stderr)
                print(f"Duration: {metadata.get('duration')}", file=sys.stderr)

            # Download audio, unless a local file was supplied. Re-transcribing
            # a long source with a different model should not re-download it.
            if args.audio:
                audio_file = Path(args.audio)
                if not audio_file.exists():
                    raise FileNotFoundError(f"--audio file not found: {audio_file}")
                print(f"Using local audio: {audio_file}", file=sys.stderr)
            else:
                audio_file = download_audio(url, temp_path, args.cookies)

            # Transcribe
            transcript, detected_lang = transcribe_with_whisper(
                audio_file, args.model, args.language, temp_path, args.backend,
                not args.no_condition_on_previous_text
            )

            # A looped transcript still runs the full duration and still reads
            # as English, so no length or coverage check catches it.
            loops = detect_repetition_loops(transcript)
            if loops:
                print(f"WARNING: {len(loops)} segment(s) look like a decoder "
                      f"repetition loop, first at {loops[0]['timestamp']}. "
                      f"Re-run with --no-condition-on-previous-text.", file=sys.stderr)
                for loop in loops[:3]:
                    print(f"  {loop['timestamp']} ({loop['repeated_fraction']:.0%} "
                          f"repeated) {loop['text']}", file=sys.stderr)

            # Extract chapters from description
            chapters = extract_chapters(metadata.get('description', ''))

            # Build result
            result = {
                **metadata,
                'url': url,
                'video_id': ident,
                'source_kind': kind,
                'language': detected_lang,
                'transcript': transcript,
                'chapters': chapters,
                'speakers': [],
                'transcription_method': f'whisper:{args.backend}',
                'whisper_model': args.model,
                'whisper_backend': args.backend,
                'condition_on_previous_text': not args.no_condition_on_previous_text,
                'repetition_warnings': loops,
            }

            # Determine output path
            if args.output:
                output_path = Path(args.output)
            else:
                output_path = Path(tempfile.gettempdir()) / f"yt_transcript_{ident}.json"

            # Write result
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            # Never report success on an empty transcription. Whisper can
            # return no segments — silent audio, a failed decode — and the
            # caller chaining on OUTPUT_FILE would write a note with no body.
            if not (result.get('transcript') or '').strip():
                print(f"ERROR: Whisper produced an empty transcript for "
                      f"{ident}. Metadata was written to {output_path}, but "
                      f"no OUTPUT_FILE marker is emitted.", file=sys.stderr)
                sys.exit(3)

            print(f"OUTPUT_FILE:{output_path}", file=sys.stderr)
            # contract: final stdout line is machine-parseable
            print(f"OUTPUT_FILE:{output_path}")

            # Optionally keep audio (a caller-supplied file is already durable)
            if args.keep_audio and not args.audio:
                final_audio = Path(tempfile.gettempdir()) / audio_file.name
                audio_file.rename(final_audio)
                print(f"Audio saved: {final_audio}", file=sys.stderr)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
