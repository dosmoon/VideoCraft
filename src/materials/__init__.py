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
    # True ⇒ the 素材 [+] menu offers [open existing] over [new]. news_video is
    # single-instance because source/ASR are still project-level (one source per
    # project; see core/subtitle_pipeline.py TODO(ADR-0005)).
    single_instance: bool = False
    default_basename: str = ""   # base for auto-increment when multi-instance
    icon: Optional[str] = None
    # (parent_frame, hub, instance_id) -> sidebar panel object
    sidebar_renderer: Optional[Callable] = None
    # (hub) -> None; creates a NEW empty instance, triggers refresh.
    # The 素材 tab [+] popup menu invokes this per type.
    create_handler: Optional[Callable] = None
    # (project, instance_id) -> model object exposing get_artifact(key) etc.
    # Slice Q uses this from creation plugins to resolve material artifacts.
    instance_factory: Optional[Callable] = None
    # (existing: list[str]) -> str; the plugin's preferred auto-name scheme.
    # When None, suggest_instance_name() falls back to default_basename / type.
    suggest_name: Optional[Callable] = None


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


def suggest_instance_name(type_name: str, existing: list[str]) -> str:
    """Suggest the next instance name given the existing ones.

    Delegates to the plugin's own `suggest_name` when provided; otherwise
    falls back to '<default_basename or type_name>-N' (first unused index).
    Mirrors creations.suggest_instance_name so the [+] menu is symmetric.
    """
    t = get(type_name)
    if t is not None and t.suggest_name is not None:
        return t.suggest_name(existing)
    stem = (t.default_basename if t and t.default_basename else type_name)
    s = set(existing)
    n = 1
    while True:
        candidate = f"{stem}-{n}"
        if candidate not in s:
            return candidate
        n += 1
