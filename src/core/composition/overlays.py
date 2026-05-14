"""Time-windowed overlay specifications — the per-render content data.

CompositionStyle holds reusable visual classes (look). OverlaySpec subclasses
hold per-render content: what to draw, when, and which style class to use.
The split mirrors AE's "character style + text layer content" or web's
"CSS class + DOM element".

Industry alignment: `LowerThirdOverlay` follows the broadcast-graphics
standard (Adobe Premiere / DaVinci / OBS / vMix all call this a
"lower third" or "L3"). `TopicStripOverlay` is our internal name for what
broadcast packages variously call "topic bar", "chapter marker strip", or
"now playing strip" — a static labeled bar pinned to the top edge. Future
overlay kinds (PullQuote / FullCard / Ticker / Bug) extend the same
discriminator pattern.

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
class LowerThirdOverlay:
    """Speaker name plate — broadcast-standard lower third.

    Anchored to the bottom-left or bottom-right safe area. Two-line content:
    `title` (the name, large weight) + `subtitle` (role / affiliation,
    smaller). Rendered as a libass dialogue with `\\pos()` absolute coords;
    the actual pixel position is derived from the matching LowerThirdStyle's
    margin pcts at render time.

    style_class: key into CompositionStyle.overlay_styles — selects which
        LowerThirdStyle drives the visual look. "default" is always
        guaranteed to exist (preset seeds it).
    """
    title: str = ""
    subtitle: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    position: str = "bottom-left"   # "bottom-left" | "bottom-right"
    style_class: str = "default"
    kind: str = "lower_third"
    z_order: int = 50
    zone: str = "lower_third"


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
OverlayUnion = Union[OverlaySpec, LowerThirdOverlay, TopicStripOverlay]


# Tuple of the typed kinds the news_desk pipeline knows about. Used by
# render.py / preview.py to test isinstance() against all supported shapes
# in one shot — extends as new kinds (PullQuote / FullCard / ...) ship.
TYPED_OVERLAY_KINDS: tuple[type, ...] = (
    OverlaySpec, LowerThirdOverlay, TopicStripOverlay,
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
    if kind == "lower_third":
        return LowerThirdOverlay(**_filter(d, LowerThirdOverlay))
    if kind == "topic_strip":
        return TopicStripOverlay(**_filter(d, TopicStripOverlay))
    return OverlaySpec(**_filter(d, OverlaySpec))


def _filter(d: dict, cls) -> dict:
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
