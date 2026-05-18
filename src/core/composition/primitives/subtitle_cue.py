"""subtitle_cue primitive — SRT-driven libass subtitle track.

All visible sizes (font, stroke) consumed here are FRACTIONS OF THE
SHORT EDGE, per the engine-wide normalization (core/composition/layout.py).
We write a full ASS file with explicit `PlayResX/Y = target_w/target_h`
so libass' script-px coordinate system maps 1:1 to target pixels —
Fontsize / Outline / MarginV are direct video pixels with no hidden
scaling. ffmpeg's bare `subtitles=` on an SRT would use libass'
default PlayResY (288), making fonts render at ~6.7x the intended
size; this module sidesteps that.
"""

from __future__ import annotations

import os
import tempfile

from core.subtitle_ops import escape_ffmpeg_path, hex_color_to_ass

from ..fonts import ass_alignment_for_position
from ..layout import font_size_px
from ..libass_helpers import ass_bgr_with_alpha, ass_escape_text, ass_time
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
                       target_h: int) -> str:
    """ASS force_style string for one subtitle track. Pure: converts pct
    fields (fractions of target frame height) to libass pixel values.

    When `bg_opacity > 0` the track switches to libass opaque-box mode
    (BorderStyle=3) — a translucent rectangle behind each cue, sized to
    fit the text with `bg_padding_x_pct` extra padding."""
    font_name = "Microsoft YaHei" if is_chinese else "Arial"
    parts = [
        f"Fontname={font_name}",
        f"Fontsize={font_size_px(fontsize_pct, target_h)}",
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
            f"Outline={max(0, font_size_px(stroke_pct, target_h))}",
            "Shadow=0",
        ]
    parts += [
        f"Bold={1 if bold else 0}",
        f"Alignment={ass_alignment_for_position(position)}",
        f"MarginV={margin_v}",
    ]
    return ",".join(parts)


# ── ASS file builder ───────────────────────────────────────────────────────

# ASS Style fields (Format line for [V4+ Styles]). Used as the canonical
# column order when assembling Style lines from a force_style dict.
_STYLE_FIELDS = (
    "Name", "Fontname", "Fontsize",
    "PrimaryColour", "SecondaryColour", "OutlineColour", "BackColour",
    "Bold", "Italic", "Underline", "StrikeOut",
    "ScaleX", "ScaleY", "Spacing", "Angle",
    "BorderStyle", "Outline", "Shadow", "Alignment",
    "MarginL", "MarginR", "MarginV", "Encoding",
)


def _force_style_to_style_line(force_style: str, *, name: str = "Default") -> str:
    """Promote a `Key=Value,...` force_style string into a full ASS
    `Style: ...` line. Defaults fill the fields the caller didn't set
    (Italic/Underline/StrikeOut=0, ScaleX/Y=100, Spacing/Angle=0,
    SecondaryColour matches PrimaryColour, MarginL/R=0, Encoding=1)."""
    kv: dict[str, str] = {}
    for pair in force_style.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            kv[k.strip()] = v.strip()
    primary = kv.get("PrimaryColour", "&H00FFFFFF")
    defaults = {
        "Name": name,
        "Fontname": kv.get("Fontname", "Arial"),
        "Fontsize": kv.get("Fontsize", "24"),
        "PrimaryColour": primary,
        "SecondaryColour": primary,
        "OutlineColour": kv.get("OutlineColour", "&H00000000"),
        "BackColour": kv.get("BackColour", "&H00000000"),
        "Bold": kv.get("Bold", "0"),
        "Italic": "0", "Underline": "0", "StrikeOut": "0",
        "ScaleX": "100", "ScaleY": "100",
        "Spacing": "0", "Angle": "0",
        "BorderStyle": kv.get("BorderStyle", "1"),
        "Outline": kv.get("Outline", "0"),
        "Shadow": kv.get("Shadow", "0"),
        "Alignment": kv.get("Alignment", "2"),
        "MarginL": "0", "MarginR": "0",
        "MarginV": kv.get("MarginV", "0"),
        "Encoding": "1",
    }
    values = [defaults[f] for f in _STYLE_FIELDS]
    return "Style: " + ",".join(values)


def _ass_header(target_w: int, target_h: int, style_line: str) -> str:
    """[Script Info] + [V4+ Styles] header. PlayResX/Y locked to the
    target frame so libass script units equal video pixels (no hidden
    PlayResY=288 scale)."""
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {target_w}\n"
        f"PlayResY: {target_h}\n"
        "ScaledBorderAndShadow: yes\n"
        "WrapStyle: 2\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: " + ",".join(_STYLE_FIELDS) + "\n"
        + style_line + "\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def build_subtitle_ass(wrapped_cues, *, force_style: str,
                         target_w: int, target_h: int) -> str:
    """Assemble a complete ASS file string. `wrapped_cues` is a list of
    srt.Subtitle objects (clip-relative times); `force_style` is the
    Key=Value,... string built by `build_force_style`."""
    style_line = _force_style_to_style_line(force_style, name="Default")
    body = _ass_header(target_w, target_h, style_line)
    for c in wrapped_cues:
        start = ass_time(c.start.total_seconds())
        end = ass_time(c.end.total_seconds())
        text = ass_escape_text(c.content)
        body += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"
    return body


# ── Renderer ────────────────────────────────────────────────────────────────

def _renderer(job, prev_label, ctx):
    ass_path = job.data.get("ass_path")
    if not (ass_path and os.path.exists(ass_path)
            and os.path.getsize(ass_path) > 0):
        return [], prev_label
    ass_ff = escape_ffmpeg_path(ass_path)
    # Point libass at the Windows system fonts dir. ffmpeg's bundled
    # fontconfig doesn't scan it by default, so a `Fontname=Microsoft
    # YaHei` Style line silently falls back to libass' internal default
    # font — visually shorter/thinner glyphs than the matching drawtext
    # path (which loads msyh.ttc by absolute fontfile). With fontsdir
    # set, libass finds the named TTF and subtitle metrics line up
    # with hook/outro at the same configured size.
    fonts_dir = escape_ffmpeg_path("C:/Windows/Fonts")
    out_label = ctx.next_label()
    return ([f"{prev_label}subtitles=filename='{ass_ff}':"
             f"fontsdir='{fonts_dir}'{out_label}"],
            out_label)


register_overlay_renderer(KIND, _renderer)
