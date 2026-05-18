"""Build a composition timeline from clip's CompositionStyle + per-clip inputs.

Clip's UI directly mutates a CompositionStyle (subtitle / watermark /
hook_outro configured via Tk vars). For each render this helper turns
that style + the per-clip extras (hook text, outro text, source SRT,
clip range) into a CompositionTimeline ready for render_composition or
CompositionPreview.set_timeline.

Single-source: same builder powers render AND preview so any layout
divergence between them is impossible.

Lives under creations/clip/ rather than core/ because it depends on
the legacy CompositionStyle shape — once clip's UI is rewritten to be
component-based (post-PR-5 follow-up), this file goes away.
"""

from __future__ import annotations

from core.composition.compile import ClipRange, CompileContext, compile_timeline
from core.composition.style import CompositionStyle
from core.composition.timeline import CompositionTimeline, Track
from creations.clip.components.hook_outro import hookoutro_adapters_from_style
from creations.clip.components.subtitle import subtitle_adapters_from_style
from creations.clip.components.watermark import watermark_adapters_from_style


def build_clip_timeline(
    style: CompositionStyle,
    clip_range: ClipRange,
    *,
    hook_text: str = "",
    outro_text: str = "",
    source_srt: str = "",
    source_srt_secondary: str = "",
) -> CompositionTimeline:
    """Translate clip's CompositionStyle into a timeline for the given clip
    window. Each layer (sub1, sub2, watermark, hook, outro) gets its own
    track. Disabled / empty layers drop entirely.

    Subtitle cues come out clip-relative (already rebased + range-clipped).
    The render-side wrap pass (_timeline_to_overlay_jobs +
    _subtitle_elements_to_temp_srt) handles libass max_chars splitting via
    process_srt_split, keeping wrap policy single-source.

    margin_v for each subtitle track is pre-computed here from the FULL
    SubtitleStyle (so sub1's margin reflects sub2's existence in the dual-
    track layout) and stashed in element.style — render doesn't need to
    recompute it.
    """
    tracks: list[Track] = []
    z = 10

    # Subtitle tracks (Step 5.1) — translate legacy CompositionStyle into
    # transient ClipSubtitleSpec adapters and let compile_timeline()
    # produce them. Re-stamps z_base from the seeder's index-based
    # assignment so the appended watermark/hook/outro tracks below
    # keep contiguous z. Drops the wrapping CompositionTimeline,
    # only need its tracks here.
    sub_adapters = subtitle_adapters_from_style(
        style, source_srt=source_srt,
        source_srt_secondary=source_srt_secondary)
    if sub_adapters:
        ctx = CompileContext(
            project=None, material_model=None,
            instance_dir="", duration=clip_range.duration_sec)
        sub_timeline = compile_timeline(sub_adapters, clip_range, ctx)
        for t in sub_timeline.tracks:
            if not t.elements:
                continue
            tracks.append(Track(
                id=t.id, component_kind="subtitle",
                z_base=z, enabled=True, elements=t.elements))
            z += 10

    # Watermark track (Step 5.2) — at most one adapter (text or image)
    # via the legacy WatermarkStyle.type switch. Same z-restamping
    # trick as subtitle so contiguous z stays preserved.
    wm_adapters = watermark_adapters_from_style(style)
    if wm_adapters:
        ctx = CompileContext(
            project=None, material_model=None,
            instance_dir="", duration=clip_range.duration_sec)
        wm_timeline = compile_timeline(wm_adapters, clip_range, ctx)
        for t in wm_timeline.tracks:
            if not t.elements:
                continue
            tracks.append(Track(
                id="wm", component_kind="watermark",
                z_base=z, enabled=True, elements=t.elements))
            z += 10

    # Hook + outro tracks (Step 5.3) — at most two adapters; the seeder
    # fills per-candidate text into each instance dict so spec.compile
    # stays purely (instance, range, ctx) → Elements.
    ho_adapters = hookoutro_adapters_from_style(
        style, hook_text=hook_text, outro_text=outro_text)
    if ho_adapters:
        ctx = CompileContext(
            project=None, material_model=None,
            instance_dir="", duration=clip_range.duration_sec)
        ho_timeline = compile_timeline(ho_adapters, clip_range, ctx)
        for t in ho_timeline.tracks:
            if not t.elements:
                continue
            # Keep the pre-5.3 component_kind label ("hook_text" /
            # "outro_text") for audit/debug stability, not the spec
            # kind ("clip_hook_card" / "clip_outro_card").
            label = "hook_text" if t.id == "hook" else "outro_text"
            tracks.append(Track(
                id=t.id, component_kind=label,
                z_base=z, enabled=True, elements=t.elements))
            z += 10

    return CompositionTimeline(
        duration_sec=clip_range.duration_sec,
        tracks=tracks,
    )


