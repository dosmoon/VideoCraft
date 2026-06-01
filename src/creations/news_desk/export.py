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

After a successful render commit_render also writes the derivative's publish.md
(best-effort, never blocks the render — the mp4 already landed). The pure
markdown template lives in creations/news_desk/publish.py (co-located like
clip's); this module gathers instance state into the plain dicts/lists it wants.
Faithful to the retired Tk news_desk_tool._write_publish_sidecar.

DEFERRED (faithful-port follow-up): the legacy Tk workbench also offered two
opt-in deliverables — transcript.md and a per-chapter mp4 split
(chapters/NN-title.mp4). The split is genuinely publish-side (ffmpeg stream
copy, not the GPU render); both stay deferred. This module owns the core
render-state plus the always-on publish.md.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from creations.news_desk.config import NewsDeskInstanceConfig

logger = logging.getLogger(__name__)

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


# ── publish.md gathering (faithful to Tk news_desk_tool, ADR-0003) ───────────

def _first_enabled_subtitle(cfg) -> Optional[dict]:
    for c in cfg.components:
        if c.get("kind") == "subtitle" and c.get("enabled", True):
            return c
    return None


def _srt_abspath(inst_dir: str, comp: Optional[dict]) -> str:
    """Resolve a subtitle component's snapshot SRT to an absolute path, mirroring
    preview.py. "" when missing — the chapter-detail section then degrades out."""
    if not comp:
        return ""
    rel = str(comp.get("srt_path") or "").strip()
    if not rel:
        return ""
    abs_path = rel if os.path.isabs(rel) else os.path.normpath(os.path.join(inst_dir, rel))
    return abs_path if os.path.isfile(abs_path) else ""


def _lang_iso(comp: Optional[dict], project) -> str:
    """Content language for publish.md — follows the SOURCE, not the UI
    ([[project_publish_sidecar]]). is_chinese on the chosen subtitle → zh/en;
    no subtitle → fall back to the project's source language."""
    if comp is not None:
        return "zh" if comp.get("is_chinese") else "en"
    try:
        return project.meta.language.source or "zh"
    except AttributeError:
        return "zh"


def _chapter_component(cfg) -> Optional[dict]:
    for c in cfg.components:
        if c.get("kind") == "chapter":
            return c
    return None


def _chapters_for_publish(schedule: list[dict]) -> list[dict]:
    """Chapter component schedule → publish.py's expected shape, adding the
    HH:MM:SS start/end strings (chapters_io owns the canonical formatter)."""
    from core.chapters_io import fmt_time_str
    out: list[dict] = []
    for ch in schedule:
        start_sec = float(ch.get("start_sec") or 0.0)
        end_sec = float(ch.get("end_sec") or 0.0)
        out.append({
            "start": fmt_time_str(start_sec),
            "end": fmt_time_str(end_sec),
            "start_sec": start_sec,
            "end_sec": end_sec,
            "title": str(ch.get("title", "")),
            "refined": str(ch.get("refined", "")),
            "key_points": list(ch.get("key_points") or []),
        })
    return out


def _write_publish_md(project, instance: str, inst_dir: str, cfg, model) -> None:
    """Render the derivative's publish.md from instance state + the bound
    material's context.json (the AI-verified single source). Per ADR-0003 we
    read snapshotted instance state, never re-scan upstream analysis."""
    from creations.news_desk.publish import render_news_desk_publish

    context = model.read_context().to_dict() if model is not None else {}

    project_title: Optional[str] = None
    source_url: Optional[str] = None
    try:
        meta = project.meta
        project_title = meta.source.title
        source_url = meta.source.url
    except AttributeError:
        pass

    sub_comp = _first_enabled_subtitle(cfg)
    chapter_comp = _chapter_component(cfg)
    schedule = list((chapter_comp or {}).get("schedule") or [])
    titles = [str(t).strip()
              for t in ((chapter_comp or {}).get("titles") or [])
              if str(t).strip()]
    adapted = [c["srt_path"] for c in cfg.components
               if c.get("kind") == "subtitle" and c.get("srt_path")]

    md = render_news_desk_publish(
        project_title=project_title,
        source_url=source_url,
        context=context,
        chapters=_chapters_for_publish(schedule),
        candidate_titles=titles,
        adapted_srts=adapted,
        rendered_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        lang_iso=_lang_iso(sub_comp, project),
        transcript_srt_path=_srt_abspath(inst_dir, sub_comp),
    )
    out = os.path.join(inst_dir, "publish.md")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)


# ── provider API ─────────────────────────────────────────────────────────────

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

    # Derivative publish.md — best-effort, never blocks the render (the mp4 and
    # render-state are already committed above). [[project_publish_sidecar]]
    try:
        _write_publish_md(project, instance, inst_dir, cfg, model)
    except Exception as e:  # noqa: BLE001 — publish.md is nice-to-have
        logger.warning(f"news_desk publish.md write skipped: {e}")

    return cfg.rendered


def delete_render(project, instance: str, out_idx: int) -> list[dict]:
    """Unlink the output mp4 + sidecar and clear rendered[]."""
    inst_dir = project.creation_instance_dir("news_desk", instance)
    cfg = NewsDeskInstanceConfig.load(os.path.join(inst_dir, "config.json"))
    for name in (_BASENAME + ".mp4", _BASENAME + ".json", "publish.md"):
        try:
            os.remove(os.path.join(inst_dir, name))
        except OSError:
            pass
    cfg.rendered = []
    cfg.save(os.path.join(inst_dir, "config.json"))
    return cfg.rendered
