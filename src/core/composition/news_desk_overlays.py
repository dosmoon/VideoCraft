"""News-desk overlay renderers — LowerThird + TopicStrip → libass dialogues.

All news_desk overlays produced for a single render are merged into one
temp .ass file and burned via a single ffmpeg `subtitles=` filter. Keeps
the filter_complex chain shallow regardless of overlay count, and reuses
the same libass engine that handles the bilingual subtitle tracks (so
font/anti-aliasing parity is automatic).

Coordinate system: the .ass declares PlayResX/Y matching the render
target dimensions, so ASS coordinates equal output pixels. Rectangles
are drawn via libass drawing mode (`{\\p1}m...{\\p0}`); text uses
absolute `{\\pos(x,y)}` overrides.

Registration: importing this module registers two renderers
("lower_third" / "topic_strip") with render._OVERLAY_RENDERERS.
render.py imports this module at the bottom for the side effect.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from typing import Iterable

from core.subtitle_ops import escape_ffmpeg_path, hex_color_to_ass

from .overlays import LowerThirdOverlay, TopicStripOverlay
from .style import (
    LowerThirdStyle, TopicStripStyle, resolve_overlay_style,
)


# ── ASS helpers ─────────────────────────────────────────────────────────────

def _ass_alpha(opacity_0_100: int) -> str:
    """Opacity (0=fully transparent, 100=opaque) → ASS \\1a hex value
    (00=opaque, FF=transparent)."""
    o = max(0, min(100, int(opacity_0_100)))
    a = int(round((100 - o) * 255 / 100))
    return f"&H{a:02X}&"


def _ass_time(sec: float) -> str:
    """Seconds → ASS H:MM:SS.cc timestamp (centisecond precision)."""
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_escape_text(text: str) -> str:
    """Escape text for an ASS Dialogue Text field. ASS-special chars are
    `{`, `}`, `\\`, `\\N` (literal backslash-N already means line break)."""
    if not text:
        return ""
    return (text.replace("\\", "\\\\")
                .replace("{", "\\{")
                .replace("}", "\\}")
                .replace("\n", "\\N"))


def _est_text_width_px(text: str, fontsize: int) -> float:
    """Quick text-width estimate in pixels. Conservative — overshoots
    slightly for Latin so the bg bar never clips the trailing glyph.
    Real measurement would need PIL + the actual font; for v0.1 we use
    the same heuristic compute_subtitle_max_chars uses internally."""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    latin = len(text) - cjk
    return cjk * fontsize + latin * fontsize * 0.55


# ── Rectangle (filled) drawing-mode dialogue ────────────────────────────────

def _rect_dialogue(start: float, end: float, *,
                    x: int, y: int, w: int, h: int,
                    color_hex: str, opacity: int, layer: int = 0) -> str:
    """One libass drawing-mode Dialogue line that paints a filled
    axis-aligned rectangle at (x, y) of size (w, h). Anchored top-left
    (\\an7) so the coords are unambiguous."""
    color_ass = hex_color_to_ass(color_hex)
    alpha = _ass_alpha(opacity)
    body = (f"{{\\an7\\pos({x},{y})\\bord0\\shad0"
            f"\\1c{color_ass}\\1a{alpha}\\p1}}"
            f"m 0 0 l {w} 0 {w} {h} 0 {h}"
            f"{{\\p0}}")
    return (f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},"
            f"NewsDeskRect,,0,0,0,,{body}")


def _text_dialogue(start: float, end: float, *,
                    x: int, y: int, anchor: int,
                    text: str, fontname: str, fontsize: int,
                    color_hex: str, bold: bool,
                    stroke_color_hex: str = "#000000",
                    stroke_width: int = 0,
                    layer: int = 1) -> str:
    """One Dialogue line for an absolutely-positioned text run.

    `anchor` = ASS \\an code (1=bottom-left ... 9=top-right). The (x,y)
    is the anchor point of the text bounding box."""
    color_ass = hex_color_to_ass(color_hex)
    stroke_ass = hex_color_to_ass(stroke_color_hex)
    body_parts = [
        f"\\an{anchor}",
        f"\\pos({x},{y})",
        f"\\fn{fontname}",
        f"\\fs{fontsize}",
        f"\\1c{color_ass}",
        f"\\3c{stroke_ass}",
        f"\\bord{max(0, int(stroke_width))}",
        "\\shad0",
    ]
    if bold:
        body_parts.append("\\b1")
    body = "{" + "".join(body_parts) + "}" + _ass_escape_text(text)
    return (f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},"
            f"NewsDeskText,,0,0,0,,{body}")


# ── Per-kind dialogue builders ──────────────────────────────────────────────

def _build_lower_third_dialogues(
    spec: LowerThirdOverlay, style: LowerThirdStyle,
    *, target_w: int, target_h: int,
) -> list[str]:
    """Compose bar bg + accent bar + 2-line text → list of Dialogue lines."""
    if not (spec.title or spec.subtitle):
        return []

    pad_px = max(4, int(style.padding_pct * target_h))
    line_gap_px = max(2, int(style.line_gap_pct * target_h))
    title_h = style.title_fontsize
    subtitle_h = style.subtitle_fontsize if spec.subtitle else 0
    text_block_h = title_h + (line_gap_px + subtitle_h if subtitle_h else 0)
    bar_h = text_block_h + pad_px * 2

    title_w_est = _est_text_width_px(spec.title, style.title_fontsize)
    sub_w_est = _est_text_width_px(spec.subtitle, style.subtitle_fontsize)
    text_w = max(title_w_est, sub_w_est)
    bar_w = int(text_w + pad_px * 2
                + (style.accent_width_pct * target_w if style.accent_width_pct > 0 else 0))
    bar_w = max(bar_w, int(target_w * 0.20))   # never narrower than 20% frame

    margin_x = int(style.margin_x_pct * target_w)
    margin_y = int(style.margin_y_pct * target_h)
    bar_y = target_h - margin_y - bar_h
    accent_w = int(style.accent_width_pct * target_w) if style.accent_width_pct > 0 else 0

    if spec.position == "bottom-right":
        bar_x = target_w - margin_x - bar_w
        accent_x = bar_x + bar_w - accent_w
        text_left = bar_x + pad_px
    else:
        bar_x = margin_x
        accent_x = bar_x
        text_left = bar_x + accent_w + pad_px

    lines: list[str] = []

    # Background bar.
    lines.append(_rect_dialogue(
        spec.start_sec, spec.end_sec,
        x=bar_x, y=bar_y, w=bar_w, h=bar_h,
        color_hex=style.bg_color, opacity=style.bg_opacity, layer=0,
    ))
    # Accent stripe (broadcast convention; left edge for left-anchored bar,
    # right edge mirror for right-anchored bar so the accent always sits
    # against the screen-side edge).
    if accent_w > 0:
        lines.append(_rect_dialogue(
            spec.start_sec, spec.end_sec,
            x=accent_x, y=bar_y, w=accent_w, h=bar_h,
            color_hex=style.accent_color, opacity=100, layer=0,
        ))

    # Text — title at the top of the inner block, subtitle below.
    title_top = bar_y + pad_px
    lines.append(_text_dialogue(
        spec.start_sec, spec.end_sec,
        x=text_left, y=title_top, anchor=7,
        text=spec.title, fontname=style.font,
        fontsize=style.title_fontsize, color_hex=style.title_color,
        bold=style.title_bold,
    ))
    if spec.subtitle:
        sub_top = title_top + title_h + line_gap_px
        lines.append(_text_dialogue(
            spec.start_sec, spec.end_sec,
            x=text_left, y=sub_top, anchor=7,
            text=spec.subtitle, fontname=style.font,
            fontsize=style.subtitle_fontsize, color_hex=style.subtitle_color,
            bold=style.subtitle_bold,
        ))
    return lines


def _build_topic_strip_dialogues(
    spec: TopicStripOverlay, style: TopicStripStyle,
    *, target_w: int, target_h: int,
) -> list[str]:
    """Top-edge full-width strip with a single text run inside."""
    if not spec.topic_text:
        return []

    strip_h = max(8, int(style.height_pct * target_h))
    strip_y = max(0, int(style.top_margin_pct * target_h))
    strip_x = 0
    strip_w = target_w
    pad_px = max(8, int(style.text_padding_pct * target_w))

    lines: list[str] = []
    lines.append(_rect_dialogue(
        spec.start_sec, spec.end_sec,
        x=strip_x, y=strip_y, w=strip_w, h=strip_h,
        color_hex=style.bg_color, opacity=style.bg_opacity, layer=0,
    ))

    # Text vertically centered in the strip.
    text_y = strip_y + strip_h // 2
    if style.text_align == "center":
        text_x = target_w // 2
        anchor = 5    # middle-center
    elif style.text_align == "right":
        text_x = target_w - pad_px
        anchor = 6    # middle-right
    else:
        text_x = pad_px
        anchor = 4    # middle-left
    lines.append(_text_dialogue(
        spec.start_sec, spec.end_sec,
        x=text_x, y=text_y, anchor=anchor,
        text=spec.topic_text, fontname=style.font,
        fontsize=style.fontsize, color_hex=style.text_color,
        bold=style.bold,
    ))
    return lines


# ── ASS file assembly ──────────────────────────────────────────────────────

_ASS_HEADER_TMPL = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: NewsDeskRect,Arial,12,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: NewsDeskText,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_news_desk_ass(specs: Iterable, *,
                          target_w: int, target_h: int,
                          overlay_styles: dict) -> str | None:
    """Build a temp .ass file containing all LowerThird + TopicStrip
    overlays for one render. Returns the file path, or None if there
    were no rendered dialogues (so the caller can skip the filter)."""
    dialogues: list[str] = []
    for spec in specs:
        if isinstance(spec, LowerThirdOverlay):
            style = resolve_overlay_style(
                overlay_styles, "lower_third", spec.style_class)
            if style is None:
                style = LowerThirdStyle()
            dialogues.extend(_build_lower_third_dialogues(
                spec, style, target_w=target_w, target_h=target_h))
        elif isinstance(spec, TopicStripOverlay):
            style = resolve_overlay_style(
                overlay_styles, "topic_strip", spec.style_class)
            if style is None:
                style = TopicStripStyle()
            dialogues.extend(_build_topic_strip_dialogues(
                spec, style, target_w=target_w, target_h=target_h))

    if not dialogues:
        return None

    body = _ASS_HEADER_TMPL.format(w=target_w, h=target_h) + \
        "\n".join(dialogues) + "\n"

    out_path = os.path.join(
        tempfile.gettempdir(),
        f"composition-newsdesk-{os.getpid()}-{id(dialogues)}.ass",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    return out_path


# ── Renderer registration ──────────────────────────────────────────────────
#
# News-desk overlays are routed through a SINGLE merged-ASS job (kind
# "news_desk_ass") rather than per-overlay jobs — see render.py
# _named_overlay_jobs which builds the merged file once and pushes one
# job into the dispatch queue.

def _renderer_news_desk_ass(job, prev_label, ctx):
    """Build the merged .ass on demand (now that ctx.target_w/h are known),
    then chain a single subtitles= filter. Temp file is registered with
    ctx.tmp_files so the parent render() cleans it up after ffmpeg returns.
    """
    specs = job.data.get("specs") or []
    overlay_styles = job.data.get("overlay_styles") or {}
    ass_path = build_news_desk_ass(
        specs, target_w=ctx.target_w, target_h=ctx.target_h,
        overlay_styles=overlay_styles,
    )
    if not ass_path:
        return [], prev_label
    ctx.tmp_files.append(ass_path)
    ass_ff = escape_ffmpeg_path(ass_path)
    out_label = ctx.next_label()
    return ([f"{prev_label}subtitles=filename='{ass_ff}'{out_label}"],
            out_label)


def register() -> None:
    """Called from render.py at import time to plug into the renderer
    table. Idempotent — re-registration just overwrites the entry."""
    from . import render
    render.register_overlay_renderer("news_desk_ass", _renderer_news_desk_ass)
