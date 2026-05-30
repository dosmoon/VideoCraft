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
        # (type_name, instance_id) -> (config owner, config.json path).
        # The single in-memory owner of a creation's config (project rule:
        # one dataclass owns config.json; writes mutate it then save()).
        self._creations: dict[tuple[str, str], tuple[Any, str]] = {}

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
        self._creations.clear()

    def close_project(self) -> None:
        self._project = None
        self._models.clear()
        self._creations.clear()

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

    # ── Creation config owners ────────────────────────────────────────────

    def creation_owner(self, type_name: str, instance_id: str) -> tuple[Any, str]:
        """Resolve (and cache) the single in-memory config owner for a creation
        instance, plus its config.json path. Loads via the type's registered
        config_owner_cls (base layer never imports a creation by name — ADR-0004).

        Returns (owner, path). Raises RpcError if the type is unknown or hasn't
        opted into a config owner.
        """
        key = (type_name, instance_id)
        cached = self._creations.get(key)
        if cached is not None:
            return cached

        import os

        import creations  # registry; plugins self-register on import

        ctype = creations.get(type_name)
        if ctype is None:
            raise RpcError(-32602, f"unknown creation type: {type_name!r}")
        owner_cls = ctype.config_owner_cls
        if owner_cls is None:
            raise RpcError(
                -32603, f"creation type {type_name!r} has no config_owner_cls"
            )
        path = os.path.join(
            self.project.creation_instance_dir(type_name, instance_id), "config.json"
        )
        owner = owner_cls.load(path)
        self._creations[key] = (owner, path)
        return owner, path
