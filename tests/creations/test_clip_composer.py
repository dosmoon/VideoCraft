"""composer.expand_for_candidate + compile_for_candidate — Step 5.5.b."""

from __future__ import annotations

import pytest

from core.composition.compile import ClipRange
from creations.clip.composer import compile_for_candidate, expand_for_candidate


SRT_BODY = """1
00:00:00,000 --> 00:00:02,000
hello

2
00:00:03,000 --> 00:00:05,000
world
"""


@pytest.fixture
def srt_file(tmp_path):
    p = tmp_path / "en.srt"
    p.write_text(SRT_BODY, encoding="utf-8")
    return str(p)


# ── expand_for_candidate ───────────────────────────────────────────────────

def test_expand_is_pure_deep_copy():
    """Source list and instance dicts are not mutated."""
    src = [{"kind": "clip_hook_card", "text": "", "duration_sec": 5.0}]
    out = expand_for_candidate(src, hook_text="boom")
    assert src[0]["text"] == ""    # original untouched
    assert out[0]["text"] == "boom"


def test_expand_fills_hook_text():
    out = expand_for_candidate(
        [{"kind": "clip_hook_card", "text": "", "duration_sec": 5.0}],
        hook_text="boom")
    assert out[0]["text"] == "boom"


def test_expand_fills_outro_text():
    out = expand_for_candidate(
        [{"kind": "clip_outro_card", "text": "", "duration_sec": 5.0}],
        outro_text="thanks")
    assert out[0]["text"] == "thanks"


def test_expand_preserves_user_set_text():
    """If instance already carries text (user explicitly set it in panel),
    per-candidate hook_text doesn't override."""
    out = expand_for_candidate(
        [{"kind": "clip_hook_card", "text": "custom",
           "duration_sec": 5.0}],
        hook_text="from candidate")
    assert out[0]["text"] == "custom"


def test_expand_routes_srt_primary_to_source_srt():
    out = expand_for_candidate(
        [{"kind": "clip_subtitle", "track": "primary"}],
        source_srt="/a/en.srt")
    assert out[0]["srt_path"] == "/a/en.srt"


def test_expand_routes_srt_secondary_to_secondary():
    out = expand_for_candidate(
        [{"kind": "clip_subtitle", "track": "secondary"}],
        source_srt="/a/en.srt", source_srt_secondary="/a/zh.srt")
    assert out[0]["srt_path"] == "/a/zh.srt"


# ── margin_v stacking ──────────────────────────────────────────────────────

def test_expand_single_subtitle_stamps_margin_from_block_margin_pct():
    """Single track: margin_v = libass_margin_v(block_margin_pct)."""
    out = expand_for_candidate(
        [{"kind": "clip_subtitle", "track": "primary",
           "position": "bottom", "block_margin_pct": 0.09}],
        source_srt="/a/en.srt")
    from core.composition.layout import libass_margin_v
    assert out[0]["margin_v"] == libass_margin_v(0.09)


def test_expand_dual_track_same_position_stacks():
    """Two subtitles on same position: outer = block_margin, inner =
    block_margin + track_gap."""
    out = expand_for_candidate([
        {"kind": "clip_subtitle", "track": "primary",
          "position": "bottom", "block_margin_pct": 0.09,
          "track_gap_pct": 0.04},
        {"kind": "clip_subtitle", "track": "secondary",
          "position": "bottom", "block_margin_pct": 0.09,
          "track_gap_pct": 0.04},
    ], source_srt="/a/en.srt", source_srt_secondary="/a/zh.srt")
    from core.composition.layout import libass_margin_v
    assert out[0]["margin_v"] == libass_margin_v(0.09)
    assert out[1]["margin_v"] == libass_margin_v(0.13)


def test_expand_two_tracks_different_positions_no_stack():
    """Subs on different positions don't share an anchor edge → each is
    treated as single-track, both at block_margin_pct from their own
    edge."""
    out = expand_for_candidate([
        {"kind": "clip_subtitle", "track": "primary",
          "position": "top", "block_margin_pct": 0.09,
          "track_gap_pct": 0.04},
        {"kind": "clip_subtitle", "track": "secondary",
          "position": "bottom", "block_margin_pct": 0.09,
          "track_gap_pct": 0.04},
    ], source_srt="/a/en.srt", source_srt_secondary="/a/zh.srt")
    from core.composition.layout import libass_margin_v
    assert out[0]["margin_v"] == libass_margin_v(0.09)
    assert out[1]["margin_v"] == libass_margin_v(0.09)


def test_expand_disabled_subtitle_skipped_in_stacking():
    """Disabled subtitle doesn't participate in stacking math."""
    out = expand_for_candidate([
        {"kind": "clip_subtitle", "track": "primary",
          "position": "bottom", "block_margin_pct": 0.09,
          "track_gap_pct": 0.04},
        {"kind": "clip_subtitle", "track": "secondary",
          "position": "bottom", "block_margin_pct": 0.09,
          "track_gap_pct": 0.04, "enabled": False},
    ], source_srt="/a/en.srt", source_srt_secondary="/a/zh.srt")
    from core.composition.layout import libass_margin_v
    # Primary still treated as single-track (secondary disabled)
    assert out[0]["margin_v"] == libass_margin_v(0.09)


# ── compile_for_candidate end-to-end ───────────────────────────────────────

def test_compile_end_to_end_with_subtitle(srt_file):
    components = [
        {"kind": "clip_subtitle", "id": "sub1", "track": "primary",
          "position": "bottom", "block_margin_pct": 0.09,
          "fontsize": 24, "color": "#FFFFFF"},
    ]
    timeline = compile_for_candidate(
        components, ClipRange(0.0, 10.0),
        source_srt=srt_file)
    assert len(timeline.tracks) == 1
    t = timeline.tracks[0]
    assert t.component_kind == "clip_subtitle"
    assert len(t.elements) == 2
    assert all(e.kind == "subtitle_cue" for e in t.elements)


def test_compile_end_to_end_with_hook(srt_file):
    components = [
        {"kind": "clip_hook_card", "id": "hook", "enabled": True,
          "text": "", "duration_sec": 5.0, "position": "upper-third"},
    ]
    timeline = compile_for_candidate(
        components, ClipRange(0.0, 30.0),
        hook_text="boom")
    assert len(timeline.tracks) == 1
    assert timeline.tracks[0].elements[0].data["text"] == "boom"


def test_compile_skips_disabled_components(srt_file):
    components = [
        {"kind": "clip_subtitle", "id": "s", "track": "primary",
          "enabled": False, "position": "bottom",
          "block_margin_pct": 0.09},
    ]
    timeline = compile_for_candidate(
        components, ClipRange(0.0, 10.0),
        source_srt=srt_file)
    assert timeline.tracks == []
