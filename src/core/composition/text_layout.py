"""Single source of truth for overlay text wrapping.

Both the ffmpeg render path and the WebView preview consume the SAME wrap
output from this module. JS-side string wrapping is forbidden for overlays
that get burned into the output — preview MUST receive pre-wrapped line
lists from Python so what the user sees matches what the final mp4 will
show.

Subtitles already follow this pattern via core.subtitle_ops.split_subtitle
(split into more timed cues, each one line). This module handles the
hook/outro/long-watermark family where text isn't time-sliced but still
needs to wrap to fit the crop.
"""

from __future__ import annotations

from typing import Callable, Optional


def wrap_overlay_text(text: str, max_width_px: float,
                       font_path: Optional[str],
                       font_size_px: int) -> list[str]:
    """Wrap `text` to a list of lines each fitting within `max_width_px`.

    Measurement: prefers PIL ImageFont.getlength against the actual font
    file used by the render path. Falls back to a CJK-aware heuristic
    (fontsize per CJK char, fontsize*0.55 per Latin char) when PIL is
    unavailable or the font fails to load.

    Breaking: CJK-friendly char-by-char wrap so a long Chinese run-on
    doesn't render as one overflowing line. Single very-long token is OK —
    we just place it on its own line as best we can.

    Returns [] for empty input.
    """
    if not text:
        return []
    if max_width_px <= 0:
        return [text]

    measure = _pil_measurer(font_path, font_size_px) \
              or _heuristic_measurer(font_size_px)

    if measure(text) <= max_width_px:
        return [text]

    lines: list[str] = []
    buf = ""
    for ch in text:
        candidate = buf + ch
        if measure(candidate) > max_width_px and buf:
            lines.append(buf)
            buf = ch
        else:
            buf = candidate
    if buf:
        lines.append(buf)
    return lines


# ── Width measurement backends ─────────────────────────────────────────────

def _pil_measurer(font_path: Optional[str],
                   font_size_px: int) -> Optional[Callable[[str], float]]:
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    candidates: list[str] = []
    if font_path:
        candidates.append(font_path)
    candidates += [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if not p:
            continue
        try:
            font = ImageFont.truetype(p, size=font_size_px)
            return lambda s, _f=font: _f.getlength(s)
        except Exception:
            continue
    return None


def _heuristic_measurer(font_size_px: int) -> Callable[[str], float]:
    def measure(s: str) -> float:
        w = 0.0
        for ch in s:
            # Rough cutoff for CJK / fullwidth ideographic ranges.
            if ord(ch) > 0x2E7F:
                w += font_size_px
            else:
                w += font_size_px * 0.55
        return w
    return measure


# ── High-level helper for hook/outro convention ────────────────────────────

def target_width_for_aspect(aspect_ratio: tuple[int, int],
                              short_edge: int = 1080) -> int:
    """Mirror render._target_dims_for_aspect width logic so wrap callers
    don't have to re-derive it."""
    aw, ah = aspect_ratio
    if aw < ah:
        return short_edge
    return round(short_edge * aw / ah)


def wrap_hook_outro(text: str, aspect_ratio: tuple[int, int],
                     font_path: Optional[str], font_size_px: int) -> list[str]:
    """Convention: hook/outro overlays wrap to 88% of the target frame
    width (6% safe margin each side). Single source for both render and
    preview."""
    target_w = target_width_for_aspect(aspect_ratio)
    return wrap_overlay_text(text, target_w * 0.88, font_path, font_size_px)
