"""Clip subtitle component — one track per instance.

Each clip uses up to two subtitle tracks (primary + secondary language).
Each track is one ClipSubtitleSpec instance. The host (composer or the
future component-list UI) decides how many tracks exist and seeds each
instance with its SRT path + the margin_v that reflects whether the
other track is also enabled (so the two tracks stack correctly).

This spec exists ALONGSIDE news_desk's subtitle spec, not as a
replacement. News_desk's subtitle is single-track with a snapshot SRT
in instance_dir; clip's is dual-capable with a dynamic SRT path
resolved from the active language at render time.

Step 5.1 — render path: composer.compile_for_candidate calls
`subtitle_adapters_from_style()` to translate the legacy
CompositionStyle.subtitle into transient instance dicts; once Step 5.5
swaps the UI to a component list, those dicts will live in
ClipInstanceConfig.components and this seeder retires.
"""

from __future__ import annotations

import os

import srt as _srt

from core.composition.compile import ClipRange, CompileContext
from core.composition.primitives.subtitle_cue import track_margins
from core.composition.style import CompositionStyle, SubtitleLineStyle, SubtitleStyle
from core.composition.timeline import Element
from creations.news_desk.components import ComponentSpec

from . import ComponentDictAdapter, register


KIND = "clip_subtitle"


# ── default_instance ───────────────────────────────────────────────────────

def _default_instance(_duration: float) -> dict:
    """Used when [+ Add Subtitle] lands in 5.5. Sane mid-range defaults."""
    return {
        "kind": KIND,
        "id": "sub1",
        "name": "subtitle",
        "enabled": True,
        # Source SRT — host writes this at compile time (Step 5.1) or
        # the future UI provides a picker (Step 5.5+).
        "srt_path": "",
        # Per-line style
        "fontsize": 24,
        "color": "#FFFFFF",
        "bold": False,
        "is_chinese": False,
        "bg_color": "#000000",
        "bg_opacity": 0,
        "bg_padding_x_pct": 0.0,
        # Track-shared style
        "stroke_color": "#000000",
        "stroke_width": 2,
        "position": "bottom",
        "block_margin_pct": 0.09,
        # Pre-computed by seeder so compile() stays pure (single-track view)
        "margin_v": 0,
    }


# ── compile — instance dict + ctx → Elements ───────────────────────────────

def _compile(instance: dict, clip_range: ClipRange,
             _ctx: CompileContext) -> list[Element]:
    """Pure: parse SRT, slice to [clip_range], rebase to 0, emit one
    subtitle_cue Element per surviving cue. Mirrors the byte-shape that
    timeline_builder._srt_to_subtitle_elements produced pre-5.1."""
    srt_path = instance.get("srt_path") or ""
    if not srt_path or not os.path.isfile(srt_path):
        return []
    try:
        with open(srt_path, "r", encoding="utf-8", errors="replace") as f:
            cues = list(_srt.parse(f.read()))
    except (OSError, ValueError):
        return []

    style_dict = {
        "fontsize": int(instance.get("fontsize", 24)),
        "color": instance.get("color", "#FFFFFF"),
        "bold": bool(instance.get("bold", False)),
        "is_chinese": bool(instance.get("is_chinese", False)),
        "bg_color": instance.get("bg_color", "#000000"),
        "bg_opacity": int(instance.get("bg_opacity", 0)),
        "bg_padding_x_pct": float(instance.get("bg_padding_x_pct", 0.0)),
        "stroke_color": instance.get("stroke_color", "#000000"),
        "stroke_width": int(instance.get("stroke_width", 2)),
        "position": instance.get("position", "bottom"),
        "block_margin_pct": float(instance.get("block_margin_pct", 0.09)),
        "margin_v": int(instance.get("margin_v", 0)),
    }

    base = float(clip_range.start_sec)
    eff_end = float(clip_range.end_sec)
    out: list[Element] = []
    for cue in cues:
        cs = cue.start.total_seconds()
        ce = cue.end.total_seconds()
        if ce <= base or cs >= eff_end:
            continue
        new_start = max(base, cs) - base
        new_end = min(eff_end, ce) - base
        if new_end <= new_start:
            continue
        out.append(Element(
            kind="subtitle_cue",
            start_sec=new_start,
            end_sec=new_end,
            style=style_dict,
            data={"text": cue.content},
        ))
    return out


# ── Seeder — legacy CompositionStyle → transient instance adapters ─────────

def subtitle_adapters_from_style(
    style: CompositionStyle,
    *,
    source_srt: str = "",
    source_srt_secondary: str = "",
) -> list[ComponentDictAdapter]:
    """Translate the legacy CompositionStyle.subtitle into transient
    subtitle component adapters for compile_timeline().

    Both tracks are inspected; disabled tracks or tracks without a
    bound SRT return no adapter. margin_v is pre-computed via
    track_margins(subtitle_style) so each compile() call stays pure.

    Step 5.1 — temporary bridge. Step 5.5 will replace this with
    ClipInstanceConfig.components-driven discovery.
    """
    sub = style.subtitle
    margin_v1, margin_v2 = track_margins(sub)
    adapters: list[ComponentDictAdapter] = []

    if sub.sub1.enabled and source_srt:
        adapters.append(ComponentDictAdapter(
            _line_to_instance(sub.sub1, sub, "sub1", source_srt, margin_v1)))
    if sub.sub2.enabled and source_srt_secondary:
        adapters.append(ComponentDictAdapter(
            _line_to_instance(sub.sub2, sub, "sub2", source_srt_secondary,
                               margin_v2)))
    return adapters


def _line_to_instance(line: SubtitleLineStyle, subtitle_style: SubtitleStyle,
                       track_id: str, srt_path: str, margin_v: int) -> dict:
    return {
        "kind": KIND,
        "id": track_id,
        "name": track_id,
        "enabled": True,
        "srt_path": srt_path,
        "fontsize": int(line.fontsize),
        "color": line.color,
        "bold": bool(line.bold),
        "is_chinese": bool(line.is_chinese),
        "bg_color": line.bg_color,
        "bg_opacity": int(line.bg_opacity),
        "bg_padding_x_pct": float(line.bg_padding_x_pct),
        "stroke_color": subtitle_style.stroke_color,
        "stroke_width": int(subtitle_style.stroke_width),
        "position": subtitle_style.position,
        "block_margin_pct": float(subtitle_style.block_margin_pct),
        "margin_v": int(margin_v),
    }


# ── register ───────────────────────────────────────────────────────────────

register(ComponentSpec(
    kind=KIND,
    name_key="clip.component.subtitle.name",
    add_label_key="clip.component.subtitle.add",
    multi_instance=True,
    default_z=10,
    default_instance=_default_instance,
    # build_property_panel lands in Step 5.5 with the UI rewrite
    build_property_panel=None,
    compile=_compile,
))
