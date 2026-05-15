"""News-desk B-class component registry.

A "component" here is one kind of time-bound overlay (LowerThird,
TopicStrip, ChapterPointCard, DateStamp, ...). Each kind contributes a
single ComponentSpec to REGISTRY, and the news-desk workbench drives
its add/derive/edit/list UI off REGISTRY — adding a new kind means
dropping a new file in this package, not editing news_desk_tool.py.

Each component file defines a spec at module import and calls
`register(spec)`. This package's __init__ imports every component
module so that side-effect registration runs without the host having
to know component names.

Spec shape — see ComponentSpec docstring below. Counterpart for
A-class (singleton) controls is the main tool's _build_form, not this
registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import tkinter as tk
from tkinter import ttk


# ── Derive source identifiers ──────────────────────────────────────────────
# A derive source is a project-level data file the component can pull
# entries from. Handlers receive a `DeriveContext` and return the list of
# overlay instances they want appended (empty list = nothing to derive).

DERIVE_BASIC_INFO = "basic_info"     # source/basic_info.json + context.json
DERIVE_ANALYSIS = "analysis"         # subtitles/<iso>.analysis.json chapters


@dataclass
class DeriveContext:
    """Read-only handle passed into derive handlers. Lets the handler
    reach project paths + duration without coupling to NewsDeskApp."""
    project: object                  # core.project.Project
    duration: float                  # full source duration in seconds
    chapters_loader: Callable        # () -> list[dict] (analysis chapters)


@dataclass
class DeriveSource:
    """One derive option exposed by a component."""
    kind: str                        # DERIVE_BASIC_INFO / DERIVE_ANALYSIS
    label_key: str                   # i18n key for the menu/button label
    handler: Callable                # (DeriveContext) -> list[overlay]
    # If True, calling this handler should first remove any existing
    # overlays of the component's dataclass_type so re-derive is
    # idempotent (DateStamp does this).
    replace_existing: bool = False


@dataclass
class ComponentSpec:
    """One B-class component kind registered with the workbench.

    Fields:
      kind            — short id matching the overlay dataclass's `kind`
                        attribute (e.g. "lower_third"). Used as REGISTRY
                        key and in config.json.
      dataclass_type  — overlay dataclass class. Used for isinstance
                        dispatch when refreshing the list and when
                        derive handlers want to filter existing overlays.
      label_key       — i18n key for the "+ Add" button/menu label (e.g.
                        "tool.news_desk.add.lower_third"). The host adds
                        the leading "+ " visual itself.
      name_key        — i18n key for the bare component name (used as
                        group header in the list). e.g.
                        "tool.news_desk.kind.lower_third" → "名牌".
      default_factory — (duration:float) -> overlay instance with sane
                        defaults. Called when the user clicks "+ Add".
      format_content  — (overlay) -> str. One-line content summary shown
                        in the list/tree.
      build_edit_fields — (parent, overlay, time_vars, on_change=None)
                        -> commit_cb. Builds the type-specific portion
                        of the edit form (start/end are owned by the
                        host). Returns a no-arg commit() that mutates
                        `overlay` in place from the form's current Tk
                        var values. If `on_change` is provided (live
                        property-panel mode), the spec attaches write
                        traces to its vars that call commit + on_change
                        on every edit; if None (modal-dialog mode), the
                        host calls commit() once on OK.
      derive_sources  — list of DeriveSource. May be empty.
    """
    kind: str
    dataclass_type: type
    label_key: str
    name_key: str
    default_factory: Callable
    format_content: Callable
    build_edit_fields: Callable
    derive_sources: list = field(default_factory=list)


REGISTRY: dict[str, ComponentSpec] = {}


def register(spec: ComponentSpec) -> None:
    """Add a spec to REGISTRY. Last-registration-wins on kind collision —
    useful for in-place hot reload during dev, harmless in production
    because each component module registers once at import time."""
    REGISTRY[spec.kind] = spec


def install_live_traces(
    variables: list,
    commit: Callable[[], None],
    on_change: Callable[[], None],
) -> None:
    """Attach write-traces to a list of Tk variables so that any user
    edit immediately calls commit() (mutating the dataclass) and then
    on_change() (notifying the host). Call this AFTER setting initial
    var values so init writes don't fire spurious events.
    """
    def _fire(*_):
        commit()
        on_change()
    for v in variables:
        v.trace_add("write", _fire)


def all_specs() -> list[ComponentSpec]:
    """Return specs in registration order (Python 3.7+ dict preserves
    insertion order). Host iterates this for button creation."""
    return list(REGISTRY.values())


def spec_for(overlay) -> ComponentSpec | None:
    """Resolve the spec for a runtime overlay instance, by isinstance.
    Falls back to None for unknown types (legacy data on disk)."""
    for s in REGISTRY.values():
        if isinstance(overlay, s.dataclass_type):
            return s
    return None


# Side-effect imports — each module calls register() at top level.
# Keep this list explicit (not glob-discovered) so the import order is
# deterministic and the dependency graph is grep-able.
from . import lower_third          # noqa: E402, F401
from . import topic_strip          # noqa: E402, F401
from . import chapter_point_card   # noqa: E402, F401
from . import date_stamp           # noqa: E402, F401
