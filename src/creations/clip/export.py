"""Clip render orchestration (sidecar side).

The GPU render itself runs in the Electron renderer (WebGPU/WebCodecs); this
module owns everything Python should own: which candidates to render, output
paths + naming (clip_NNN[_hook]), the per-clip sidecar JSON, stale-file cleanup,
and the persisted `rendered[]` state. Registered on CreationType.render_provider
so core_rpc resolves it generically (ADR-0004 — the base layer never imports
this by name).

  plan_render(project, instance)                      -> render plan (paths + geometry)
  commit_render(project, instance, src, out, dur)     -> updated rendered[]
  delete_render(project, instance, out)               -> updated rendered[]

Faithful to clip_tool.py's Export tab: _clip_basename / _sanitize_filename_part
/ _existing_clip_files / the sidecar dict / _effective_* override-wins.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from creations.clip.candidates import HotclipsRepo
from creations.clip.config import ClipInstanceConfig

logger = logging.getLogger(__name__)

_TS_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d+))?$")


# ── helpers ─────────────────────────────────────────────────────────────────

def _parse_ts(s: str) -> float:
    m = _TS_RE.match((s or "").strip())
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mn = int(m.group(2))
    sec = int(m.group(3))
    frac = m.group(4)
    base = h * 3600 + mn * 60 + sec
    if frac:
        base += int(frac[:3].ljust(3, "0")) / 1000.0
    return base


def _sanitize_filename_part(text: str, max_len: int = 30) -> str:
    """Strip filesystem-invalid chars and trim (faithful to clip_tool)."""
    if not text:
        return ""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(". ")
    if len(text) > max_len:
        text = text[:max_len].rstrip(". ")
    return text


def _basename(out_idx: int, hook: str) -> str:
    suffix = _sanitize_filename_part(hook or "")
    return f"clip_{out_idx:03d}_{suffix}" if suffix else f"clip_{out_idx:03d}"


def _existing_clip_files(inst_dir: str, out_idx: int) -> list[str]:
    """All on-disk files for an output index (clip_NNN.* and clip_NNN_<hook>.*)."""
    prefix = f"clip_{out_idx:03d}"
    out: list[str] = []
    try:
        for name in os.listdir(inst_dir):
            if not name.startswith(prefix):
                continue
            tail = name[len(prefix):]
            if tail and not (tail.startswith(".") or tail.startswith("_")):
                continue
            if not (name.endswith(".mp4") or name.endswith(".json") or name.endswith(".md")):
                continue
            out.append(os.path.join(inst_dir, name))
    except OSError:
        pass
    return out


# ── effective values (override-wins, faithful to clip_tool._effective_*) ──────

def _eff_start_end(cand: dict, ov: dict) -> tuple[float, float]:
    start = ov.get("start_sec")
    if start is None:
        start = _parse_ts(cand.get("start", ""))
    end = ov.get("end_sec")
    if end is None:
        end = _parse_ts(cand.get("end", ""))
    return (float(start), float(end))


def _eff_hook(cand: dict, ov: dict) -> str:
    if "hook_text" in ov:
        return str(ov["hook_text"])
    return (cand.get("hook") or "").strip()


def _eff_outro(cand: dict, ov: dict) -> str:
    if "outro_text" in ov:
        return str(ov["outro_text"])
    return (cand.get("outro") or "").strip()


def _eff_title(cand: dict, ov: dict) -> str:
    if "title" in ov:
        return str(ov["title"])
    return (cand.get("suggested_title") or "").strip()


def _eff_tags(cand: dict, ov: dict) -> list[str]:
    if "hashtags" in ov:
        t = ov["hashtags"]
        if isinstance(t, list):
            return [str(x) for x in t]
        if isinstance(t, str):
            return [x.strip() for x in t.split() if x.strip()]
        return []
    t = cand.get("suggested_hashtags") or cand.get("hashtags") or []
    return [str(x) for x in t] if isinstance(t, list) else []


# ── candidate resolution (mirrors preview.py) ────────────────────────────────

def _resolve(project, instance: str):
    """Return (cfg, inst_dir, lang, candidates). candidates=[] when unbound."""
    inst_dir = project.creation_instance_dir("clip", instance)
    cfg = ClipInstanceConfig.load(os.path.join(inst_dir, "config.json"))
    if cfg.bound_material is None:
        return cfg, inst_dir, cfg.source_subtitle, []

    import materials

    mtype = materials.get(cfg.bound_material.type_name)
    model = (
        mtype.instance_factory(project, cfg.bound_material.instance_name)
        if mtype and mtype.instance_factory
        else None
    )
    if model is None:
        return cfg, inst_dir, cfg.source_subtitle, []

    repo = HotclipsRepo(inst_dir, model)
    lang = cfg.source_subtitle or (repo.list_available_langs()[:1] or [""])[0]
    data = repo.load_hotclips(lang) or {}
    raw = data.get("clips") if isinstance(data, dict) else None
    candidates = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
    return cfg, inst_dir, lang, candidates


# ── publish docs (faithful to Tk clip_tool._write_publish_sidecar) ───────────

def _publish_meta(project) -> tuple[Optional[str], str]:
    """(project_title, lang_iso) for the publish docs. Content language follows
    the SOURCE, not the UI ([[project_publish_sidecar]])."""
    try:
        return project.meta.source.title, (project.meta.language.source or "zh")
    except AttributeError:
        return None, "zh"


def _rebuild_clip_index(project, instance: str, inst_dir: str) -> None:
    """Rewrite the instance index.md by rescanning every clip_*.json, so
    deleted / re-rendered clips stay in sync without bespoke state."""
    from creations.clip.publish import collect_clip_sidecars, render_clip_index
    project_title, lang_iso = _publish_meta(project)
    index_md = render_clip_index(
        project_title=project_title,
        instance_name=instance,
        sidecars=collect_clip_sidecars(inst_dir),
        rendered_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        lang_iso=lang_iso,
    )
    with open(os.path.join(inst_dir, "index.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(index_md)


def _write_clip_publish(project, instance: str, inst_dir: str, base: str,
                        sidecar: dict) -> None:
    """Per-clip clip_NNN[_hook].md (the X / TikTok caption copy) + a rebuilt
    instance index.md. The mp4 + JSON are already on disk; this is nice-to-have."""
    from creations.clip.publish import render_clip_publish
    project_title, lang_iso = _publish_meta(project)
    md = render_clip_publish(project_title=project_title, sidecar=sidecar, lang_iso=lang_iso)
    with open(os.path.join(inst_dir, base + ".md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    _rebuild_clip_index(project, instance, inst_dir)


# ── provider API ─────────────────────────────────────────────────────────────

def plan_render(project, instance: str) -> dict[str, Any]:
    """Output paths + geometry for the selected candidates (selected_clip_indices,
    ascending → out_idx 1..N, faithful to _on_render). The renderer builds the
    timeline per clip and encodes to outputPath."""
    cfg, inst_dir, lang, candidates = _resolve(project, instance)
    selected = sorted(
        i for i in cfg.selected_clip_indices if 0 <= i < len(candidates)
    )
    clips: list[dict[str, Any]] = []
    for out_idx, src_idx in enumerate(selected, start=1):
        cand = candidates[src_idx]
        ov = cfg.clips_overrides.get(src_idx) or {}
        start, end = _eff_start_end(cand, ov)
        base = _basename(out_idx, _eff_hook(cand, ov))
        crop = ov.get("crop_rect")
        clips.append({
            "srcIdx": src_idx,
            "outIdx": out_idx,
            "outputPath": os.path.join(inst_dir, base + ".mp4"),
            "startSec": start,
            "endSec": end,
            "cropRect": crop if isinstance(crop, dict) else None,
        })
    return {
        "lang": lang,
        "mode": cfg.output_mode,
        "aspect": cfg.output_aspect,
        "shortEdge": int(cfg.output_short_edge),
        "instanceDir": inst_dir,
        "clips": clips,
    }


def commit_render(project, instance: str, src_idx: int, out_idx: int,
                  duration_sec: float) -> list[dict]:
    """Write the per-clip sidecar JSON, clean stale files for this out_idx, and
    record the result in rendered[]. Returns the updated rendered list."""
    cfg, inst_dir, _lang, candidates = _resolve(project, instance)
    cand = candidates[src_idx] if 0 <= src_idx < len(candidates) else {}
    ov = cfg.clips_overrides.get(src_idx) or {}
    start, end = _eff_start_end(cand, ov)
    base = _basename(out_idx, _eff_hook(cand, ov))
    filename = base + ".mp4"

    # Sidecar JSON next to the mp4 (faithful field set).
    sidecar = {
        "source_clip_idx": src_idx,
        "output_index": out_idx,
        "filename": filename,
        "title": _eff_title(cand, ov),
        "hashtags": _eff_tags(cand, ov),
        "hook": _eff_hook(cand, ov),
        "outro": _eff_outro(cand, ov),
        "transcript": cand.get("transcript") or "",
        "why_viral": cand.get("why_viral") or "",
        "duration_sec": float(duration_sec),
        "start_sec": start,
        "end_sec": end,
        "score": cand.get("score"),
        "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(os.path.join(inst_dir, base + ".json"), "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)

    # Stale cleanup: drop any older files for this out_idx under a different
    # basename (e.g. the hook text changed since the last render).
    keep = {base + ext for ext in (".mp4", ".json", ".md")}
    for p in _existing_clip_files(inst_dir, out_idx):
        if os.path.basename(p) not in keep:
            try:
                os.remove(p)
            except OSError:
                pass

    # rendered[]: newest first, one entry per out_idx.
    rendered = [r for r in cfg.rendered
                if int(r.get("output_index") or -1) != out_idx]
    rendered.insert(0, {
        "file": filename,
        "source_clip_idx": src_idx,
        "output_index": out_idx,
        "duration_sec": float(duration_sec),
        "rendered_at": sidecar["rendered_at"],
    })
    cfg.rendered = rendered
    cfg.save(os.path.join(inst_dir, "config.json"))

    # Publish docs — best-effort, never blocks the render. [[project_publish_sidecar]]
    try:
        _write_clip_publish(project, instance, inst_dir, base, sidecar)
    except Exception as e:  # noqa: BLE001 — publish docs are nice-to-have
        logger.warning(f"clip publish.md write skipped: {e}")

    return rendered


def delete_render(project, instance: str, out_idx: int) -> list[dict]:
    """Unlink all files for an output index and drop it from rendered[]."""
    inst_dir = project.creation_instance_dir("clip", instance)
    cfg = ClipInstanceConfig.load(os.path.join(inst_dir, "config.json"))
    for p in _existing_clip_files(inst_dir, out_idx):
        try:
            os.remove(p)
        except OSError:
            pass
    cfg.rendered = [r for r in cfg.rendered
                    if int(r.get("output_index") or -1) != out_idx]
    cfg.save(os.path.join(inst_dir, "config.json"))

    # Rebuild index.md so the deleted clip drops out (per-clip .md was removed
    # above via _existing_clip_files). Best-effort.
    try:
        _rebuild_clip_index(project, instance, inst_dir)
    except Exception as e:  # noqa: BLE001 — index.md is nice-to-have
        logger.warning(f"clip index.md rebuild skipped: {e}")

    return cfg.rendered
