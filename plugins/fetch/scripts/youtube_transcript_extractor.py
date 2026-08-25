#!/usr/bin/env python3
"""
YouTube Transcript Extractor v3.1
Extracts transcripts, chapters, speakers, and metadata from YouTube videos.

Strategy (in order):
1. youtube_transcript_api — fast, no browser, no auth, covers most videos
2. gstack browser (headed) — for auth-gated or API-missing transcripts
3. Whisper via yt-dlp — last resort for videos with no captions at all

New in v3.1:
- Tier 2 runs through _browse.py (gstack, pinned to headed mode) instead of
  launching its own Playwright Chromium on a throwaway profile. The throwaway
  profile was logged out until someone sat through a five-minute interactive
  login, and went stale silently after that — at which point a members-only
  video reported "no transcript available", which reads as a fact about the
  video rather than about the session.
- `--profile` and `--headless` are accepted and ignored (see BrowserExtractor).

New in v3.0:
- youtube_transcript_api as primary extraction method (no browser needed)
- oembed metadata (title, channel, thumbnail) without browser
- Browser demoted to fallback for auth-gated transcripts
- Login detection: warns loudly when the browser session is not signed in

New in v2.1:
- Whisper fallback: automatically transcribes using yt-dlp + Whisper when no native transcript

New in v2.0:
- Scrolling to load full transcript (handles lazy loading)
- Deduplication of transcript segments
- Chapter extraction from description
- Speaker extraction from description
- Thumbnail URL extraction
- Saves to temp file by default (avoids stdout truncation)
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _browse import browse_page  # noqa: E402


def _extract_video_id(url: str) -> str | None:
    """Extract video ID from YouTube URL."""
    match = re.search(r'[?&]v=([^&]+)', url) or re.search(r'youtu\.be/([^?]+)', url)
    return match.group(1) if match else None


def _detect_language(text: str) -> str:
    """Simple language detection based on character patterns."""
    if not text:
        return 'unknown'
    if re.search(r'[\u0900-\u097F]', text):
        return 'hi'
    if re.search(r'[\u0600-\u06FF]', text):
        return 'ar'
    if re.search(r'[\u4e00-\u9fff]', text):
        return 'zh'
    if re.search(r'[\u3040-\u30ff]', text):
        return 'ja'
    if re.search(r'[\uac00-\ud7af]', text):
        return 'ko'
    if re.search(r'[\u0400-\u04FF]', text):
        return 'ru'
    return 'en'


def _extract_chapters(description: str) -> list[dict]:
    """Extract chapter timestamps and titles from description."""
    chapters = []
    chapter_patterns = [
        r'^(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]?\s*(.+)$',
        r'^\((\d{1,2}:\d{2}(?::\d{2})?)\)\s*(.+)$',
    ]
    for line in description.split('\n'):
        line = line.strip()
        match = None
        for pattern in chapter_patterns:
            match = re.match(pattern, line)
            if match:
                break
        if match:
            timestamp, title = match.groups()
            parts = timestamp.split(':')
            if len(parts) == 2:
                seconds = int(parts[0]) * 60 + int(parts[1])
            else:
                seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            chapters.append({'timestamp': timestamp, 'seconds': seconds, 'title': title.strip()})
    chapters.sort(key=lambda x: x['seconds'])
    return chapters


def _extract_speakers(description: str, title: str) -> list[dict]:
    """Extract speaker information from description and title."""
    speakers = []
    seen_names = set()

    patterns = [
        r'(?:guests?|featuring|with|speakers?|hosts?|panelists?)[:]\s*(.+)',
        r'(?:interview(?:ing)?|conversation with)\s+([^.]+)',
        r'[-•]\s*([A-Z][a-zA-Z\s\.]+)(?::|,)\s*(?:[A-Z][a-zA-Z\s]+(?:at|of|@)\s+[A-Z][a-zA-Z\s]+)',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, description, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            names = re.split(r'[,&]|\band\b', match)
            for name in names:
                name = re.sub(r'\s*\([^)]*\)\s*', '', name)
                name = re.sub(r'\s*[-–—]\s*.*$', '', name)
                name = name.strip(' *\n:')
                if name and 2 < len(name) < 50 and not name.lower().startswith(('http', 'www')):
                    name_lower = name.lower()
                    if name_lower not in seen_names:
                        seen_names.add(name_lower)
                        speakers.append({'name': name, 'role': 'speaker'})

    title_patterns = [
        r'\bwith\s+([A-Z][a-zA-Z\s]+)',
        r'\|\s*([A-Z][a-zA-Z\s]+)\s*$',
    ]
    for pattern in title_patterns:
        match = re.search(pattern, title)
        if match:
            potential_speaker = match.group(1).strip()
            if 2 < len(potential_speaker) < 40:
                name_lower = potential_speaker.lower()
                if name_lower not in seen_names:
                    seen_names.add(name_lower)
                    speakers.append({'name': potential_speaker, 'role': 'guest'})

    return speakers


def fetch_oembed_metadata(video_url: str, video_id: str | None) -> dict:
    """Fetch basic metadata via YouTube oembed (no auth needed)."""
    try:
        oembed_url = f'https://www.youtube.com/oembed?url={urllib.request.quote(video_url, safe="")}&format=json'
        req = urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {
            'title': data.get('title', 'Unknown Title'),
            'channel': data.get('author_name', 'Unknown Channel'),
            'thumbnail_url': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg" if video_id else data.get('thumbnail_url'),
        }
    except Exception as e:
        print(f"oembed fetch failed: {e}", file=sys.stderr)
        return {
            'title': 'Unknown Title',
            'channel': 'Unknown Channel',
            'thumbnail_url': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg" if video_id else None,
        }


def try_youtube_transcript_api(video_id: str) -> dict | None:
    """Primary method: fetch transcript via youtube_transcript_api (no browser)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("youtube_transcript_api not installed, skipping API method", file=sys.stderr)
        return None

    try:
        ytt_api = YouTubeTranscriptApi()

        # List available transcripts
        transcript_list = ytt_api.list(video_id)
        available = [(t.language, t.language_code, t.is_generated) for t in transcript_list]
        print(f"Available transcripts: {available}", file=sys.stderr)

        # Preference order: manual first, then auto-generated
        lang_prefs = ['en', 'hi', 'hi-IN']
        fetched = None

        # Try manual transcripts first
        for t in transcript_list:
            if not t.is_generated:
                try:
                    fetched = ytt_api.fetch(video_id, languages=[t.language_code])
                    break
                except Exception:
                    continue

        # Then auto-generated
        if not fetched:
            try:
                fetched = ytt_api.fetch(video_id, languages=lang_prefs)
            except Exception:
                # Fetch whatever is available
                for t in transcript_list:
                    try:
                        fetched = ytt_api.fetch(video_id, languages=[t.language_code])
                        break
                    except Exception:
                        continue

        if not fetched:
            return None

        # Format transcript with timestamps
        lines = []
        for s in fetched.snippets:
            mins = int(s.start // 60)
            secs = int(s.start % 60)
            lines.append(f'{mins}:{secs:02d} {s.text}')

        transcript_text = '\n'.join(lines)

        # Use the API's language code
        language = fetched.language_code.split('-')[0] if fetched.language_code else _detect_language(transcript_text)

        print(f"Fetched {len(lines)} segments via youtube_transcript_api ({fetched.language})", file=sys.stderr)

        return {
            'language': language,
            'transcript': transcript_text,
        }

    except Exception as e:
        print(f"youtube_transcript_api failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Caption integrity scan
# ---------------------------------------------------------------------------
# YouTube auto-captions silently drop words — disproportionately NUMBERS in
# Q&A (the highest-value content in a finance/research video). The gap is
# invisible in the text but recoverable from the audio. This scan flags the
# windows where a figure was most likely dropped so a caller can re-transcribe
# just those seconds with Whisper (see verify_caption_window.py) instead of
# re-transcribing the whole video. The signal that maps cleanly to the failure
# class: a question that demands a number, answered by a span with no number.

# Tokens that count as "a number was present" in an answer.
_NUM_RE = re.compile(
    r'\d|%|\bpercent\b'
    r'|\b(?:half|third|quarter|double|triple|dozen)\b'
    r'|\b(?:hundred|thousand|million|billion|trillion)\b'
    r'|\b(?:one|two|three|four|five|six|seven|eight|nine|ten'
    r'|eleven|twelve|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\b',
    re.IGNORECASE,
)

# Questions that strongly imply a numeric answer.
_QUANT_Q_RE = re.compile(
    r'\bwhat\s+percentage\b|\bwhat\s+percent\b'
    r'|\bwhat\s+(?:fraction|share|portion|multiple|valuation|margin)\b'
    r"|\bwhat(?:'s| is)\s+the\s+"
    r'(?:number|revenue|margin|valuation|multiple|price|size|cap|count|figure|percentage|fraction)\b'
    r'|\bhow\s+much\b|\bhow\s+many\b|\bhow\s+big\b|\bhow\s+fast\b|\bhow\s+large\b'
    r'|\bballpark\b|\border\s+of\s+magnitude\b',
    re.IGNORECASE,
)


def _parse_ts_line(line: str):
    """Parse a 'M:SS text' transcript line into (start_seconds, text)."""
    m = re.match(r'^(\d+):(\d{2})\s+(.*)$', line)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2)), m.group(3)


