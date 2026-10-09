---
title: YouTube slide extraction
status: complete
created: 2026-10-10
---

# YouTube slide extraction

## 1. Objective

Make `fetch:youtube-download` capture the on-screen slides of a video (prediction tables, charts, decks) as image files, so that `notes:clip` can embed and transcribe them. Today the fetcher returns the transcript only. The 2026-10-09 Chariot Palmistry clip needed six manual steps to get three slides, and two of those steps failed silently.

## 2. Key findings

- **The transcript tells you when slides exist.** The speaker says "this is my screenshot", "as you can see", "this chart". These cues are cheap to detect from the text the fetcher already has.
- **Browser screenshots are unreliable.** The YouTube player in the gstack browser stopped seeking after the first frame, and seven screenshots came out byte-identical. Nothing errored.
- **Downloading the video needs the client fallback.** The default yt-dlp clients returned HTTP 403 (SABR). The `android` client worked, at 360p. `whisper_transcriber.download_audio` already relies on the same fallback for audio.
- **Scene-change detection misses slides.** `select='gt(scene,0.25)'` found 9 cuts but missed dissolves and the opening slide (on screen from 0:05, with no cut to detect).
- **Slides separate cleanly from talking-head frames on one feature.** On a 64×36 grey thumbnail, the share of pixels in the most common of 16 luminance bins is 0.64–0.94 for slide frames and 0.28–0.34 for talking-head frames (measured at 1 s intervals over the whole 4:46 video, §5).
- **Slides build up over time.** Lines are revealed one by one and annotations (boxes, arrows) are added. The best copy of a slide is the one with the most ink, not the first or middle frame.
- **Dissolves look like slides with extra ink.** A one-second blend of the talking head into a slide passes the flatness test and has more ink than the slide itself. The first smoke run returned 5 slides instead of 3 for this reason (§5.3).
- **The same slide reappears.** The Gold 2026–2030 slide is shown three times. Output must be one file per distinct slide, listing every time it was on screen.

## 3. Recommendation

1. Add `plugins/fetch/scripts/youtube_slides.py`: download the video (client fallback), sample grey frames at a fixed interval, classify, group into runs, merge repeats, export the most complete frame of each distinct slide at source resolution, plus a contact sheet and `slides.json`. Final stdout line `OUTPUT_DIR:`.
2. `youtube_downloader.py` emits `slide_cues` in its JSON: the transcript lines that point at on-screen material.
3. `fetch:youtube-download` documents when to run the slide step: `slide_cues` non-empty, or a channel template declaring `slides: always`. Never when it declares `slides: never`.
4. `notes:clip` embeds each slide beside its transcript moment, transcribes it, and fails the clip when cues exist but no slides were extracted and no reason is given.

## 4. Next steps

Milestone M1 (stream A + B) ships a runnable `youtube_slides.py` with tests. Milestone M2 (stream C) wires it into the skills. Both land on branch `youtube-slides`, fast-forwarded onto `main`.

## 5. Smoke investigation

Video `WLMQ93ah-oI` (Chariot Palmistry, 4:46), downloaded with the `android` client at 640×360. Ground truth read from a 5-second contact sheet.

### 5.1 Frame features (1 s sampling, 64×36 grey)

| t (s) | Content | dominant-bin share | white ≥235 share |
|---|---|---|---|
| 0 | talking head | 0.31 | 0.00 |
| 9 | Gold 2026–2030 slide | 0.75 | 0.75 |
| 45 | talking head | 0.28 | 0.00 |
| 84 | Gold 2026–2030 (repeat) | 0.74 | 0.75 |
| 102 | Predictions 2025–2027 slide | 0.70 | 0.73 |
| 159 | Gold Oct 2026–Apr 2027, first line only | 0.94 | 0.95 |
| 225 | same slide, all lines | 0.70 | 0.72 |
| 270 | same slide (repeat) | 0.69 | 0.72 |

Threshold: a frame is slide-like when the dominant-bin share is **≥ 0.50**. The closest talking-head value is 0.34 and the closest slide value 0.64.

### 5.2 Expected output

