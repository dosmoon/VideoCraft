"""Font name → file path resolution + position/alignment helpers.

Used by the render layer to translate user-facing style fields (font name,
position preset) into the concrete ffmpeg drawtext / ASS strings.
"""

from __future__ import annotations

import os


# Windows-bundled font name → file path. Names are what the user picks in
# the workbench dropdowns; lookup is case-insensitive. Unknown names fall
# back to msyh.ttc (Microsoft YaHei) which ships on every zh-CN Windows.
# Latin-only fonts (Arial / Times New Roman) won't render CJK glyphs.
_FONT_MAP: dict[str, str] = {
    "microsoft yahei":   "C:/Windows/Fonts/msyh.ttc",
    "微软雅黑":          "C:/Windows/Fonts/msyh.ttc",
    "simhei":            "C:/Windows/Fonts/simhei.ttf",
    "黑体":              "C:/Windows/Fonts/simhei.ttf",
    "simsun":            "C:/Windows/Fonts/simsun.ttc",
    "宋体":              "C:/Windows/Fonts/simsun.ttc",
    "kaiti":             "C:/Windows/Fonts/simkai.ttf",
    "楷体":              "C:/Windows/Fonts/simkai.ttf",
    "dengxian":          "C:/Windows/Fonts/Deng.ttf",
    "等线":              "C:/Windows/Fonts/Deng.ttf",
    "arial":             "C:/Windows/Fonts/arial.ttf",
    "times new roman":   "C:/Windows/Fonts/times.ttf",
}

# Vertical anchor presets — mapped to ffmpeg drawtext y= expressions in
# y_expr_for_position(). Persisted in style JSON as canonical strings.
HOOK_OUTRO_POSITIONS: tuple[str, ...] = (
    "top", "upper-third", "center", "lower-third", "bottom"
)


def hook_outro_font_path(font_name: str) -> str:
    """Resolve a user-facing font name to an absolute Windows TTF path.

    Falls back to Microsoft YaHei when the name isn't recognized or the
    target file is absent — keeps a typo from killing the render.
    """
    fallback = "C:/Windows/Fonts/msyh.ttc"
    if not font_name:
        return fallback
    raw = font_name.strip()
    # User-supplied absolute path: trust it if it exists.
    if os.path.isfile(raw):
        return raw.replace("\\", "/")
    path = _FONT_MAP.get(raw.lower())
    if path and os.path.isfile(path):
        return path
    return fallback


def y_expr_for_position(position: str) -> str:
    """Translate a position preset to an ffmpeg drawtext y= expression."""
    return {
        "top":          "h*0.08",
        "upper-third":  "h*0.25",
        "center":       "(h-text_h)/2",
        "lower-third":  "h*0.65",
        "bottom":       "h*0.85",
    }.get(position, "h*0.25")


def ass_alignment_for_position(position: str) -> int:
    """ASS alignment code for a top/middle/bottom subtitle position."""
    return {"top": 8, "middle": 5, "bottom": 2}.get(position, 2)
