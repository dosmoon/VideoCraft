"""Creation plugin registry.

See ADR-0004 (docs/adr/0004-three-tier-plugin-architecture.md).

A creation plugin = one downstream workbench that produces a video from
a project's source materials. Each plugin lives at creations/<type_name>/
and self-registers at import time by calling register().

Base layer (core/) MUST NOT hard-code plugin names. Discovery happens via
core_rpc.methods.load_plugins() importing each plugin module at sidecar
startup, which triggers the plugin's register() call.

Replaces the old core/derivative_types.py REGISTRY (slice E retires it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CreationType:
    """Metadata describing one creation plugin type.

    ADR-0008: a creation plugin's logic (config owner / preview / render / preset
    / import) lives entirely in TS (desktop/src/creations/<type>/). The sidecar
    only carries this type metadata for the framework directory lifecycle
    (create/rename/delete instance + dir resolution via project.*). The former
    config_owner_cls / preview_provider / render_provider / import_provider fields
    are gone — the per-plugin Python they delegated to was retired.
    """
    type_name: str               # folder under creations/ AND under <project>/derivatives/<type>/
    display_name_key: str        # i18n key for the type's user-facing label
    tool_key: str                # TOOL_MAP entry used to open its workbench
    default_basename: str        # base for auto-increment ("default", "cut", "v")
    single_instance: bool        # True ⇒ menu offers [open existing] vs [new]
    description_zh: str          # subtitle in the type-picker dialog (zh)
    description_en: str          # subtitle in the type-picker dialog (en)
    icon: Optional[str] = None


# Module-private registry. Plugins call register() at import time.
_REGISTRY: dict[str, CreationType] = {}
_ORDER: list[str] = []   # canonical display order = registration order


def register(t: CreationType) -> None:
    """Plugin self-registration entry point. Idempotent."""
    if t.type_name in _REGISTRY:
        return
    _REGISTRY[t.type_name] = t
    _ORDER.append(t.type_name)


def get(type_name: str) -> Optional[CreationType]:
    return _REGISTRY.get(type_name)


def all_types() -> list[CreationType]:
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

    For single_instance types: 'default' if free, else 'v2', 'v3', ...
    For multi-instance types:  '<basename>-1', '<basename>-2', ... (the
        first unused number).
    """
    t = get(type_name)
    if t is None:
        return _next_numbered("v", existing)

    existing_set = set(existing)
    if t.single_instance:
        if "default" not in existing_set:
            return "default"
        return _next_numbered("v", existing)
    return _next_numbered(t.default_basename, existing, sep="-")


def _next_numbered(stem: str, existing: list[str], sep: str = "") -> str:
    """Return f'{stem}{sep}{n}' for the smallest n>=1 not in existing."""
    s = set(existing)
    n = 1
    while True:
        candidate = f"{stem}{sep}{n}" if sep else f"{stem}{n}"
        if candidate not in s:
            return candidate
        n += 1
