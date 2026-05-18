"""subtitle_cue primitive — SRT-driven libass subtitle track.

All visible sizes (font, stroke) consumed here are FRACTIONS OF THE
SHORT EDGE, per the engine-wide normalization (core/composition/layout.py).
The libass ASS values (Fontsize, Outline, MarginV) are pixel-equivalent
because we force `original_size = target_w x target_h` on the
`subtitles=` filter — libass' script-px space then maps 1:1 to target
pixels, eliminating the old ASS_RENDER_SCALE / PlayResY guess-work.
"""

from __future__ import annotations

import os

from core.subtitle_ops import escape_ffmpeg_path, hex_color_to_ass

from ..fonts import ass_alignment_for_position
from ..layout import font_size_px, libass_margin_v
from ..libass_helpers import ass_bgr_with_alpha
from . import register_overlay_renderer


KIND = "subtitle_cue"


# ── Force-style builder ────────────────────────────────────────────────────

def build_force_style(*, fontsize_pct: float, color: str, bold: bool,
                       is_chinese: bool,
                       bg_color: str, bg_opacity: int,
                       bg_padding_x_pct: float,
                       stroke_color: str, stroke_pct: float,
                       position: str,
                       margin_v: int,
                       short_edge: int,
                       target_h: int) -> str:
    """ASS force_style string for one subtitle track. Pure: converts pct
    fields to libass pixel values using short_edge / target_h, no dataclass
    indirection.

    When `bg_opacity > 0` the track switches to libass opaque-box mode
    (BorderStyle=3) — a translucent rectangle behind each cue, sized to
    fit the text with `bg_padding_x_pct` extra padding."""
    font_name = "Microsoft YaHei" if is_chinese else "Arial"
    parts = [
        f"Fontname={font_name}",
        f"Fontsize={font_size_px(fontsize_pct, short_edge)}",
        f"PrimaryColour={hex_color_to_ass(color)}",
    ]
    if bg_opacity > 0:
        # Box mode. OutlineColour mirrors BackColour so the box edge
        # blends with its own fill — reads as a single flat backdrop.
        bg_ass = ass_bgr_with_alpha(bg_color, bg_opacity)
        pad_px = max(1, int(bg_padding_x_pct * target_h))
        parts += [
            f"OutlineColour={bg_ass}",
            f"BackColour={bg_ass}",
            "BorderStyle=3",
            f"Outline={pad_px}",
            "Shadow=0",
        ]
    else:
        parts += [
            f"OutlineColour={hex_color_to_ass(stroke_color)}",
            "BorderStyle=1",
            f"Outline={max(0, font_size_px(stroke_pct, short_edge))}",
            "Shadow=0",
        ]
    parts += [
        f"Bold={1 if bold else 0}",
        f"Alignment={ass_alignment_for_position(position)}",
        f"MarginV={margin_v}",
    ]
    return ",".join(parts)


# ── Renderer ────────────────────────────────────────────────────────────────

def _renderer(job, prev_label, ctx):
    srt_path = job.data.get("srt_path")
    force_style = job.data.get("force_style")
    if not (srt_path and os.path.exists(srt_path)
            and os.path.getsize(srt_path) > 0):
        return [], prev_label
    srt_ff = escape_ffmpeg_path(srt_path)
    # Force libass' script-pixel space to match the target frame
    # exactly. Without this libass picks a default PlayResY (typically
    # 288 for SRT auto-convert), scaling all ASS values by an unknown
    # factor — the source of the long-standing preview/render font-size
    # divergence. With original_size=target, ASS Fontsize / Outline /
    # MarginV are direct video pixels.
    out_label = ctx.next_label()
    return ([f"{prev_label}subtitles=filename='{srt_ff}':"
             f"force_style='{force_style}':"
             f"original_size={ctx.target_w}x{ctx.target_h}{out_label}"],
            out_label)


register_overlay_renderer(KIND, _renderer)
