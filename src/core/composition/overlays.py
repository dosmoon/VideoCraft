"""Time-windowed overlay specifications — the per-render content data.

CompositionStyle holds reusable visual classes (look). OverlaySpec holds
per-render content: what to draw, when, and which style class to use. The
split mirrors AE's "character style + text layer content" or web's
"CSS class + DOM element".

This module currently defines only the generic OverlaySpec shape — concrete
typed kinds (ChapterCardOverlay, LowerThirdOverlay, HotclipMarkerOverlay,
...) will be added when news_desk derivatives go live. The seat reserves
the API contract so consumers can pass `req.overlays=[...]` today and the
render path will pick the matching renderer when one is registered.

Pattern for future concrete kinds:

    @dataclass
    class ChapterCardOverlay:
        kind: Literal["chapter_card"] = "chapter_card"
        start_sec: float
        end_sec: float
        zone: str = "banner_top"
        z_order: int = 50
        title: str
        subtitle: str = ""
        style_class: str = "default"    # → style.overlay_styles[key]

Each kind dataclass becomes the single contract shared by: AI prompt JSON
schema, on-disk JSON storage, UI list editor, and composition renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OverlaySpec:
    """Generic time-windowed overlay. Concrete kinds will subclass / replace
    this shape when news_desk goes live; for now this is the API seat.

    Fields:
        kind: discriminator that selects a registered renderer in render.py.
        start_sec / end_sec: time window relative to the composition's clip
            range (0..duration), NOT absolute source video time.
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
