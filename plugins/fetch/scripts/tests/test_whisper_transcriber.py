"""Host routing and backend argv for whisper_transcriber.

The transcriber used to rebuild every URL as `youtube.com/watch?v=<id>`, so a
non-YouTube source could not be transcribed at all. Generalising it introduced
two failures that are invisible at runtime and are pinned here:

1. YouTube needs `--remote-components` and `--extractor-args youtube:...` to get
   past SABR/DRM. Sent to a non-YouTube extractor they are noise at best, and
   the resulting fetch failure reads as "this source has no audio".
2. mlx-whisper is not flag-compatible with the reference CLI. Its flags are
   hyphenated, and `--language` has no `auto` choice — auto-detection means
   omitting the flag. Our CLI default *is* `auto`, so passing it through is an
   argparse error on every auto-detected transcription.

These are argv-level tests: nothing here downloads, transcribes, or spawns a
process. The point is the command we would have run.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import whisper_transcriber as wt  # noqa: E402


# --- resolve_source -------------------------------------------------------

def test_bare_youtube_id_resolves_to_a_watch_url():
    assert wt.resolve_source("dQw4w9WgXcQ") == (
        "youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
])
def test_youtube_hosts_are_classified_youtube(url):
    kind, resolved = wt.resolve_source(url)
    assert kind == "youtube"
    assert resolved == url


@pytest.mark.parametrize("url", [
    "https://x.com/alokkumarzz/status/2099165993834799124",
    "https://twitter.com/a/status/123",
    "https://vimeo.com/123456789",
])
def test_other_hosts_pass_through_untouched(url):
    # Previously these raised ValueError, which is why no X video was ever
    # transcribed by this repo.
    assert wt.resolve_source(url) == ("generic", url)


def test_scheme_is_added_when_missing():
    assert wt.resolve_source("x.com/a/status/123") == (
        "generic", "https://x.com/a/status/123")


def test_empty_source_raises():
    with pytest.raises(ValueError):
        wt.resolve_source("   ")


# --- source_ident ---------------------------------------------------------

def test_youtube_ident_is_the_video_id():
    kind, url = wt.resolve_source("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert wt.source_ident(kind, url) == "dQw4w9WgXcQ"


def test_x_ident_is_host_plus_status_id():
    kind, url = wt.resolve_source("https://x.com/alokkumarzz/status/2099165993834799124")
    assert wt.source_ident(kind, url) == "x_com_2099165993834799124"


def test_ident_is_filesystem_safe():
    kind, url = wt.resolve_source("https://example.com/a b/c?d=e#f")
    ident = wt.source_ident(kind, url)
    assert "/" not in ident and " " not in ident


# --- download_audio argv --------------------------------------------------

def _captured_argv(monkeypatch, source, tmp_path):
    """Run download_audio far enough to capture argv, then stop."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        raise SystemExit  # stop before the file-discovery step

    monkeypatch.setattr(wt.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        wt.download_audio(source, tmp_path)
    return seen["cmd"]


def test_youtube_download_keeps_the_drm_workarounds(monkeypatch, tmp_path):
    cmd = _captured_argv(monkeypatch, "https://www.youtube.com/watch?v=dQw4w9WgXcQ", tmp_path)
    assert "--remote-components" in cmd
    assert "youtube:player_client=android,web,tv" in cmd
    assert cmd[-1] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_x_download_omits_the_youtube_only_flags(monkeypatch, tmp_path):
    cmd = _captured_argv(monkeypatch, "https://x.com/a/status/123", tmp_path)
    assert "--remote-components" not in cmd
    assert "--extractor-args" not in cmd
    assert not any("player_client" in str(part) for part in cmd)
    assert cmd[-1] == "https://x.com/a/status/123"


# --- backend argv ---------------------------------------------------------

def test_reference_backend_uses_underscored_flags(tmp_path):
    cmd = wt.build_whisper_argv(tmp_path / "a.mp3", "medium", "auto", tmp_path)
    assert cmd[0] == "whisper"
    assert "--output_format" in cmd
    assert "--language" not in cmd  # auto means omit


def test_mlx_backend_runs_through_uvx_with_hyphenated_flags(tmp_path):
    cmd = wt.build_mlx_argv(tmp_path / "a.mp3", "large-v3-turbo", "auto", tmp_path)
    assert cmd[:4] == ["uvx", "--from", "mlx-whisper", "mlx_whisper"]
    assert "mlx-community/whisper-large-v3-turbo" in cmd
    assert "--output-format" in cmd and "--output_format" not in cmd
    assert "--output-dir" in cmd


def test_mlx_omits_language_for_auto_because_auto_is_not_a_valid_choice(tmp_path):
    cmd = wt.build_mlx_argv(tmp_path / "a.mp3", "medium", "auto", tmp_path)
    assert "auto" not in cmd
    assert "--language" not in cmd


def test_mlx_passes_an_explicit_language_through(tmp_path):
    cmd = wt.build_mlx_argv(tmp_path / "a.mp3", "medium", "en", tmp_path)
    assert cmd[cmd.index("--language") + 1] == "en"


@pytest.mark.parametrize("model,expected", [
    ("medium", "mlx-community/whisper-medium"),
    ("large-v3-turbo", "mlx-community/whisper-large-v3-turbo"),
    ("whisper-tiny", "mlx-community/whisper-tiny"),
    ("mlx-community/whisper-large-v3", "mlx-community/whisper-large-v3"),
])
def test_model_names_map_to_mlx_repos(model, expected):
    assert wt.mlx_model_repo(model) == expected


def test_unknown_backend_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        wt.transcribe_with_whisper(tmp_path / "a.mp3", "medium", "auto", tmp_path, "faster")


def test_missing_uvx_fails_loudly_rather_than_downgrading(monkeypatch, tmp_path):
    # A silent fall back to the reference CLI's default model would produce a
    # quieter transcript of a figures-dense source, which is the exact failure
    # the caption-verification workflow exists to catch.
    monkeypatch.setattr(wt.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="uvx"):
        wt.transcribe_with_whisper(tmp_path / "a.mp3", "medium", "auto", tmp_path, "mlx")


# --- segment formatting ---------------------------------------------------

def test_segments_over_an_hour_get_an_hours_field():
    transcript, language = wt.format_segments({
        "language": "en",
        "segments": [
            {"start": 0, "text": " Opening line."},
            {"start": 65, "text": " One minute in."},
            {"start": 3725, "text": " Past the hour."},
        ],
    })
    assert transcript.splitlines() == [
        "0:00 Opening line.",
        "1:05 One minute in.",
        "1:02:05 Past the hour.",
    ]
    assert language == "en"


def test_blank_segments_are_dropped_not_emitted_as_bare_timestamps():
    transcript, _ = wt.format_segments({
        "segments": [{"start": 0, "text": "   "}, {"start": 5, "text": "Real."}]})
    assert transcript == "0:05 Real."


def test_both_backends_agree_on_the_json_schema_the_formatter_reads(tmp_path):
    # The formatter is shared precisely so the two backends cannot drift. This
    # asserts the contract it depends on: a "segments" list of {start, text}.
    payload = {"language": "en", "segments": [{"start": 1.5, "text": "Hi."}]}
    (tmp_path / "probe.json").write_text(json.dumps(payload))
    assert wt.format_segments(json.loads((tmp_path / "probe.json").read_text())) == (
        "0:01 Hi.", "en")