def scan_caption_integrity(transcript_text: str | None,
                           answer_window_s: int = 28,
                           pad_before_s: int = 4) -> list[dict]:
    """Flag spots where the caption likely dropped a figure.

    Returns a list of {start_seconds, end_seconds, reason, snippet} windows,
    each a candidate for targeted Whisper re-transcription. High precision by
    design: a flagged window with no real drop just costs one cheap audio clip.
    """
    if not transcript_text:
        return []
    parsed = [p for p in (_parse_ts_line(l) for l in transcript_text.splitlines()) if p]
    n = len(parsed)
    if not n:
        return []

    warnings = []
    for i, (t, text) in enumerate(parsed):
        if not _QUANT_Q_RE.search(text):
            continue
        # Collect the answer span: lines from the question up to +answer_window_s.
        parts, j = [], i
        while j < n and parsed[j][0] <= t + answer_window_s:
            parts.append(parsed[j][1])
            j += 1
        answer = ' '.join(parts)
        if _NUM_RE.search(answer):
            continue  # answered with a number — nothing to recover
        warnings.append({
            'start_seconds': max(0, t - pad_before_s),
            'end_seconds': t + answer_window_s,
            'reason': 'quantitative question with no number in the answer window — '
                      'caption may have dropped a figure; re-transcribe with Whisper',
            'snippet': answer[:200],
        })

    # Merge overlapping windows so adjacent flags become one recheck clip.
    warnings.sort(key=lambda w: w['start_seconds'])
    merged: list[dict] = []
    for w in warnings:
        if merged and w['start_seconds'] <= merged[-1]['end_seconds']:
            merged[-1]['end_seconds'] = max(merged[-1]['end_seconds'], w['end_seconds'])
            merged[-1]['snippet'] = (merged[-1]['snippet'] + ' … ' + w['snippet'])[:320]
        else:
            merged.append(dict(w))
    return merged


