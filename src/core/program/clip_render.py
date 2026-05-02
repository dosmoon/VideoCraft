"""
core/program/clip_render.py — Style preview composition.

Pure PIL rendering: given a ClipProjectConfig + a source frame, compose a
preview image that approximates the final output's framing, subtitles,
watermark, and Hook/Outro card. Used by the workbench's "输出样式" tab to
let the user see their settings before committing.

Not a perfect preview: font face is approximated to the closest local TTF
(real export uses the user-typed name via ffmpeg's libass/drawtext, which
honors arbitrary system fonts). Position, size, color, stroke, watermark
placement, aspect crop are all faithful.

Public:
    compose_style_preview(mode, config, source_frame=None, target_height=240)
        -> PIL.Image.Image
"""

from __future__ import annotations

import os

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from core.program.clip import ClipProjectConfig


_PLACEHOLDER_BG = (40, 40, 48)
_PLACEHOLDER_GRID = (60, 60, 70)
_DEFAULT_SAMPLE_TEXT_PRIMARY = "Sample subtitle"
_DEFAULT_SAMPLE_TEXT_SECONDARY = "示例字幕"
_DEFAULT_HOOK_TEXT = "示例 Hook 文案"
_DEFAULT_OUTRO_TEXT = "示例 Outro 文案"


# ── Font resolution ────────────────────────────────────────────────────────

