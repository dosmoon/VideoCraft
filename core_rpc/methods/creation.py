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


@rpc_method("creation.update_config")
def update_config(ctx: Context, type: str, instance: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Patch top-level config fields (output geometry, selection, per-candidate
    overrides) through the single owner's `apply_patch`, persist, and broadcast.
    The owner decides what's patchable, so this stays creation-agnostic. Returns
    the updated config dict.
    """
    if not isinstance(patch, dict):
        raise RpcError(-32602, "patch must be an object")
    owner, path = ctx.session.creation_owner(type, instance)
    apply = getattr(owner, "apply_patch", None)
    if not callable(apply):
        raise RpcError(-32603, f"creation type {type!r} config does not support update_config")
    apply(patch)
    owner.save(path)
    ctx.notify("event.creation.changed", {"type": type, "instance": instance})
    return _config_dict(owner)


@rpc_method("creation.list_addable_components")
def list_addable_components(ctx: Context, type: str, instance: str) -> list[dict[str, Any]]:
    """Component kinds the workbench's [+ Add] menu may offer, in registration
    order, each with its `multi_instance` flag. The owner decides what's
    addable, so the base layer stays creation-agnostic (ADR-0004)."""
    owner, _ = ctx.session.creation_owner(type, instance)
    fn = getattr(owner, "addable_kinds", None)
    if not callable(fn):
        raise RpcError(-32603, f"creation type {type!r} does not support add-component")
    return fn()


@rpc_method("creation.add_component")
def add_component(ctx: Context, type: str, instance: str, kind: str) -> list[dict[str, Any]]:
    """Append a default instance of `kind` (with a unique id) via the owner,
    persist, broadcast. Returns the updated component list."""
    owner, path = ctx.session.creation_owner(type, instance)
    fn = getattr(owner, "add_component", None)
    if not callable(fn):
        raise RpcError(-32603, f"creation type {type!r} does not support add-component")
    try:
        fn(kind)
    except ValueError as exc:
        raise RpcError(-32602, str(exc)) from exc
    owner.save(path)
    ctx.notify("event.creation.changed", {"type": type, "instance": instance})
    return list(owner.components)


@rpc_method("creation.remove_component")
def remove_component(ctx: Context, type: str, instance: str, component_id: str) -> list[dict[str, Any]]:
    """Remove the component with id `component_id` via the owner, persist,
    broadcast. Returns the updated component list."""
    owner, path = ctx.session.creation_owner(type, instance)
    fn = getattr(owner, "remove_component", None)
    if not callable(fn):
        raise RpcError(-32603, f"creation type {type!r} does not support remove-component")
    fn(component_id)
    owner.save(path)
    ctx.notify("event.creation.changed", {"type": type, "instance": instance})
    return list(owner.components)


@rpc_method("creation.move_component")
def move_component(
    ctx: Context, type: str, instance: str, component_id: str, delta: int
) -> list[dict[str, Any]]:
    """Move the component `delta` positions in the z-order (±1) via the owner,
    persist, broadcast. Returns the updated component list."""
    owner, path = ctx.session.creation_owner(type, instance)
    fn = getattr(owner, "move_component", None)
    if not callable(fn):
        raise RpcError(-32603, f"creation type {type!r} does not support move-component")
    try:
        fn(component_id, int(delta))
    except (TypeError, ValueError) as exc:
        raise RpcError(-32602, f"invalid delta: {exc}") from exc
    owner.save(path)
    ctx.notify("event.creation.changed", {"type": type, "instance": instance})
    return list(owner.components)


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
