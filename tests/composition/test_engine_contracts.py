"""Unit and regression tests to solidify core VideoCraft Composition Engine contracts.

Guards against regressions from past dogfood bugs and documents the mathematical
and structural invariants of the layout, timeline, and rendering layers.
"""

from __future__ import annotations

import os
import pytest
from PIL import ImageFont

from core.composition.timeline import Element
from core.composition.layout import font_size_px, libass_margin_v, pixel_offset, PositionedRect
from core.composition.text_layout import (
    font_line_height_px,
    measure_max_line_width_px,
    wrap_overlay_text,
)
from core.composition.render import wrap_subtitle_elements
from core.composition.compile import ClipRange, CompileContext
from creations.clip.components import spec_for_kind
from creations.clip.components.subtitle import KIND as SUB_KIND


# ── 1. Element Runtime Contract Validation ───────────────────────────────

def test_element_contract_checks():
    # Valid Element should construct without exceptions
    e = Element(kind="subtitle_cue", start_sec=1.5, end_sec=3.0, style={"color": "#FFFFFF"}, data={"text": "hello"})
    assert e.kind == "subtitle_cue"
    assert e.start_sec == 1.5
    assert e.end_sec == 3.0
    assert e.style == {"color": "#FFFFFF"}
    assert e.data == {"text": "hello"}

    # Invalid empty or non-string kind
    with pytest.raises(TypeError):
        Element(kind="", start_sec=0.0, end_sec=1.0)
    with pytest.raises(TypeError):
        Element(kind=123, start_sec=0.0, end_sec=1.0)  # type: ignore

    # Invalid start_sec / end_sec type
    with pytest.raises(TypeError):
        Element(kind="subtitle_cue", start_sec="1.0", end_sec=2.0)  # type: ignore

    # start_sec > end_sec
    with pytest.raises(ValueError) as exc:
        Element(kind="subtitle_cue", start_sec=3.0, end_sec=1.0)
    assert "cannot be greater than end_sec" in str(exc.value)

    # Invalid style / data dictionary type
    with pytest.raises(TypeError):
        Element(kind="subtitle_cue", start_sec=0.0, end_sec=1.0, style="flat_string")  # type: ignore
    with pytest.raises(TypeError):
        Element(kind="subtitle_cue", start_sec=0.0, end_sec=1.0, data="flat_string")  # type: ignore

    # Nested "style" inside style (contract violation)
    with pytest.raises(ValueError) as exc:
        Element(kind="subtitle_cue", start_sec=0.0, end_sec=1.0, style={"style": {"nested": True}})
    assert "data dict cannot contain nested 'style'" in str(exc.value) or "style dict cannot contain nested 'style'" in str(exc.value)

    # Nested "style" inside data (contract violation)
    with pytest.raises(ValueError) as exc:
        Element(kind="subtitle_cue", start_sec=0.0, end_sec=1.0, data={"style": {"nested": True}})
    assert "data dict cannot contain nested 'style'" in str(exc.value)


# ── 2. Font Size Scaling Across Aspect Ratios ────────────────────────────

def test_layout_font_size_px_aspect_ratios():
    """Verify that vertical font sizes scale proportional to the frame's
    vertical extent (target_h) rather than the short edge, preserving proportional sizing."""
    fontsize_pct = 0.05  # 5% of height

    # 16:9 Landscape (target_h = 1080, target_w = 1920)
    h_16_9 = 1080
    px_16_9 = font_size_px(fontsize_pct, h_16_9)
    assert px_16_9 == 54  # 1080 * 0.05

    # 9:16 Portrait (target_h = 1920, target_w = 1080)
    h_9_16 = 1920
    px_9_16 = font_size_px(fontsize_pct, h_9_16)
    assert px_9_16 == 96  # 1920 * 0.05

    # Proportional aspect ratio scale check (Portrait text is physically larger)
    assert px_9_16 > px_16_9
    assert px_9_16 == int(round(px_16_9 * 1920 / 1080))


# ── 3. Horizontal vs Vertical Watermark Margins ──────────────────────────

