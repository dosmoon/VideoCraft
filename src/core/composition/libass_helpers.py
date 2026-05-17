"""Pure libass helpers — shared by all primitive renderers that emit
ASS dialogue strings. No side effects, no file IO.

Harvested verbatim from the old news_desk_overlays.py + render.py
during the PR 2 primitive split. Behavior preserved byte-for-byte —
the golden tests under tests/composition/golden/ verify this.

Lives at the engine level (not under primitives/) because multiple
primitive files import from here; keeps the import graph acyclic.
"""

from __future__ import annotations

from core.subtitle_ops import hex_color_to_ass


# ── Alpha / color encoding ──────────────────────────────────────────────────

def ass_alpha(opacity_0_100: int) -> str:
    """Opacity (0=fully transparent, 100=opaque) → ASS \\1a hex value
    (00=opaque, FF=transparent)."""
    o = max(0, min(100, int(opacity_0_100)))
    a = int(round((100 - o) * 255 / 100))
    return f"&H{a:02X}&"


def ass_bgr_with_alpha(hex_color: str, opacity_0_100: int) -> str:
    """libass colour with alpha — `&HAABBGGRR&`. 0 = fully opaque, 255 =
    fully transparent. opacity_0_100 follows the dataclass convention
    (0 = transparent, 100 = opaque)."""
    h = (hex_color or "#000000").lstrip("#")
    if len(h) != 6:
        h = "000000"
    rr, gg, bb = h[0:2], h[2:4], h[4:6]
    o = max(0, min(100, int(opacity_0_100)))
    aa = int(round((100 - o) * 255 / 100))
    return f"&H{aa:02X}{bb}{gg}{rr}&"


# ── Time / text formatting ──────────────────────────────────────────────────

def ass_time(sec: float) -> str:
    """Seconds → ASS H:MM:SS.cc timestamp (centisecond precision)."""
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def ass_escape_text(text: str) -> str:
    r"""Escape text for an ASS Dialogue Text field. ASS-special chars
    are `{`, `}`, `\` (literal backslash-N already means line break)."""
    if not text:
        return ""
    return (text.replace("\\", "\\\\")
                .replace("{", "\\{")
                .replace("}", "\\}")
                .replace("\n", "\\N"))


# ── Geometry / measurement ──────────────────────────────────────────────────

def est_text_width_px(text: str, fontsize: int) -> float:
    """Quick text-width estimate in pixels. Conservative — overshoots
    slightly for Latin so the bg bar never clips the trailing glyph.
    Real measurement would need PIL + the actual font; for v0.1 we use
    the same heuristic compute_subtitle_max_chars uses internally."""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    latin = len(text) - cjk
    return cjk * fontsize + latin * fontsize * 0.55


# ── Dialogue builders (low-level, primitive-agnostic) ──────────────────────

def rect_dialogue(start: float, end: float, *,
                    x: int, y: int, w: int, h: int,
                    color_hex: str, opacity: int, layer: int = 0) -> str:
    """One libass drawing-mode Dialogue line that paints a filled
    axis-aligned rectangle at (x, y) of size (w, h). Anchored top-left
    (\\an7) so the coords are unambiguous."""
    color_ass = hex_color_to_ass(color_hex)
    alpha = ass_alpha(opacity)
    body = (f"{{\\an7\\pos({x},{y})\\bord0\\shad0"
            f"\\1c{color_ass}\\1a{alpha}\\p1}}"
            f"m 0 0 l {w} 0 {w} {h} 0 {h}"
            f"{{\\p0}}")
    return (f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},"
            f"NewsDeskRect,,0,0,0,,{body}")


def text_dialogue(start: float, end: float, *,
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
    body = "{" + "".join(body_parts) + "}" + ass_escape_text(text)
    return (f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},"
            f"NewsDeskText,,0,0,0,,{body}")


# ── ASS file header ─────────────────────────────────────────────────────────

ASS_HEADER_TMPL = """[Script Info]
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
