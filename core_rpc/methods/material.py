"""Material-domain RPC methods (migration doc §2.2, Material domain).

Read-only bindings over the MaterialInstanceModel protocol, resolved through
the material registry's instance_factory (Session caches the model so its
subscribe() callbacks survive across calls). Base layer never hard-codes a
plugin name — the type string drives the factory lookup (ADR-0004).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ..registry import Context, rpc_method


def _jsonable(value: Any) -> Any:
    """Best-effort serialize a model return value for the wire.

    Dataclasses (e.g. SlotState) → dict; Paths/anything-with-__fspath__ → str;
    dicts/lists recurse. Keeps the binding decoupled from each model's exact
    field set (no per-plugin serializer here)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__fspath__"):  # Path-like
        return str(value)
    return str(value)


@rpc_method("material.slot_readiness")
def slot_readiness(ctx: Context, type: str, instance: str) -> dict[str, Any]:
    """Per-slot readiness for one material instance (drives sidebar tree)."""
    model = ctx.session.material_model(type, instance)
    return _jsonable(model.slot_readiness())


@rpc_method("material.get_artifact")
def get_artifact(ctx: Context, type: str, instance: str, key: str) -> str | None:
    """Resolve an artifact key to an absolute file path, or null if absent.

    The renderer reads the file directly (e.g. via vc-media://); the path
    namespace is the model's stable contract (source / context / subtitle:<lang>
    / analysis:<lang>:<kind>)."""
    model = ctx.session.material_model(type, instance)
    path = model.get_artifact(key)
    return str(path) if path is not None else None
