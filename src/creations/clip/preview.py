"""Clip preview-data provider for the workbench (sidecar RPC).

Returns the data the TS clip preview assembler needs to build the real
composition timeline: the hotclip candidates, the selected index, the snapshot
SRT path, and the selected clip's override. Pure read — no Tk. Registered on
CreationType.preview_provider so core_rpc resolves it generically (ADR-0004:
the base layer never imports this module by name).

Snapshot principle ([[project_snapshot_principle]]): candidates + SRT come from
the creation instance's own snapshot via HotclipsRepo, not live upstream.
"""

from __future__ import annotations

import os
from typing import Any

from creations.clip.candidates import HotclipsRepo
from creations.clip.config import ClipInstanceConfig


def _empty(lang: str) -> dict[str, Any]:
    return {"lang": lang, "candidates": [], "selectedIndex": 0,
            "subtitlePath": None, "override": None}


def preview_data(project, instance_id: str) -> dict[str, Any]:
    inst_dir = project.creation_instance_dir("clip", instance_id)
    cfg = ClipInstanceConfig.load(os.path.join(inst_dir, "config.json"))
    if cfg.bound_material is None:
        return _empty(cfg.source_subtitle)

    import materials  # registry; resolve the bound material without hard-coding

    mtype = materials.get(cfg.bound_material.type_name)
    model = (
        mtype.instance_factory(project, cfg.bound_material.instance_name)
        if mtype and mtype.instance_factory
        else None
    )
    if model is None:
        return _empty(cfg.source_subtitle)

    repo = HotclipsRepo(inst_dir, model)
    lang = cfg.source_subtitle
    if not lang:
        avail = repo.list_available_langs()
        lang = avail[0] if avail else ""

    data = repo.load_hotclips(lang) or {}
    raw = data.get("clips") if isinstance(data, dict) else None
    candidates = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []

    sel = cfg.selected_clip_indices[0] if cfg.selected_clip_indices else 0
    if sel < 0 or sel >= len(candidates):
        sel = 0

    return {
        "lang": lang,
        "candidates": candidates,
        "selectedIndex": sel,
        "subtitlePath": repo.resolve_source_srt(lang),
        "override": cfg.clips_overrides.get(sel),
    }
