"""composer.expand_for_candidate + compile_for_candidate."""

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


def test_expand_routes_srt_by_language():
    out = expand_for_candidate(
        [{"kind": "clip_subtitle", "language": "en"},
         {"kind": "clip_subtitle", "language": "zh"}],
        srt_by_lang={"en": "/a/en.srt", "zh": "/a/zh.srt"})
    assert out[0]["srt_path"] == "/a/en.srt"
    assert out[1]["srt_path"] == "/a/zh.srt"


def test_expand_unknown_language_empty_srt():
    out = expand_for_candidate(
        [{"kind": "clip_subtitle", "language": "fr"}],
        srt_by_lang={"en": "/a/en.srt"})
    assert out[0]["srt_path"] == ""


def test_expand_empty_language_empty_srt():
    out = expand_for_candidate(
        [{"kind": "clip_subtitle", "language": ""}],
        srt_by_lang={"en": "/a/en.srt"})
    assert out[0]["srt_path"] == ""


# ── stacking pct (composer stamps `effective_block_margin_pct`) ────────────

def test_expand_single_subtitle_stamps_effective_pct_eq_base():
    out = expand_for_candidate(
        [{"kind": "clip_subtitle", "language": "en",
           "position": "bottom", "block_margin_pct": 0.09}],
        srt_by_lang={"en": "/a/en.srt"})
    assert out[0]["effective_block_margin_pct"] == pytest.approx(0.09)


def test_expand_two_subtitles_same_position_stack_in_list_order():
    """Two subtitles at the same position: list-order earlier is outer
    (block_margin), the next is inner (block_margin + gap)."""
    out = expand_for_candidate([
        {"kind": "clip_subtitle", "language": "en",
          "position": "bottom", "block_margin_pct": 0.09},
        {"kind": "clip_subtitle", "language": "zh",
          "position": "bottom", "block_margin_pct": 0.09},
    ], srt_by_lang={"en": "/a/en.srt", "zh": "/a/zh.srt"})
    assert out[0]["effective_block_margin_pct"] == pytest.approx(0.09)
    assert out[1]["effective_block_margin_pct"] == pytest.approx(0.13)


def test_expand_two_subtitles_different_positions_no_stack():
    out = expand_for_candidate([
        {"kind": "clip_subtitle", "language": "en",
          "position": "top", "block_margin_pct": 0.09},
        {"kind": "clip_subtitle", "language": "zh",
          "position": "bottom", "block_margin_pct": 0.09},
    ], srt_by_lang={"en": "/a/en.srt", "zh": "/a/zh.srt"})
    assert out[0]["effective_block_margin_pct"] == pytest.approx(0.09)
    assert out[1]["effective_block_margin_pct"] == pytest.approx(0.09)


def test_expand_disabled_subtitle_skipped_in_stacking():
    out = expand_for_candidate([
        {"kind": "clip_subtitle", "language": "en",
          "position": "bottom", "block_margin_pct": 0.09},
        {"kind": "clip_subtitle", "language": "zh",
          "position": "bottom", "block_margin_pct": 0.09,
          "enabled": False},
    ], srt_by_lang={"en": "/a/en.srt", "zh": "/a/zh.srt"})
    # First subtitle still treated as single (disabled doesn't count)
    assert out[0]["effective_block_margin_pct"] == pytest.approx(0.09)


# ── compile_for_candidate end-to-end ───────────────────────────────────────

def test_compile_end_to_end_with_subtitle(srt_file):
    components = [
        {"kind": "clip_subtitle", "id": "sub1", "language": "en",
          "position": "bottom", "block_margin_pct": 0.09,
          "fontsize": 24, "color": "#FFFFFF"},
    ]
    timeline = compile_for_candidate(
        components, ClipRange(0.0, 10.0),
        srt_by_lang={"en": srt_file})
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
        {"kind": "clip_subtitle", "id": "s", "language": "en",
          "enabled": False, "position": "bottom",
          "block_margin_pct": 0.09},
    ]
    timeline = compile_for_candidate(
        components, ClipRange(0.0, 10.0),
        srt_by_lang={"en": srt_file})
    assert timeline.tracks == []
