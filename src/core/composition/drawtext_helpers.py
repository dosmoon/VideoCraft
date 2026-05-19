"""Pure ffmpeg drawtext helpers — shared by primitives that emit
drawtext filter snippets (hook_text, outro_text, text_watermark).

Harvested verbatim from render.py during the PR 2 primitive split.
Drawtext filter strings are mostly stable across primitives; the
only role-specific parts are position + enable expression. The
shared helper here covers both. Behavior preserved byte-for-byte —
the golden tests under tests/composition/golden/ verify this.

Stays at the engine level (not under primitives/) because multiple
primitive files import from here — keeps the import graph acyclic.
"""

from __future__ import annotations

import os
import tempfile

from .fonts import hook_outro_font_path, y_expr_for_position
from .text_layout import wrap_hook_outro


# Default field values for drawtext_filter when an element.style omits
# them. Sizes carried as fractions of the short edge per the engine-wide
# normalization — drawtext multiplies by short_edge at render to get
# pixel values.
_HOOK_OUTRO_DEFAULTS = {
    "font": "Microsoft YaHei",
    "size_pct": 0.05,
    "color": "#FFFFFF",
    "bg_color": "#000000",
    "bg_opacity": 70,
    "stroke_color": "#000000",
    "stroke_pct": 0.003,
    "box_padding_pct": 0.012,
    "hook_position": "upper-third",
    "outro_position": "lower-third",
}


def hex_to_drawtext_rgba(hex_color: str, alpha: float) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    a = max(0.0, min(1.0, alpha))
    if len(h) == 6:
        return f"#{h.upper()}@{a:.2f}"
    return f"white@{a:.2f}"


# Line height for stacked drawtext lines is read from the font itself
# (PIL ImageFont.getmetrics → ascender + descender), not hardcoded as
# a fraction of fontsize. See text_layout.font_line_height_px.
# Magic 1.x constants here would only paper over per-font metric
# differences (Microsoft YaHei: ~1.37·EM, Arial: ~1.15·EM).


def drawtext_filter(text: str, *, role: str, style: dict,
                      duration: float, aspect_ratio: tuple[int, int],
                      tmp_files: list[str],
                      short_edge: int = 1080,
                      target_h: int = 1080) -> str:
    """Build a drawtext snippet for hook (first hook_duration_sec) or outro
    (last outro_duration_sec). role ∈ {'hook', 'outro'}.

    `style` is a flat dict with hook/outro rendering fields — font, size,
    color, bg_color, bg_opacity, stroke_color, stroke_width, box_padding,
    hook_position / outro_position, hook_duration_sec / outro_duration_sec.
    The legacy HookOutroStyle dataclass is no longer required at render
    time; engine reads dict directly.

    Multi-line behaviour: text is wrapped to fit the target frame width
    via core.composition.text_layout.wrap_hook_outro (same call as the
    WebView preview); EACH wrapped line emits its own drawtext sub-filter
    with `x=(w-text_w)/2` so each line is centered to its own width
    (single-textfile drawtext left-aligns lines to the widest one's
    block, which diverges from the per-line centered preview canvas).
    Line vertical spacing is `_LINE_HEIGHT_PCT * fontsize`, matching the
    preview's lineHeight factor.
    """
    if not text:
        return ""

    def _g(key, default=None):
        v = style.get(key)
        if v is None:
            v = _HOOK_OUTRO_DEFAULTS.get(key, default)
        return v

    font = _g("font")
    # Resolve px from frame-height pct (engine-wide font sizing
    # convention — see core/composition/layout.py).
    from .layout import font_size_px
    size = font_size_px(float(_g("size_pct")), target_h)
    color = _g("color")
    font_path = hook_outro_font_path(font)
    lines = wrap_hook_outro(text, aspect_ratio, font_path, size,
                              short_edge=short_edge)
    if not lines:
        return ""

    if role == "hook":
        position = _g("hook_position")
        hook_dur = float(_g("hook_duration_sec", 5.0))
        enable = f"between(t,0,{hook_dur})"
    else:
        position = _g("outro_position")
        outro_dur = float(_g("outro_duration_sec", 5.0))
        start = max(0.0, duration - outro_dur)
        enable = f"between(t,{start},{duration})"

    fontfile_ff = font_path.replace(":", "\\:")
    from .text_layout import font_line_height_px, measure_max_line_width_px
    line_h = font_line_height_px(font_path, size)
    total_h = line_h * len(lines)
    # Vertical anchor of the multi-line block top (matches the y= expr
    # the canvas uses via _hoYForPosition). We replace text_h with a
    # known total_h so the position formula evaluates server-side.
    top_y_expr = _block_top_y(position, total_h)

    stroke_width = font_size_px(float(_g("stroke_pct")), target_h)
    stroke_color = _g("stroke_color")
    bg_opacity = int(_g("bg_opacity"))
    bg_color = _g("bg_color")
    box_padding = font_size_px(float(_g("box_padding_pct")), target_h)

    snippets: list[str] = []

    # Background: one unified drawbox spanning the widest line + padding,
    # so all lines share a single uniform rectangle (matching the canvas
    # `widestLine + 2*padding` block). Per-line `box=1` on drawtext
    # would draw N independent boxes sized to each line's text_w —
    # short lines get narrow boxes, the preview ≢ render divergence
    # the user hit.
    if bg_opacity > 0:
        widest_px = measure_max_line_width_px(lines, font_path, size)
        opacity = max(0.0, min(1.0, bg_opacity / 100.0))
        box_w = widest_px + 2 * box_padding
        # Match canvas's vertical extents (boxY = topY - 0.4*padding,
        # boxH = totalTextHeight + 1.2*padding).
        box_y_offset = int(round(0.4 * box_padding))
        box_h = total_h + int(round(1.2 * box_padding))
        snippets.append(
            f"drawbox=x=(w-{box_w})/2"
            f":y=({top_y_expr})-{box_y_offset}"
            f":w={box_w}:h={box_h}"
            f":color={bg_color}@{opacity:.2f}:t=fill"
            f":enable='{enable}'")

    for i, line in enumerate(lines):
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"composition-{role}-{os.getpid()}-{id(text)}-{i}.txt",
        )
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            continue
        tmp_files.append(tmp_path)
        textfile_ff = tmp_path.replace("\\", "/").replace(":", "\\:")
        parts = [
            f"drawtext=textfile='{textfile_ff}'",
            f"fontfile='{fontfile_ff}'",
            f"fontcolor={color}",
            f"fontsize={size}",
            "x=(w-text_w)/2",
            f"y=({top_y_expr})+{i * line_h}",
        ]
        if stroke_width > 0:
            parts.append(f"borderw={stroke_width}")
            parts.append(f"bordercolor={stroke_color}")
        parts.append(f"enable='{enable}'")
        snippets.append(":".join(parts))

    return ",".join(snippets)


def _block_top_y(position: str, total_h: int) -> str:
    """ffmpeg-expression for the top Y of a multi-line drawtext block,
    given the total wrapped block height in pixels. Mirrors
    canvas-side _hoYForPosition exactly."""
    return {
        "top":          "h*0.08",
        "upper-third":  "h*0.25",
        "center":       f"(h-{total_h})/2",
        "lower-third":  f"h*0.65 - {total_h}/2",
        "bottom":       f"h*0.85 - {total_h}",
    }.get(position, "h*0.25")