# ---------------------------------------------------------------------------
# Browser-based extraction (fallback) — gstack browser, headed
# ---------------------------------------------------------------------------

# The transcript panel exists in two shapes. YouTube's current one is
# `PAmodern_transcript_view` / `transcript-segment-view-model`; the legacy one
# is `ytd-transcript-renderer` / `ytd-transcript-segment-renderer`. Both are
# probed everywhere, because the rollout is not uniform and matching neither is
# indistinguishable from "this video has no transcript".
_SEGMENT_SELECTOR = "transcript-segment-view-model, ytd-transcript-segment-renderer"

_SEGMENT_COUNTS_JS = """() => {
    const panel = Array.from(document.querySelectorAll('ytd-engagement-panel-section-list-renderer'))
        .find(el => (el.getAttribute('visibility') || '').includes('EXPANDED'));
    return {
        modern: document.querySelectorAll('transcript-segment-view-model').length,
        legacy: document.querySelectorAll('ytd-transcript-segment-renderer').length,
        expanded: panel ? (panel.getAttribute('target-id') || 'unknown') : null,
    };
}"""

# Finding the scroller by measurement rather than by name: the modern panel
# scrolls a `div.ytSectionListRendererContents`, the legacy one a `#content`,
# and neither name is a contract.
_SCROLLER_JS = """
    const panel = document.querySelector('ytd-engagement-panel-section-list-renderer[target-id="PAmodern_transcript_view"]')
        || document.querySelector('ytd-transcript-renderer');
    if (!panel) return -1;
    let sc = panel.querySelector('.ytSectionListRendererContents')
        || panel.querySelector('#content')
        || panel.querySelector('[class*="body"]');
    if (!sc) {
        panel.querySelectorAll('*').forEach(el => {
            if (!sc && el.clientHeight > 100 && el.scrollHeight > el.clientHeight + 40) sc = el;
        });
    }
    if (!sc) sc = panel;
"""

_SCROLL_STEP_JS = "() => {" + _SCROLLER_JS + """
    sc.scrollTop = sc.scrollHeight;
    return document.querySelectorAll('%s').length;
}""" % _SEGMENT_SELECTOR

_SCROLL_RESET_JS = "() => {" + _SCROLLER_JS + """
    sc.scrollTop = 0;
    return true;
}"""


