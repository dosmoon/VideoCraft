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
    # Bound material's model object (e.g. NewsVideoModel). The ONLY
    # legitimate handle components have on upstream material data —
    # ask the model for paths / context / analyses, never reach into
    # the material plugin's path helpers directly. None until host
    # establishes the binding.
    material_model: object = None
    # Optional preview hooks — host wires these so component panels can
    # drive the WebView preview (e.g. chapter list click-to-seek).
    # None when no preview is mounted; callers must guard.
    seek_to: Callable = None         # (sec: float) -> None
    # Optional language codes that the bound material exposes as
    # subtitle tracks. clip's host fills this from the hotclips SRT
    # pool so the subtitle property panel can show a language picker.
    # Empty list when the host doesn't know (e.g. news_desk).
    subtitle_languages: list = field(default_factory=list)


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

    # Timeline-IR compile: pure function emitting a list of timeline
    # Elements for this instance. PR 3 (Axis 7.2/7.6) — runs alongside
    # to_overlays during the migration; PR 4 wires it to render. Signature:
    #   (instance: dict, clip_range: ClipRange, ctx: CompileContext)
    #     -> list[core.composition.timeline.Element]
    # Must be pure: no UI, no writes, no side effects beyond reading
    # material data. Element.kind must be in primitives.KNOWN_KINDS.
    compile: Callable = None

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
