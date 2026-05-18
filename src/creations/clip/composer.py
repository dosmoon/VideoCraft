"""Compile one candidate's CompositionTimeline from a components list.

Single entry point clip_tool calls per candidate. Takes the user's
project-level component templates (config.components) plus this
candidate's per-instance data (hook/outro text, SRT path) and produces
a CompositionTimeline ready for render or preview.

The expansion happens here (deepcopy + patch), NOT inside spec.compile —
so each spec stays a pure `(instance, clip_range, ctx) → Elements`
function with no per-candidate awareness. The "template → concrete
instances" mapping is the only clip-specific orchestration layer; the
specs themselves are reusable.
"""

from __future__ import annotations

import copy

from core.composition.compile import ClipRange, CompileContext, compile_timeline
from core.composition.layout import libass_margin_v
from core.composition.timeline import CompositionTimeline

from creations.clip.components import ComponentDictAdapter


# ── Public entry — clip_tool calls this per candidate ──────────────────────

def compile_for_candidate(
    components: list[dict],
    clip_range: ClipRange,
    *,
    hook_text: str = "",
    outro_text: str = "",
    source_srt: str = "",
    source_srt_secondary: str = "",
) -> CompositionTimeline:
    """Render-time single source: instantiate template into concrete
    per-candidate component dicts, then compile through the engine."""
    concrete = expand_for_candidate(
        components,
        hook_text=hook_text, outro_text=outro_text,
        source_srt=source_srt, source_srt_secondary=source_srt_secondary)
    adapters = [ComponentDictAdapter(c) for c in concrete]
    ctx = CompileContext(
        project=None, material_model=None,
        instance_dir="", duration=clip_range.duration_sec)
    return compile_timeline(adapters, clip_range, ctx)


# ── Template expansion ─────────────────────────────────────────────────────

def expand_for_candidate(
    components: list[dict],
    *,
    hook_text: str = "",
    outro_text: str = "",
    source_srt: str = "",
    source_srt_secondary: str = "",
) -> list[dict]:
    """Deep-copy + fill per-candidate data. Pure function.

    - clip_subtitle.srt_path ← source_srt / source_srt_secondary by track
    - clip_subtitle.margin_v ← computed for two-track stacking if both
      tracks are enabled on the same position
    - clip_hook_card.text ← hook_text
    - clip_outro_card.text ← outro_text

    Disabled components, components missing required data (empty SRT
    path / empty text), and any spec.compile() rules are still applied
    downstream by compile_timeline. expand_for_candidate only fills
    fields; it never drops components.
    """
    concrete = [copy.deepcopy(c) for c in components]

    # Subtitle: route SRT path + compute margin_v stacking
    sub_instances = [c for c in concrete if c.get("kind") == "clip_subtitle"]
    for c in sub_instances:
        track = c.get("track", "primary")
        if track == "primary":
            c["srt_path"] = source_srt
        elif track == "secondary":
            c["srt_path"] = source_srt_secondary
        else:
            c["srt_path"] = ""
    _stamp_subtitle_margin_v(sub_instances)

    # Hook + outro: fill text from per-candidate data
    for c in concrete:
        if c.get("kind") == "clip_hook_card" and not c.get("text"):
            c["text"] = hook_text
        elif c.get("kind") == "clip_outro_card" and not c.get("text"):
            c["text"] = outro_text

    return concrete


# ── Subtitle stacking ──────────────────────────────────────────────────────

def _stamp_subtitle_margin_v(subs: list[dict]) -> None:
    """For each enabled subtitle, compute margin_v from block_margin_pct.

    Dual-track stacking: if BOTH a primary and a secondary subtitle are
    enabled AND share the same position (top/bottom), the "inner" track
    sits one track_gap_pct further from the anchor edge. Falls back to
    single-track margin when only one track is enabled or they target
    different positions.
    """
    enabled = [c for c in subs if c.get("enabled", True)
                and c.get("srt_path")]
    by_pos: dict[str, list[dict]] = {}
    for c in enabled:
        by_pos.setdefault(c.get("position", "bottom"), []).append(c)

    for pos, group in by_pos.items():
        if len(group) < 2:
            for c in group:
                c["margin_v"] = libass_margin_v(
                    float(c.get("block_margin_pct", 0.09)))
            continue
        # Two-or-more on same position: stamp outer = block_margin,
        # inner = block_margin + track_gap. Primary track is the outer
        # one (closer to the edge) by convention. Order is determined
        # by the `track` field — primary first, then secondaries.
        group_sorted = sorted(group,
                               key=lambda c: 0 if c.get("track") == "primary"
                                              else 1)
        for i, c in enumerate(group_sorted):
            base = float(c.get("block_margin_pct", 0.09))
            gap = float(c.get("track_gap_pct", 0.04))
            c["margin_v"] = libass_margin_v(base + i * gap)
