"""Regression tests for source_acquire.

Clip-range history: clipping a YouTube download via yt-dlp's section downloader
(download_ranges/FFmpegFD) reports no progress + is slow → looks frozen. The link
path now ALWAYS does a full download (proven, with progress) and clips the result
locally with a fast stream-copy cut. These tests pin: (1) link opts never carry a
section-download key, (2) the cut is stream-copy (no re-encode), (3) a failed
import never destroys the existing source (staging + atomic swap).
"""

import core.source_acquire as sa
from core.source_acquire import _build_link_opts, _ffmpeg_cut, parse_hms, acquire
from core.project_schema import ClipRange, Source, ORIGIN_LINK


def test_link_opts_is_always_full_download():
    opts = _build_link_opts("out.mp4", None, None)
    # No section-download key (neither the Python-API callable nor the CLI name)
    # — clipping is a separate local step now.
    assert "download_ranges" not in opts
    assert "download_sections" not in opts
    assert "force_keyframes_at_cuts" not in opts
    assert opts["overwrites"] is True  # re-import must actually re-download


def test_ffmpeg_cut_uses_no_pipes_and_stream_copy(monkeypatch):
    """The cut must run ffmpeg with NO output pipe (stdout→devnull, stderr→a
    file, stdin→devnull) and stream-copy. Reading ffmpeg's output through a pipe
    deadlocks in the frozen sidecar when a long copy floods stderr; a pipe-free
    cut can't block on us. Also pin stream-copy (no re-encode) + -t duration."""
    import subprocess as _sp

    captured = {}

    class _FakeCompleted:
        returncode = 0

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return _FakeCompleted()

    monkeypatch.setattr(sa.subprocess, "run", _fake_run)
    _ffmpeg_cut("in.mp4", "out.mp4", ClipRange(start="00:01:00", end="00:02:30"),
                lambda p: None, None)
    cmd, kw = captured["cmd"], captured["kw"]
    # No pipe ffmpeg can block on: stdin/stdout must be DEVNULL, stderr NOT a PIPE.
    assert kw["stdin"] is _sp.DEVNULL
    assert kw["stdout"] is _sp.DEVNULL
    assert kw["stderr"] is not _sp.PIPE
    # Stream copy, not a re-encode; -t carries the duration (end-start seconds).
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert "libx264" not in cmd
    assert "-progress" not in cmd
    assert cmd[cmd.index("-t") + 1] == "90"


def test_parse_hms():
    assert parse_hms("00:01:00") == 60
    assert parse_hms("1:02:03") == 3723
    assert parse_hms("02:30") == 150  # MM:SS form


def test_acquire_failure_preserves_existing_source(tmp_path, monkeypatch):
    """A failed / cancelled (re-)import must NOT destroy the existing source."""
    import core.source_acquire as sa

    dest = tmp_path / "video.mp4"
    dest.write_bytes(b"ORIGINAL")

    def boom(*a, **k):
        raise sa.AcquireError(sa.ERR_FFMPEG, "boom", "simulated failure")

    monkeypatch.setattr(sa, "_acquire_link", boom)

    import pytest
    with pytest.raises(sa.AcquireError):
        acquire(Source(origin=ORIGIN_LINK, url="https://x/y"), str(dest))

    assert dest.read_bytes() == b"ORIGINAL"               # original intact
    assert not (tmp_path / "video.incoming.mp4").exists()  # staging cleaned


def test_acquire_success_swaps_staging_into_dest(tmp_path, monkeypatch):
    """On success the staged file atomically replaces the live source."""
    import core.source_acquire as sa

    dest = tmp_path / "video.mp4"
    dest.write_bytes(b"OLD")

    def fake_link(url, staging, meta, clip, cb, tok):
        # _acquire_* leaves the finished file exactly at `staging`.
        with open(staging, "wb") as f:
            f.write(b"NEW")
        return sa.AcquireResult(title="t", duration_sec=1.0, width=2, height=3, info_json={})

    monkeypatch.setattr(sa, "_acquire_link", fake_link)

    res = acquire(Source(origin=ORIGIN_LINK, url="https://x/y"), str(dest))
    assert dest.read_bytes() == b"NEW"
    assert res.title == "t"
    assert not (tmp_path / "video.incoming.mp4").exists()
