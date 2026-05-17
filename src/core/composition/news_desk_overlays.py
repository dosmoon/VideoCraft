"""News-desk overlay renderers — TopicStrip + ChapterHeroCard → libass
dialogues.

All news_desk overlays produced for a single render are merged into one
temp .ass file and burned via a single ffmpeg `subtitles=` filter. Keeps
the filter_complex chain shallow regardless of overlay count, and reuses
the same libass engine that handles the bilingual subtitle tracks (so
font/anti-aliasing parity is automatic).

Coordinate system: the .ass declares PlayResX/Y matching the render
target dimensions, so ASS coordinates equal output pixels. Rectangles
are drawn via libass drawing mode (`{\\p1}m...{\\p0}`); text uses
absolute `{\\pos(x,y)}` overrides.

Registration: importing this module registers the `news_desk_ass`
renderer with render._OVERLAY_RENDERERS. render.py imports this module
at the bottom for the side effect.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from typing import Iterable

from core.subtitle_ops import escape_ffmpeg_path, hex_color_to_ass

from .overlays import ChapterHeroCardOverlay, TopicStripOverlay
from .style import (
    ChapterHeroCardStyle, TopicStripStyle,
    resolve_overlay_style,
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


def _wrap_text_cjk_n(text: str, max_chars: int, max_lines: int) -> list[str]:
    """Greedy wrap on `max_chars` budget with configurable max_lines (≥ 1).
    CJK char counts as 1; ASCII char counts as 0.5 (so a 20-char budget fits
    ~40 Latin chars). Breaks on spaces for Latin runs; CJK breaks anywhere.
    Surplus past max_lines is appended with an ellipsis on the last line."""
    text = (text or "").strip()
    if not text or max_chars <= 0 or max_lines <= 0:
        return []

    def _cost(ch: str) -> float:
        return 1.0 if ord(ch) > 0x2E80 else 0.5

    lines: list[str] = []
    cur: list[str] = []
    cur_w = 0.0
    last_break = -1
    overflow = False
    for ch in text:
        w = _cost(ch)
        if cur_w + w > max_chars and cur:
            if last_break >= 0 and ord(cur[-1]) <= 0x2E80:
                lines.append("".join(cur[:last_break]).rstrip())
                cur = cur[last_break + 1:]
                cur_w = sum(_cost(c) for c in cur)
                last_break = -1
            else:
                lines.append("".join(cur))
                cur = []
                cur_w = 0.0
                last_break = -1
            if len(lines) >= max_lines:
                overflow = True
                break
        cur.append(ch)
        cur_w += w
        if ch == " ":
            last_break = len(cur) - 1

    if cur and len(lines) < max_lines:
        lines.append("".join(cur).rstrip())
    elif cur:
        overflow = True

    if overflow and lines:
        tail = lines[-1]
        while tail and sum(_cost(c) for c in tail) > max_chars - 0.5:
            tail = tail[:-1]
        lines[-1] = (tail.rstrip() + "…") if tail else "…"
    return lines


# ── Per-kind dialogue builders ──────────────────────────────────────────────

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


def _build_chapter_hero_card_dialogues(
    spec: ChapterHeroCardOverlay, style: ChapterHeroCardStyle,
    *, target_w: int, target_h: int,
) -> list[str]:
    """Sidebar hero card — left/right-anchored vertical panel.

    Composition: translucent backdrop + screen-edge accent stripe +
    title block + divider + body block. Slides in from the screen
    edge on enter, fades out on exit.

    Layout (left-anchored example):

        ┌──────────────────────────┐
        │█│  title line 1          │ ← accent stripe full-height on the
        │█│  title line 2          │   screen-edge side; title left-
        │█│ ─────────────────────  │   aligned within the text region;
        │█│  body line 1           │   thin divider between title and
        │█│  body line 2           │   body; body wraps narrow.
        │█│  ...                   │
        └──────────────────────────┘
    """
    title = (spec.title or "").strip()
    body  = (spec.body  or "").strip()
    if not (title or body):
        return []

    title_size = max(12, int(style.title_fontsize))
    body_size  = max(10, int(style.body_fontsize))
    pad_x = max(8, int(style.padding_x_pct * target_w))
    pad_y = max(6, int(style.padding_y_pct * target_h))
    gap_px = max(4, int(style.title_body_gap_pct * target_h))
    accent_w = max(0, int(style.accent_width_pct * target_w))
    divider_h = max(0, int(style.divider_height_px))

    # Fixed card width from style; text region = card minus paddings + accent.
    card_w = max(80, int(style.width_pct * target_w))
    text_region_w = max(40, card_w - pad_x * 2 - accent_w)

    # Pixel-fit wrap budget — the char "unit" in _wrap_text_cjk_n is
    # ~1 CJK char ≈ fontsize px (Latin counts as 0.5 unit ≈ 0.55*fs px).
    # A 0.92 safety factor absorbs bold-weight glyph widening + per-char
    # variance so we don't clip at the card edge. Static field
    # body_max_chars_per_line is now an upper cap, not a default.
    def _budget(region_px: int, fs: int) -> int:
        return max(2, int(region_px * 0.92 / max(8, fs)))

    title_budget = _budget(text_region_w, title_size)
    body_budget = _budget(text_region_w, body_size)
    user_cap = int(style.body_max_chars_per_line) or 0
    if user_cap > 0:
        body_budget = min(body_budget, user_cap)

    title_max_lines = max(1, int(style.title_max_lines))
    title_wrapped = _wrap_text_cjk_n(
        title, title_budget, title_max_lines,
    ) if title else []
    body_wrapped = _wrap_text_cjk_n(
        body, body_budget, max(1, int(style.body_max_lines)),
    ) if (body and style.show_body) else []

    n_title = len(title_wrapped)
    n_body  = len(body_wrapped)
    has_divider = bool(n_title and n_body)

    text_block_h = (n_title * title_size
                     + (gap_px + divider_h + gap_px if has_divider else 0)
                     + n_body * body_size)
    card_h = text_block_h + pad_y * 2

    # Anchor to screen edge; vertically centered.
    margin_x = int(style.margin_x_pct * target_w)
    card_y = (target_h - card_h) // 2
    if style.position == "right":
        card_x_final = target_w - margin_x - card_w
        accent_x = card_x_final + card_w - accent_w
        text_left_offset = pad_x                                 # accent on the right
        slide_dx = max(0, int(style.slide_in_px))                # slide from right edge
    else:    # "left" (default)
        card_x_final = margin_x
        accent_x = card_x_final
        text_left_offset = accent_w + pad_x
        slide_dx = -max(0, int(style.slide_in_px))               # slide from left edge

    fade_in  = max(0, int(style.fade_in_ms))
    fade_out = max(0, int(style.fade_out_ms))

    def _anim(x: int, y: int) -> str:
        """`\\move(start → final)` for slide-in entry + `\\fad` for both
        ends. Same offsets applied to every layer so the whole sidebar
        moves as one unit."""
        parts: list[str] = []
        if slide_dx and fade_in > 0:
            parts.append(
                f"\\move({x + slide_dx},{y},{x},{y},0,{fade_in})")
        else:
            parts.append(f"\\pos({x},{y})")
        if fade_in > 0 or fade_out > 0:
            parts.append(f"\\fad({fade_in},{fade_out})")
        return "".join(parts)

    lines: list[str] = []

    # Layer 0 — translucent backdrop.
    bg_color = hex_color_to_ass(style.bg_color)
    bg_alpha = _ass_alpha(style.bg_opacity)
    band_body = ("{\\an7" + _anim(card_x_final, card_y)
                  + f"\\bord0\\shad0\\1c{bg_color}\\1a{bg_alpha}\\p1}}"
                  f"m 0 0 l {card_w} 0 {card_w} {card_h} 0 {card_h}"
                  "{\\p0}")
    lines.append(
        f"Dialogue: 0,{_ass_time(spec.start_sec)},"
        f"{_ass_time(spec.end_sec)},NewsDeskRect,,0,0,0,,{band_body}"
    )

    # Layer 1 — accent stripe on the screen-edge side.
    if accent_w > 0:
        acc_color = hex_color_to_ass(style.accent_color)
        acc_body = ("{\\an7" + _anim(accent_x, card_y)
                     + f"\\bord0\\shad0\\1c{acc_color}\\1a&H00&\\p1}}"
                     f"m 0 0 l {accent_w} 0 {accent_w} {card_h} 0 {card_h}"
                     "{\\p0}")
        lines.append(
            f"Dialogue: 1,{_ass_time(spec.start_sec)},"
            f"{_ass_time(spec.end_sec)},NewsDeskRect,,0,0,0,,{acc_body}"
        )

    text_left_x = card_x_final + text_left_offset
    title_top = card_y + pad_y

    # Layer 2 — divider (when both title and body exist).
    divider_y = title_top + n_title * title_size + gap_px
    if has_divider:
        div_color = hex_color_to_ass(style.divider_color)
        div_alpha = _ass_alpha(style.divider_opacity)
        div_body = ("{\\an7" + _anim(text_left_x, divider_y)
                     + f"\\bord0\\shad0\\1c{div_color}\\1a{div_alpha}\\p1}}"
                     f"m 0 0 l {text_region_w} 0 {text_region_w} {divider_h} 0 {divider_h}"
                     "{\\p0}")
        lines.append(
            f"Dialogue: 2,{_ass_time(spec.start_sec)},"
            f"{_ass_time(spec.end_sec)},NewsDeskRect,,0,0,0,,{div_body}"
        )

    # Layer 3 — title (left-anchored within text region).
    if title_wrapped:
        title_color = hex_color_to_ass(style.title_color)
        joined = "\\N".join(_ass_escape_text(ln) for ln in title_wrapped)
        # Anchor 7 = top-left.
        body_str = ("{\\an7" + _anim(text_left_x, title_top)
                     + f"\\fn{style.font}\\fs{title_size}"
                     f"\\1c{title_color}\\bord0\\shad0"
                     + ("\\b1" if style.title_bold else "")
                     + "}" + joined)
        lines.append(
            f"Dialogue: 3,{_ass_time(spec.start_sec)},"
            f"{_ass_time(spec.end_sec)},NewsDeskText,,0,0,0,,{body_str}"
        )

    # Layer 4 — body (left-anchored, below divider).
    if body_wrapped:
        body_color = hex_color_to_ass(style.body_color)
        joined = "\\N".join(_ass_escape_text(ln) for ln in body_wrapped)
        body_top = (divider_y + divider_h + gap_px) if has_divider else title_top
        body_str = ("{\\an7" + _anim(text_left_x, body_top)
                     + f"\\fn{style.font}\\fs{body_size}"
                     f"\\1c{body_color}\\bord0\\shad0"
                     + ("\\b1" if style.body_bold else "")
                     + "}" + joined)
        lines.append(
            f"Dialogue: 4,{_ass_time(spec.start_sec)},"
            f"{_ass_time(spec.end_sec)},NewsDeskText,,0,0,0,,{body_str}"
        )

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
    """Build a temp .ass file containing all TopicStrip + ChapterHeroCard
    overlays for one render. Returns the file path, or None if there
    were no rendered dialogues (so the caller can skip the filter)."""
    dialogues: list[str] = []
    for spec in specs:
        if isinstance(spec, TopicStripOverlay):
            style = resolve_overlay_style(
                overlay_styles, "topic_strip", spec.style_class)
            if style is None:
                style = TopicStripStyle()
            dialogues.extend(_build_topic_strip_dialogues(
                spec, style, target_w=target_w, target_h=target_h))
        elif isinstance(spec, ChapterHeroCardOverlay):
            style = resolve_overlay_style(
                overlay_styles, "chapter_hero_card", spec.style_class)
            if style is None:
                style = ChapterHeroCardStyle()
            # Per-spec inline overrides — chapter component routes its
            # property panel edits here so changes take effect without
            # touching the project-wide overlay_styles dict.
            for k, v in (spec.inline_style or {}).items():
                if k in ChapterHeroCardStyle.__dataclass_fields__:
                    setattr(style, k, v)
            dialogues.extend(_build_chapter_hero_card_dialogues(
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
