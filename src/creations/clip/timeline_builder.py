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

import os

import srt as _srt

from core.composition.compile import ClipRange
from core.composition.primitives.subtitle_cue import track_margins
from core.composition.style import CompositionStyle, SubtitleLineStyle, SubtitleStyle
from core.composition.timeline import CompositionTimeline, Element, Track


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

    sub = style.subtitle
    margin_v1, margin_v2 = track_margins(sub)

    if sub.sub1.enabled and source_srt:
        elements = _srt_to_subtitle_elements(
            source_srt, sub.sub1, sub,
            margin_v=margin_v1, clip_range=clip_range)
        if elements:
            tracks.append(Track(
                id="sub1", component_kind="subtitle",
                z_base=z, enabled=True, elements=elements))
            z += 10

    if sub.sub2.enabled and source_srt_secondary:
        elements = _srt_to_subtitle_elements(
            source_srt_secondary, sub.sub2, sub,
            margin_v=margin_v2, clip_range=clip_range)
        if elements:
            tracks.append(Track(
                id="sub2", component_kind="subtitle",
                z_base=z, enabled=True, elements=elements))
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
    if hook_text and ho.hook_duration_sec > 0:
        end = min(clip_range.duration_sec, float(ho.hook_duration_sec))
        if end > 0:
            tracks.append(Track(
                id="hook", component_kind="hook_text",
                z_base=z, enabled=True,
                elements=[Element(
                    kind="hook_text",
                    start_sec=0.0, end_sec=end,
                    data={"text": hook_text},
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
                    data={"text": outro_text},
                )],
            ))
            z += 10

    return CompositionTimeline(
        duration_sec=clip_range.duration_sec,
        tracks=tracks,
    )


def _srt_to_subtitle_elements(
    srt_path: str,
    line: SubtitleLineStyle,
    subtitle_style: SubtitleStyle,
    *,
    margin_v: int,
    clip_range: ClipRange,
) -> list[Element]:
    """Read SRT, slice to [clip_range.start, end], rebase to 0, emit one
    subtitle_cue Element per surviving cue. All elements share one
    style dict carrying everything force_style needs at render time
    (incl. pre-computed margin_v for dual-track layouts)."""
    if not srt_path or not os.path.isfile(srt_path):
        return []
    try:
        with open(srt_path, "r", encoding="utf-8", errors="replace") as f:
            cues = list(_srt.parse(f.read()))
    except (OSError, ValueError):
        return []

    base = float(clip_range.start_sec)
    eff_end = float(clip_range.end_sec)
    style_dict = {
        "fontsize": line.fontsize,
        "color": line.color,
        "bold": line.bold,
        "is_chinese": line.is_chinese,
        "bg_color": line.bg_color,
        "bg_opacity": line.bg_opacity,
        "bg_padding_x_pct": line.bg_padding_x_pct,
        "stroke_color": subtitle_style.stroke_color,
        "stroke_width": subtitle_style.stroke_width,
        "position": subtitle_style.position,
        "block_margin_pct": subtitle_style.block_margin_pct,
        "margin_v": margin_v,
    }
    elements: list[Element] = []
    for cue in cues:
        cs = cue.start.total_seconds()
        ce = cue.end.total_seconds()
        if ce <= base or cs >= eff_end:
            continue
        new_start = max(base, cs) - base
        new_end = min(eff_end, ce) - base
        if new_end <= new_start:
            continue
        elements.append(Element(
            kind="subtitle_cue",
            start_sec=new_start, end_sec=new_end,
            style=style_dict,
            data={"text": cue.content},
        ))
    return elements
