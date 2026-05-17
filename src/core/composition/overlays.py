"""Time-windowed overlay specifications.

Generic `OverlaySpec` lives here; the typed kinds were moved into
`core/composition/primitives/<kind>.py` by the PR 2 split. This module
keeps the typed names as re-exports so existing callers (creations,
preview.py, presets.py) still see the old import path. PR 5 (timeline
migration) drops the typed re-exports when callers update to import
from primitives directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

# Typed overlay classes re-exported from primitives. The aliases
# (TopicStripOverlay, ChapterHeroCardOverlay) keep legacy import paths
# working during PR 2~5; the canonical names are <Kind>Spec on the
# primitive side.
from .primitives.chapter_hero_card import (
    ChapterHeroCardOverlay,    # = ChapterHeroCardSpec alias
)
from .primitives.topic_strip import (
    TopicStripOverlay,         # = TopicStripSpec alias
)


@dataclass
class OverlaySpec:
    """Generic time-windowed overlay — fallback / forward-compat shape for
    overlay kinds that don't have a typed dataclass yet.

    Fields (also present on every typed kind — duck-typed):
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
