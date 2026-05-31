"""News-desk render orchestration (sidecar side).

The GPU render runs in the Electron renderer (WebGPU/WebCodecs); this module
owns what Python should own: the output path, the per-render sidecar JSON, stale
cleanup, and the persisted `rendered[]` state. Registered on
CreationType.render_provider so core_rpc resolves it generically (ADR-0004 — the
base layer never imports this by name).

Contrast with clip: clip emits one mp4 per selected candidate (out_idx 1..N).
news_desk composes the FULL source into a SINGLE output (out_idx is always 1),
so plan_render returns one render, not a list of clips. The base RPC layer's
fixed signatures (src_idx/out_idx/duration_sec) are honored; src_idx is unused
and out_idx is pinned to 1.

  plan_render(project, instance)                       -> render plan (one output)
  commit_render(project, instance, src, out, dur)      -> updated rendered[]
  delete_render(project, instance, out)                -> updated rendered[]

DEFERRED (faithful-port follow-up): the legacy Tk workbench also split the
rendered mp4 into per-chapter files (chapters/NN-title.mp4) and wrote a publish
sidecar + transcript. Those are publish-side artifacts (ffmpeg split, not the
GPU render); they belong in tools/news_desk/publish.py, not here. This module is
the core render-state owner only.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from creations.news_desk.config import NewsDeskInstanceConfig

# news_desk has a single output; clip-style indices collapse to this constant so
# the generic base-layer RPC (which always passes an out_idx) stays unchanged.
_OUT_IDX = 1
_BASENAME = "output"


def _resolve(project, instance: str):
    """(cfg, inst_dir, model | None). model is None when unbound."""
    inst_dir = project.creation_instance_dir("news_desk", instance)
    cfg = NewsDeskInstanceConfig.load(os.path.join(inst_dir, "config.json"))
    if cfg.bound_material is None:
        return cfg, inst_dir, None

    import materials  # registry; resolve without hard-coding a plugin name

    mtype = materials.get(cfg.bound_material.type_name)
    model = (
        mtype.instance_factory(project, cfg.bound_material.instance_name)
        if mtype and mtype.instance_factory
        else None
    )
    return cfg, inst_dir, model


def _source_duration(model) -> float:
    if model is None:
        return 0.0
    meta = model.get_source_meta()
    if meta is None:
        return 0.0
    try:
        return float(getattr(meta, "duration_sec", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def plan_render(project, instance: str) -> dict[str, Any]:
    """The single full-source render: media reference + output path. The
    renderer builds the timeline from the components and encodes to outputPath."""
    cfg, inst_dir, model = _resolve(project, instance)
    media_ref = model.source_video_path if model is not None else None
    output_path = os.path.join(inst_dir, _BASENAME + ".mp4")
    return {
        "instanceDir": inst_dir,
        "mediaRef": media_ref,
        "durationSec": _source_duration(model),
        "outIdx": _OUT_IDX,
        "outputPath": output_path,
    }


def commit_render(project, instance: str, src_idx: int, out_idx: int,
                  duration_sec: float) -> list[dict]:
    """After the renderer writes output.mp4: write the sidecar JSON and record
    the result in rendered[]. src_idx is unused (single output); out_idx is
    pinned to 1. Returns the updated rendered list."""
    cfg, inst_dir, model = _resolve(project, instance)
    filename = _BASENAME + ".mp4"
    rendered_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    sidecar = {
        "output_index": _OUT_IDX,
        "filename": filename,
        "duration_sec": float(duration_sec),
        "rendered_at": rendered_at,
    }
    with open(os.path.join(inst_dir, _BASENAME + ".json"), "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)

    # rendered[]: one entry, replaced on each render.
    cfg.rendered = [{
        "file": filename,
        "output_index": _OUT_IDX,
        "duration_sec": float(duration_sec),
        "rendered_at": rendered_at,
    }]
    cfg.save(os.path.join(inst_dir, "config.json"))
    return cfg.rendered


def delete_render(project, instance: str, out_idx: int) -> list[dict]:
    """Unlink the output mp4 + sidecar and clear rendered[]."""
    inst_dir = project.creation_instance_dir("news_desk", instance)
    cfg = NewsDeskInstanceConfig.load(os.path.join(inst_dir, "config.json"))
    for name in (_BASENAME + ".mp4", _BASENAME + ".json"):
        try:
            os.remove(os.path.join(inst_dir, name))
        except OSError:
            pass
    cfg.rendered = []
    cfg.save(os.path.join(inst_dir, "config.json"))
    return cfg.rendered
