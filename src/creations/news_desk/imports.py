"""News-desk import provider (sidecar side).

The user-facing "import subtitle / import chapters" flows for the news_desk
workbench. Both pull from the bound material and SNAPSHOT into this creation
instance ([[project_snapshot_principle]]): a subtitle component copies the
chosen language's SRT into the instance dir and points its srt_path at it; the
chapter component copies the analysis.json chapter rows into its schedule.

Registered on CreationType.import_provider so core_rpc resolves it generically
(ADR-0004 — the base layer never imports this by name). This round covers
importing from the bound material's existing artifacts only (the common case
after ASR / chapter analysis has run); external file import is a follow-up.

  list_imports(project, instance)                              -> {subtitleLangs, analyses}
  import_resource(project, instance, component_id, params)     -> updated component dict

`params` is provider-defined and opaque to the base layer:
  {"kind": "subtitle", "lang": "<iso>"}           — snapshot that language's SRT
  {"kind": "chapters", "filename": "<analysis>"}  — fill schedule from analysis
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from creations.news_desk.config import NewsDeskInstanceConfig


def _resolve(project, instance: str):
    """(cfg, inst_dir, model | None). model is None when unbound. Mirrors
    export.py::_resolve — resolves the bound material via the registry without
    hard-coding a plugin name."""
    inst_dir = project.creation_instance_dir("news_desk", instance)
    cfg = NewsDeskInstanceConfig.load(os.path.join(inst_dir, "config.json"))
    if cfg.bound_material is None:
        return cfg, inst_dir, None

    import materials

    mtype = materials.get(cfg.bound_material.type_name)
    model = (
        mtype.instance_factory(project, cfg.bound_material.instance_name)
        if mtype and mtype.instance_factory
        else None
    )
    return cfg, inst_dir, model


def list_imports(project, instance: str) -> dict[str, Any]:
    """What this instance can import from its bound material: subtitle languages
    (for subtitle components) and analysis filenames (for the chapter component).
    Empty lists when unbound or the model lacks the artifacts."""
    _cfg, _inst_dir, model = _resolve(project, instance)
    if model is None:
        return {"subtitleLangs": [], "analyses": []}
    langs = model.list_subtitle_languages() if hasattr(model, "list_subtitle_languages") else []
    analyses = model.list_analyses() if hasattr(model, "list_analyses") else []
    return {"subtitleLangs": list(langs), "analyses": list(analyses)}


def _find_component(cfg: NewsDeskInstanceConfig, component_id: str) -> dict:
    for c in cfg.components:
        if c.get("id") == component_id:
            return c
    raise ValueError(f"no component with id {component_id!r}")


def _import_subtitle(inst_dir, cfg, model, component, lang: str) -> dict:
    """Snapshot the bound material's <lang>.srt into the instance dir and point
    the subtitle component's srt_path at it (faithful to the Tk _import_srt
    snapshot, but sourcing from the material instead of a file dialog)."""
    if component.get("kind") != "subtitle":
        raise ValueError("import subtitle: component is not a subtitle")
    src = model.subtitle_path(lang)
    if not os.path.isfile(src):
        raise ValueError(f"subtitle not found for language {lang!r}")
    rel = f"subtitles/{component['id']}.srt"
    dst = os.path.join(inst_dir, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    component["srt_path"] = rel
    cfg.save(os.path.join(inst_dir, "config.json"))
    return component


def _import_chapters(inst_dir, cfg, model, component, filename: str) -> dict:
    """Fill the chapter component's schedule from an analysis.json envelope
    (faithful to the Tk _import_from_analysis snapshot)."""
    if component.get("kind") != "chapter":
        raise ValueError("import chapters: component is not a chapter")
    try:
        env = model.read_analysis(filename)
    except (OSError, ValueError) as exc:
        raise ValueError(f"read analysis failed: {exc}") from exc
    chapters = env.get("chapters") if isinstance(env, dict) else None
    if not chapters:
        raise ValueError("analysis has no chapters")
    schedule = [
        {
            "start_sec": float(ch.get("start_sec", 0.0)),
            "end_sec": float(ch.get("end_sec", 0.0)),
            "title": str(ch.get("title", "")),
            "refined": str(ch.get("refined", "")),
            "key_points": list(ch.get("key_points") or []),
        }
        for ch in chapters
        if isinstance(ch, dict)
    ]
    component["schedule"] = schedule
    cfg.save(os.path.join(inst_dir, "config.json"))
    return component


def import_resource(project, instance: str, component_id: str, params: dict) -> dict:
    """Perform an import into one component and return the updated component dict.
    The single owner persists the mutation (cfg.save). See module docstring for
    the params shape."""
    if not isinstance(params, dict):
        raise ValueError("import params must be an object")
    cfg, inst_dir, model = _resolve(project, instance)
    if model is None:
        raise ValueError("creation is not bound to a material")
    component = _find_component(cfg, component_id)
    kind = params.get("kind")
    if kind == "subtitle":
        return _import_subtitle(inst_dir, cfg, model, component, str(params.get("lang", "")))
    if kind == "chapters":
        return _import_chapters(inst_dir, cfg, model, component, str(params.get("filename", "")))
    raise ValueError(f"unknown import kind: {kind!r}")
