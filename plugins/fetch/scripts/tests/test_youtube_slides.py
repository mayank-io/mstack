"""Slide extraction from YouTube videos.

Design and boundary semantics: docs/plans/2026-10-10-youtube-slides.md.

Everything except the last test runs on synthetic bytes, with ffmpeg and yt-dlp
replaced by injected runners. The end-to-end test synthesises a small video with
ffmpeg's lavfi sources (no fonts needed) and is skipped when ffmpeg is absent.
"""

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import youtube_slides as ys  # noqa: E402

W, H = ys.ANALYSIS_WIDTH, ys.ANALYSIS_HEIGHT
N = W * H


def make_frame(bg: int, boxes=()) -> bytes:
    """A grey frame of background `bg` with filled rectangles (x, y, w, h, value)."""
    px = bytearray([bg]) * N
    for x, y, w, h, v in boxes:
        for row in range(y, y + h):
            px[row * W + x: row * W + x + w] = bytes([v]) * w
    return bytes(px)


def sample(t: float, frame: bytes) -> "ys.Sample":
    return ys.Sample(t=t, frame=frame, features=ys.frame_features(frame, W))


SLIDE_A = make_frame(250, [(10, 5, 120, 8, 0), (10, 20, 90, 6, 0)])
SLIDE_A_MORE = make_frame(250, [(10, 5, 120, 8, 0), (10, 20, 90, 6, 0), (10, 40, 100, 6, 0)])
SLIDE_B = make_frame(250, [(80, 60, 70, 20, 0)])
NOISE = bytes(random.Random(0).randrange(256) for _ in range(N))


# --- parse_timestamp ------------------------------------------------------

@pytest.mark.parametrize("token,expected", [
    ("0:00", 0), ("4:46", 286), ("1:16:58", 4618),
    ("abc", None), ("1:2:3:4", None), ("", None),
])
def test_parse_timestamp(token, expected):
    assert ys.parse_timestamp(token) == expected


# --- find_slide_cues ------------------------------------------------------

def test_screenshot_cue_carries_the_line_time():
    cues = ys.find_slide_cues("0:04 six months. This is my screenshot for\n0:06 the price of gold")
    assert cues == [{"seconds": 4, "phrase": "screenshot",
                     "line": "six months. This is my screenshot for"}]


@pytest.mark.parametrize("text", [
    "as you can see here", "look at this chart", "it is on the screen now",
    "and you'll notice the second line",
])
def test_other_cues_hit(text):
    assert len(ys.find_slide_cues(f"1:00 {text}")) == 1


@pytest.mark.parametrize("text", ["too much screen time", "a chartered accountant"])
def test_near_misses_do_not_hit(text):
    assert ys.find_slide_cues(f"1:00 {text}") == []


def test_untimestamped_line_is_skipped():
    assert ys.find_slide_cues("this is my screenshot") == []


def test_cue_split_across_caption_lines_belongs_to_the_first_line():
    cues = ys.find_slide_cues("0:10 and as you can\n0:12 see the gold price")
    assert [(c["seconds"], c["phrase"]) for c in cues] == [(10, "as you can see")]


def test_cue_entirely_in_the_next_line_is_not_credited_twice():
    cues = ys.find_slide_cues("0:10 hello there\n0:12 this is my screenshot")
    assert [c["seconds"] for c in cues] == [12]


def test_one_entry_per_line_even_with_two_cues():
    cues = ys.find_slide_cues("2:00 as you can see on this slide")
    assert len(cues) == 1 and cues[0]["seconds"] == 120


# --- frame_features / is_slide --------------------------------------------

def test_white_slide_with_text_blocks_is_a_slide():
    assert ys.is_slide(ys.frame_features(SLIDE_A, W))


def test_dark_slide_is_a_slide():
    dark = make_frame(10, [(10, 5, 120, 8, 255), (10, 20, 90, 6, 255)])
    assert ys.is_slide(ys.frame_features(dark, W))


def test_blank_frame_is_not_a_slide():
    f = ys.frame_features(make_frame(250), W)
    assert f.ink == 0 and not ys.is_slide(f)


def test_noise_is_not_a_slide():
    assert not ys.is_slide(ys.frame_features(NOISE, W))


