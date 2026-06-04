"""Regression tests for source_acquire link-download options.

The clip-range bug: yt-dlp's Python-API key is `download_ranges` (a callable),
NOT the CLI name `download_sections`. Setting the latter is silently ignored and
the whole video downloads. These tests pin the correct key + resolved seconds so
the wrong-key regression can't come back.
"""

from core.source_acquire import _build_link_opts, parse_hms
from core.project_schema import ClipRange


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
    assert opts["force_keyframes_at_cuts"] is True


def test_link_opts_no_clip_range_omits_ranges():
    opts = _build_link_opts("out.mp4", None, None, None)
    assert "download_ranges" not in opts
    assert "download_sections" not in opts
    assert "force_keyframes_at_cuts" not in opts


def test_parse_hms():
    assert parse_hms("00:01:00") == 60
    assert parse_hms("1:02:03") == 3723
    assert parse_hms("02:30") == 150  # MM:SS form
