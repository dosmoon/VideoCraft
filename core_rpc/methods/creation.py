"""Creation-domain RPC methods (migration doc §2.2, Creation domain).

The first write surface: load a creation instance's config, list its
components, and patch one component. All writes funnel through the single
in-memory config owner (Session.creation_owner) → owner.save() → a
`event.creation.changed` notification, honoring the one-writer-per-config.json
rule ([[project_creation_config_owner]]). No business logic here — the owner
dataclass already owns load/save; this just forwards + broadcasts.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ..protocol import RpcError
from ..registry import Context, rpc_method


def _config_dict(owner: Any) -> dict[str, Any]:
    """Serialize a config owner (a dataclass) for the wire."""
    return dataclasses.asdict(owner)


@rpc_method("creation.load_config")
def load_config(ctx: Context, type: str, instance: str) -> dict[str, Any]:
    """Full config for one creation instance (the editable state)."""
    owner, _ = ctx.session.creation_owner(type, instance)
    return _config_dict(owner)


@rpc_method("creation.list_components")
def list_components(ctx: Context, type: str, instance: str) -> list[dict[str, Any]]:
    """The instance's component instances, in z-order (top of list = topmost)."""
    owner, _ = ctx.session.creation_owner(type, instance)
    return list(owner.components)


@rpc_method("creation.preview_data")
def preview_data(ctx: Context, type: str, instance: str) -> dict[str, Any]:
    """Per-creation preview inputs for the workbench (candidates, snapshot SRT,
    …), produced by the type's registered preview_provider. The shape is opaque
    to core_rpc — the matching TS assembler consumes it (ADR-0004)."""
    import creations

    ctype = creations.get(type)
    if ctype is None:
        raise RpcError(-32602, f"unknown creation type: {type!r}")
    if ctype.preview_provider is None:
        raise RpcError(-32603, f"creation type {type!r} has no preview_provider")
    return ctype.preview_provider(ctx.session.project, instance)


@rpc_method("creation.update_component")
def update_component(
    ctx: Context,
    type: str,
    instance: str,
    component_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Shallow-merge `patch` into the component with id `component_id`, persist
    via the owner, and broadcast event.creation.changed. Returns the updated
    component dict.
    """
    if not isinstance(patch, dict):
        raise RpcError(-32602, "patch must be an object")
    owner, path = ctx.session.creation_owner(type, instance)

    target = None
    for comp in owner.components:
        if isinstance(comp, dict) and comp.get("id") == component_id:
            target = comp
            break
    if target is None:
        raise RpcError(-32602, f"no component with id {component_id!r}")

    # Don't let a patch rewrite identity fields — id/kind are structural.
    for protected in ("id", "kind"):
        patch.pop(protected, None)
    target.update(patch)

    owner.save(path)
    ctx.notify("event.creation.changed", {"type": type, "instance": instance})
    return target
