"""Fixture storage + project-pull helpers for the AI Console Playground.

Fixtures are reusable input snapshots for prompt debugging:
  prompts/_fixtures/<task_id>/<name>.json
  {
    "task": "...", "name": "...",
    "vars": {"<placeholder_no_braces>": "<value>", ...},
    "saved_at": "ISO-8601", "note": "optional"
  }

extract_from_project(task, file_path, **kwargs) builds a `vars` dict from a
real project artifact (SRT, postprocess.json, cut JSON), so the user can
debug a prompt against actual data with two clicks.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from core.prompts import prompts_dir, placeholders


# ── Storage ────────────────────────────────────────────────────────────────

def _fixtures_root() -> str:
    return os.path.join(prompts_dir(), "_fixtures")


def _task_dir(task: str) -> str:
    safe = re.sub(r"[^\w.\-]", "_", task)
    return os.path.join(_fixtures_root(), safe)


def _fixture_path(task: str, name: str) -> str:
    safe = re.sub(r"[^\w.\-]", "_", name)
    return os.path.join(_task_dir(task), f"{safe}.json")


def list_fixtures(task: str) -> list[str]:
    """Return fixture names (without extension) for a task, sorted."""
    d = _task_dir(task)
    if not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        if fn.endswith(".json"):
            out.append(fn[:-5])
    out.sort()
    return out


def save_fixture(task: str, name: str, vars_: dict[str, str],
                 note: str = "") -> str:
    """Persist a fixture. Overwrites if name already exists."""
    path = _fixture_path(task, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "task": task,
        "name": name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "note": note,
        "vars": dict(vars_),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_fixture(task: str, name: str) -> dict:
    """Return the raw payload dict (with vars subkey)."""
    path = _fixture_path(task, name)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_fixture(task: str, name: str) -> None:
    path = _fixture_path(task, name)
    if os.path.exists(path):
        os.remove(path)


# ── Project pull (per-task extractors) ─────────────────────────────────────

def _strip_braces(ph: str) -> str:
    return ph[1:-1] if ph.startswith("{") and ph.endswith("}") else ph


def task_placeholder_keys(task: str) -> list[str]:
    """Return placeholder names without braces, in catalog order."""
    return [_strip_braces(p) for p in placeholders(task)]


def _format_srt_for_subtitle_content(srt_path: str) -> str:
    """Match srt_ops.generate_subtitle_pack: '[HH:MM:SS] <content>\\n' per cue."""
    import srt as _srt
    with open(srt_path, "r", encoding="utf-8") as f:
        subs = list(_srt.parse(f.read()))
    out = []
    for sub in subs:
        time_str = str(sub.start)[:8]
        content = sub.content.replace("\n", " ")
        out.append(f"[{time_str}] {content}")
    return "\n".join(out) + ("\n" if out else "")


def _build_chapter_list_json(pack: dict, paragraphs_txt_path: str = "") -> str:
    """Mirror clip.rank_chapters: JSON list of {idx, title, paragraphs}.

    Falls back to refined summary when paragraphs.txt is missing for that
    chapter (matches the runtime fallback in core.program.clip.rank_chapters).
    """
    from core.program.clip import list_chapters as _lc, chapter_paragraphs as _cp
    chapters_meta = _lc(pack)
    raw = pack.get("segments") or []
    out = []
    for idx, seg in enumerate(raw):
        body = ""
        if paragraphs_txt_path and os.path.isfile(paragraphs_txt_path):
            body = _cp(paragraphs_txt_path, idx, chapters_meta)
        if not body:
            body = (seg.get("refined") or "").strip()
        out.append({
            "idx":        idx,
            "title":      (seg.get("title") or "").strip(),
            "paragraphs": body,
        })
    return json.dumps(out, ensure_ascii=False, indent=2)


def list_chapters_for_picker(pack_path: str) -> list[dict]:
    """For UI: chapter list to pick from (used by clip.find-peaks pull)."""
    from core.program.clip import load_pack, list_chapters, probe_duration
    pack = load_pack(pack_path)
    # Try to find a sibling video for accurate end_sec; if not, fallback ok
    duration = None
    base = os.path.splitext(os.path.basename(pack_path))[0].replace("-postprocess", "")
    parent = os.path.dirname(pack_path)
    for ext in (".mp4", ".mkv", ".mov", ".webm"):
        guess = os.path.join(parent, "..", base + ext)
        guess = os.path.normpath(guess)
        if os.path.exists(guess):
            try:
                duration = probe_duration(guess)
            except Exception:
                pass
            break
    return list_chapters(pack, video_duration=duration)


def list_clips_for_picker(cut_path: str) -> list[dict]:
    """For UI: clip list to pick from (used by clip.package pull). Returns
    [{idx, label, start_sec, end_sec, original_excerpt, chapter_title,
       refined}] — refined comes from the linked pack if reachable."""
    from core.program.clip import load_cut_file, load_pack
    cut = load_cut_file(cut_path)
    pack = None
    pack_path = (cut.get("sources") or {}).get("pack_path", "")
    if pack_path and os.path.exists(pack_path):
        try:
            pack = load_pack(pack_path)
        except Exception:
            pack = None
    refined_by_idx: dict[int, str] = {}
    title_by_idx: dict[int, str] = {}
    if pack:
        for idx, seg in enumerate(pack.get("segments") or []):
            refined_by_idx[idx] = (seg.get("refined") or "").strip()
            title_by_idx[idx] = (seg.get("title") or "").strip()

    out = []
    for i, c in enumerate(cut.get("clips") or []):
        ch_idx = int(getattr(c, "chapter_idx", 0))
        out.append({
            "idx": i,
            "label": f"#{i+1}  {getattr(c, 'chapter_title', '') or title_by_idx.get(ch_idx, '')}"
                     f"  [{getattr(c, 'start_sec', 0):.1f}-{getattr(c, 'end_sec', 0):.1f}s]",
            "start_sec": float(getattr(c, "start_sec", 0)),
            "end_sec":   float(getattr(c, "end_sec", 0)),
            "original_excerpt": getattr(c, "original_excerpt", "") or "",
            "chapter_title":    getattr(c, "chapter_title", "") or title_by_idx.get(ch_idx, ""),
            "chapter_refined":  refined_by_idx.get(ch_idx, ""),
        })
    return out


def extract_from_project(task: str, file_path: str,
                         **kwargs: Any) -> dict[str, str]:
    """Build a placeholder vars dict from a real project file.

    Supported tasks (kwargs in parens):
      subtitle.pack          (file=*.srt)
      subtitle.segments      (file=*.srt)
      subtitle.refine        (file=*-postprocess.json)
      subtitle.titles        ()  -- nothing to pull, returns {}
      translate              (file=*.srt, batch_size=10, source_lang_name=...,
                              target_lang_name=...)
      clip.rank-chapters     (file=*-postprocess.json)
      clip.find-peaks        (file=*-postprocess.json, chapter_idx=int)
      clip.package           (file=cut.json, clip_idx=int)

    Unrecognized tasks return {} — caller falls back to manual fill.
    """
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if task in ("subtitle.pack", "subtitle.segments"):
        return {"subtitle_content": _format_srt_for_subtitle_content(file_path)}

    if task == "subtitle.refine":
        # Pulled from pack: build all_segments_content as time + title + refined
        with open(file_path, "r", encoding="utf-8") as f:
            pack = json.load(f)
        lines = []
        for seg in (pack.get("segments") or []):
            ts = (seg.get("time_str") or "").strip()
            title = (seg.get("title") or "").strip()
            refined = (seg.get("refined") or "").strip()
            lines.append(f"{ts} {title}\n{refined}\n")
        return {"all_segments_content": "\n".join(lines)}

    if task == "subtitle.titles":
        return {}

    if task == "translate":
        import srt as _srt
        with open(file_path, "r", encoding="utf-8") as f:
            subs = list(_srt.parse(f.read()))
        batch = int(kwargs.get("batch_size", 10))
        head = subs[:batch]
        numbered = "\n".join(f"【{i+1}】{s.content.replace(chr(10), ' ')}"
                              for i, s in enumerate(head))
        return {
            "source_lang_name": str(kwargs.get("source_lang_name", "English")),
            "target_lang_name": str(kwargs.get("target_lang_name", "中文")),
            "batch_size":       str(len(head)),
            "numbered_input":   numbered,
        }

    if task == "clip.rank-chapters":
        from core.program.clip import load_pack
        pack = load_pack(file_path)
        parent = os.path.dirname(file_path)
        base = os.path.splitext(os.path.basename(file_path))[0].replace("-postprocess", "")
        paragraphs_path = os.path.join(parent, f"{base}-paragraphs.txt")
        return {"chapter_list": _build_chapter_list_json(pack, paragraphs_path)}

    if task == "clip.find-peaks":
        from core.program.clip import (load_cues, number_cues,
                                         slice_chapter_cues)
        chapters = list_chapters_for_picker(file_path)
        idx = int(kwargs.get("chapter_idx", 0))
        if idx < 0 or idx >= len(chapters):
            raise ValueError(f"chapter_idx out of range: {idx}")
        ch = chapters[idx]
        # Resolve sibling SRT (manifest unit layout: pack at <unit>/output/,
        # SRT at <unit>/<base>.srt). Try a few common locations.
        srt_path = kwargs.get("srt_path", "")
        if not srt_path:
            parent = os.path.dirname(file_path)
            base = os.path.splitext(os.path.basename(file_path))[0].replace(
                "-postprocess", "")
            for guess in (os.path.join(parent, "..", base + ".srt"),
                           os.path.join(parent, base + ".srt")):
                guess = os.path.normpath(guess)
                if os.path.exists(guess):
                    srt_path = guess
                    break
        if not srt_path or not os.path.exists(srt_path):
            raise FileNotFoundError(
                "未找到 SRT 文件（pack 旁边）。Pull 时把 srt_path= 传进来或"
                "手工填 chapter_paragraphs。")
        cues = load_cues(srt_path)
        chapter_cues = slice_chapter_cues(cues, ch["start_sec"], ch["end_sec"])
        return {"chapter_paragraphs": number_cues(chapter_cues)}

    if task == "clip.package":
        clips = list_clips_for_picker(file_path)
        idx = int(kwargs.get("clip_idx", 0))
        if idx < 0 or idx >= len(clips):
            raise ValueError(f"clip_idx out of range: {idx}")
        c = clips[idx]
        return {"clip_excerpt": c["original_excerpt"]}

    return {}