def _frame_with_dominant_share(count: int) -> bytes:
    """`count` pixels at 248 (bin 15); the rest spread over bins 0..14, each smaller."""
    rest = N - count
    values = [248] * count
    for i in range(rest):
        values.append((i % 15) * 16 + 8)
    return bytes(values)


def test_flat_exactly_at_threshold_is_a_slide():
    f = ys.frame_features(_frame_with_dominant_share(N // 2), W)
    assert f.flat == 0.5 and ys.is_slide(f)


def test_flat_just_below_threshold_is_not():
    f = ys.frame_features(_frame_with_dominant_share(int(N * 0.49)), W)
    assert f.flat < 0.5 and not ys.is_slide(f)


def test_ink_exactly_at_threshold_is_a_slide():
    frame = make_frame(250, [(0, 0, 144, 1, 0)])   # 144 of 14,400 pixels = 0.01
    f = ys.frame_features(frame, W)
    assert f.ink == 0.01 and ys.is_slide(f)


def test_empty_frame_raises():
    with pytest.raises(ValueError):
        ys.frame_features(b"", W)


def test_ragged_frame_raises():
    with pytest.raises(ValueError):
        ys.frame_features(b"\x00" * (W + 1), W)


# --- ink_mask -------------------------------------------------------------

def test_ink_delta_is_strict():
    frame = bytes([200, 200 - 48, 200 - 49]) + bytes([200]) * (W - 3)
    assert ys.ink_mask(frame, 200) == frozenset({2})


def test_ink_delta_applies_above_background_too():
    frame = bytes([10, 10 + 48, 10 + 49]) + bytes([10]) * (W - 3)
    assert ys.ink_mask(frame, 10) == frozenset({2})


# --- containment / same_slide ---------------------------------------------

def test_progressive_reveal_is_the_same_slide():
    assert ys.same_slide(sample(0, SLIDE_A), sample(1, SLIDE_A_MORE), W)


def test_added_annotation_is_the_same_slide():
    boxed = make_frame(250, [(10, 5, 120, 8, 0), (10, 20, 90, 6, 0), (5, 3, 130, 1, 0)])
    assert ys.same_slide(sample(0, SLIDE_A), sample(1, boxed), W)


def test_different_layouts_are_different_slides():
    assert not ys.same_slide(sample(0, SLIDE_A), sample(1, SLIDE_B), W)


def test_one_pixel_shift_is_the_same_slide():
    shifted = make_frame(250, [(11, 6, 120, 8, 0), (11, 21, 90, 6, 0)])
    assert ys.same_slide(sample(0, SLIDE_A), sample(1, shifted), W)


def test_one_pixel_shift_of_hairlines_needs_the_tolerance():
    # 1-px lines moved down one row share no pixel, so only the 8-neighbourhood joins them.
    lines = make_frame(250, [(10, 10, 100, 1, 0), (10, 30, 100, 1, 0)])
    moved = make_frame(250, [(10, 11, 100, 1, 0), (10, 31, 100, 1, 0)])
    assert ys.same_slide(sample(0, lines), sample(1, moved), W)


def test_one_column_shift_of_vertical_hairlines_needs_the_tolerance():
    lines = make_frame(250, [(20, 5, 1, 80, 0), (60, 5, 1, 80, 0)])
    moved = make_frame(250, [(21, 5, 1, 80, 0), (61, 5, 1, 80, 0)])
    assert ys.same_slide(sample(0, lines), sample(1, moved), W)


def test_two_pixel_shift_of_hairlines_is_a_different_slide():
    lines = make_frame(250, [(10, 10, 100, 1, 0), (10, 30, 100, 1, 0)])
    moved = make_frame(250, [(10, 12, 100, 1, 0), (10, 32, 100, 1, 0)])
    assert not ys.same_slide(sample(0, lines), sample(1, moved), W)


def test_same_slide_exactly_at_threshold():
    # sparser: 8 dots shared with the denser frame + 2 far away -> containment 0.8
    dots = [(c, 0, 1, 1, 0) for c in range(0, 80, 10)]
    sparse = make_frame(250, dots + [(5, 50, 1, 1, 0), (80, 60, 1, 1, 0)])
    dense = make_frame(250, dots + [(c, 85, 1, 1, 0) for c in range(0, 120, 4)])
    assert ys.same_slide(sample(0, sparse), sample(1, dense), W)


def test_containment_exactly_at_threshold_counts_as_same():
    big = frozenset(range(0, 8 * 10, 10))          # 8 isolated pixels on row 0
    small = frozenset(list(big) + [W * 50 + 5, W * 60 + 80])  # 8 inside, 2 far away
    assert ys.containment(small, big, W) == 0.8
    assert ys.containment(small, big, W) >= ys.SAME_MIN


# --- group_runs -----------------------------------------------------------

def test_runs_split_on_non_slide_samples():
    s = [sample(0, NOISE), sample(1, SLIDE_A), sample(2, SLIDE_A),
         sample(3, NOISE), sample(4, SLIDE_A)]
    runs = ys.group_runs(s, W)
    assert [[x.t for x in r.samples] for r in runs] == [[1, 2], [4]]


def test_runs_split_on_a_direct_cut_between_slides():
    runs = ys.group_runs([sample(0, SLIDE_A), sample(1, SLIDE_B)], W)
    assert len(runs) == 2


def test_no_slides_no_runs():
    assert ys.group_runs([sample(0, NOISE), sample(1, NOISE)], W) == []


# --- best_sample ----------------------------------------------------------

def test_best_sample_has_the_most_ink():
    run = ys.Run(samples=(sample(0, SLIDE_A), sample(1, SLIDE_A_MORE), sample(2, SLIDE_A)))
    assert ys.best_sample(run).t == 1


def test_best_sample_skips_the_edges_of_a_long_run():
    blend = make_frame(120, [(0, 0, W, 40, 250)])     # a dissolve: most ink of all
    run = ys.Run(samples=(sample(0, blend), sample(1, SLIDE_A), sample(2, SLIDE_A_MORE),
                          sample(3, blend)))
    assert ys.best_sample(run).t == 2


def test_best_sample_uses_every_sample_in_a_short_run():
    run = ys.Run(samples=(sample(0, SLIDE_A_MORE), sample(1, SLIDE_A)))
    assert ys.best_sample(run).t == 0


def test_transient_runs_are_dropped_at_the_minimum_exclusive():
    one = ys.Run(samples=(sample(0, SLIDE_A),))
    two = ys.Run(samples=(sample(5, SLIDE_A), sample(6, SLIDE_A)))
    assert ys.drop_transients([one, two], interval=1.0) == [two]
    assert ys.drop_transients([one], interval=2.0) == [one]      # exactly 2.0 s is kept
    assert ys.drop_transients([one], interval=1.9) == []


def test_best_sample_tie_goes_to_the_later_sample():
    run = ys.Run(samples=(sample(0, SLIDE_A), sample(1, SLIDE_A)))
    assert ys.best_sample(run).t == 1


# --- merge_repeats --------------------------------------------------------

def test_repeated_slide_merges_and_keeps_the_most_complete_copy():
    runs = [ys.Run(samples=(sample(0, SLIDE_A), sample(1, SLIDE_A))),
            ys.Run(samples=(sample(5, SLIDE_B),)),
            ys.Run(samples=(sample(9, SLIDE_A_MORE),))]
    slides = ys.merge_repeats(runs, W, interval=1.0)
    assert len(slides) == 2
    assert slides[0].best.t == 9
    assert slides[0].appearances == ((0, 2.0), (9, 10.0))
    assert slides[1].appearances == ((5, 6.0),)


def test_equal_ink_repeat_keeps_the_later_copy():
    runs = [ys.Run(samples=(sample(0, SLIDE_A),)), ys.Run(samples=(sample(7, SLIDE_A),))]
    (slide,) = ys.merge_repeats(runs, W, interval=1.0)
    assert slide.best.t == 7


# --- build_download_argv / download_video ---------------------------------

def test_download_argv_is_video_only_and_capped_at_1080p(tmp_path):
    argv = ys.build_download_argv("https://youtu.be/x", "android", tmp_path / "v.%(ext)s")
    assert "youtube:player_client=android" in argv
    assert any("height<=1080" in a for a in argv)
    assert "-x" not in argv and argv[-1] == "https://youtu.be/x"


def test_download_tries_each_client_in_order(tmp_path):
    seen = []
    def run(argv, **_):
        seen.append(next(a for a in argv if a.startswith("youtube:player_client=")))
        return subprocess.CompletedProcess(argv, 1, "", "ERROR: 403")
    with pytest.raises(RuntimeError):
        ys.download_video("https://youtu.be/x", tmp_path, run=run)
    assert [s.split("=")[1] for s in seen] == list(ys.CLIENTS)


def _fake_runner(results: dict):
    """results[client] = (returncode, write_file)."""
    def run(argv, **_):
        client = next(a for a in argv if a.startswith("youtube:player_client=")).split("=")[1]
        code, write = results[client]
        if write:
            out = Path(argv[argv.index("-o") + 1].replace("%(ext)s", "mp4"))
            out.write_bytes(b"video")
        return subprocess.CompletedProcess(argv, code, "", f"ERROR: {client} failed")
    return run


def test_second_client_succeeds(tmp_path):
    run = _fake_runner({"web_safari": (1, False), "tv": (0, True), "android": (0, True)})
    path = ys.download_video("https://youtu.be/x", tmp_path, run=run)
    assert path.name == "video-tv.mp4"


def test_all_clients_fail_names_each_one(tmp_path):
    run = _fake_runner({c: (1, False) for c in ys.CLIENTS})
    with pytest.raises(RuntimeError) as e:
        ys.download_video("https://youtu.be/x", tmp_path, run=run)
    for c in ys.CLIENTS:
        assert c in str(e.value)


def test_exit_zero_without_a_file_tries_the_next_client(tmp_path):
    run = _fake_runner({"web_safari": (0, False), "tv": (1, False), "android": (0, True)})
    assert ys.download_video("https://youtu.be/x", tmp_path, run=run).name == "video-android.mp4"


# --- sample_frames --------------------------------------------------------

def test_partial_trailing_frame_is_dropped(tmp_path):
    raw = SLIDE_A + NOISE + SLIDE_A[: N // 2]
    run = lambda argv, **_: subprocess.CompletedProcess(argv, 0, raw, b"")
    samples = ys.sample_frames(tmp_path / "v.mp4", 2.0, run=run)
    assert [s.t for s in samples] == [0.0, 2.0]


def test_ffmpeg_failure_raises(tmp_path):
    run = lambda argv, **_: subprocess.CompletedProcess(argv, 1, b"", b"moov atom not found")
    with pytest.raises(RuntimeError, match="moov atom"):
        ys.sample_frames(tmp_path / "v.mp4", 1.0, run=run)


# --- end to end -----------------------------------------------------------

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_extract_slides_on_a_synthetic_video(tmp_path):
    """noise, slide A, noise, slide A plus a box, noise, slide B: 2 slides."""
    seg = "d=3:s=320x180:r=10"
    a = "drawbox=x=20:y=10:w=240:h=16:c=black:t=fill,drawbox=x=20:y=40:w=180:h=12:c=black:t=fill"
    a_more = a + ",drawbox=x=20:y=80:w=200:h=12:c=black:t=fill"
    b = "drawbox=x=160:y=120:w=140:h=40:c=black:t=fill"
    graph = (
        f"testsrc={seg}[n0];color=c=white:{seg},{a}[a1];testsrc={seg}[n1];"
        f"color=c=white:{seg},{a_more}[a2];testsrc={seg}[n2];color=c=white:{seg},{b}[b1];"
        "[n0][a1][n1][a2][n2][b1]concat=n=6:v=1:a=0,format=yuv420p[v]"
    )
    video = tmp_path / "synthetic.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex", graph, "-map", "[v]",
                    str(video)], check=True)

    doc = ys.extract_slides(video, tmp_path / "out", interval=0.5)

    assert len(doc["slides"]) == 2
    first, second = doc["slides"]
    assert 9.0 <= first["t"] < 12.0          # best copy is the second appearance
    assert len(first["appearances"]) == 2
    assert 15.0 <= second["t"] < 18.0
    for s in doc["slides"]:
        assert (tmp_path / "out" / s["file"]).stat().st_size > 0
    assert (tmp_path / "out" / "contact_sheet.png").exists()
    assert json.loads((tmp_path / "out" / "slides.json").read_text()) == doc
    assert doc["source_height"] == 180
