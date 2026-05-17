"""text_watermark primitive — corner-anchored text watermark via ffmpeg
drawtext filter.

WatermarkStyle currently still lives in style.py with a `type`
discriminator distinguishing text vs image; this primitive uses only
the text-mode fields. PR 5 splits WatermarkStyle into two narrow
primitives per Axis 7.5; for PR 2 we keep the unified dataclass.
"""

from __future__ import annotations

import os
import tempfile

from ..drawtext_helpers import hex_to_drawtext_rgba
from ..layout import pixel_offset
from ..style import WatermarkStyle
from ..text_layout import wrap_overlay_text
from . import register_overlay_renderer


KIND = "text_watermark"


def build_drawtext(watermark: WatermarkStyle,
                     target_w: int,
                     target_h: int,
                     tmp_files: list[str]) -> str:
    """Text-mode watermark via textfile so long strings wrap consistently
    with the preview. Wraps at 40% of target width — watermarks should be
    small / corner-anchored, not banner-width."""
    if not watermark.enabled or watermark.type != "text":
        return ""
    raw = (watermark.text or "").strip()
    if not raw:
        return ""

    font_path = "C:/Windows/Fonts/msyh.ttc"
    lines = wrap_overlay_text(
        raw, max(40.0, target_w * 0.40),
        font_path, watermark.text_fontsize)
    if not lines:
        return ""
    wrapped = "\n".join(lines)

    tmp_path = os.path.join(
        tempfile.gettempdir(),
        f"composition-watermark-{os.getpid()}-{id(watermark)}.txt",
    )
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(wrapped)
    except OSError:
        return ""
    tmp_files.append(tmp_path)

    margin_x = pixel_offset(watermark.margin_x_pct, target_w)
    margin_y = pixel_offset(watermark.margin_y_pct, target_h)
    pos = watermark.position or "top-right"
    x = f"w-text_w-{margin_x}" if pos.endswith("right") else f"{margin_x}"
    y = f"h-text_h-{margin_y}" if pos.startswith("bottom") else f"{margin_y}"
    opacity = max(0.0, min(1.0, (watermark.text_opacity or 70) / 100.0))
    textfile_ff = tmp_path.replace("\\", "/").replace(":", "\\:")
    return (f"drawtext=textfile='{textfile_ff}':"
            f"fontfile='{font_path.replace(':', chr(92)+':')}':"
            f"fontcolor={hex_to_drawtext_rgba(watermark.text_color, opacity)}:"
            f"fontsize={watermark.text_fontsize}:"
            f"x={x}:y={y}:"
            f"borderw=2:bordercolor=black@{opacity*0.5:.2f}")


def _renderer(job, prev_label, ctx):
    wm: WatermarkStyle = job.data["watermark"]
    snippet = build_drawtext(
        wm, ctx.target_w, ctx.target_h, ctx.tmp_files)
    if not snippet:
        return [], prev_label
    out_label = ctx.next_label()
    return [f"{prev_label}{snippet}{out_label}"], out_label


register_overlay_renderer(KIND, _renderer)
