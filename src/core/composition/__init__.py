"""Composition — VideoCraft's unified style + render layer.

Style schemas, preset persistence, ffmpeg-based rendering, and the
WebView-driven realtime preview adapter all live here. Derivative
workbenches consume this module instead of building their own
style/render plumbing.

Architecturally the layer is the rendering kernel of a video editor minus
the timeline UI — per-shot composition driven by structured config, with
overlays as the open-ended extension point for news-desk style elements
(chapter cards, lower-thirds, tickers, ...).

Stage 1 consumer: derivatives/clip (AI Clip workbench).
Stage 2: derivatives/bilingual_video (subtitle burn).
Future: derivatives/news_desk.
"""

from .style import (
    CompositionStyle,
    OutputGeometry,
    SubtitleStyle,
    SubtitleLineStyle,
    WatermarkStyle,
    HookOutroStyle,
    compute_subtitle_max_chars,
    effective_max_chars,
)
from .overlays import OverlaySpec
from .layout import (
    libass_margin_v, pixel_offset,
    subtitle_baseline_y_from_canvas_top,
    LIBASS_DEFAULT_PLAY_RES_Y,
)
from .render import (
    CompositionRequest,
    CompositionResult,
    render_composition,
    prepare_subtitle_cues,
    probe_video_resolution,
)
from .text_layout import (
    wrap_overlay_text,
    wrap_hook_outro,
    target_width_for_aspect,
)

__all__ = [
    "CompositionStyle",
    "OutputGeometry",
    "SubtitleStyle",
    "SubtitleLineStyle",
    "WatermarkStyle",
    "HookOutroStyle",
    "OverlaySpec",
    "libass_margin_v",
    "pixel_offset",
    "subtitle_baseline_y_from_canvas_top",
    "LIBASS_DEFAULT_PLAY_RES_Y",
    "compute_subtitle_max_chars",
    "effective_max_chars",
    "CompositionRequest",
    "CompositionResult",
    "render_composition",
    "prepare_subtitle_cues",
    "probe_video_resolution",
    "wrap_overlay_text",
    "wrap_hook_outro",
    "target_width_for_aspect",
]
