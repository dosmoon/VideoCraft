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


# Default field values for drawtext_filter when an element.style omits them.
# Pulled from the original HookOutroStyle dataclass defaults so behavior
# stays identical pre/post engine-style decoupling.
_HOOK_OUTRO_DEFAULTS = {
    "font": "Microsoft YaHei",
    "size": 48,
    "color": "#FFFFFF",
    "bg_color": "#000000",
    "bg_opacity": 70,
    "stroke_color": "#000000",
    "stroke_width": 3,
    "box_padding": 10,
    "hook_position": "upper-third",
    "outro_position": "lower-third",
}


def hex_to_drawtext_rgba(hex_color: str, alpha: float) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    a = max(0.0, min(1.0, alpha))
    if len(h) == 6:
        return f"#{h.upper()}@{a:.2f}"
    return f"white@{a:.2f}"


def drawtext_filter(text: str, *, role: str, style: dict,
                      duration: float, aspect_ratio: tuple[int, int],
                      tmp_files: list[str], short_edge: int = 1080) -> str:
    """Build a drawtext snippet for hook (first hook_duration_sec) or outro
    (last outro_duration_sec). role ∈ {'hook', 'outro'}.

    `style` is a flat dict with hook/outro rendering fields — font, size,
    color, bg_color, bg_opacity, stroke_color, stroke_width, box_padding,
    hook_position / outro_position, hook_duration_sec / outro_duration_sec.
    The legacy HookOutroStyle dataclass is no longer required at render
    time; engine reads dict directly.

    Multi-line behaviour: text is wrapped to fit the target frame width
    via core.composition.text_layout.wrap_hook_outro (same call as the
    WebView preview), then written to a temp file consumed by drawtext's
    `textfile=` parameter. The temp file is appended to tmp_files for the
    caller to clean up after ffmpeg returns.
    """
    if not text:
        return ""

    def _g(key, default=None):
        v = style.get(key)
        if v is None:
            v = _HOOK_OUTRO_DEFAULTS.get(key, default)
        return v

    font = _g("font")
    size = int(_g("size"))
    color = _g("color")
    font_path = hook_outro_font_path(font)
    lines = wrap_hook_outro(text, aspect_ratio, font_path, size,
                              short_edge=short_edge)
    if not lines:
        return ""
    wrapped = "\n".join(lines)

    tmp_path = os.path.join(
        tempfile.gettempdir(),
        f"composition-{role}-{os.getpid()}-{id(text)}.txt",
    )
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(wrapped)
    except OSError:
        return ""
    tmp_files.append(tmp_path)

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
    textfile_ff = tmp_path.replace("\\", "/").replace(":", "\\:")
    y_expr = y_expr_for_position(position)
    parts = [
        f"drawtext=textfile='{textfile_ff}'",
        f"fontfile='{fontfile_ff}'",
        f"fontcolor={color}",
        f"fontsize={size}",
        "x=(w-text_w)/2",
        f"y={y_expr}",
    ]
    stroke_width = int(_g("stroke_width"))
    if stroke_width > 0:
        parts.append(f"borderw={stroke_width}")
        parts.append(f"bordercolor={_g('stroke_color')}")
    bg_opacity = int(_g("bg_opacity"))
    if bg_opacity > 0:
        parts.append("box=1")
        opacity = max(0.0, min(1.0, bg_opacity / 100.0))
        parts.append(f"boxcolor={_g('bg_color')}@{opacity:.2f}")
        parts.append(f"boxborderw={int(_g('box_padding'))}")
    parts.append(f"enable='{enable}'")
    return ":".join(parts)
