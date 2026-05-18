"""Clip-workbench component registry — Step 5.0 scaffold.

A "component" in clip is the same edit-time unit news_desk uses
(see creations/news_desk/components/__init__.py). Clip migrates to the
component model so its hook / outro / subtitle / watermark each become
a registered ComponentSpec and the render path can go through
compile_timeline() against composed adapters.

Why a clip-local registry instead of sharing news_desk's:
    Each creation owns its own set of component kinds (clip's subtitle
    has dual-track semantics that news_desk's subtitle doesn't; clip
    has hook/outro that news_desk doesn't have). Sharing one REGISTRY
    would let creations see each other's kinds and collide on shared
    names (e.g. both want "subtitle").

The ComponentSpec dataclass itself is reused as-is from news_desk's
components package — pure type, no state, zero coupling. A follow-up
will physically relocate it to core/composition/component_spec.py
once both creations have been on it for a release cycle.

This module is a SCAFFOLD: no component specs are registered yet.
Step 5.1 onward will drop one component file at a time into this
package, each calling register() at import time.
"""

from __future__ import annotations

from creations.news_desk.components import ComponentSpec, ImportSource


# ── Clip-local registry ─────────────────────────────────────────────────────

REGISTRY: dict[str, ComponentSpec] = {}


def register(spec: ComponentSpec) -> None:
    """Register a spec under its kind. Last-registration-wins so dev
    hot-reload works the same way news_desk's does."""
    REGISTRY[spec.kind] = spec


def all_specs() -> list[ComponentSpec]:
    """Specs in registration order — drives the [+ Add] menu order."""
    return list(REGISTRY.values())


def spec_for_kind(kind: str) -> ComponentSpec | None:
    return REGISTRY.get(kind)


def spec_for_instance(instance: dict) -> ComponentSpec | None:
    if not isinstance(instance, dict):
        return None
    return REGISTRY.get(instance.get("kind", ""))


# ── ComponentDictAdapter — engine ComponentInstance protocol adapter ────────
# Same shape as news_desk's adapter but resolves specs against the
# clip-local REGISTRY above (not news_desk's).

class ComponentDictAdapter:
    """Wraps a clip instance dict + its registered ComponentSpec to
    satisfy core.composition.compile.ComponentInstance protocol."""

    def __init__(self, instance_dict: dict):
        self.instance = instance_dict
        self._spec = spec_for_instance(instance_dict)

    @property
    def kind(self) -> str:
        return self.instance.get("kind", "")

    @property
    def id(self) -> str:
        return self.instance.get("id", "")

    def is_enabled(self) -> bool:
        return bool(self.instance.get("enabled", True))

    def compile(self, clip_range, ctx):
        if self._spec is None or self._spec.compile is None:
            return []
        return self._spec.compile(self.instance, clip_range, ctx)


# ── Side-effect imports — each module calls register() on import ────────────
# Same convention as news_desk: explicit imports, deterministic order,
# import-time registration via register(spec).

from . import subtitle      # noqa: E402, F401
from . import watermark     # noqa: E402, F401
from . import hook_outro    # noqa: E402, F401
