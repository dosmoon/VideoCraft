"""Single in-memory owner of the open Project (migration doc §2.3).

The sidecar holds exactly one open Project at a time. Material model
instances are cached per (type, instance) so their subscribe() callbacks
(change events) survive across calls. Disk remains the source of truth;
this is just the live handle the renderer talks to.
"""

from __future__ import annotations

from typing import Any, Optional

from .protocol import RpcError


class Session:
    """Holds the live Project + a cache of material model instances."""

    def __init__(self) -> None:
        self._project: Optional[Any] = None
        # (type_name, instance_id) -> model object (e.g. NewsVideoModel)
        self._models: dict[tuple[str, str], Any] = {}

    # ── Project ───────────────────────────────────────────────────────────

    @property
    def project(self) -> Any:
        """The open Project, or raise if none is open (client called too early)."""
        if self._project is None:
            raise RpcError(
                -32001, "no project open — call project.open first"
            )
        return self._project

    def has_project(self) -> bool:
        return self._project is not None

    def set_project(self, project: Any) -> None:
        self._project = project
        self._models.clear()  # models are project-scoped; drop stale handles

    def close_project(self) -> None:
        self._project = None
        self._models.clear()

    # ── Material models ───────────────────────────────────────────────────

    def material_model(self, type_name: str, instance_id: str) -> Any:
        """Resolve (and cache) a material model via its registered factory.

        Raises RpcError if the type is unknown or has no instance_factory.
        Caching keeps subscribe() callbacks alive across RPC calls.
        """
        key = (type_name, instance_id)
        cached = self._models.get(key)
        if cached is not None:
            return cached

        import materials  # registry; plugins self-register on import

        mtype = materials.get(type_name)
        if mtype is None:
            raise RpcError(-32602, f"unknown material type: {type_name!r}")
        if mtype.instance_factory is None:
            raise RpcError(
                -32603, f"material type {type_name!r} has no instance_factory"
            )
        model = mtype.instance_factory(self.project, instance_id)
        self._models[key] = model
        return model
