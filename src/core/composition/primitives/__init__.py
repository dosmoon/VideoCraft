"""Primitive registry — render-time dispatch by element kind.

Each primitive module (primitives/<kind>.py, landing in PR 2) registers
its renderer at import time via register_overlay_renderer(KIND, fn).
The engine render loop looks up the renderer by element.kind string —
no isinstance, no per-kind branches in render.py.

PR 1 lands the registry scaffolding only; the 7 primitive modules
(subtitle_cue, text_watermark, image_watermark, hook_text, outro_text,
topic_strip, chapter_hero_card) arrive in PR 2 along with the
libass_helpers harvest from news_desk_overlays.py.
"""

from __future__ import annotations

from typing import Callable


# Renderer signature stays loose until PR 2 wires it to the actual
# render.py job / context types. The registry only needs to hold and
# dispatch by kind; the call site validates the signature.
OverlayRenderer = Callable[..., object]


# ── Primitive catalog (design-intent kind names for timeline IR) ────────────
#
# Frozen set of every kind string an Element may carry. compile_timeline()
# validates each emitted element against this set so typos in component
# code fail loudly at compile time rather than silently producing renders
# with missing elements.
#
# Note: this is the *design-intent* catalog (Element.kind names). The
# renderer-registration kind names overlap mostly but not entirely —
# the legacy "subtitle_libass" renderer corresponds to the "subtitle_cue"
# primitive; "news_desk_ass" is a render-internal renderer that merges
# topic_strip + chapter_hero_card dialogues. PR 4 reconciles the two
# name spaces by switching render dispatch to match the primitive names.
KNOWN_KINDS: frozenset[str] = frozenset({
    "subtitle_cue",
    "text_watermark",
    "image_watermark",
    "hook_text",
    "outro_text",
    "topic_strip",
    "chapter_hero_card",
})


_registry: dict[str, OverlayRenderer] = {}


def register_overlay_renderer(kind: str, fn: OverlayRenderer) -> None:
    """Register a renderer for a primitive kind. Each kind has exactly
    one renderer (module-level register on import); re-registering is
    a programming error, not a runtime hot-swap.
    """
    if not kind:
        raise ValueError("register_overlay_renderer: empty kind")
    if kind in _registry:
        raise ValueError(
            f"register_overlay_renderer: kind {kind!r} already registered")
    _registry[kind] = fn


def get_overlay_renderer(kind: str) -> OverlayRenderer:
    """Look up a renderer. Unknown kind raises KeyError — caller must
    ensure the primitive module has been imported before render.
    """
    if kind not in _registry:
        raise KeyError(
            f"get_overlay_renderer: kind {kind!r} not registered")
    return _registry[kind]


def is_registered(kind: str) -> bool:
    return kind in _registry


def _reset_for_tests() -> None:
    """Test-only escape hatch — tests that exercise registration need a
    clean slate. Never call from production code.
    """
    _registry.clear()
