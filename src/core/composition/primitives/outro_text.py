"""outro_text primitive — clip-closing text card (last N seconds).

Implementation: ffmpeg drawtext filter with role='outro'. Reads styling
from element.style (no engine-level CompositionStyle reach).
"""

from __future__ import annotations

from ..drawtext_helpers import drawtext_filter
from . import register_overlay_renderer


KIND = "outro_text"


def _renderer(job, prev_label, ctx):
    text = job.data.get("text", "")
    style_dict = job.data.get("style") or {}
    snippet = drawtext_filter(
        text, role="outro", style=style_dict,
        duration=ctx.duration, aspect_ratio=ctx.aspect,
        tmp_files=ctx.tmp_files, short_edge=ctx.short_edge)
    if not snippet:
        return [], prev_label
    out_label = ctx.next_label()
    return [f"{prev_label}{snippet}{out_label}"], out_label


register_overlay_renderer(KIND, _renderer)
