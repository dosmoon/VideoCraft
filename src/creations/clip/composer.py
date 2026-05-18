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
from core.composition.timeline import CompositionTimeline

from creations.clip.components import ComponentDictAdapter


# ── Public entry — clip_tool calls this per candidate ──────────────────────

def compile_for_candidate(
    components: list[dict],
    clip_range: ClipRange,
    *,
    hook_text: str = "",
    outro_text: str = "",
    srt_by_lang: dict | None = None,
) -> CompositionTimeline:
    """Render-time single source: instantiate template into concrete
    per-candidate component dicts, then compile through the engine."""
    concrete = expand_for_candidate(
        components,
        hook_text=hook_text, outro_text=outro_text,
        srt_by_lang=srt_by_lang)
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
    srt_by_lang: dict | None = None,
) -> list[dict]:
    """Deep-copy + fill per-candidate data. Pure function.

    - clip_subtitle.srt_path ← srt_by_lang[component.language]
    - clip_subtitle.margin_v ← stacked by components-list order when
      multiple subtitles share the same position
    - clip_hook_card.text ← hook_text
    - clip_outro_card.text ← outro_text

    Disabled components, components missing required data (unknown
    language / empty text), and any spec.compile() rules are still
    applied downstream by compile_timeline. expand_for_candidate only
    fills fields; it never drops components.
    """
    concrete = [copy.deepcopy(c) for c in components]
    lookup = srt_by_lang or {}

    # Subtitle: resolve srt_path by language + stack margin_v
    sub_instances = [c for c in concrete if c.get("kind") == "clip_subtitle"]
    for c in sub_instances:
        c["srt_path"] = lookup.get(c.get("language", ""), "")
    _stamp_subtitle_margin_v(sub_instances)

    # Hook + outro: fill text from per-candidate data
    for c in concrete:
        if c.get("kind") == "clip_hook_card" and not c.get("text"):
            c["text"] = hook_text
        elif c.get("kind") == "clip_outro_card" and not c.get("text"):
            c["text"] = outro_text

    return concrete


# ── Subtitle stacking ──────────────────────────────────────────────────────

# Pre-render gap between two subtitles sharing the same anchor edge.
# When only one subtitle sits at a position, this is unused (single
# block_margin_pct wins). Constant rather than per-component so the
# user doesn't see a knob they'd never tune.
_STACK_GAP_PCT = 0.04


def _stamp_subtitle_margin_v(subs: list[dict]) -> None:
    """For each enabled subtitle, compute libass margin_v.

    Stacking rule: subtitles at the same position (top or bottom) stack
    in components-list order — the one earlier in the list (closer to
    the top of the StylePanel list, i.e. higher z) sits at
    block_margin_pct, the next at block_margin_pct + gap, etc. This
    matches the user's mental model of the list reading top-to-bottom
    as outer-to-inner.
    """
    enabled = [c for c in subs if c.get("enabled", True)
                and c.get("srt_path")]
    by_pos: dict[str, list[dict]] = {}
    for c in enabled:
        by_pos.setdefault(c.get("position", "bottom"), []).append(c)

    for group in by_pos.values():
        for i, c in enumerate(group):
            base = float(c.get("block_margin_pct", 0.09))
            # Single stacked pct that BOTH render (libass MarginV) and
            # preview (canvas edge offset) compute pixel anchors from.
            # Render multiplies by target_h, preview by canvas height.
            c["effective_block_margin_pct"] = base + i * _STACK_GAP_PCT
