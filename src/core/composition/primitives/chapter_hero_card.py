"""chapter_hero_card primitive — sidebar interstitial announcing a new
chapter. Large title (+ optional body) on a sidebar-anchored translucent
panel, shown for the first few seconds of a chapter.

Bundles: Spec dataclass (data) + Style dataclass (visuals) +
build_dialogues() helper that emits libass dialogue strings the
news_desk_ass orchestrator merges into the per-render .ass file.

After Axis 7.4/7.5 the typed Overlay class moved here; legacy import
sites still see `ChapterHeroCardOverlay` via the shim in
`core.composition.overlays`. PR 5 (timeline migration) drops that
alias when callers update.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.subtitle_ops import hex_color_to_ass

from ..libass_helpers import ass_alpha, ass_escape_text, ass_time
from ..text_layout import wrap_text_cjk_n


# ── Spec (per-render content data) ──────────────────────────────────────────

@dataclass
class ChapterHeroCardSpec:
    """Chapter intro/hero card. inline_style is a per-spec override
    hatch — chapter component routes per-instance style edits through it
    so the property panel actually drives the render. Empty dict = use
    the resolved overlay_styles entry verbatim.
    """
    title: str = ""
    body: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    style_class: str = "default"
    inline_style: dict = field(default_factory=dict)
    kind: str = "chapter_hero_card"
    z_order: int = 46
    zone: str = "center"


# Legacy alias — overlays.py shim re-exports this name during PR 2~5.
ChapterHeroCardOverlay = ChapterHeroCardSpec


# ── Style (visual fields) ───────────────────────────────────────────────────

@dataclass
class ChapterHeroCardStyle:
    """Sidebar hero card — left/right-anchored vertical panel carrying
    a chapter title + multi-line body. Sits BESIDE the speaker rather
    than over them; defaults are translucent so the underlying video
    remains visible behind the card.

    Geometry: card width is a fixed fraction of the frame; height
    auto-fits the title + divider + body. Vertically centered.
    """
    # Title (large, top). Title-only mode is the default: body rendering
    # is gated by show_body so the hero card stays a high-recognition
    # broadcast-style topic flash, not a wall of summary text.
    title_color: str = "#FFFFFF"
    title_fontsize: int = 56
    title_bold: bool = True
    title_max_lines: int = 3
    # Body (smaller, multi-line). Hidden by default — flip show_body to
    # True to render the chapter's refined summary below the title.
    show_body: bool = False
    body_color: str = "#E5E7EB"
    body_fontsize: int = 22
    body_bold: bool = False
    body_max_chars_per_line: int = 14
    body_max_lines: int = 8
    # Card backdrop — broadcast-navy + heavy transparency so the video
    # behind the sidebar stays legible.
    bg_color: str = "#0F1B2C"
    bg_opacity: int = 55
    # Geometry — fractions of frame dim. Sidebar mode: anchored to
    # screen edge, vertically centered.
    position: str = "left"                  # "left" | "right"
    width_pct: float = 0.30                 # card width as fraction of frame
    margin_x_pct: float = 0.025             # offset from anchored edge
    padding_x_pct: float = 0.025
    padding_y_pct: float = 0.030
    title_body_gap_pct: float = 0.020
    # Accent stripe on the screen-edge side (broadcast convention).
    accent_color: str = "#DC2626"
    accent_width_pct: float = 0.005
    # Thin divider between title and body.
    divider_color: str = "#FFFFFF"
    divider_opacity: int = 30
    divider_height_px: int = 2
    # Animation — slide in from the screen edge + fade.
    fade_in_ms: int = 400
    fade_out_ms: int = 350
    slide_in_px: int = 60
    font: str = "Microsoft YaHei"


# ── Dialogue builder (consumed by news_desk_ass orchestrator) ──────────────

def build_dialogues(spec: ChapterHeroCardSpec, style: ChapterHeroCardStyle,
                     *, target_w: int, target_h: int) -> list[str]:
    """Sidebar hero card — left/right-anchored vertical panel.

    Composition: translucent backdrop + screen-edge accent stripe +
    title block + divider + body block. Slides in from the screen
    edge on enter, fades out on exit.
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

    # Pixel-fit wrap budget — the char "unit" in wrap_text_cjk_n is
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
    title_wrapped = wrap_text_cjk_n(
        title, title_budget, title_max_lines,
    ) if title else []
    body_wrapped = wrap_text_cjk_n(
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
    bg_alpha = ass_alpha(style.bg_opacity)
    band_body = ("{\\an7" + _anim(card_x_final, card_y)
                  + f"\\bord0\\shad0\\1c{bg_color}\\1a{bg_alpha}\\p1}}"
                  f"m 0 0 l {card_w} 0 {card_w} {card_h} 0 {card_h}"
                  "{\\p0}")
    lines.append(
        f"Dialogue: 0,{ass_time(spec.start_sec)},"
        f"{ass_time(spec.end_sec)},NewsDeskRect,,0,0,0,,{band_body}"
    )

    # Layer 1 — accent stripe on the screen-edge side.
    if accent_w > 0:
        acc_color = hex_color_to_ass(style.accent_color)
        acc_body = ("{\\an7" + _anim(accent_x, card_y)
                     + f"\\bord0\\shad0\\1c{acc_color}\\1a&H00&\\p1}}"
                     f"m 0 0 l {accent_w} 0 {accent_w} {card_h} 0 {card_h}"
                     "{\\p0}")
        lines.append(
            f"Dialogue: 1,{ass_time(spec.start_sec)},"
            f"{ass_time(spec.end_sec)},NewsDeskRect,,0,0,0,,{acc_body}"
        )

    text_left_x = card_x_final + text_left_offset
    title_top = card_y + pad_y

    # Layer 2 — divider (when both title and body exist).
    divider_y = title_top + n_title * title_size + gap_px
    if has_divider:
        div_color = hex_color_to_ass(style.divider_color)
        div_alpha = ass_alpha(style.divider_opacity)
        div_body = ("{\\an7" + _anim(text_left_x, divider_y)
                     + f"\\bord0\\shad0\\1c{div_color}\\1a{div_alpha}\\p1}}"
                     f"m 0 0 l {text_region_w} 0 {text_region_w} {divider_h} 0 {divider_h}"
                     "{\\p0}")
        lines.append(
            f"Dialogue: 2,{ass_time(spec.start_sec)},"
            f"{ass_time(spec.end_sec)},NewsDeskRect,,0,0,0,,{div_body}"
        )

    # Layer 3 — title (left-anchored within text region).
    if title_wrapped:
        title_color = hex_color_to_ass(style.title_color)
        joined = "\\N".join(ass_escape_text(ln) for ln in title_wrapped)
        # Anchor 7 = top-left.
        body_str = ("{\\an7" + _anim(text_left_x, title_top)
                     + f"\\fn{style.font}\\fs{title_size}"
                     f"\\1c{title_color}\\bord0\\shad0"
                     + ("\\b1" if style.title_bold else "")
                     + "}" + joined)
        lines.append(
            f"Dialogue: 3,{ass_time(spec.start_sec)},"
            f"{ass_time(spec.end_sec)},NewsDeskText,,0,0,0,,{body_str}"
        )

    # Layer 4 — body (left-anchored, below divider).
    if body_wrapped:
        body_color = hex_color_to_ass(style.body_color)
        joined = "\\N".join(ass_escape_text(ln) for ln in body_wrapped)
        body_top = (divider_y + divider_h + gap_px) if has_divider else title_top
        body_str = ("{\\an7" + _anim(text_left_x, body_top)
                     + f"\\fn{style.font}\\fs{body_size}"
                     f"\\1c{body_color}\\bord0\\shad0"
                     + ("\\b1" if style.body_bold else "")
                     + "}" + joined)
        lines.append(
            f"Dialogue: 4,{ass_time(spec.start_sec)},"
            f"{ass_time(spec.end_sec)},NewsDeskText,,0,0,0,,{body_str}"
        )

    return lines