| # | Slide | Appearances (approx., s) | Best frame from |
|---|---|---|---|
| 1 | Gold 2026–2030 | 5–43, 80–92, 233–253 | the most-inked appearance (an annotated one) |
| 2 | Predictions for 2025–2027 | 99–115, 141–153 | either |
| 3 | Gold predictions Oct 2026–Apr 2027 | 159–227, 264–286 | after the last line is revealed (≥ 215 s) |

Acceptance: **exactly 3 slides**, in first-appearance order, each listing ≥ 2 appearances.

### 5.3 Smoke results (2026-10-10)

| Run | Result |
|---|---|
| Local file, before dissolve handling | 5 slides: the 3 expected plus two 1-sample dissolves at 99 s and 232 s (ink 0.25 and 0.43) |
| Local file, after `drop_transients` and interior `best_sample` | **3 slides**: 01 at 0:35 (appearances 7–43, 82–93, 233–253), 02 at 1:49 (100–115, 142–153), 03 at 4:44 (159–227, 264–286); each the most complete copy |
| URL (`web_safari` and `tv` refused, `android` served 360p) | 3 slides, same three; 2 s for 286 samples |
| Negative control: 3 min of Bloomberg Open Interest (`SKxWFc2MJO0`, 4620–4800 s) | 0 slides |
| `slide_cues` on the gold transcript / the 87-minute Bloomberg episode | 5 cues (first "screenshot" at 0:04) / 0 cues |

## 6. Design

### 6.1 Pipeline

```
download_video(url) ──▶ sample_frames(video, interval) ──▶ classify each frame
      │                                                       │
      │                                    group_runs ──▶ merge_repeats
      │                                                       │
      └──────────────────────────── export_slides(video, slides, out_dir) ──▶ slides.json, contact_sheet.png
```

### 6.2 Helper contracts

All pure helpers take and return plain Python values; no helper below `extract_slides` touches the network.

| Function | Signature | Returns | Side effects |
|---|---|---|---|
| `find_slide_cues` | `(transcript: str) -> list[dict]` | `[{"seconds": int, "phrase": str, "line": str}]`, in transcript order, one entry per line; each line is searched together with the next, and a match belongs to the line it starts in | none |
| `parse_timestamp` | `(token: str) -> int \| None` | seconds for `m:ss` or `h:mm:ss`, else `None` | none |
| `frame_features` | `(frame: bytes, width: int) -> FrameFeatures` | `FrameFeatures(flat: float, ink: float, background: int)` | none |
| `is_slide` | `(f: FrameFeatures) -> bool` | `f.flat >= FLAT_MIN and f.ink >= INK_MIN` | none |
| `ink_mask` | `(frame: bytes, background: int) -> frozenset[int]` | pixel indices whose luminance differs from `background` by more than `INK_DELTA` | none |
| `containment` | `(small: frozenset, big: frozenset, width: int) -> float` | share of `small` within 1 px of `big`; `1.0` when `small` is empty | none |
| `same_slide` | `(a: Sample, b: Sample, width: int) -> bool` | `containment(sparser, denser) >= SAME_MIN` | none |
| `group_runs` | `(samples: list[Sample], width: int) -> list[Run]` | consecutive slide samples, split where a sample is not a slide or not `same_slide` as its predecessor | none |
| `drop_transients` | `(runs: list[Run], interval: float) -> list[Run]` | runs with `len(samples) × interval >= MIN_RUN_SECONDS` | none |
| `best_sample` | `(run: Run) -> Sample` | the sample with the highest `ink`, ignoring the first and last sample of a run of 3 or more; ties go to the later sample | none |
| `merge_repeats` | `(runs: list[Run], width: int, interval: float) -> list[Slide]` | runs whose best samples are `same_slide` merged into one `Slide(best, appearances)`, ordered by first appearance | none |
| `build_download_argv` | `(url: str, client: str, out: Path) -> list[str]` | the yt-dlp argv for one client attempt, video only, ≤ 1080p | none |
| `download_video` | `(url, out_dir, run=subprocess.run) -> Path` | the first file a client produced | runs yt-dlp; raises `RuntimeError` when every client fails |
| `sample_frames` | `(video, interval, run=subprocess.run) -> list[Sample]` | one grey `Sample(t, frame, features)` per interval | runs ffmpeg |
| `export_slides` | `(video, slides, out_dir, run=subprocess.run) -> list[dict]` | the `slides.json` entries | writes `slides/NN-mmss.png`, `contact_sheet.png` |
| `probe_height` | `(video, run=subprocess.run) -> int \| None` | the first video stream's height | runs ffprobe |
| `extract_slides` | `(video, out_dir, interval, video_id=None) -> dict` | the `slides.json` document | all of the above, offline |

