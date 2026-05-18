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
from core.composition.timeline import CompositionTimeline, Element, Track
from creations.clip.components.subtitle import subtitle_adapters_from_style


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

    if style.watermark.enabled:
        wm = style.watermark
        is_image = (wm.type == "image")
        kind = "image_watermark" if is_image else "text_watermark"
        elements = [Element(
            kind=kind,
            start_sec=0.0, end_sec=clip_range.duration_sec,
            style={
                "text_fontsize": wm.text_fontsize,
                "text_color": wm.text_color,
                "text_opacity": wm.text_opacity,
                "image_scale": wm.image_scale,
                "image_opacity": wm.image_opacity,
                "position": wm.position,
                "margin_x_pct": wm.margin_x_pct,
                "margin_y_pct": wm.margin_y_pct,
            },
            data={
                "text": (wm.text or "") if not is_image else "",
                "image_path": (wm.image_path or "") if is_image else "",
            },
        )]
        tracks.append(Track(
            id="wm", component_kind="watermark",
            z_base=z, enabled=True, elements=elements))
        z += 10

    ho = style.hook_outro
    hook_outro_style_dict = _hook_outro_style_dict(ho)

    if hook_text and ho.hook_duration_sec > 0:
        end = min(clip_range.duration_sec, float(ho.hook_duration_sec))
        if end > 0:
            tracks.append(Track(
                id="hook", component_kind="hook_text",
                z_base=z, enabled=True,
                elements=[Element(
                    kind="hook_text",
                    start_sec=0.0, end_sec=end,
                    data={"text": hook_text,
                           "style": hook_outro_style_dict},
                )],
            ))
            z += 10

    if outro_text and ho.outro_duration_sec > 0:
        start_sec = max(0.0,
            clip_range.duration_sec - float(ho.outro_duration_sec))
        if clip_range.duration_sec > start_sec:
            tracks.append(Track(
                id="outro", component_kind="outro_text",
                z_base=z, enabled=True,
                elements=[Element(
                    kind="outro_text",
                    start_sec=start_sec,
                    end_sec=clip_range.duration_sec,
                    data={"text": outro_text,
                           "style": hook_outro_style_dict},
                )],
            ))
            z += 10

    return CompositionTimeline(
        duration_sec=clip_range.duration_sec,
        tracks=tracks,
    )


def _hook_outro_style_dict(ho) -> dict:
    """Translate clip's HookOutroStyle dataclass into a flat dict the
    drawtext_helpers.drawtext_filter renderer reads from element.style."""
    return {
        "font": ho.font,
        "size": ho.size,
        "color": ho.color,
        "bg_color": ho.bg_color,
        "bg_opacity": ho.bg_opacity,
        "stroke_color": ho.stroke_color,
        "stroke_width": ho.stroke_width,
        "box_padding": ho.box_padding,
        "hook_position": ho.hook_position,
        "outro_position": ho.outro_position,
        "hook_duration_sec": ho.hook_duration_sec,
        "outro_duration_sec": ho.outro_duration_sec,
    }


