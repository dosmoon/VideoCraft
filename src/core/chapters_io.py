"""Subtitle analysis envelope IO + chapter normalization.

The unified `<iso>.analysis.json` envelope is the AI subtitle pack output:
titles + chapters with per-chapter refined summary + key_points bullets.
Replaces the legacy 3-file split (titles.json + chapters.json +
chapter_refined.md) — they were always derived from one AI call.

Envelope schema (schema_version=2):
    {
      "schema_version":  2,
      "generated_at":    ISO8601 string,
      "source_subtitle": "zh.srt",
      "titles":          ["...", ...],
      "chapters": [
        {
          "start":      "HH:MM:SS",   # human-readable
          "start_sec":  float,         # parsed
          "end":        "HH:MM:SS",
          "end_sec":    float,
          "title":      "...",
          "refined":    "...",         # ≤128 字 narrative summary
          "key_points": ["...", ...]   # 3-5 short bullets, ≤25 字 each
        },
        ...
      ]
    }

Invariants enforced on save (normalize_chapters):
  - chapters sorted by start ascending
  - end = next chapter's start (last chapter's end = srt_end_sec)
  - degenerate chapters (end <= start) dropped
  - first chapter must start at 00:00:00 (synthetic intro inserted
    when missing, so YouTube chapter rules accept the output)
  - refined + key_points carried through per chapter (identified by
    start time match before sort)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from core.io_utils import atomic_write_json


SCHEMA_VERSION = 2

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


def _coerce_key_points(value) -> list[str]:
    """Normalize key_points to list[str]. Tolerates the brief-lived dict
    shape from a v3 schema attempt (extracts the .text field) so any
    analysis.json written during that window still loads cleanly."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def normalize_chapters(chapters: list[dict], srt_end_sec: float,
                       lang_iso: str) -> list[dict]:
    """Enforce the chapter invariants. See module docstring.

    Carries refined + key_points through per chapter, so user edits to
    `start` or `title` don't lose the AI-generated narrative attached
    to that chapter. The synthetic intro chapter (when inserted) gets
    empty refined + key_points.
    """
    parsed: list[tuple[float, str, str, list[str]]] = []
    for ch in chapters:
        start = ch.get("start")
        if isinstance(start, (int, float)):
            start_sec = float(start)
        else:
            start_sec = parse_time_str(str(start or ""))
        title = str(ch.get("title", "")).strip()
        refined = str(ch.get("refined", "")).strip()
        key_points = _coerce_key_points(ch.get("key_points"))
        if start_sec < 0:
            start_sec = 0.0
        parsed.append((start_sec, title, refined, key_points))

    parsed.sort(key=lambda x: x[0])

    out: list[dict] = []
    for i, (start_sec, title, refined, key_points) in enumerate(parsed):
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
            "start_sec":    start_sec,
            "end":          fmt_time_str(end_sec),
            "end_sec":      end_sec,
            "title":        title,
            "refined":      refined,
            "key_points":   key_points,
            "duration_sec": max(0.0, end_sec - start_sec),
        })

    if out and out[0]["start"] != "00:00:00":
        first_start_sec = out[0]["start_sec"]
        out.insert(0, {
            "start":        "00:00:00",
            "start_sec":    0.0,
            "end":          out[0]["start"],
            "end_sec":      first_start_sec,
            "title":        intro_chapter_title(lang_iso),
            "refined":      "",
            "key_points":   [],
            "duration_sec": max(0.0, first_start_sec),
        })
    return out


# ── Envelope IO ─────────────────────────────────────────────────────────────

def load_analysis(path: str) -> dict:
    """Return the full envelope dict. Raises on missing file / bad JSON."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_analysis(path: str, *,
                   titles: list[str],
                   chapters: list[dict],
                   srt_end_sec: float,
                   lang_iso: str,
                   source_subtitle: str) -> dict:
    """Normalize chapters + atomically persist the full envelope.

    Returns the saved envelope dict so the caller can refresh its UI
    from the exact same data that hit disk.
    """
    normalized = normalize_chapters(chapters, srt_end_sec, lang_iso)
    envelope = {
        "schema_version":   SCHEMA_VERSION,
        "generated_at":     _now_iso(),
        "source_subtitle":  source_subtitle,
        "titles":           [str(t).strip() for t in (titles or []) if t],
        "chapters":         normalized,
    }
    atomic_write_json(path, envelope)
    return envelope


def save_analysis_chapters_only(path: str, chapters: list[dict], *,
                                  srt_end_sec: float, lang_iso: str,
                                  source_subtitle: str) -> dict:
    """Re-save the envelope when ONLY the chapters list changed (typical
    chapter editor save). Preserves existing titles[] from disk. Returns
    the saved envelope.
    """
    titles: list[str] = []
    if os.path.isfile(path):
        try:
            existing = load_analysis(path)
            titles = list(existing.get("titles") or [])
        except (OSError, json.JSONDecodeError):
            pass
    return save_analysis(
        path, titles=titles, chapters=chapters,
        srt_end_sec=srt_end_sec, lang_iso=lang_iso,
        source_subtitle=source_subtitle,
    )
