"""Regression tests for source_acquire link-download options.

The clip-range bug: yt-dlp's Python-API key is `download_ranges` (a callable),
NOT the CLI name `download_sections`. Setting the latter is silently ignored and
the whole video downloads. These tests pin the correct key + resolved seconds so
the wrong-key regression can't come back.
"""

from core.source_acquire import _build_link_opts, parse_hms, acquire
from core.project_schema import ClipRange, Source, ORIGIN_LINK


def test_link_opts_clip_range_uses_download_ranges():
    opts = _build_link_opts(
        "out.mp4", ClipRange(start="00:01:00", end="00:02:00"), None, None
    )
    # The CLI name must NOT leak into the Python API (silently ignored there).
    assert "download_sections" not in opts
    # The real key is a callable resolving to absolute-second ranges.
    fn = opts["download_ranges"]
    resolved = list(fn({}, None))
    assert [(r["start_time"], r["end_time"]) for r in resolved] == [(60, 120)]
    # Fast keyframe cut — no whole-range re-encode (would look frozen on long ranges).
    assert "force_keyframes_at_cuts" not in opts


def test_link_opts_no_clip_range_omits_ranges():
    opts = _build_link_opts("out.mp4", None, None, None)
    assert "download_ranges" not in opts
    assert "download_sections" not in opts


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
