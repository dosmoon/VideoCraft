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

    return {}
