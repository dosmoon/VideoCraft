"""ClipSubtitleSpec — Step 5.1 compile parity + seeder behaviour."""

from __future__ import annotations

import os

import pytest

from core.composition.compile import ClipRange, CompileContext
from core.composition.style import CompositionStyle
from creations.clip.components.subtitle import KIND, template_from_style
from creations.clip.components import spec_for_kind


SRT_BODY = """1
00:00:00,000 --> 00:00:02,000
hello world

2
00:00:03,000 --> 00:00:05,000
second cue

3
00:00:08,000 --> 00:00:10,000
third cue
"""


@pytest.fixture
def srt_file(tmp_path):
    p = tmp_path / "en.srt"
    p.write_text(SRT_BODY, encoding="utf-8")
    return str(p)


def _empty_ctx(duration: float = 10.0) -> CompileContext:
    return CompileContext(project=None, material_model=None,
                           instance_dir="", duration=duration)


# ── compile() basics ───────────────────────────────────────────────────────

def test_compile_missing_srt_returns_empty():
    spec = spec_for_kind(KIND)
    out = spec.compile({"kind": KIND, "srt_path": ""},
                        ClipRange(0.0, 10.0), _empty_ctx())
    assert out == []


def test_compile_nonexistent_srt_returns_empty(tmp_path):
    spec = spec_for_kind(KIND)
    out = spec.compile({"kind": KIND, "srt_path": str(tmp_path / "no.srt")},
                        ClipRange(0.0, 10.0), _empty_ctx())
    assert out == []


def test_compile_emits_one_element_per_in_range_cue(srt_file):
    spec = spec_for_kind(KIND)
    out = spec.compile(
        {"kind": KIND, "srt_path": srt_file,
          "fontsize": 24, "color": "#FFFFFF"},
        ClipRange(0.0, 10.0), _empty_ctx())
    assert len(out) == 3
    assert all(e.kind == "subtitle_cue" for e in out)
    assert out[0].data == {"text": "hello world"}


def test_compile_clip_relative_times(srt_file):
    """Cue at [3s, 5s] within source becomes [1s, 3s] for clip [2s, 8s]."""
    spec = spec_for_kind(KIND)
    out = spec.compile(
        {"kind": KIND, "srt_path": srt_file},
        ClipRange(2.0, 8.0), _empty_ctx())
    # Cue #1 [0,2] drops (ends at 2, clip starts at 2)
    # Cue #2 [3,5] keeps → [1, 3]
    # Cue #3 [8,10] drops (starts at 8, clip ends at 8)
    assert len(out) == 1
    assert out[0].start_sec == pytest.approx(1.0)
    assert out[0].end_sec == pytest.approx(3.0)


def test_compile_style_dict_carries_all_required_fields(srt_file):
    spec = spec_for_kind(KIND)
    out = spec.compile({
        "kind": KIND, "srt_path": srt_file,
        "fontsize_pct": 0.03, "color": "#FF0000", "bold": True,
        "is_chinese": True,
        "bg_color": "#000000", "bg_opacity": 70, "bg_padding_x_pct": 0.05,
        "stroke_color": "#222222", "stroke_pct": 0.003,
        "position": "top", "block_margin_pct": 0.12,
        "effective_block_margin_pct": 0.15,
    }, ClipRange(0.0, 10.0), _empty_ctx())
    s = out[0].style
    assert s["fontsize_pct"] == pytest.approx(0.03)
    assert s["color"] == "#FF0000"
    assert s["bold"] is True
    assert s["is_chinese"] is True
    assert s["bg_color"] == "#000000"
    assert s["bg_opacity"] == 70
    assert s["bg_padding_x_pct"] == pytest.approx(0.05)
    assert s["stroke_color"] == "#222222"
    assert s["stroke_pct"] == pytest.approx(0.003)
    assert s["position"] == "top"
    assert s["block_margin_pct"] == pytest.approx(0.12)
    # effective_block_margin_pct only stamped when composer computed
    # one (multi-track stacking). When absent, render falls back to
    # block_margin_pct.
    assert s["effective_block_margin_pct"] == pytest.approx(0.15)


