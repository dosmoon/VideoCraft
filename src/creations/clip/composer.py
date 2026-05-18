"""Compile one candidate's CompositionTimeline.

Single entry point clip_tool calls per candidate: gathers adapters from
the 3 component seeders (subtitle / watermark / hook_outro), then runs
the engine's compile_timeline() against them.

This is the Step 5.4 successor of the retired inline-Element builder.
Composes existing per-component seeders and lets the engine do the
actual compile — no manual Track wrapping, no z-restamping, no direct
Element construction.

The signature still takes a legacy CompositionStyle + per-candidate
text/SRT args because the StylePanel UI hasn't been migrated yet
(Step 5.5). When the UI switches to component-list editing, this
helper retires too — clip_tool will call compile_timeline() against
the user's persisted components after one expansion pass.
"""

from __future__ import annotations

from core.composition.compile import ClipRange, CompileContext, compile_timeline
from core.composition.style import CompositionStyle
from core.composition.timeline import CompositionTimeline

from creations.clip.components.hook_outro import hookoutro_adapters_from_style
from creations.clip.components.subtitle import subtitle_adapters_from_style
from creations.clip.components.watermark import watermark_adapters_from_style


def compile_for_candidate(
    style: CompositionStyle,
    clip_range: ClipRange,
    *,
    hook_text: str = "",
    outro_text: str = "",
    source_srt: str = "",
    source_srt_secondary: str = "",
) -> CompositionTimeline:
    """Translate clip's legacy CompositionStyle + per-candidate data into
    a CompositionTimeline via the component-spec compile path.

    Single-source: same compile drives render AND preview, no layout
    divergence possible (ADR-0006 invariant #6).
    """
    adapters = [
        *subtitle_adapters_from_style(
            style, source_srt=source_srt,
            source_srt_secondary=source_srt_secondary),
        *watermark_adapters_from_style(style),
        *hookoutro_adapters_from_style(
            style, hook_text=hook_text, outro_text=outro_text),
    ]
    ctx = CompileContext(
        project=None, material_model=None,
        instance_dir="", duration=clip_range.duration_sec)
    return compile_timeline(adapters, clip_range, ctx)