class BrowserExtractor:
    """Tier 2: read the transcript panel out of the user's real, logged-in browser.

    All browser work goes through `_browse.py`, which pins the gstack daemon to
    `headed` mode — the mode attached to the user's own Chrome, carrying their
    real YouTube session. That guarantee matters here specifically: a
    members-only or age-gated video served to a logged-out browser renders a
    normal-looking watch page with no "Show transcript" button, which is
    indistinguishable from "this video has no captions". The failure reads as a
    fact about the video rather than a fact about the session.

    Until 2026-08-24 this launched its own Playwright Chromium against a
    throwaway profile at ~/.claude/youtube-chrome-profile
    (`launch_persistent_context`). That profile was a strictly worse substitute
    for what the headed daemon already has: it started logged out, needed a
    five-minute interactive login the first time, and went stale silently
    whenever its cookies expired — after which every gated video quietly
    reported "no transcript available". The `--profile` and `--headless` flags
    that fed it are now accepted and ignored, so existing call sites and the
    skill's documented invocation keep working.
    """

    def __init__(self):
        self.cookies_file = None

    async def extract(self, video_url: str, export_cookies: bool = True) -> dict:
        """Extract transcript and metadata from a YouTube video via the gstack browser."""
        # gstack browser — never headless, always headed (see _browse.py)
        async with browse_page() as page:
            if not await self._check_youtube_login(page):
                # Warn, do not block. The old throwaway profile was guaranteed
                # logged out on first use, so waiting five minutes for a manual
                # login was worth it. The headed daemon is the user's own
                # browser: if that is not signed in, an unattended run has
                # nobody to wait for. Public videos still work; a gated one
                # yields no transcript and main() then exits non-zero without
                # emitting OUTPUT_FILE.
                print("\n" + "=" * 60, file=sys.stderr)
                print("WARNING: the browser session is NOT signed in to YouTube.",
                      file=sys.stderr)
                print("Members-only and age-gated videos will look like they have",
                      file=sys.stderr)
                print("no captions. Sign in to YouTube in Chrome and re-run.",
                      file=sys.stderr)
                print("=" * 60 + "\n", file=sys.stderr)

            result = await self._extract_from_page(page, video_url)
            if export_cookies:
                self._export_cookies(page)
            return result

    async def _check_youtube_login(self, page) -> bool:
        """Check whether the browser session is signed in to YouTube."""
        try:
            await page.goto('https://www.youtube.com', wait_until='domcontentloaded')
            await page.wait_for_timeout(2000)
            return bool(await page.evaluate('''() => {
                // Logged-in users have an avatar button
                const avatar = document.querySelector('#avatar-btn')
                    || document.querySelector('button#avatar-btn')
                    || document.querySelector('img.yt-spec-avatar-shape__avatar');
                if (avatar) return true;

                // Not logged in if "Sign in" button is present
                const signIn = document.querySelector('a[href*="ServiceLogin"]')
                    || Array.from(document.querySelectorAll('a')).find(a => a.textContent
                        && a.textContent.trim() === 'Sign in');
                if (signIn) return false;

                // Ambiguous — assume not logged in
                return false;
            }'''))
        except Exception:
            return False

    def _export_cookies(self, page) -> None:
        """Write the session's YouTube cookies to a Netscape jar for yt-dlp.

        yt-dlp cannot share the browser session, so the Whisper tier needs the
        cookies handed to it on disk or member-only audio 403s.
        """
        try:
            cookies = page.cookies()
            youtube_cookies = [c for c in cookies
                               if 'youtube' in (c.get('domain') or '').lower()
                               or 'google' in (c.get('domain') or '').lower()]
            if not youtube_cookies:
                return

            cookies_file = Path(tempfile.gettempdir()) / "yt_cookies.txt"
            lines = ["# Netscape HTTP Cookie File", "# https://curl.haxx.se/rfc/cookie_spec.html", ""]
            for cookie in youtube_cookies:
                domain = cookie.get('domain', '')
                flag = "TRUE" if domain.startswith('.') else "FALSE"
                path = cookie.get('path', '/')
                secure = "TRUE" if cookie.get('secure', False) else "FALSE"
                expires_raw = cookie.get('expires', 0)
                if expires_raw is None or expires_raw < 0:
                    expires = "2147483647"
                else:
                    expires = str(int(expires_raw)) if expires_raw > 0 else "2147483647"
                name = cookie.get('name', '')
                value = cookie.get('value', '')
                lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}")

            cookies_file.write_text('\n'.join(lines))
            self.cookies_file = str(cookies_file)
            print(f"Exported {len(youtube_cookies)} cookies to {cookies_file}", file=sys.stderr)
        except Exception as e:
            print(f"Failed to export cookies: {e}", file=sys.stderr)

    async def _extract_from_page(self, page, video_url: str) -> dict:
        """Extract transcript and full metadata from the page."""
        print(f"Navigating to: {video_url}", file=sys.stderr)
        await page.goto(video_url, wait_until='domcontentloaded')
        await page.wait_for_selector('#movie_player', timeout=30000)
        await page.wait_for_timeout(2000)

        video_id = _extract_video_id(video_url)
        metadata = await self._extract_metadata(page, video_id)
        print(f"Title: {metadata['title']}", file=sys.stderr)
        print(f"Channel: {metadata['channel']}", file=sys.stderr)

        chapters = _extract_chapters(metadata.get('description', ''))
        speakers = _extract_speakers(metadata.get('description', ''), metadata.get('title', ''))

        transcript = await self._extract_transcript_text(page)

        if not transcript:
            return {
                **metadata,
                'url': video_url,
                'video_id': video_id,
                'transcript': None,
                'chapters': chapters,
                'speakers': speakers,
                'error': 'No transcript available'
            }

        language = _detect_language(transcript)
        return {
            **metadata,
            'url': video_url,
            'video_id': video_id,
            'language': language,
            'transcript': transcript,
            'chapters': chapters,
            'speakers': speakers,
        }

    async def _extract_metadata(self, page, video_id: str | None) -> dict:
        """Extract video metadata from the page.

        One evaluate() per concern rather than Playwright's query_selector +
        inner_text: the adapter deliberately exposes only goto/wait/evaluate,
        because those are the three `$B` can implement without lying about
        their semantics.
        """
        await page.wait_for_selector('h1.ytd-watch-metadata', timeout=10000)

        # Expand the description before reading it — collapsed, YouTube renders
        # only the first few lines, which is where chapters and speakers live.
        try:
            expanded = await page.evaluate('''() => {
                const btn = document.querySelector('#expand');
                if (btn) { btn.click(); return true; }
                return false;
            }''')
            if expanded:
                await page.wait_for_timeout(700)
        except Exception:
            pass

        info = await page.evaluate('''() => {
            const text = (sel) => {
                const el = document.querySelector(sel);
                return el && el.textContent ? el.textContent.trim() : null;
            };

            let duration = null;
            const player = document.querySelector('#movie_player');
            if (player && player.getDuration) {
                const seconds = player.getDuration();
                const h = Math.floor(seconds / 3600);
                const m = Math.floor((seconds % 3600) / 60);
                const s = Math.floor(seconds % 60);
                duration = h > 0
                    ? h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0')
                    : m + ':' + String(s).padStart(2, '0');
            }
            if (!duration) duration = text('.ytp-time-duration');

            let published = null;
            const infoStrings = document.querySelector('#info-strings');
            if (infoStrings) {
                const dateEl = infoStrings.querySelector('yt-formatted-string');
                if (dateEl && dateEl.textContent) published = dateEl.textContent.trim();
            }
            if (!published) published = text('#tooltip');

            return {
                title: text('h1.ytd-watch-metadata') || 'Unknown Title',
                channel: text('#channel-name a') || 'Unknown Channel',
                duration: duration || 'Unknown',
                description: text('#description-inline-expander') || '',
                published_date: published,
            };
        }''')

        info = info or {}
        return {
            'title': (info.get('title') or 'Unknown Title').strip(),
            'channel': (info.get('channel') or 'Unknown Channel').strip(),
            'duration': info.get('duration') or 'Unknown',
            'description': (info.get('description') or '').strip(),
            'published_date': info.get('published_date'),
            'thumbnail_url': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg" if video_id else None,
        }

    async def _extract_transcript_text(self, page) -> str | None:
        """Extract transcript by opening the transcript panel."""
        try:
            print("Looking for transcript button...", file=sys.stderr)
            await page.evaluate('() => { window.scrollBy(0, 300); return true; }')
            await page.wait_for_timeout(1000)

            expanded = await page.evaluate('''() => {
                const expandBtn = document.querySelector('tp-yt-paper-button#expand')
                    || document.querySelector('#expand')
                    || document.querySelector('#description-inline-expander #expand')
                    || Array.from(document.querySelectorAll('button')).find(b => b.textContent
                        && b.textContent.includes('...more'));
                if (expandBtn) { expandBtn.click(); return true; }
                return false;
            }''')
            if expanded:
                print("Expanding description...", file=sys.stderr)
                await page.wait_for_timeout(1500)

            transcript_clicked = await page.evaluate('''() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent && btn.textContent.includes('Show transcript')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }''')

            if not transcript_clicked:
                print("No 'Show transcript' button found in description", file=sys.stderr)
                return None

            print("Clicked 'Show transcript' button...", file=sys.stderr)

            # Poll for either panel markup rather than waiting on one selector.
            # YouTube has replaced `ytd-transcript-renderer` /
            # `ytd-transcript-segment-renderer` with a `PAmodern_transcript_view`
            # panel built from `transcript-segment-view-model`. Verified live
            # 2026-08-24: the old selectors match nothing on a current watch
            # page, so this tier reported "Transcript panel did not appear" for
            # every video, including ones whose transcript was right there on
            # screen. The legacy branch is kept because the rollout is not
            # uniform and costs one querySelectorAll to check.
            counts = {}
            for _ in range(24):
                await page.wait_for_timeout(500)
                counts = await page.evaluate(_SEGMENT_COUNTS_JS) or {}
                if counts.get('modern') or counts.get('legacy'):
                    break
            else:
                # Distinguish the two failures. An expanded-but-empty panel is
                # the logged-out signature: YouTube renders the transcript
                # chrome ("In this video / Chapters / Transcript") and never
                # fills it. Reporting that as "no transcript panel" sent people
                # looking for a video-side problem — the video has captions,
                # the session just is not entitled to them. Observed live
                # 2026-08-24 against a `launched` (logged-out) daemon on a
                # video whose captions the API returns fine.
                if counts.get('expanded'):
                    print(f"Transcript panel '{counts['expanded']}' opened but stayed "
                          f"empty after 12s. That is what a signed-out session looks "
                          f"like — the video's captions may exist and simply not be "
                          f"served. Sign in to YouTube in Chrome and re-run.",
                          file=sys.stderr)
                else:
                    print("Transcript panel did not appear", file=sys.stderr)
                return None

            print("Scrolling to load full transcript...", file=sys.stderr)
            await self._scroll_transcript_panel(page)

            transcript_lines = await page.evaluate('''() => {
                const lines = [];
                const clean = (el) => (el && el.textContent ? el.textContent.trim() : '');

                const modern = document.querySelectorAll('transcript-segment-view-model');
                if (modern.length) {
                    modern.forEach(segment => {
                        // The second div is a screen-reader duration label
                        // ("1 second"); never treat it as the timestamp.
                        const timestampEl = segment.querySelector('.ytwTranscriptSegmentViewModelTimestamp')
                            || segment.querySelector('div');
                        const textEl = segment.querySelector('span[role="text"]')
                            || segment.querySelector('span');
                        const text = clean(textEl);
                        if (text) lines.push((clean(timestampEl) + ' ' + text).trim());
                    });
                    return lines;
                }

                document.querySelectorAll('ytd-transcript-segment-renderer').forEach(segment => {
                    const timestampEl = segment.querySelector('[class*="timestamp"]')
                        || segment.querySelector('div[class*="segment-start-offset"]')
                        || segment.querySelector('div');
                    const textEl = segment.querySelector('[class*="segment-text"]')
                        || segment.querySelector('yt-formatted-string');
                    if (!timestampEl || !textEl) {
                        const divs = segment.querySelectorAll('div');
                        if (divs.length >= 2) {
                            const text = clean(divs[1]);
                            if (text) lines.push((clean(divs[0]) + ' ' + text).trim());
                            return;
                        }
                    }
                    const text = clean(textEl);
                    if (text) lines.push((clean(timestampEl) + ' ' + text).trim());
                });
                return lines;
            }''')

            if not transcript_lines:
                return None

            unique_lines = self._deduplicate(transcript_lines)
            print(f"Extracted {len(unique_lines)} unique transcript segments (from {len(transcript_lines)} total)", file=sys.stderr)
            return '\n'.join(unique_lines)

        except Exception as e:
            print(f"Error extracting transcript: {e}", file=sys.stderr)
            return None

    async def _scroll_transcript_panel(self, page) -> None:
        """Scroll the transcript panel until the segment count stops growing.

        The loop is driven from Python, one synchronous evaluate() per step.
        It used to be a single `async () => { ... setTimeout ... }` block, which
        real Playwright awaits — `$B js` does not, so the adapter refuses async
        JavaScript outright rather than return an unresolved promise that reads
        as "the panel is empty". Long videos lazily render their transcript, so
        skipping the scroll silently truncates the result.
        """
        prev_count = -1
        for _ in range(100):
            count = await page.evaluate(_SCROLL_STEP_JS)
            if not isinstance(count, int) or count < 0 or count == prev_count:
                break
            prev_count = count
            await page.wait_for_timeout(200)

        await page.evaluate(_SCROLL_RESET_JS)

    @staticmethod
    def _deduplicate(lines: list[str]) -> list[str]:
        """Remove duplicate segments that can occur from lazy loading."""
        seen = set()
        unique = []
        for line in lines:
            key = line.strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(line)
        return unique


