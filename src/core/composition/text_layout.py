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


def font_line_height_px(font_path: Optional[str], font_size_px: int) -> int:
    """Per-line vertical advance for stacking drawtext lines without
    overlap. Reads the font's own `ascender + descender` via PIL
    (PIL.ImageFont.getmetrics shares its source with FreeType, which
    is what ffmpeg drawtext uses to size each line's text box).

    Different fonts report different totals — Microsoft YaHei reserves
    ~1.37·EM for CJK win-metrics headroom, Arial sits near 1.15·EM.
    Returning the font's actual metric value makes drawtext lines and
    preview canvas lines stack with the same gap, no per-font tuning.

    Falls back to `round(font_size_px * 1.4)` only when PIL can't load
    the font (CJK win-metric worst case)."""
    try:
        from PIL import ImageFont
        if font_path:
            f = ImageFont.truetype(font_path, size=font_size_px)
            ascent, descent = f.getmetrics()
            return max(font_size_px, ascent + descent)
    except Exception:
        pass
    return int(round(font_size_px * 1.4))


def wrap_hook_outro(text: str, aspect_ratio: tuple[int, int],
                     font_path: Optional[str], font_size_px: int,
                     *, short_edge: int = 1080) -> list[str]:
    """Convention: hook/outro overlays wrap to 88% of the target frame
    width (6% safe margin each side). Single source for both render and
    preview. Pass `short_edge` to override the default 1080 (e.g. for
    passthrough renders preserving source resolution)."""
    target_w = target_width_for_aspect(aspect_ratio, short_edge)
    return wrap_overlay_text(text, target_w * 0.88, font_path, font_size_px)


# ── CJK character-budget wrap (chapter card / topic strip family) ──────────

def wrap_text_cjk_n(text: str, max_chars: int, max_lines: int) -> list[str]:
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