def test_layout_pixel_offset_watermark_margins():
    """Verify horizontal margins scale against target_w and vertical margins against target_h,
    and verify the edge padding floors to min_px correctly."""
    margin_pct = 0.025  # 2.5% of dimension

    # 16:9 target frame dimensions
    w, h = 1920, 1080

    # Horizontal margin offset (x)
    offset_x = pixel_offset(margin_pct, w)
    assert offset_x == 48  # 1920 * 0.025

    # Vertical margin offset (y)
    offset_y = pixel_offset(margin_pct, h)
    assert offset_y == 27  # 1080 * 0.025

    # Floor limit check: tiny pct should resolve to min_px instead of 0 or tiny pixel values
    tiny_pct = 0.0001
    offset_floored = pixel_offset(tiny_pct, h, min_px=12)
    assert offset_floored == 12


# ── 4. Drawtext vs Drawbox h_var coordinates ─────────────────────────────

def test_drawtext_vs_drawbox_coordinate_variables():
    """Verify that PositionedRect produces matching but distinct video-height references
    for drawtext ('h') vs drawbox ('ih') to avoid drawn-box centering collapsing to 0."""
    total_h = 150

    # For drawtext, video height parameter is 'h'
    rect = PositionedRect("center", total_h)
    expr_drawtext = rect.y_expr(h_var="h")
    assert expr_drawtext == f"(h-{total_h})/2"
    # For drawbox, video height parameter is 'ih' (drawbox reserves 'h' for its box height)
    expr_drawbox = rect.y_expr(h_var="ih")
    assert expr_drawbox == f"(ih-{total_h})/2"
    assert "ih" in expr_drawbox
    # Make sure we don't have standalone "h" (only as part of "ih")
    assert expr_drawbox.replace("ih", "") == f"(-{total_h})/2"

    # Lower-third check
    rect_lt = PositionedRect("lower-third", total_h)
    expr_lt_drawtext = rect_lt.y_expr(h_var="h")
    assert expr_lt_drawtext == f"h*0.65 - {total_h}/2"

    expr_lt_drawbox = rect_lt.y_expr(h_var="ih")
    assert expr_lt_drawbox == f"ih*0.65 - {total_h}/2"


def test_layout_metrics_matrix():
    """Matrix test: verify layout font sizing, line height, and wrapping width metrics
    across a combination of fonts, sizes, and aspect ratios to lock in the rendering invariants."""
    fonts = [None, "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"]
    sizes = [12, 24, 36, 48, 60, 72]

    for f in fonts:
        if f and not os.path.exists(f):
            continue
        for sz in sizes:
            # 1. font_line_height_px calculation check
            lh = font_line_height_px(f, sz)
            assert lh >= sz, f"Line height ({lh}) must be at least font size ({sz}) for font {f}"
            if f and "msyh" in f:
                # Microsoft YaHei should have large win-metrics headroom (~1.3x EM)
                assert lh >= int(round(sz * 1.3))
            
            # 2. measure_max_line_width_px check
            lines = ["Hello", "World", "This is a longer line"]
            max_w = measure_max_line_width_px(lines, f, sz)
            assert max_w > 0
            
            # Widest line must be measured correctly
            single_line_w = measure_max_line_width_px(["This is a longer line"], f, sz)
            assert max_w == single_line_w

            # 3. wrap_overlay_text boundary check
            wrapped = wrap_overlay_text("This is a super long text block designed to check wrapping bounds", max_width_px=200, font_path=f, font_size_px=sz)
            assert len(wrapped) >= 1


# ── 5. Clip-Relative Cue Timestamp Re-basing ─────────────────────────────

