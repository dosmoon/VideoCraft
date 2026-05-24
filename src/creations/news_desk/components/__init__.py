"""News-desk component registry.

A "component" is a user-level editing unit (字幕 / 章节 / 水印 / ...).
Each component type is registered once via `register(spec)` and the
news-desk workbench drives its add/edit/render UI off the resulting
REGISTRY — adding a new component type means dropping a new file in
this package, not editing news_desk_tool.py.

Each component INSTANCE in a project is a plain dict with at minimum:
    kind:    matches a registered ComponentSpec.kind
    name:    user-given label shown in the list
    enabled: bool — temporarily hide without deleting
    ... + component-specific fields owned by the spec

The project-level config persists components as an ordered list. List
order IS the z-order (top of list = topmost render layer).

Components are the EDIT-TIME abstraction. At render time the spec's
`to_overlays(instance, ctx)` translates each instance into one or more
low-level overlay dataclasses that the existing renderer consumes.
This decoupling lets the UI evolve independently of the render layer.
"""

from __future__ import annotations

from typing import Callable

import tkinter as tk
from tkinter import ttk

from creations.component_spec import ComponentSpec, ImportSource, ProjectContext


REGISTRY: dict[str, ComponentSpec] = {}


def register(spec: ComponentSpec) -> None:
    """Register a spec under its kind. Last-registration-wins on
    collision so dev hot-reload works."""
    REGISTRY[spec.kind] = spec


def all_specs() -> list[ComponentSpec]:
    """Specs in registration order. Drives the [+ Add] menu order."""
    return list(REGISTRY.values())


def spec_for_kind(kind: str) -> ComponentSpec | None:
    return REGISTRY.get(kind)


def spec_for_instance(instance: dict) -> ComponentSpec | None:
    """Resolve the spec for a runtime instance dict by its kind field."""
    if not isinstance(instance, dict):
        return None
    return REGISTRY.get(instance.get("kind", ""))


# ── ComponentInstance adapter for timeline-IR compile_timeline() ────────────
#
# news_desk stores components as dict instances; the engine's
# ComponentInstance protocol expects objects with kind/id/is_enabled()/
# compile(). This adapter bridges so the dict pipeline can feed into
# core.composition.compile.compile_timeline() without rewriting all
# components as classes.

class ComponentDictAdapter:
    """Wraps a news_desk instance dict + its registered ComponentSpec to
    satisfy core.composition.compile.ComponentInstance protocol.

    PR 3 introduces this as a thin shim; PR 4 wires news_desk's render
    pipeline to feed compile_timeline() via these adapters. PR 5 may
    drop it if the dict-based config becomes object-based.
    """
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
# Explicit (not glob-discovered) so import order is deterministic and
# the dependency graph is grep-able. Order also drives the [+ Add]
# menu — put the most-used first.

from . import chapter           # noqa: E402, F401
from . import subtitle          # noqa: E402, F401
from . import text_watermark    # noqa: E402, F401
from . import image_watermark   # noqa: E402, F401