# ── template_from_style legacy migration ───────────────────────────────────

def test_template_disabled_sub1_returns_empty():
    style = CompositionStyle()
    style.subtitle.sub1.enabled = False
    style.subtitle.sub2.enabled = True    # ignored — dual-track dropped
    assert template_from_style(style) == []


def test_template_one_dict_for_enabled_sub1():
    style = CompositionStyle()
    style.subtitle.sub1.enabled = True
    style.subtitle.sub2.enabled = True    # ignored — only sub1 migrates
    out = template_from_style(style)
    assert len(out) == 1
    assert out[0]["kind"] == KIND
    assert out[0]["language"] == ""    # host fills on first open


def test_template_propagates_line_and_shared_style():
    style = CompositionStyle()
    style.subtitle.sub1.enabled = True
    style.subtitle.sub1.fontsize = 28
    style.subtitle.sub1.color = "#00FF00"
    style.subtitle.position = "top"
    style.subtitle.stroke_color = "#123456"
    out = template_from_style(style)
    # Legacy int-px fields convert to pct via /1080 (canonical baseline).
    assert out[0]["fontsize_pct"] == pytest.approx(28 / 1080.0)
    assert out[0]["color"] == "#00FF00"
    assert out[0]["position"] == "top"
    assert out[0]["stroke_color"] == "#123456"


# ── Wrap-budget regression (clip dogfood round 2) ─────────────────────────

def test_wrap_subtitle_elements_keeps_cues_within_frame_width():
    """Clip dogfood round 2 (2026-05-23): subtitles overflowed both
    sides of the burned mp4.

    Two compounding engine bugs caused it:
      (a) wrap_subtitle_elements read `style["fontsize"]` (default 24)
          but clip's component schema writes `fontsize_pct`, so the
          budget was computed against a phantom small font;
      (b) compute_subtitle_max_chars still applied the legacy
          ass_render_scale=4.7 magic, stale since the engine started
          writing explicit ASS PlayResX/Y matching the target frame.

    Pre-fix: wrap split happened but cues were sized for a wrong fontsize
    assumption — each cue still rendered wider than the frame.
    Post-fix: cue width at real libass render size < frame width.
    """
    from core.composition.render import wrap_subtitle_elements
    from core.composition.timeline import Element

    long_cn = "这是一行非常非常长的中文字幕用来触发自动换行测试看看是否能被正确切分成多个 cue"
    fontsize_pct = 0.08
    aspect_str = "9:16"
    short_edge = 1080
    # 9:16 portrait: target_h = 1920, target_w (frame width) = 1080.
    target_h = 1920
    frame_width = short_edge

    elements = [
        Element(
            kind="subtitle_cue", start_sec=0.0, end_sec=5.0,
            style={"fontsize_pct": fontsize_pct, "is_chinese": True,
                    "color": "#FFFFFF", "position": "bottom",
                    "block_margin_pct": 0.09},
            data={"text": long_cn},
        ),
    ]
    wrapped = wrap_subtitle_elements(
        elements, aspect_str=aspect_str, short_edge=short_edge)
    assert wrapped, "wrap must keep at least one cue"

    # Real libass render size — what the burned mp4 actually paints.
    # CN glyph is roughly 0.85x fontsize after typical font metrics
    # (matches PIL.ImageFont measurement on msyh.ttc).
    real_fontsize_px = int(fontsize_pct * target_h)
    cn_glyph_px = real_fontsize_px * 0.85
    safe_frame_width = frame_width * 0.95

    for c in wrapped:
        line_px = len(c.content) * cn_glyph_px
        assert line_px < safe_frame_width, (
            f"cue {c.index} would overflow at real render size: "
            f"{len(c.content)} chars × {cn_glyph_px:.0f}px ≈ "
            f"{line_px:.0f}px > frame {safe_frame_width:.0f}px "
            f"(text={c.content!r})")