Types are frozen dataclasses: `FrameFeatures(flat, ink, background)`, `Sample(t: float, frame: bytes, features: FrameFeatures)`, `Run(samples: tuple[Sample, ...])`, `Slide(best: Sample, appearances: tuple[tuple[float, float], ...])`.

### 6.3 Constants and boundary semantics

| Constant | Value | Boundary |
|---|---|---|
| `FLAT_MIN` | 0.50 | inclusive: exactly 0.50 is a slide |
| `INK_MIN` | 0.01 | inclusive; below it the frame is blank (a white fade), not a slide |
| `INK_DELTA` | 48 | strict: a pixel exactly 48 from the background is not ink |
| `SAME_MIN` | 0.80 | inclusive |
| `MIN_RUN_SECONDS` | 2.0 | inclusive: a run lasting exactly 2.0 s is kept |
| `ANALYSIS_SIZE` | 160×90 | features and masks are computed at this size |
| bins | 16 of 16 levels | luminance `p // 16`; `background` is the dominant bin's centre (`bin * 16 + 8`) |
| default `interval` | 1.0 s | a sample at `t = k × interval`, `k = 0 … floor(duration / interval)` |

- An **appearance** is `(first sample t, last sample t + interval)` of a run, so a single-sample run spans one interval.
- `containment` of an empty `small` is `1.0`, but `is_slide` already rejects frames with ink below 1%, so two blank frames never reach it.
- Slide numbering is 1-based in first-appearance order; files are `NN-mmss.png` using the best sample's time.

### 6.4 Download order

Clients tried in order: `web_safari`, `tv`, `android`. Format `bv*[height<=1080]/b[height<=1080]/b`, no audio (`-f` picks a video-only stream when one exists). The resolution obtained is read from the file with ffprobe and recorded as `source_height`, because 360p text can be hard to read.

### 6.5 Output

```
<out_dir>/
├── slides/01-0042.png …   full-resolution frames, one per distinct slide
├── contact_sheet.png      all slides tiled (absent when there are none)
└── slides.json            {"video_id", "source_height", "interval", "slides": [{"index", "file", "t", "appearances", "ink"}]}
```

The final stdout line is `OUTPUT_DIR:<out_dir>`, including when zero slides are found (an empty `slides` list is a valid result). No marker on failure; exit code 1 for download failure, 2 for bad arguments.

### 6.6 Error paths

| Function | Failure | Behaviour |
|---|---|---|
| `parse_timestamp` | `"abc"`, `"1:2:3:4"`, `""` | returns `None` |
| `find_slide_cues` | line without a timestamp | skipped |
| `frame_features` | empty frame, or length not a multiple of `width` | `ValueError` |
| `download_video` | every client exits non-zero | `RuntimeError` naming each client's last stderr line |
| `download_video` | a client exits 0 but writes no file | treated as a failure; tries the next client |
| `sample_frames` | ffmpeg exits non-zero | `RuntimeError` with stderr tail |
| `sample_frames` | trailing partial frame | dropped |
| `extract_slides` | video has no slides | returns `slides: []`, writes no contact sheet |
| CLI | no URL and no `--video` | exit 2 |

## 7. Milestones and streams

| Milestone | Ships | Acceptance |
|---|---|---|
| M1 | `youtube_slides.py` runnable offline on a local video and online on a URL; `slide_cues` in `youtube_downloader.py` output | `test_youtube_slides.py` green (§8); live smoke on `WLMQ93ah-oI` gives 3 slides per §5.2 |
| M2 | skills wired: fetch skill documents the slide step, clip embeds and gates on it, YouTube template has a Slides section | docs reviewed; full suite green |

