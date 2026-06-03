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
    #
    # ADR-0008 B5: material data lives in TS (desktop/src/materials/news_video/);
    # the sidecar no longer resolves Python material models. The model cache +
    # invalidate_material are kept (now a no-op cache) because project.rename/
    # delete_instance still call invalidate_material defensively.

    def invalidate_material(self, type_name: str, instance_id: str) -> None:
        """Drop any cached material model handle for the instance (no-op now that
        models live in TS; kept for project.rename/delete_instance callers)."""
        self._models.pop((type_name, instance_id), None)