# ---------------------------------------------------------------------------
# Whisper fallback (last resort)
# ---------------------------------------------------------------------------

def run_whisper_fallback(video_url: str, video_id: str, metadata: dict, whisper_model: str, cookies_file: str | None = None) -> dict | None:
    """Run Whisper fallback transcription using yt-dlp + whisper."""
    print(f"\nUsing Whisper fallback...", file=sys.stderr)
    print(f"Model: {whisper_model}", file=sys.stderr)

    script_dir = Path(__file__).parent
    fallback_script = script_dir / "whisper_transcriber.py"

    if not fallback_script.exists():
        print(f"Whisper script not found: {fallback_script}", file=sys.stderr)
        return None

    try:
        cmd = [sys.executable, str(fallback_script), video_url, "--model", whisper_model]
        if cookies_file and Path(cookies_file).exists():
            cmd.extend(["--cookies", cookies_file])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

        if result.returncode != 0:
            print(f"Whisper fallback failed: {result.stderr}", file=sys.stderr)
            return None

        # whisper_transcriber emits the contract marker as its final stdout line
        _last = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        output_path = _last[len("OUTPUT_FILE:"):] if _last.startswith("OUTPUT_FILE:") else _last
        if not output_path or not Path(output_path).exists():
            print(f"Whisper output file not found", file=sys.stderr)
            return None

        with open(output_path) as f:
            whisper_result = json.load(f)

        whisper_result.update({
            'title': metadata.get('title') or whisper_result.get('title'),
            'channel': metadata.get('channel') or whisper_result.get('channel'),
            'duration': metadata.get('duration') or whisper_result.get('duration'),
            'description': metadata.get('description') or whisper_result.get('description'),
            'published_date': metadata.get('published_date') or whisper_result.get('published_date'),
            'thumbnail_url': metadata.get('thumbnail_url') or whisper_result.get('thumbnail_url'),
        })
        return whisper_result

    except subprocess.TimeoutExpired:
        print("Whisper transcription timed out (30 min limit)", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Whisper fallback error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description='Extract YouTube video transcript')
    parser.add_argument('url', help='YouTube video URL')
    # Both browser flags are dead: tier 2 drives the gstack daemon, which owns
    # its own (headed, logged-in) Chrome. They are still accepted because the
    # skill's documented invocation and existing call sites pass --profile.
    parser.add_argument('--profile', default=None,
                       help='Deprecated and ignored — the gstack browser supplies the session')
    parser.add_argument('--headless', action='store_true',
                       help='Deprecated and ignored — browser work is always headed')
    parser.add_argument('--output', '-o', help='Output file path (default: temp file)')
    parser.add_argument('--output-dir', dest='output_dir', default=None,
                        help='Output directory; filename is derived (default: temp dir)')
    parser.add_argument('--no-whisper-fallback', action='store_true',
                       help='Disable Whisper fallback when no native transcript')
    parser.add_argument('--whisper-model', default='medium',
                       help='Whisper model to use for fallback (tiny, base, small, medium, large)')
    parser.add_argument('--no-api', action='store_true',
                       help='Skip youtube_transcript_api and go straight to the browser tier')

    args = parser.parse_args()

    if args.profile:
        print("Note: --profile is ignored; the gstack browser supplies the session.",
              file=sys.stderr)
    if args.headless:
        print("Note: --headless is ignored; browser work is always headed.",
              file=sys.stderr)

    video_id = _extract_video_id(args.url)
    if not video_id:
        print("Could not extract video ID from URL", file=sys.stderr)
        sys.exit(1)

    # --- Metadata (oembed, no browser) ---
    print(f"Video ID: {video_id}", file=sys.stderr)
    print(f"Fetching video metadata...", file=sys.stderr)
    metadata = fetch_oembed_metadata(args.url, video_id)
    print(f"Title: {metadata['title']}", file=sys.stderr)
    print(f"Channel: {metadata['channel']}", file=sys.stderr)

    result = None
    cookies_file = None

    # --- Strategy 1: youtube_transcript_api ---
    if not args.no_api:
        print("\n[1/3] Trying youtube_transcript_api...", file=sys.stderr)
        api_result = try_youtube_transcript_api(video_id)
        if api_result and api_result.get('transcript'):
            transcript = api_result['transcript']
            language = api_result.get('language', _detect_language(transcript))
            speakers = _extract_speakers('', metadata.get('title', ''))
            result = {
                **metadata,
                'url': args.url,
                'video_id': video_id,
                'language': language,
                'transcript': transcript,
                'chapters': [],
                'speakers': speakers,
            }
            print(f"Success via youtube_transcript_api", file=sys.stderr)

    # --- Strategy 2: gstack browser (headed) ---
    if not result:
        print("\n[2/3] Trying the gstack browser (headed)...", file=sys.stderr)
        extractor = BrowserExtractor()
        try:
            browser_result = await extractor.extract(args.url)
        except RuntimeError as e:
            # _browse.py refuses to run when gstack is missing or stuck in
            # `launched` mode, because a logged-out capture looks like a
            # successful one. Say so out loud and fall through to Whisper,
            # which needs no browser — never substitute a silent empty page.
            print(f"Browser tier unavailable: {e}", file=sys.stderr)
            browser_result = {}
        cookies_file = extractor.cookies_file

        if browser_result.get('transcript'):
            result = browser_result
            print("Success via the gstack browser", file=sys.stderr)
        else:
            # Browser metadata is richer than oembed: description, duration,
            # published_date. Keep whatever it managed to read.
            metadata = {k: browser_result.get(k) or metadata.get(k) for k in
                        ['title', 'channel', 'duration', 'description', 'published_date', 'thumbnail_url']}

    # --- Strategy 3: Whisper ---
    if not result and not args.no_whisper_fallback:
        print("\n[3/3] Trying Whisper fallback...", file=sys.stderr)
        whisper_result = run_whisper_fallback(
            args.url, video_id, metadata, args.whisper_model, cookies_file
        )
        if whisper_result and whisper_result.get('transcript'):
            result = whisper_result

    # --- No transcript from any source ---
    if not result:
        result = {
            **metadata,
            'url': args.url,
            'video_id': video_id,
            'transcript': None,
            'chapters': [],
            'speakers': [],
            'error': 'No transcript available from any source',
        }

    # --- Caption integrity scan (flag spots where a figure was likely dropped) ---
    if result.get('transcript') and not result.get('error'):
        warnings = scan_caption_integrity(result['transcript'])
        result['caption_warnings'] = warnings
        if warnings:
            print(f"\n⚠ Caption integrity: {len(warnings)} window(s) where a number may have "
                  f"been dropped — re-transcribe with verify_caption_window.py:", file=sys.stderr)
            for w in warnings:
                s, e = w['start_seconds'], w['end_seconds']
                print(f"   {s // 60}:{s % 60:02d}-{e // 60}:{e % 60:02d}  {w['snippet'][:90]}",
                      file=sys.stderr)

    # --- Write output ---
    if args.output:
        output_path = Path(args.output)
    elif args.output_dir:
        # contract: output_dir optional -> filename derived, dir created if missing
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        output_path = Path(args.output_dir) / f"yt_transcript_{video_id}.json"
    else:
        output_path = Path(tempfile.gettempdir()) / f"yt_transcript_{video_id}.json"

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    # --- Refuse to report success on an empty transcript ---
    # All three tiers can fail (no captions, no transcript panel, yt-dlp
    # refused) and still leave usable metadata. Emitting OUTPUT_FILE then is a
    # lie the caller cannot detect: it chains on the marker, reads a JSON with
    # transcript "", and writes a note with no content.
    #
    # Real case, 2026-08-24: a pg gyaan video had gone members-only. Every tier
    # failed loudly in stderr, and the script still printed OUTPUT_FILE.
    #
    # The skill contract says an absent marker means STOP — so withhold it.
    # The JSON is still written; the metadata is worth keeping.
    if not (result.get("transcript") or "").strip():
        print(
            f"\nERROR: no transcript could be extracted for {video_id}. "
            f"All three tiers failed — see the log above for which and why. "
            f"Metadata was still written to {output_path}, but no OUTPUT_FILE "
            f"marker is emitted, because a caller chaining on it would build a "
            f"note with an empty body.",
            file=sys.stderr,
        )
        sys.exit(3)

    print(f"\nOUTPUT_FILE:{output_path}", file=sys.stderr)
    # contract: final stdout line is machine-parseable
    print(f"OUTPUT_FILE:{output_path}")


if __name__ == '__main__':
    asyncio.run(main())