| Stream | Work | Depends on |
|---|---|---|
| A | cue detection (`parse_timestamp`, `find_slide_cues`) and the `slide_cues` field | none |
| B | frame analysis, grouping, export, download, CLI | none |
| C | skill and template docs | A, B |

## 8. Tests

File `plugins/fetch/scripts/tests/test_youtube_slides.py`. Synthetic frames are built in the test from bytes; the one end-to-end test synthesises a video with ffmpeg `lavfi` (`color`, `testsrc`, `drawbox`; no fonts) and is skipped when ffmpeg is absent.

| Area | Cases |
|---|---|
| `parse_timestamp` | `0:00`→0, `4:46`→286, `1:16:58`→4618, `abc`→None, `1:2:3:4`→None, `""`→None |
| `find_slide_cues` | "this is my screenshot" hit with seconds; "as you can see", "this chart", "on the screen", "you'll notice" hit; "screen time" and "chartered" miss; untimestamped line skipped; cue split across two caption lines credited to the first; cue wholly in the next line credited once; one entry per line with two cues |
| `frame_features` / `is_slide` | white + black boxes → slide; black + white boxes (dark slide) → slide; uniform white (ink 0) → not; random noise → not; flat exactly 0.50 → slide; flat 0.49 → not; ink exactly 0.01 → slide; empty frame → ValueError; ragged length → ValueError |
| `ink_mask` | pixel at delta 48 excluded, 49 included |
| `containment` / `same_slide` | reveal (subset) → same; annotation added → same; disjoint layouts → different; 1 px shift → same; 1-row shift of hairlines → same; 1-column shift of hairlines → same; 2-row shift → different; containment exactly 0.80, directly and through `same_slide` → same |
| `group_runs` | head, A, A, head, A → two runs; A then B directly → two runs; all heads → no runs |
| `best_sample` | picks max ink; edges of a run of 4 skipped; a run of 2 uses both; tie → later |
| `drop_transients` | 1-sample run at 1 s dropped; exactly 2.0 s kept; 1.9 s dropped |
| `merge_repeats` | A, B, A(more ink) → 2 slides, slide 1's best is the third run's, appearances listed in order; equal-ink repeat keeps the later copy |
| `build_download_argv` | client arg present, ≤1080 format, no `-x`; one argv per client |
| `download_video` | first client fails, second succeeds → second file; all fail → RuntimeError naming three clients; exit 0 with no file → next client |
| `sample_frames` | partial trailing frame dropped; ffmpeg failure → RuntimeError |
| end-to-end | synthetic video: noise, slide A, noise, slide A + extra box, noise, slide B → 2 slides, slide 1 best frame from the second appearance, contact sheet written |

Counts: parse_timestamp 6 · cues 11 · features 9 · ink_mask 2 · containment/same_slide 9 · group_runs 3 · best_sample 4 · drop_transients 1 · merge_repeats 2 · download 5 · sample_frames 2 · end-to-end 1 = **55 cases**. Every boundary comparison was mutation-tested (`>=` → `>`, the 8-neighbourhood reduced to rows or columns, sparser/denser swapped); each mutant fails at least one case.

### 8.1 Per-stream commands

```bash
# Stream A
uv run --group dev pytest plugins/fetch/scripts/tests/test_youtube_slides.py -v -k "timestamp or cues"
# Stream B
uv run --group dev pytest plugins/fetch/scripts/tests/test_youtube_slides.py -v -k "not timestamp and not cues"
# Full suite (gate for main)
uv run --group dev pytest plugins
```

## 9. Appendix: the manual run this replaces

On 2026-10-09: browser seek-and-screenshot (seven identical frames), default yt-dlp download (403), `android` client download (360p, worked), scene detection (9 cuts, missed the opening slide), a 3×3 contact sheet to tell slides from the talking head, a separate frame grab at 8 s for the opening slide, then reading the slides by eye.
