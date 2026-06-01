"""Project-domain RPC methods (migration doc §2.2, Project domain).

Read-only + lifecycle bindings over src/project.py. Each method is a thin
forward to the existing Project API; no business logic lives here. Mutating
material/creation ops land in later slices.
"""

from __future__ import annotations

import os
from typing import Any

import project as _project  # src/project.py (src/ on sys.path)

from ..protocol import RpcError
from ..registry import Context, rpc_method


def _project_brief(folder: str) -> dict[str, Any]:
    """Lightweight descriptor for a project folder (recent list / current)."""
    return {"folder": folder, "name": os.path.basename(os.path.normpath(folder))}


@rpc_method("project.recent_list")
def recent_list(ctx: Context) -> list[dict[str, Any]]:
    """Recent projects, newest first. Folders that no longer exist are already
    filtered out by get_recent_projects()."""
    return [_project_brief(p) for p in _project.get_recent_projects()]


@rpc_method("project.open")
def open_project(ctx: Context, folder: str) -> dict[str, Any]:
    """Load a project from disk, make it the session's current project, and
    record it in the recent list. Returns the project brief + meta."""
    if not isinstance(folder, str) or not folder:
        raise RpcError(-32602, "folder must be a non-empty string")
    if not os.path.isdir(folder):
        raise RpcError(-32602, f"not a directory: {folder}")
    try:
        proj = _project.Project.open(folder)
    except Exception as exc:  # noqa: BLE001 — surface as a clean RPC error
        raise RpcError(-32001, f"failed to open project: {exc}") from exc
    ctx.session.set_project(proj)
    _project.add_recent_project(folder)
    ctx.notify("event.project.opened", {"folder": folder})
    return _current_payload(proj)


@rpc_method("project.close")
def close_project(ctx: Context) -> dict[str, Any]:
    ctx.session.close_project()
    ctx.notify("event.project.closed", None)
    return {"closed": True}


@rpc_method("project.current")
def current(ctx: Context) -> dict[str, Any] | None:
    """The open project's brief + meta, or null if none is open."""
    if not ctx.session.has_project():
        return None
    return _current_payload(ctx.session.project)


def _current_payload(proj: Any) -> dict[str, Any]:
    payload = _project_brief(proj.folder)
    try:
        payload["meta"] = proj.meta.to_dict()
    except Exception:  # noqa: BLE001 — meta is best-effort, never block open
        payload["meta"] = None
    return payload


@rpc_method("project.list_material_types")
def list_material_types(ctx: Context) -> list[str]:
    return ctx.session.project.list_material_types()


@rpc_method("project.list_material_instances")
def list_material_instances(ctx: Context, type: str) -> list[str]:
    return ctx.session.project.list_material_instances(type)


@rpc_method("project.list_materials")
def list_materials(ctx: Context) -> dict[str, list[str]]:
    """All material types → their instance names, in one call (sidebar build)."""
    return ctx.session.project.list_materials()


@rpc_method("project.list_creations")
def list_creations(ctx: Context) -> dict[str, list[str]]:
    return ctx.session.project.list_creations()


@rpc_method("project.list_creation_types")
def list_creation_types(ctx: Context) -> list[dict[str, Any]]:
    """Registered creation types for the 创作 [+] menu, in registration order.
    Returns user-facing descriptions — `display_name_key` is an i18n key not
    resolvable headless, so the renderer shows description_zh/_en, never the raw
    type_name ([[feedback_user_facing_naming]])."""
    import creations

    return [
        {
            "type_name": t.type_name,
            "single_instance": t.single_instance,
            "description_zh": t.description_zh,
            "description_en": t.description_en,
        }
        for t in creations.all_types()
    ]


@rpc_method("project.list_material_types_info")
def list_material_types_info(ctx: Context) -> list[dict[str, Any]]:
    """Registered material types for the 素材 [+] menu, in registration order.
    Returns user-facing descriptions — `display_name_key` is an i18n key not
    resolvable headless, so the renderer shows description_zh/_en, never the raw
    type_name ([[feedback_user_facing_naming]])."""
    import materials

    return [
        {
            "type_name": t.type_name,
            "single_instance": t.single_instance,
            "description_zh": t.description_zh,
            "description_en": t.description_en,
        }
        for t in materials.all_types()
    ]


