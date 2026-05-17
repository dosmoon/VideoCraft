"""Composition timeline IR — engine's single source of "what to draw".

Authoritative shape consumed by render.py (after PR 4) and preview.py
(after PR 4) following compile. Transient: never persisted, never
human-edited. See docs/design/composition-timeline-v0.md (and the
pending ADR-0006) for the full design.

PR 1 lands the dataclasses only; no caller consumes timeline yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Element:
    """Single visual unit on a timeline track.

    kind: primitive registry key. Dispatch at render time happens on
        this string — no isinstance, no per-kind branches.
    start_sec / end_sec: clip-relative time window (0 = clip start).
        Out-of-range elements get clipped or dropped at compile time.
    z_offset: per-element stacking inside its track. Final z =
        track.z_base + z_offset; most elements leave it 0.
    style: visual fields ("how to draw"), already inlined at compile
        time (no late style-library lookup at render).
    data: kind-specific content fields ("what to draw").
    """
    kind: str
    start_sec: float
    end_sec: float
    z_offset: int = 0
    style: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)


@dataclass
class Track:
    """A single component instance's contribution to the timeline.

    Track : ComponentInstance = 1 : 1 (hard invariant). Disabling a
    component drops its track entirely at compile time.

    z_base: assigned by compile_timeline() from sidebar order. Elements
        stack on top via z_offset within the same track.
    component_kind: label only — never a dispatch key. Audit / debug use.
    """
    id: str
    component_kind: str
    z_base: int
    enabled: bool
    elements: list[Element] = field(default_factory=list)


@dataclass
class CompositionTimeline:
    """Compile output — engine's only "what to draw" input.

    duration_sec is the clip's full duration; element windows are
    clipped into [0, duration_sec] at compile time so render-side
    code can assume in-range timestamps.
    """
    duration_sec: float
    tracks: list[Track] = field(default_factory=list)