def test_cue_time_base_clip_relative(tmp_path):
    """Cues starting at [3s, 5s] within source must compile to [1s, 3s]
    when extracted for a clip starting at 2s and ending at 8s."""
    srt_body = (
        "1\n00:00:01,000 --> 00:00:03,000\nFirst cue\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nSecond cue\n\n"
        "3\n00:00:08,000 --> 00:00:10,000\nThird cue\n"
    )
    srt_file = tmp_path / "test.srt"
    srt_file.write_text(srt_body, encoding="utf-8")

    spec = spec_for_kind(SUB_KIND)
    ctx = CompileContext(project=None, material_model=None, instance_dir="", duration=10.0)

    # Compile clip window [2.0s, 8.0s]
    elements = spec.compile(
        {"kind": SUB_KIND, "srt_path": str(srt_file)},
        ClipRange(start_sec=2.0, end_sec=8.0),
        ctx
    )

    # First cue [1s, 3s] -> starts at 1, ends at 3. Ends after clip start (2.0), but starts before it.
    # It gets clipped or kept? Since end_sec > clip_start (3.0 > 2.0), it is kept and shifted.
    # Wait, let's verify exact shifting. In subtitle.py:
    #   shifted start = max(0.0, cue.start - clip.start)
    #   shifted end = min(clip.duration, cue.end - clip.start)
    # Let's verify what the compiled outputs are.
    # Cues in original source:
    #  Cue 1: [1.0s, 3.0s] -> relative to 2.0s: start = max(0, -1.0) = 0.0s, end = min(6.0, 1.0) = 1.0s.
    #  Cue 2: [3.0s, 5.0s] -> relative to 2.0s: start = max(0, 1.0) = 1.0s, end = min(6.0, 3.0) = 3.0s.
    #  Cue 3: [8.0s, 10.0s] -> starts at 8.0s (>= clip_end 8.0s), gets dropped completely.

    assert len(elements) == 2

    # Cue 1 (originally 1.0s to 3.0s)
    assert elements[0].start_sec == pytest.approx(0.0)
    assert elements[0].end_sec == pytest.approx(1.0)
    assert elements[0].data["text"] == "First cue"

    # Cue 2 (originally 3.0s to 5.0s)
    assert elements[1].start_sec == pytest.approx(1.0)
    assert elements[1].end_sec == pytest.approx(3.0)
    assert elements[1].data["text"] == "Second cue"


# ── 6. CJK Auto-Detection when is_chinese is False ───────────────────────

def test_cjk_auto_detection_subtitles():
    """Verify that subtitle wrapping auto-detects CJK characters and enforces
    correct wrap boundaries, even if the user failed to tick the is_chinese flag."""
    cjk_text = "这是一行非常非常非常长的中文字幕用来测试即使没有勾选中文选项是否也能被引擎自动换行"

    elements = [
        Element(
            kind="subtitle_cue", start_sec=0.0, end_sec=5.0,
            style={
                "fontsize_pct": 0.05,
                "is_chinese": False,  # User did not check the CJK checkbox
                "color": "#FFFFFF", "position": "bottom",
                "block_margin_pct": 0.09
            },
            data={"text": cjk_text}
        )
    ]

    # Without auto-detection, the budget would treat CJK characters as narrow Latin glyphs (0.55 width multiplier),
    # resulting in a large character count budget (e.g. 36+) and NO wrapping, leading to burned text overflow.
    # With auto-detection, it detects CJK, correctly bounds characters as 1.0 EM width, and wraps it into multiple cues.
    wrapped = wrap_subtitle_elements(elements, aspect_str="9:16", short_edge=1080)

    assert len(wrapped) >= 2, (
        f"CJK subtitle should be auto-detected and wrapped into multiple lines. "
        f"Wrapped count: {len(wrapped)}. Cues: {[c.content for c in wrapped]}"
    )


# ── 7. Line Height and Font Metrics Validation ───────────────────────────

def test_font_line_height_metrics_and_heuristic_fallback():
    """Verify font_line_height_px successfully reads true font metrics when PIL loads
    a standard system font, and seamlessly falls back to 1.4x fontsize when not available."""
    size = 40

    # 1. Fallback heuristic check (for nonexistent font)
    fallback_lh = font_line_height_px("C:/Windows/Fonts/nonexistent.ttf", size)
    assert fallback_lh == round(size * 1.4)

    # 2. Standard system font metrics check (if running on Windows)
    win_msyh = "C:/Windows/Fonts/msyh.ttc"
    if os.path.exists(win_msyh):
        lh = font_line_height_px(win_msyh, size)
        # MS YaHei has Win-metrics ascender + descender headroom.
        # It must be significantly larger than font size (typically ~1.37x).
        assert lh > size
        assert lh == pytest.approx(int(round(size * 1.35)), abs=5)
