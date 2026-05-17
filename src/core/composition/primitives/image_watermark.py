"""image_watermark primitive — corner-anchored image overlay via ffmpeg
movie + overlay filter pair.

Image watermarks cannot go through libass or drawtext — ASS draws
vectors but doesn't reference external image files; drawtext renders
text. They need ffmpeg's movie source + overlay filter chain. This is
the one primitive that does NOT emit a single filter snippet — it adds
a source node alongside the overlay node.
"""

from __future__ import annotations

import os

try:
    from hub_logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from core.subtitle_ops import escape_ffmpeg_path

from ..layout import pixel_offset
from ..style import WatermarkStyle
from . import register_overlay_renderer


KIND = "image_watermark"


def build_chain(watermark: WatermarkStyle,
                  target_w: int,
                  target_h: int,
                  prev_label: str,
                  src_label: str,
                  out_label: str,
                  ) -> tuple[list[str], str]:
    """Image watermark needs a `movie` source + overlay pair (drawtext can't
    render external images). Returns (extra_nodes, new_chain_head)."""
    if not watermark.enabled or watermark.type != "image":
        return [], prev_label
    img_path = (watermark.image_path or "").strip()
    if not img_path:
        logger.warning("image watermark skipped: image_path is empty")
        return [], prev_label
    if not os.path.exists(img_path):
        logger.warning(
            f"image watermark skipped: file not found at {img_path}")
        return [], prev_label
    img_ff = escape_ffmpeg_path(img_path)
    wm_w = max(1, int(target_w * max(0.01, watermark.image_scale or 0.15)))
    opacity = max(0.0, min(1.0, (watermark.image_opacity or 100) / 100.0))
    pos = watermark.position or "top-right"
    margin_x = pixel_offset(watermark.margin_x_pct, target_w)
    margin_y = pixel_offset(watermark.margin_y_pct, target_h)
    # overlay W/H = main video dims, w/h = overlay dims
    x = f"W-w-{margin_x}" if pos.endswith("right") else f"{margin_x}"
    y = f"H-h-{margin_y}" if pos.startswith("bottom") else f"{margin_y}"
    return ([
        f"movie='{img_ff}',scale={wm_w}:-1,"
        f"format=rgba,colorchannelmixer=aa={opacity:.3f}{src_label}",
        f"{prev_label}{src_label}overlay={x}:{y}{out_label}",
    ], out_label)


def _renderer(job, prev_label, ctx):
    wm: WatermarkStyle = job.data["watermark"]
    src_label = ctx.next_label()
    out_label = ctx.next_label()
    return build_chain(
        wm, ctx.target_w, ctx.target_h, prev_label, src_label, out_label)


register_overlay_renderer(KIND, _renderer)
