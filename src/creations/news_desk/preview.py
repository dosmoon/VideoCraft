"""News-desk preview-data provider for the workbench (sidecar RPC).

Returns the material-derived data the TS news_desk assembler needs to build the
composition timeline: the source media reference, the source duration, and the
absolute path of each subtitle component's snapshot SRT (so the host can parse
cues into `buildNewsDeskTimeline`'s `cuesBySrtPath`). Pure read — no Tk, no
ffprobe. Registered on CreationType.preview_provider so core_rpc resolves it
generically (ADR-0004: the base layer never imports this module by name).

Contrast with clip's preview: news_desk renders the FULL source (no candidate
cutting), so there are no candidates/selection here — just the source handles +
per-subtitle snapshot SRTs. Chapter data is NOT returned: the chapter
component's `schedule` is already snapshotted into config at import time
([[project_snapshot_principle]]), so it rides through load_config/list_components.

Snapshot principle ([[project_snapshot_principle]]): a subtitle component's
`srt_path` points at a file already snapshotted into this creation instance's
own dir; we resolve it relative to that dir, never live from the material.
"""

from __future__ import annotations

import os
from typing import Any

from creations.news_desk.config import NewsDeskInstanceConfig


def _empty() -> dict[str, Any]:
    return {"mediaRef": None, "durationSec": 0.0, "subtitlePaths": {}}


def preview_data(project, instance_id: str) -> dict[str, Any]:
    inst_dir = project.creation_instance_dir("news_desk", instance_id)
    cfg = NewsDeskInstanceConfig.load(os.path.join(inst_dir, "config.json"))
    if cfg.bound_material is None:
        return _empty()

    import materials  # registry; resolve the bound material without hard-coding

    mtype = materials.get(cfg.bound_material.type_name)
    model = (
        mtype.instance_factory(project, cfg.bound_material.instance_name)
        if mtype and mtype.instance_factory
        else None
    )
    if model is None:
        return _empty()

    # The source video path is the media reference the renderer loads. It is the
    # canonical path regardless of presence — a missing file yields an empty
    # preview downstream, same as clip handing a path to its <video>.
    media_ref = model.source_video_path

    # Duration from the stored source meta (headless — no ffprobe subprocess).
    duration = 0.0
    meta = model.get_source_meta()
    if meta is not None:
        try:
            duration = float(getattr(meta, "duration_sec", 0.0) or 0.0)
        except (TypeError, ValueError):
            duration = 0.0

    # Each subtitle component's snapshot SRT, keyed by the component's own
    # `srt_path` value (the exact key the TS assembler uses for cuesBySrtPath).
    # Only emit entries whose snapshot actually exists on disk.
    subtitle_paths: dict[str, str] = {}
    for c in cfg.components:
        if c.get("kind") != "subtitle":
            continue
        rel = str(c.get("srt_path") or "").strip()
        if not rel:
            continue
        abs_path = (
            rel if os.path.isabs(rel)
            else os.path.normpath(os.path.join(inst_dir, rel))
        )
        if os.path.isfile(abs_path):
            subtitle_paths[rel] = abs_path

    return {
        "mediaRef": media_ref,
        "durationSec": duration,
        "subtitlePaths": subtitle_paths,
    }
