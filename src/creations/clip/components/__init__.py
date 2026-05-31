"""Clip-workbench component registry.

A "component" in clip is an edit-time unit: its hook / outro / subtitle /
watermark each become a registered ComponentSpec and the render path goes
through compile_timeline() against composed adapters (ComponentDictAdapter).

clip owns its component framework locally — the ComponentSpec / ImportSource /
ProjectContext dataclasses are defined below, and clip keeps its own REGISTRY.
This is deliberate: each creation owns its own component kinds (clip's subtitle
has dual-track semantics news_desk's doesn't; clip has hook/outro it doesn't),
and a shared registry would let creations see each other's kinds and collide on
shared names. These framework types were formerly imported from news_desk; they
moved here when the Tk news_desk workbench was retired (clip is the sole
remaining Tk consumer of the framework). They die with clip's Tk workbench.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


# ── Component-framework types (clip-local) ──────────────────────────────────
# These plain dataclasses were the shared Tk-era component framework, formerly
# imported from news_desk.components. news_desk's new-arch (Electron + headless
# sidecar) workbench no longer uses them, so clip — the sole remaining Tk
# consumer — now owns them. They are Tk-era scaffolding and die with clip's Tk
# workbench; until then they live here (not in core/, which would enshrine
# soon-dead types in a permanent location).

@dataclass
class ProjectContext:
    """Lightweight handle so component code can reach project-level data
    without coupling to the workbench / Project class details."""
    project: object                  # core.project.Project (duck-typed)
    duration: float                  # full source duration in seconds
    # Per ADR-0003 derivatives own their data; components that snapshot
    # upstream materials write into <instance_dir>/. Empty string when the
    # host hasn't established a per-instance directory yet.
    instance_dir: str = ""
    # Bound material's model object — the ONLY legitimate handle components
    # have on upstream material data. None until the host binds.
    material_model: object = None
    # Optional preview hook so component panels can drive the WebView preview
    # (e.g. click-to-seek). None when no preview is mounted; guard before use.
    seek_to: Callable = None         # (sec: float) -> None
    # Subtitle track language codes the bound material exposes. clip fills this
    # from the hotclips SRT pool so the subtitle panel can show a language
    # picker. Empty when the host doesn't know.
    subtitle_languages: list = field(default_factory=list)


@dataclass
class ImportSource:
    """A "[⇩ Import...]" button in the property panel. The handler receives
    the instance dict + ProjectContext and mutates the instance in place."""
    label_key: str
    handler: Callable                # (instance: dict, ctx: ProjectContext) -> None


@dataclass
class ComponentSpec:
    """Declares one component type. Callable fields hold the per-type
    behaviour (defaults, UI, render translation, imports)."""

    # Identity
    kind: str                                  # "subtitle", "hook_outro", ...
    name_key: str                              # i18n key — display name
    add_label_key: str                         # i18n key — [+ Add] menu entry

    # Multiplicity. False = singleton; True = user can add many instances.
    multi_instance: bool = True

    # Default insertion position in the component list (higher = more in front).
    default_z: int = 50

    # Factory: build a fresh instance dict with sane defaults. duration is the
    # source video length (seconds) so factories can default full-length data.
    default_instance: Callable = None          # (duration: float) -> dict

    # Property-panel builder: owns ALL widgets for this component's editor
    # surface, live-editing the instance dict via Tk var write-traces.
    build_property_panel: Callable = None      # (parent, instance, ctx, on_change) -> None

    # Render translation: produce the low-level overlay dataclasses the
    # existing renderer consumes. Returning [] disables the instance.
    to_overlays: Callable = None               # (instance, ctx) -> list

    # Timeline-IR compile: pure function emitting timeline Elements. Signature:
    #   (instance: dict, clip_range: ClipRange, ctx: CompileContext) -> list[Element]
    # Must be pure; Element.kind must be in primitives.KNOWN_KINDS.
    compile: Callable = None

    # Import options shown in the property panel ([⇩ Import...]).
    import_sources: list = field(default_factory=list)


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


# ── Shared property-panel widget helpers ────────────────────────────────────
# Each spec's build_property_panel uses these to keep the look consistent
# across components. Re-implementing here (rather than importing from
# news_desk) keeps clip's components physically independent.

import tkinter as tk
from tkinter import ttk


def add_color_picker(parent, var: tk.StringVar) -> None:
    """Inline color swatch + entry. Click swatch → tk colorchooser."""
    from tkinter import colorchooser
    ttk.Entry(parent, textvariable=var, width=10).pack(side="left")
    swatch = tk.Label(parent, text="🎨", width=2)
    swatch.pack(side="left", padx=(2, 0))

    def _pick(_evt=None):
        _rgb, hexv = colorchooser.askcolor(
            color=var.get() or "#FFFFFF",
            parent=parent.winfo_toplevel())
        if hexv:
            var.set(hexv.upper())
    swatch.bind("<Button-1>", _pick)


# ── Side-effect imports — each module calls register() on import ────────────
# Same convention as news_desk: explicit imports, deterministic order,
# import-time registration via register(spec).

from . import subtitle      # noqa: E402, F401
from . import watermark     # noqa: E402, F401
from . import hook_outro    # noqa: E402, F401