def _resolve_font(name: str, size: int):
    """Best-effort TTF lookup. Tries the user's font name first (Windows
    Fonts dir), then a small list of CJK-capable fallbacks. Final fallback
    is PIL's bitmap font which lacks CJK glyphs but at least renders Latin.
    """
    if not _PIL_OK:
        return None
    name = (name or "").strip()
    candidates: list[str] = []
    if name:
        # Try common path layouts for the typed name.
        for ext in (".ttf", ".ttc", ".otf"):
            candidates.append(os.path.join(
                "C:/Windows/Fonts", name.lower() + ext))
            candidates.append(os.path.join(
                "C:/Windows/Fonts", name + ext))
    # CJK-capable fallbacks (Windows). PIL load_default has no CJK glyphs.
    candidates += [
        "C:/Windows/Fonts/msyh.ttc",      # Microsoft YaHei
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/PingFang.ttc",       # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


# ── Geometry helpers ───────────────────────────────────────────────────────

def _aspect_size(aspect: str, target_height: int) -> tuple[int, int]:
    try:
        w, h = aspect.split(":", 1)
        w, h = int(w), int(h)
    except Exception:
        w, h = 9, 16
    height = target_height
    width = max(1, int(round(target_height * w / h)))
    return (width, height)


def _placeholder_frame(size: tuple[int, int]) -> "Image.Image":
    """Build a dark gray frame with a faint diagonal grid as a visual hint
    when no real video keyframe is available."""
    img = Image.new("RGB", size, _PLACEHOLDER_BG)
    draw = ImageDraw.Draw(img)
    step = 24
    for x in range(-size[1], size[0] + size[1], step):
        draw.line([(x, 0), (x + size[1], size[1])],
                   fill=_PLACEHOLDER_GRID, width=1)
    # "No source" note in the corner
    font = _resolve_font("", 11)
    if font is not None:
        msg = "no source frame"
        draw.text((6, size[1] - 18), msg, fill=(110, 110, 120), font=font)
    return img


def _fit_aspect(source: "Image.Image", target: tuple[int, int]) -> "Image.Image":
    """Crop `source` to match `target`'s aspect (centered), then resize."""
    sw, sh = source.size
    tw, th = target
    if sh == 0 or th == 0:
        return source.resize(target)
    src_ratio = sw / sh
    tgt_ratio = tw / th
    if src_ratio > tgt_ratio:
        # source wider than target → crop sides
        new_w = int(round(sh * tgt_ratio))
        x0 = (sw - new_w) // 2
        cropped = source.crop((x0, 0, x0 + new_w, sh))
    else:
        # source taller → crop top/bottom
        new_h = int(round(sw / tgt_ratio))
        y0 = (sh - new_h) // 2
        cropped = source.crop((0, y0, sw, y0 + new_h))
    return cropped.resize(target, Image.LANCZOS)


def _hex_to_rgb(hex_str: str, default=(255, 255, 255)) -> tuple[int, int, int]:
    s = (hex_str or "").strip().lstrip("#")
    if len(s) != 6:
        return default
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return default


# ── Layer composers ────────────────────────────────────────────────────────

def _draw_subtitle(canvas: "Image.Image",
                    config: ClipProjectConfig) -> None:
    sub = config.subtitle
    w, h = canvas.size
    # Lines: each enabled track contributes one line. sub1 = primary
    # (typically Chinese, bold, larger), sub2 = secondary.
    lines: list[tuple[str, "ImageFont.ImageFont", tuple[int,int,int], bool]] = []
    for line_cfg in (sub.sub1, sub.sub2):
        if not line_cfg.enabled:
            continue
        # CJK sample if line is Chinese; Latin sample otherwise.
        sample_text = (_DEFAULT_SAMPLE_TEXT_SECONDARY
                       if line_cfg.is_chinese
                       else _DEFAULT_SAMPLE_TEXT_PRIMARY)
        scaled_size = max(8, int(round(line_cfg.fontsize * h / 1080.0 * 4)))
        font = _resolve_font("", scaled_size)
        if font is None:
            continue
        color = _hex_to_rgb(line_cfg.color, (255, 255, 255))
        lines.append((sample_text, font, color, line_cfg.bold))

    if not lines:
        return
    draw = ImageDraw.Draw(canvas)

    stroke_color = _hex_to_rgb(sub.stroke_color, (0, 0, 0))
    stroke_width = max(0, int(sub.stroke_width))

    # Stack lines vertically with a small gap.
    line_gap = max(2, h // 80)

    def _measure(text: str, font) -> tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])

    sizes = [_measure(t, f) for (t, f, _c, _b) in lines]
    total_h = sum(s[1] for s in sizes) + line_gap * (len(lines) - 1)

    margin = max(8, h // 20)
    if sub.position == "top":
        y_start = margin
    elif sub.position == "middle":
        y_start = (h - total_h) // 2
    else:  # bottom
        y_start = h - margin - total_h

    cur_y = y_start
    for i, (text, font, color, bold) in enumerate(lines):
        tw_, th_ = sizes[i]
        x = (w - tw_) // 2
        # Approximate bold by drawing the text twice with 1px offset when
        # the font face itself doesn't have a bold variant available.
        draw.text((x, cur_y), text, font=font, fill=color,
                  stroke_width=stroke_width, stroke_fill=stroke_color)
        if bold:
            draw.text((x + 1, cur_y), text, font=font, fill=color,
                      stroke_width=stroke_width, stroke_fill=stroke_color)
        cur_y += th_ + line_gap


def _draw_watermark(canvas: "Image.Image",
                     config: ClipProjectConfig) -> None:
    wm = config.watermark
    if not wm.enabled:
        return
    if wm.type == "text":
        _draw_text_watermark(canvas, wm)
    else:
        _draw_image_watermark(canvas, wm)


def _watermark_anchor(canvas_size: tuple[int, int],
                       box_size: tuple[int, int],
                       position: str) -> tuple[int, int]:
    w, h = canvas_size
    box_w, box_h = box_size
    margin = max(4, w // 30)
    if position == "top-left":
        return (margin, margin)
    if position == "top-right":
        return (w - margin - box_w, margin)
    if position == "bottom-left":
        return (margin, h - margin - box_h)
    return (w - margin - box_w, h - margin - box_h)  # bottom-right


def _draw_image_watermark(canvas: "Image.Image", wm) -> None:
    w, h = canvas.size
    box_w = max(8, int(round(w * max(0.0, min(1.0, wm.image_scale)))))
    box_h = max(8, int(round(box_w * 0.4)))
    x, y = _watermark_anchor((w, h), (box_w, box_h), wm.position)

    overlay = None
    if wm.image_path and os.path.isfile(wm.image_path):
        try:
            with Image.open(wm.image_path) as im:
                im.load()
                overlay = im.convert("RGBA").resize(
                    (box_w, box_h), Image.LANCZOS)
                op = max(0, min(100, wm.image_opacity))
                if op < 100:
                    alpha = overlay.split()[-1].point(
                        lambda v, k=op: int(v * k / 100.0))
                    overlay.putalpha(alpha)
        except Exception:
            overlay = None

    if overlay is None:
        overlay = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        op = max(0, min(100, wm.image_opacity))
        d.rectangle([(0, 0), (box_w - 1, box_h - 1)],
                    outline=(220, 220, 220, int(op * 2.55)),
                    width=2)
        wm_font = _resolve_font("", max(8, box_h // 2))
        if wm_font is not None:
            label = "WM"
            bbox = d.textbbox((0, 0), label, font=wm_font)
            tw_ = bbox[2] - bbox[0]
            th_ = bbox[3] - bbox[1]
            d.text(((box_w - tw_) // 2, (box_h - th_) // 2 - 2),
                   label, fill=(220, 220, 220, int(op * 2.55)),
                   font=wm_font)

    canvas.paste(overlay, (x, y), overlay)


def _draw_text_watermark(canvas: "Image.Image", wm) -> None:
    w, h = canvas.size
    text = (wm.text or "").strip() or "@watermark"
    scaled_size = max(8, int(round(wm.text_fontsize * h / 1080.0 * 4)))
    font = _resolve_font("", scaled_size)
    if font is None:
        return
    color = _hex_to_rgb(wm.text_color, (255, 255, 255))
    op = max(0, min(100, wm.text_opacity))

    # Render text onto an RGBA layer first to apply opacity uniformly.
    tmp_draw = ImageDraw.Draw(canvas)
    bbox = tmp_draw.textbbox((0, 0), text, font=font)
    tw_ = bbox[2] - bbox[0]
    th_ = bbox[3] - bbox[1]
    pad_x, pad_y = 4, 2
    overlay = Image.new("RGBA", (tw_ + pad_x * 2, th_ + pad_y * 2),
                         (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    fill = color + (int(op * 2.55),)
    stroke = (0, 0, 0, int(op * 2.55))
    d.text((pad_x, pad_y), text, font=font, fill=fill,
           stroke_width=2, stroke_fill=stroke)
    x, y = _watermark_anchor((w, h), overlay.size, wm.position)
    canvas.paste(overlay, (x, y), overlay)


def _draw_hook_outro_card(target: tuple[int, int],
                            config: ClipProjectConfig,
                            text: str) -> "Image.Image":
    """Standalone Hook/Outro card preview — solid bg + centered text."""
    bg = _hex_to_rgb(config.hook_outro.bg_color, (0, 0, 0))
    fg = _hex_to_rgb(config.hook_outro.color, (255, 255, 255))
    opacity = max(0, min(100, config.hook_outro.bg_opacity))
    bg_rgba = bg + (int(round(opacity * 2.55)),)
    canvas = Image.new("RGB", target, (16, 16, 16))   # dim "video" backdrop
    overlay = Image.new("RGBA", target, bg_rgba)
    canvas.paste(overlay, (0, 0), overlay)
    draw = ImageDraw.Draw(canvas)
    scaled_size = max(10, int(round(
        config.hook_outro.size * target[1] / 1080.0 * 4)))
    font = _resolve_font(config.hook_outro.font, scaled_size)
    if font is not None:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw_ = bbox[2] - bbox[0]
        th_ = bbox[3] - bbox[1]
        x = (target[0] - tw_) // 2
        y = (target[1] - th_) // 2
        draw.text((x, y), text, font=font, fill=fg)
    return canvas


# ── Public API ─────────────────────────────────────────────────────────────

def compose_style_preview(mode: str,
                            config: ClipProjectConfig,
                            source_frame: "Image.Image | None" = None,
                            target_height: int = 240) -> "Image.Image | None":
    """Render a single still preview of the current style.

    Args:
        mode: "main" | "hook" | "outro"
        config: ClipProjectConfig in effect
        source_frame: PIL Image of a real video frame (any size); cropped
            and resized to the chosen aspect. None → placeholder.
        target_height: preview height in pixels; width derives from aspect.

    Returns: composed RGB Image, or None when PIL is unavailable.
    """
    if not _PIL_OK:
        return None
    target = _aspect_size(config.aspect, target_height)
    if mode == "hook":
        return _draw_hook_outro_card(target, config, _DEFAULT_HOOK_TEXT)
    if mode == "outro":
        return _draw_hook_outro_card(target, config, _DEFAULT_OUTRO_TEXT)
    # mode = "main"
    if source_frame is None:
        canvas = _placeholder_frame(target)
    else:
        try:
            canvas = _fit_aspect(source_frame.convert("RGB"), target)
        except Exception:
            canvas = _placeholder_frame(target)
    _draw_watermark(canvas, config)
    _draw_subtitle(canvas, config)
    return canvas


__all__ = ["compose_style_preview"]
