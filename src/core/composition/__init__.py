"""Composition — VideoCraft's unified style + render layer.

Style schemas, preset persistence, ffmpeg-based rendering, and the
WebView-driven realtime preview adapter all live here. Derivative
workbenches consume this module instead of building their own
style/render plumbing.

Architecturally the layer is the rendering kernel of a video editor minus
the timeline UI — per-shot composition driven by structured config, with
overlays as the open-ended extension point for news-desk style elements
(chapter cards, lower-thirds, tickers, ...).

Consumers: creations/clip (AI Clip workbench), creations/news_desk
(press-briefing / news-show composer).
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
    libass_margin_v, font_size_px, pixel_offset,
    subtitle_baseline_y_from_canvas_top,
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
    "font_size_px",
    "pixel_offset",
    "subtitle_baseline_y_from_canvas_top",
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
