"""Composition timeline compiler — turn components into a timeline IR.

compile_timeline() is a pure function: same inputs always produce the
same timeline. ComponentInstance.compile() must also be pure (no side
effects, no UI, no file IO beyond reading material data).

CompileContext is engine-side and intentionally narrow — no UI hooks.
Creations may subclass it to add their own UI callbacks (e.g. news_desk
adds seek_to in its ProjectContext), but the engine signature only
sees the narrow shape.

See docs/design/composition-timeline-v0.md (and pending ADR-0006).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .timeline import CompositionTimeline, Element, Track


@dataclass
class ClipRange:
    """The clip's time window relative to the source video.

    end_sec is exclusive in spirit (duration_sec = end_sec - start_sec).
    Components receive ClipRange to compute their per-clip windows;
    they do not see the source-video absolute times.
    """
    start_sec: float
    end_sec: float

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


@dataclass
class CompileContext:
    """Engine-side compile context — pure data, no UI callbacks.

    Creations may subclass to add UI hooks (seek_to, on_cue_split, ...);
    the engine signature only depends on these four fields, so adding
    a UI hook in a creation does not leak into the engine API.
    """
    project: object
    material_model: object
    instance_dir: str
    duration: float


class ComponentInstance(Protocol):
    """Producer-side contract — the engine's only knowledge about
    "what user content lives in this creation".

    Implementations live in each creation's components/ package.
    compile() must be pure and deterministic given (config + clip_range
    + ctx); empty result is legal (e.g. an enabled subtitle component
    with no SRT bound yet).
    """
    kind: str
    id: str

    def is_enabled(self) -> bool: ...

    def compile(
        self, clip_range: ClipRange, ctx: CompileContext,
    ) -> list[Element]: ...


def compile_timeline(
    components: list[ComponentInstance],
    clip_range: ClipRange,
    ctx: CompileContext,
) -> CompositionTimeline:
    """Walk components in sidebar order, emit element lists, wrap into
    tracks with z_base from position. Disabled components are dropped
    entirely. Elements outside [0, duration] are dropped; partial
    overlaps get clamped to the range.
    """
    tracks: list[Track] = []
    for index, ci in enumerate(components):
        if not ci.is_enabled():
            continue
        elements = ci.compile(clip_range, ctx)
        kept = _clip_to_range(elements, clip_range.duration_sec)
        tracks.append(Track(
            id=ci.id,
            component_kind=ci.kind,
            z_base=(index + 1) * 10,
            enabled=True,
            elements=kept,
        ))
    return CompositionTimeline(
        duration_sec=clip_range.duration_sec,
        tracks=tracks,
    )


def _clip_to_range(
    elements: list[Element], duration: float,
) -> list[Element]:
    """Drop elements fully outside [0, duration]; clamp partial overlaps.
    Returns a new list; input elements with partial overlap are replaced
    with clamped copies so the originals stay untouched.
    """
    out: list[Element] = []
    for e in elements:
        if e.end_sec <= 0 or e.start_sec >= duration:
            continue
        if e.start_sec < 0 or e.end_sec > duration:
            e = Element(
                kind=e.kind,
                start_sec=max(0.0, e.start_sec),
                end_sec=min(duration, e.end_sec),
                z_offset=e.z_offset,
                style=e.style,
                data=e.data,
            )
        out.append(e)
    return out
