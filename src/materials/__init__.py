"""Material plugin registry.

See ADR-0004 (docs/adr/0004-three-tier-plugin-architecture.md).

A material plugin = one type of structured input asset (e.g. a news
video and its derived AI artifacts). Each plugin lives at
materials/<type_name>/ and self-registers at import time by calling
register().

Materials are consumed by creation plugins via artifact_resolver. The
creation plugin queries (instance, key) -> Path and snapshots the file
into its own instance_dir per ADR-0003.

Base layer (core/, ui/) MUST NOT hard-code plugin names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class MaterialType:
    """Metadata describing one material plugin type.

    sidebar_renderer / create_handler / artifact_resolver are filled
    when the concrete plugin lands (slices F / H). Optional until then.
    """
    type_name: str               # folder under materials/
    display_name_key: str        # i18n key for the type's user-facing label
    description_zh: str = ""     # subtitle in the type-picker dialog (zh)
    description_en: str = ""     # subtitle in the type-picker dialog (en)
    icon: Optional[str] = None
    sidebar_renderer: Optional[Callable] = None   # renders this material's tree node in 素材 tab; slice H
    create_handler: Optional[Callable] = None     # handles 素材 tab [+] click; slice F
    artifact_resolver: Optional[Callable] = None  # (instance, key) -> Path | None; slice F
    has_instance: Optional[Callable] = None       # (project) -> bool; gates whether the sidebar paints this material


_REGISTRY: dict[str, MaterialType] = {}
_ORDER: list[str] = []


def register(t: MaterialType) -> None:
    """Plugin self-registration entry point. Idempotent."""
    if t.type_name in _REGISTRY:
        return
    _REGISTRY[t.type_name] = t
    _ORDER.append(t.type_name)


def get(type_name: str) -> Optional[MaterialType]:
    return _REGISTRY.get(type_name)


def all_types() -> list[MaterialType]:
    """All registered types in registration order."""
    return [_REGISTRY[n] for n in _ORDER]


def display_name(type_name: str) -> str:
    """Translate type_name to its user-facing label via i18n.
    Falls back to raw type_name if unknown.
    """
    t = get(type_name)
    if t is None:
        return type_name
    from i18n import tr
    return tr(t.display_name_key)