@rpc_method("project.create_material_instance")
def create_material_instance(ctx: Context, type: str, name: str | None = None) -> dict[str, Any]:
    """Create a new material instance and return {type, instance}. When `name`
    is omitted the plugin's auto-name scheme is used (suggest_instance_name). The
    instance starts with an instance.json skeleton + empty source/ + subtitles/
    dirs (faithful to the Tk _create_handler). Emits event.materials.changed so
    the sidebar tree refreshes."""
    import materials

    if materials.get(type) is None:
        raise RpcError(-32602, f"unknown material type: {type!r}")
    proj = ctx.session.project
    existing = proj.list_material_instances(type)
    inst = (name or "").strip() or materials.suggest_instance_name(type, existing)
    if inst in existing:
        raise RpcError(-32602, f"material instance already exists: {inst!r}")
    try:
        inst_dir = proj.create_material_instance(
            type, inst,
            initial_config={
                "schema_version": 1,
                "type_name": type,
                "instance_name": inst,
                "display_name": inst,
            },
            config_filename="instance.json",
        )
    except FileExistsError as exc:
        raise RpcError(-32602, f"material instance already exists: {inst!r}") from exc
    except ValueError as exc:
        raise RpcError(-32602, str(exc)) from exc
    # Skeleton slot dirs so later writes (source acquire, ASR) don't ENOENT.
    os.makedirs(os.path.join(inst_dir, "source"), exist_ok=True)
    os.makedirs(os.path.join(inst_dir, "subtitles"), exist_ok=True)
    ctx.notify("event.materials.changed", {"type": type, "instance": inst})
    return {"type": type, "instance": inst}


@rpc_method("project.create_creation_instance")
def create_creation_instance(ctx: Context, type: str, name: str | None = None) -> dict[str, Any]:
    """Create a new creation instance and return {type, instance}. When `name`
    is omitted the next auto-numbered name is used (suggest_instance_name). The
    instance starts with an empty config.json (the single owner fills it on first
    edit). Emits event.creations.changed so any open view refreshes."""
    import creations

    if creations.get(type) is None:
        raise RpcError(-32602, f"unknown creation type: {type!r}")
    proj = ctx.session.project
    existing = proj.list_creation_instances(type)
    inst = (name or "").strip() or creations.suggest_instance_name(type, existing)
    if inst in existing:
        raise RpcError(-32602, f"creation instance already exists: {inst!r}")
    try:
        proj.create_creation_instance(type, inst, initial_config={})
    except FileExistsError as exc:
        raise RpcError(-32602, f"creation instance already exists: {inst!r}") from exc
    except ValueError as exc:
        raise RpcError(-32602, str(exc)) from exc
    ctx.notify("event.creations.changed", {"type": type, "instance": inst})
    return {"type": type, "instance": inst}


@rpc_method("project.creation_instance_dir")
def creation_instance_dir(ctx: Context, type: str, instance: str) -> str:
    """Absolute path of a creation instance's directory. Generic, plugin-agnostic
    framework dir resolution (ADR-0008): the TS config owner reads/writes its
    config.json + render outputs through the main-process fs, but the directory
    LAYOUT stays owned by Project — so TS asks for the path rather than rebuilding
    the layout. No plugin name is hard-coded here (ADR-0004)."""
    return ctx.session.project.creation_instance_dir(type, instance)


@rpc_method("project.rename_instance")
def rename_instance(ctx: Context, kind: str, type: str, instance: str, new_name: str) -> dict[str, Any]:
    """Rename a material/creation instance directory. kind ∈ {material, creation}.
    A binding to a renamed material is NOT chased (matches Tk) — it dangles and the
    bound creation falls back to nobind. Emits the matching changed event."""
    proj = ctx.session.project
    new = (new_name or "").strip()
    try:
        if kind == "material":
            proj.rename_material_instance(type, instance, new)
            ctx.session.invalidate_material(type, instance)
            ctx.notify("event.materials.changed", {"type": type, "instance": new})
        elif kind == "creation":
            proj.rename_creation_instance(type, instance, new)
            ctx.session.invalidate_creation(type, instance)
            ctx.notify("event.creations.changed", {"type": type, "instance": new})
        else:
            raise RpcError(-32602, f"unknown kind: {kind!r}")
    except FileExistsError as exc:
        raise RpcError(-32602, f"instance already exists: {new!r}") from exc
    except (ValueError, FileNotFoundError) as exc:
        raise RpcError(-32602, str(exc)) from exc
    return {"type": type, "instance": new}


@rpc_method("project.delete_instance")
def delete_instance(ctx: Context, kind: str, type: str, instance: str) -> dict[str, Any]:
    """Delete a material/creation instance directory. kind ∈ {material, creation}.
    Emits the matching changed event so the sidebar refreshes."""
    proj = ctx.session.project
    try:
        if kind == "material":
            proj.delete_material_instance(type, instance)
            ctx.session.invalidate_material(type, instance)
            ctx.notify("event.materials.changed", {"type": type, "instance": instance})
        elif kind == "creation":
            proj.delete_creation_instance(type, instance)
            ctx.session.invalidate_creation(type, instance)
            ctx.notify("event.creations.changed", {"type": type, "instance": instance})
        else:
            raise RpcError(-32602, f"unknown kind: {kind!r}")
    except FileNotFoundError as exc:
        raise RpcError(-32602, str(exc)) from exc
    return {"ok": True}
