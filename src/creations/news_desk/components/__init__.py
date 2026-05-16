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

from dataclasses import dataclass, field
from typing import Callable

import tkinter as tk
from tkinter import ttk


# ── Project context handed to spec callbacks ────────────────────────────────
# Lightweight handle so component code can reach project-level data
# without coupling to NewsDeskApp / Project class details.

@dataclass
class ProjectContext:
    project: object                  # core.project.Project (duck-typed)
    duration: float                  # full source duration in seconds
    # Per ADR-0003 derivatives own their data; components that snapshot
    # upstream materials write into <instance_dir>/. Host wires this so
    # property panels can write local files; empty string when host
    # hasn't established a per-instance directory yet.
    instance_dir: str = ""
    # ADR-0005 slice Q: the bound material instance ID. Components that
    # need to peek at upstream material paths (e.g. chapter import,
    # subtitle import filedialog initialdir) resolve via
    # `_nv_paths.X(project, material_instance_id)`.
    material_instance_id: str = ""
    # Optional preview hooks — host wires these so component panels can
    # drive the WebView preview (e.g. chapter list click-to-seek).
    # None when no preview is mounted; callers must guard.
    seek_to: Callable = None         # (sec: float) -> None


# ── Import source declaration ──────────────────────────────────────────────
# A "[⇩ Import...]" button in the property panel. Handler receives the
# instance dict + ProjectContext and mutates the instance in place.

@dataclass
class ImportSource:
    label_key: str
    handler: Callable                # (instance: dict, ctx: ProjectContext) -> None


# ── ComponentSpec ───────────────────────────────────────────────────────────

@dataclass
class ComponentSpec:
    """Declares one component type. Callable fields hold the per-type
    behaviour (defaults, UI, render translation, imports)."""

    # Identity
    kind: str                                  # "chapter", "subtitle", ...
    name_key: str                              # i18n key — display name
    add_label_key: str                         # i18n key — [+ Add] menu entry

    # Multiplicity. False = singleton (e.g. chapter — bound to a
    # project-unique data source). True = user can add many instances.
    multi_instance: bool = True

    # Default insertion position in the project's component list.
    # Higher value = more "in front" by render convention. New
    # instances slot in so list order matches z conventions:
    #   subtitles (top), watermark (high), name plate, chapter (mid)
    default_z: int = 50

    # Factory: build a fresh instance dict with sane defaults. duration
    # is the source video length (seconds) so factories can default
    # full-length schedules.
    default_instance: Callable = None          # (duration: float) -> dict

    # Property-panel builder: own ALL widgets for this component's
    # editor surface. Live-edit by attaching write-traces to Tk vars
    # that mutate `instance` and call on_change(). Host re-uses the
    # instance dict for serialization, so all edits land back here.
    build_property_panel: Callable = None      # (parent, instance, ctx, on_change) -> None

    # Render translation: produce the low-level overlay dataclasses
    # the existing renderer consumes. Called once per export with the
    # current project state. Returning [] disables this instance for
    # the render (also use `enabled` flag for the same effect).
    to_overlays: Callable = None               # (instance, ctx) -> list

    # Import options shown in the property panel ([⇩ Import...]).
    import_sources: list = field(default_factory=list)


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


# ── Side-effect imports — each module calls register() on import ────────────
# Explicit (not glob-discovered) so import order is deterministic and
# the dependency graph is grep-able. Order also drives the [+ Add]
# menu — put the most-used first.

from . import chapter           # noqa: E402, F401
from . import subtitle          # noqa: E402, F401
from . import text_watermark    # noqa: E402, F401
from . import image_watermark   # noqa: E402, F401
