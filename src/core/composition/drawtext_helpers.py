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
from .style import HookOutroStyle
from .text_layout import wrap_hook_outro


def hex_to_drawtext_rgba(hex_color: str, alpha: float) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    a = max(0.0, min(1.0, alpha))
    if len(h) == 6:
        return f"#{h.upper()}@{a:.2f}"
    return f"white@{a:.2f}"


def drawtext_filter(text: str, *, role: str, ho: HookOutroStyle,
                      duration: float, aspect_ratio: tuple[int, int],
                      tmp_files: list[str], short_edge: int = 1080) -> str:
    """Build a drawtext snippet for hook (first hook_duration_sec) or outro
    (last outro_duration_sec). role ∈ {'hook', 'outro'}.

    Multi-line behaviour: text is wrapped to fit the target frame width
    via core.composition.text_layout.wrap_hook_outro (same call as the
    WebView preview), then written to a temp file consumed by drawtext's
    `textfile=` parameter. `text=` doesn't reliably accept newlines, so
    going through a file is the only escape-safe path. The temp file is
    appended to tmp_files for the caller to clean up after ffmpeg returns.

    `short_edge` lets passthrough renders pass the actual source short
    edge so wrap budgets scale with the real frame width.
    """
    if not text:
        return ""

    font_path = hook_outro_font_path(ho.font)
    lines = wrap_hook_outro(text, aspect_ratio, font_path, ho.size,
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
        position = ho.hook_position
        enable = f"between(t,0,{ho.hook_duration_sec})"
    else:
        position = ho.outro_position
        start = max(0.0, duration - ho.outro_duration_sec)
        enable = f"between(t,{start},{duration})"

    fontfile_ff = font_path.replace(":", "\\:")
    textfile_ff = tmp_path.replace("\\", "/").replace(":", "\\:")
    y_expr = y_expr_for_position(position)
    parts = [
        f"drawtext=textfile='{textfile_ff}'",
        f"fontfile='{fontfile_ff}'",
        f"fontcolor={ho.color}",
        f"fontsize={ho.size}",
        "x=(w-text_w)/2",
        f"y={y_expr}",
    ]
    if ho.stroke_width > 0:
        parts.append(f"borderw={int(ho.stroke_width)}")
        parts.append(f"bordercolor={ho.stroke_color}")
    if ho.bg_opacity > 0:
        parts.append("box=1")
        opacity = max(0.0, min(1.0, ho.bg_opacity / 100.0))
        parts.append(f"boxcolor={ho.bg_color}@{opacity:.2f}")
        parts.append(f"boxborderw={int(ho.box_padding)}")
    parts.append(f"enable='{enable}'")
    return ":".join(parts)
