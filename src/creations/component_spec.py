"""Creations component spec declarations.

Provides base structures and interfaces shared by creations plugin components
(e.g., news_desk and clip components) to drive editing panels and compilations.
Declaring these in creations domain isolates engine composition layer (core/composition)
and resolves cross-plugin coupling dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


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
    seek_to: Optional[Callable] = None  # (sec: float) -> None
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
