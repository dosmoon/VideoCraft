"""Composition — VideoCraft's unified style + render layer.

Style schemas, preset persistence, ffmpeg-based rendering, and the
WebView-driven realtime preview adapter all live here. Derivative
workbenches consume this module instead of building their own
style/render plumbing.

Stage 1 consumer: derivatives/clip (AI Clip workbench).
Stage 2: derivatives/bilingual_video (subtitle burn).
"""

from .style import (
    CompositionStyle,
    SubtitleStyle,
    SubtitleLineStyle,
    WatermarkStyle,
    HookOutroStyle,
    BgmConfig,
    compute_subtitle_max_chars,
    effective_max_chars,
)
from .render import (
    CompositionRequest,
    CompositionResult,
    render_composition,
)
from .text_layout import (
    wrap_overlay_text,
    wrap_hook_outro,
    target_width_for_aspect,
)

__all__ = [
    "CompositionStyle",
    "SubtitleStyle",
    "SubtitleLineStyle",
    "WatermarkStyle",
    "HookOutroStyle",
    "BgmConfig",
    "compute_subtitle_max_chars",
    "effective_max_chars",
    "CompositionRequest",
    "CompositionResult",
    "render_composition",
    "wrap_overlay_text",
    "wrap_hook_outro",
    "target_width_for_aspect",
]
