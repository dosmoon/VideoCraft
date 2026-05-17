"""Time-windowed overlay specifications — the per-render content data.

CompositionStyle holds reusable visual classes (look). OverlaySpec subclasses
hold per-render content: what to draw, when, and which style class to use.
The split mirrors AE's "character style + text layer content" or web's
"CSS class + DOM element".

Industry alignment: `TopicStripOverlay` is our internal name for what
broadcast packages variously call "topic bar", "chapter marker strip", or
"now playing strip" — a static labeled bar pinned to the top edge.
`ChapterHeroCardOverlay` is a sidebar interstitial that announces a new
chapter. Future overlay kinds extend the same discriminator pattern.

Each kind dataclass is the single contract shared by: AI prompt JSON
schema, on-disk JSON storage, UI list editor, and composition renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass
class OverlaySpec:
    """Generic time-windowed overlay — fallback / forward-compat shape for
    overlay kinds that don't have a typed dataclass yet.

    Fields (also present on every typed kind below — duck-typed):
        kind: discriminator that selects a registered renderer in render.py.
        start_sec / end_sec: time window in the composition's clip range
            (rebased to 0..duration), NOT absolute source video time.
        zone: layout hint for the future zone manager. "auto" lets the
            renderer pick. Reserved values: "subtitle", "banner_top",
            "lower_third", "ticker", "top_left", "top_right", "bottom_left",
            "bottom_right", "full".
        z_order: stacking order (higher = later draw = on top).
        payload: kind-specific data. Concrete typed kinds replace this.
    """
    kind: str
    start_sec: float = 0.0
    end_sec: float = 0.0
    zone: str = "auto"
    z_order: int = 100
    payload: dict = field(default_factory=dict)


@dataclass
class ChapterHeroCardOverlay:
    """Chapter intro/hero card — large title (+ optional body) on a
    sidebar-anchored translucent panel, shown for the first few seconds
    of a chapter as a "now showing" interstitial. The chapter component
    routes its `start_card` visual mode here.

    inline_style is a per-spec override hatch — chapter.py uses it so
    the property panel's per-instance style fields actually drive the
    render instead of being purely cosmetic. Empty dict = use the
    resolved overlay_styles entry verbatim.
    """
    title: str = ""
    body: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    style_class: str = "default"
    inline_style: dict = field(default_factory=dict)
    kind: str = "chapter_hero_card"
    z_order: int = 46
    zone: str = "center"


@dataclass
class TopicStripOverlay:
    """Top-edge labeled strip — chapter marker / topic bar.

    A thin always-on strip (when active) showing the current chapter or
    topic title. Auto-derivable from `analysis.json` (one strip per
    chapter, time window = chapter [start, end]); also user-editable.

    style_class: key into CompositionStyle.overlay_styles → TopicStripStyle.
    """
    topic_text: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    style_class: str = "default"
    kind: str = "topic_strip"
    z_order: int = 40
    zone: str = "banner_top"


# Union for callers that want type-narrowing. Renderer dispatch keys off
# `kind` (str) so this union is purely for static typing convenience.
OverlayUnion = Union[
    OverlaySpec, TopicStripOverlay, ChapterHeroCardOverlay,
]


# Tuple of the typed kinds the news_desk pipeline knows about. Used by
# render.py / preview.py to test isinstance() against all supported shapes
# in one shot — extends as new kinds (PullQuote / FullCard / ...) ship.
TYPED_OVERLAY_KINDS: tuple[type, ...] = (
    OverlaySpec, TopicStripOverlay, ChapterHeroCardOverlay,
)


def overlay_to_dict(spec) -> dict:
    """Serialize any supported overlay to a plain dict (for JSON storage,
    AI prompt I/O, web preview push). Includes a `kind` discriminator so
    overlay_from_dict() can round-trip it."""
    from dataclasses import asdict, is_dataclass
    if not is_dataclass(spec):
        raise TypeError(f"overlay_to_dict: not a dataclass: {type(spec)}")
    return asdict(spec)


def overlay_from_dict(d: dict):
    """Reconstruct a typed overlay from a dict. Unknown `kind` falls back
    to OverlaySpec (so future-shipped kinds round-trip safely on older
    builds — they just won't render until a renderer is registered)."""
    if not isinstance(d, dict):
        raise TypeError(f"overlay_from_dict: not a dict: {type(d)}")
    kind = d.get("kind", "")
    if kind == "topic_strip":
        return TopicStripOverlay(**_filter(d, TopicStripOverlay))
    if kind == "chapter_hero_card":
        return ChapterHeroCardOverlay(**_filter(d, ChapterHeroCardOverlay))
    return OverlaySpec(**_filter(d, OverlaySpec))


def _filter(d: dict, cls) -> dict:
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
