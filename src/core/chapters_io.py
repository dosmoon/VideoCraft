"""Chapter list IO + normalization.

Single source of truth for the `chapters.json` envelope and the
invariants over its `chapters` list. Both the AI generation path
(subtitle_analysis_runners._derive_chapters) and the UI edit-save
path go through `normalize_chapters` so the two cannot drift.

Invariants enforced on save:
  - chapters sorted by start ascending
  - end = next chapter's start (last chapter's end = srt_end_sec)
  - degenerate chapters (end <= start) dropped
  - first chapter must start at 00:00:00 (synthetic intro inserted
    when missing, so YouTube chapter rules accept the output)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from core.io_utils import atomic_write_json


_TS_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.\d+)?$")


def parse_time_str(ts: str) -> float:
    """Parse mm:ss or HH:MM:SS into seconds. 0.0 on failure."""
    ts = (ts or "").strip()
    m = _TS_RE.match(ts)
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mn = int(m.group(2))
    s = int(m.group(3))
    return h * 3600 + mn * 60 + s


def fmt_time_str(sec: float) -> str:
    """Format seconds as HH:MM:SS."""
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def intro_chapter_title(lang_iso: str) -> str:
    """Localized label for the synthetic 00:00 chapter.

    Core layer does not consume tr(); pick from the language tag the
    project's subtitles were generated in.
    """
    code = (lang_iso or "").lower().split("-")[0]
    if code.startswith("zh"):
        return "开始"
    return "Intro"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_chapters(chapters: list[dict], srt_end_sec: float,
                       lang_iso: str) -> list[dict]:
    """Enforce the chapter invariants. See module docstring.

    `chapters` may contain user-edited entries with arbitrary key
    presence. Only `start` and `title` are read here — `end` and
    `duration_sec` are recomputed from neighbours.
    """
    parsed: list[tuple[float, str]] = []
    for ch in chapters:
        start = ch.get("start")
        if isinstance(start, (int, float)):
            start_sec = float(start)
        else:
            start_sec = parse_time_str(str(start or ""))
        title = str(ch.get("title", "")).strip()
        if start_sec < 0:
            start_sec = 0.0
        parsed.append((start_sec, title))

    parsed.sort(key=lambda x: x[0])

    out: list[dict] = []
    for i, (start_sec, title) in enumerate(parsed):
        if i + 1 < len(parsed):
            end_sec = parsed[i + 1][0]
        else:
            end_sec = max(srt_end_sec, start_sec)
        if end_sec <= start_sec:
            # Degenerate — drop (covers duplicate starts and the
            # auto-intro collapsing when user moves a real chapter to
            # 00:00:00).
            continue
        out.append({
            "start":        fmt_time_str(start_sec),
            "end":          fmt_time_str(end_sec),
            "title":        title,
            "duration_sec": max(0.0, end_sec - start_sec),
        })

    if out and out[0]["start"] != "00:00:00":
        first_start_sec = parse_time_str(out[0]["start"])
        out.insert(0, {
            "start":        "00:00:00",
            "end":          out[0]["start"],
            "title":        intro_chapter_title(lang_iso),
            "duration_sec": max(0.0, first_start_sec),
        })
    return out


def load_chapters(path: str) -> dict:
    """Return the full envelope dict ({schema_version, ..., chapters})."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_chapters(path: str, chapters: list[dict], *,
                  srt_end_sec: float, lang_iso: str,
                  source_subtitle: str) -> list[dict]:
    """Normalize and atomically persist a chapter list.

    Returns the normalized list so the caller can refresh its UI from
    the same data that hit disk.
    """
    normalized = normalize_chapters(chapters, srt_end_sec, lang_iso)
    atomic_write_json(path, {
        "schema_version":   1,
        "generated_at":     _now_iso(),
        "source_subtitle":  source_subtitle,
        "chapters":         normalized,
    })
    return normalized
