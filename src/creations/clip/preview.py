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
            "subtitlePath": None, "subtitlePaths": {}, "override": None,
            "availableLangs": [], "subtitleLangs": []}


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
    avail = repo.list_available_langs()
    lang = cfg.source_subtitle or (avail[0] if avail else "")

    data = repo.load_hotclips(lang) or {}
    raw = data.get("clips") if isinstance(data, dict) else None
    candidates = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []

    sel = cfg.selected_clip_indices[0] if cfg.selected_clip_indices else 0
    if sel < 0 or sel >= len(candidates):
        sel = 0

    # Snapshot every SUBTITLE language's SRT so bilingual clips work: each
    # subtitle component resolves its own language against this map (mirrors
    # clip_tool._srt_by_lang). Subtitle languages (SRT files) are distinct from
    # candidate languages (hotclips) — a video can have en+zh subtitles but only
    # zh AI hotclips. subtitlePath kept as the active-lang convenience.
    sub_langs = repo.list_subtitle_langs()
    sub_paths: dict[str, str] = {}
    for l in sub_langs:
        p = repo.resolve_source_srt(l)
        if p:
            sub_paths[l] = p

    return {
        "lang": lang,
        "candidates": candidates,
        "selectedIndex": sel,
        "subtitlePath": sub_paths.get(lang),
        "subtitlePaths": sub_paths,
        "override": cfg.clips_overrides.get(sel),
        "availableLangs": avail,        # hotclips/candidate languages (toolbar picker)
        "subtitleLangs": sub_langs,     # SRT languages (subtitle component dropdown)
    }
