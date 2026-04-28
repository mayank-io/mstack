#!/usr/bin/env python3
"""
Whisper Transcriber

Downloads audio from YouTube using yt-dlp and transcribes using Whisper.
Can be used standalone or as a fallback when native YouTube transcripts are unavailable.

Usage:
    python3 whisper_transcriber.py <video_url_or_id> [--model medium] [--language auto] [--chrome-profile PATH]

Output:
    Prints path to JSON file with transcript in same format as youtube_transcript_extractor.py
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from YouTube URL or return as-is if already an ID."""
    # Already an ID (11 characters, alphanumeric with - and _)
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
        return url_or_id

    # Extract from URL
    patterns = [
        r'[?&]v=([a-zA-Z0-9_-]{11})',
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
        r'embed/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def download_audio(video_id: str, output_dir: Path, cookies_file: str | None = None) -> Path:
    """Download audio from YouTube using yt-dlp."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_path = output_dir / f"{video_id}.%(ext)s"

    print(f"Downloading audio for {video_id}...", file=sys.stderr)

    cmd = [
        "yt-dlp",
        "-x",  # Extract audio
        "--audio-format", "mp3",
        "--audio-quality", "0",  # Best quality
        "-o", str(output_path),
        "--no-playlist",
        "--quiet",
        "--progress",
        "--remote-components", "ejs:github",  # Required for YouTube JS challenges
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
    audio_file = output_dir / f"{video_id}.mp3"
    if not audio_file.exists():
        # Try to find any audio file with the video ID
        for ext in ['mp3', 'm4a', 'opus', 'webm']:
            candidate = output_dir / f"{video_id}.{ext}"
            if candidate.exists():
                audio_file = candidate
                break

    if not audio_file.exists():
        raise RuntimeError(f"Audio file not found after download")

    print(f"Downloaded: {audio_file}", file=sys.stderr)
    return audio_file


def transcribe_with_whisper(audio_path: Path, model: str, language: str, output_dir: Path) -> str:
    """Transcribe audio using Whisper CLI."""
    print(f"Transcribing with Whisper (model={model}, language={language})...", file=sys.stderr)

    cmd = [
        "whisper",
        str(audio_path),
        "--model", model,
        "--output_format", "json",
        "--output_dir", str(output_dir),
        "--verbose", "False",
    ]

    # Add language if not auto-detect
    if language and language != "auto":
        cmd.extend(["--language", language])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Whisper failed: {result.stderr}")

    # Find the output JSON file
    json_file = output_dir / f"{audio_path.stem}.json"
    if not json_file.exists():
        raise RuntimeError(f"Whisper output not found: {json_file}")

    # Read and parse the Whisper output
    with open(json_file) as f:
        whisper_data = json.load(f)

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


def get_video_metadata(video_id: str) -> dict:
    """Get video metadata using yt-dlp."""
    url = f"https://www.youtube.com/watch?v={video_id}"

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
            "thumbnail_url": data.get("thumbnail", f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"),
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
    parser = argparse.ArgumentParser(description='Transcribe YouTube video using Whisper')
    parser.add_argument('video', help='YouTube video URL or ID')
    parser.add_argument('--model', default='medium',
                       help='Whisper model (tiny, base, small, medium, large)')
    parser.add_argument('--language', default='auto',
                       help='Language code (e.g., en, hi, es) or "auto" for detection')
    parser.add_argument('--output', '-o', help='Output JSON file path')
    parser.add_argument('--keep-audio', action='store_true',
                       help='Keep the downloaded audio file')
    parser.add_argument('--cookies',
                       help='Path to Netscape format cookies file for YouTube (for member-only videos)')

    args = parser.parse_args()

    try:
        video_id = extract_video_id(args.video)
        print(f"Video ID: {video_id}", file=sys.stderr)

        # Create temp directory for working files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Get metadata first
            print("Fetching video metadata...", file=sys.stderr)
            metadata = get_video_metadata(video_id)

            if metadata:
                print(f"Title: {metadata.get('title')}", file=sys.stderr)
                print(f"Channel: {metadata.get('channel')}", file=sys.stderr)
                print(f"Duration: {metadata.get('duration')}", file=sys.stderr)

            # Download audio
            audio_file = download_audio(video_id, temp_path, args.cookies)

            # Transcribe
            transcript, detected_lang = transcribe_with_whisper(
                audio_file, args.model, args.language, temp_path
            )

            # Extract chapters from description
            chapters = extract_chapters(metadata.get('description', ''))

            # Build result
            result = {
                **metadata,
                'url': f"https://www.youtube.com/watch?v={video_id}",
                'video_id': video_id,
                'language': detected_lang,
                'transcript': transcript,
                'chapters': chapters,
                'speakers': [],
                'transcription_method': 'whisper',
                'whisper_model': args.model,
            }

            # Determine output path
            if args.output:
                output_path = Path(args.output)
            else:
                output_path = Path(tempfile.gettempdir()) / f"yt_transcript_{video_id}.json"

            # Write result
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"OUTPUT_FILE:{output_path}", file=sys.stderr)
            print(str(output_path))

            # Optionally keep audio
            if args.keep_audio:
                final_audio = Path(tempfile.gettempdir()) / audio_file.name
                audio_file.rename(final_audio)
                print(f"Audio saved: {final_audio}", file=sys.stderr)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
