"""outro_text primitive — clip-closing text card (last N seconds).

Implementation: ffmpeg drawtext filter with role='outro'. Shares
position + enable-expression logic with hook_text through the
drawtext_helpers.drawtext_filter() helper. HookOutroStyle (which
bundles both hook and outro visual fields) still lives in style.py
until PR 5 splits it per Axis 7.5.
"""

from __future__ import annotations

from ..drawtext_helpers import drawtext_filter
from . import register_overlay_renderer


KIND = "outro_text"


def _renderer(job, prev_label, ctx):
    snippet = drawtext_filter(
        job.data["text"], role="outro", ho=ctx.style.hook_outro,
        duration=ctx.duration, aspect_ratio=ctx.aspect,
        tmp_files=ctx.tmp_files, short_edge=ctx.short_edge)
    if not snippet:
        return [], prev_label
    out_label = ctx.next_label()
    return [f"{prev_label}{snippet}{out_label}"], out_label


register_overlay_renderer(KIND, _renderer)
