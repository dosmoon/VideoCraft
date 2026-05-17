"""subtitle_cue primitive — SRT-driven libass subtitle track.

Spec/Style for now still live in style.py (SubtitleStyle / SubtitleLineStyle)
because clip + presets.py persist them. PR 5 atomizes the god object and
those classes land here.

This module owns the libass force_style builder + the renderer that
threads an SRT through ffmpeg's subtitles= filter.
"""

from __future__ import annotations

import os

from core.subtitle_ops import escape_ffmpeg_path, hex_color_to_ass

from ..fonts import ass_alignment_for_position
from ..layout import libass_margin_v
from ..libass_helpers import ass_bgr_with_alpha
from ..style import SubtitleLineStyle, SubtitleStyle
from . import register_overlay_renderer


KIND = "subtitle_cue"


# ── Force-style builder + margin computation ────────────────────────────────

def build_force_style(line: SubtitleLineStyle,
                        subtitle: SubtitleStyle,
                        *, margin_v: int,
                        target_h: int,
                        position: str | None = None) -> str:
    """ASS force_style string for one subtitle track. When
    `line.bg_opacity > 0` the track switches to libass opaque-box mode
    (BorderStyle=3) — a translucent rectangle is drawn behind each cue
    line, sized to fit the text with `bg_padding_x_pct` extra padding."""
    font_name = "Microsoft YaHei" if line.is_chinese else "Arial"
    parts = [
        f"Fontname={font_name}",
        f"Fontsize={line.fontsize}",
        f"PrimaryColour={hex_color_to_ass(line.color)}",
    ]
    if line.bg_opacity > 0:
        # Box mode. OutlineColour mirrors BackColour so the box edge
        # blends with its own fill — reads as a single flat backdrop.
        bg_ass = ass_bgr_with_alpha(line.bg_color, line.bg_opacity)
        pad_px = max(1, int(line.bg_padding_x_pct * target_h))
        parts += [
            f"OutlineColour={bg_ass}",
            f"BackColour={bg_ass}",
            "BorderStyle=3",
            f"Outline={pad_px}",
            "Shadow=0",
        ]
    else:
        parts += [
            f"OutlineColour={hex_color_to_ass(subtitle.stroke_color)}",
            "BorderStyle=1",
            f"Outline={max(0, int(subtitle.stroke_width))}",
            "Shadow=0",
        ]
    parts += [
        f"Bold={1 if line.bold else 0}",
        f"Alignment={ass_alignment_for_position(position or subtitle.position)}",
        f"MarginV={margin_v}",
    ]
    return ",".join(parts)


def track_margins(subtitle: SubtitleStyle) -> tuple[int, int]:
    """Vertical MarginV for (sub1, sub2) derived from the normalized
    layout fields on SubtitleStyle. The JS preview reads the SAME
    block_margin_pct + track_gap_pct via core.composition.layout, so the
    two renderers stay aligned by construction — no magic-number drift.

    sub1 is the primary track and sits visually above sub2 (translation).
    position=top: sub1 outer (near top edge), sub2 inner (below sub1).
    position=bottom: sub2 outer (near bottom edge), sub1 inner (above sub2).
    position=middle: libass Alignment=5 ignores MarginV — stacking not
    supported; callers should use top/bottom for bilingual."""
    outer = libass_margin_v(subtitle.block_margin_pct)
    inner = libass_margin_v(subtitle.block_margin_pct + subtitle.track_gap_pct)
    pos = subtitle.position
    if pos == "top":
        return (outer, inner)
    if pos == "bottom":
        return (inner, outer)
    return (outer, outer)


# ── Renderer ────────────────────────────────────────────────────────────────

def _renderer(job, prev_label, ctx):
    srt_path = job.data.get("srt_path")
    force_style = job.data.get("force_style")
    if not (srt_path and os.path.exists(srt_path)
            and os.path.getsize(srt_path) > 0):
        return [], prev_label
    srt_ff = escape_ffmpeg_path(srt_path)
    out_label = ctx.next_label()
    return ([f"{prev_label}subtitles=filename='{srt_ff}':"
             f"force_style='{force_style}'{out_label}"],
            out_label)


register_overlay_renderer(KIND, _renderer)
