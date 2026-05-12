"""Runners for the 6 subtitle analysis kinds.

Each runner takes the source SRT path + output artifact path + the
SubtitlesProgressModal worker signature `(progress_cb, cancel_token)`
and writes the artifact in its canonical format.

Most of the heavy lifting happens in core.srt_ops which already
implements the AI calls (used by the standalone menu tools). This
module re-shapes their output into the project-anchored JSON/MD
schemas used by the subtitle analysis layer.

P2 scope: 5 reused-AI runners. P4 will add `run_hotclips`.
"""

from __future__ import annotations

import json
import os
import re
import srt
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.subtitle_pipeline import ProgressInfo
from core.ai.cancellation import CancellationToken
from core.subtitle_ops import read_srt
from core.source_context import read_context as _read_context


# ── Shared output helpers ────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_text(path: str, text: str) -> None:
    """Write text to path via a temp file + rename to avoid partial files."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _atomic_write_json(path: str, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _say(progress_cb, phase: str, status: str, percent: float | None = None) -> None:
    """Push one progress tick via the modal's callback."""
    if progress_cb is not None:
        progress_cb(ProgressInfo(phase=phase, percent=percent, status_text=status))


# ── Chapter timestamp helpers ────────────────────────────────────────────────

_TS_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.\d+)?$")


def _parse_time_str(ts: str) -> float:
    """Parse mm:ss or HH:MM:SS into seconds. 0.0 on failure."""
    ts = ts.strip()
    m = _TS_RE.match(ts)
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mn = int(m.group(2))
    s = int(m.group(3))
    return h * 3600 + mn * 60 + s


def _fmt_time_str(sec: float) -> str:
    """Format seconds as HH:MM:SS."""
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _srt_end_seconds(srt_path: str) -> float:
    """Return the end timestamp of the last cue in seconds, or 0.0."""
    try:
        subs = list(srt.parse(read_srt(srt_path)))
    except Exception:
        return 0.0
    if not subs:
        return 0.0
    return subs[-1].end.total_seconds()


def _derive_chapters(pack_segments: list[dict], srt_path: str) -> list[dict]:
    """Pack 'segments' carry only `time_str` (chapter start). Derive `end`
    from the next chapter's start, with the last chapter ending at the
    SRT's final cue end.
    """
    starts = []
    for seg in pack_segments:
        t = seg.get("time_str", "").strip()
        if not t:
            continue
        starts.append((seg, _parse_time_str(t)))
    if not starts:
        return []
    last_end = _srt_end_seconds(srt_path)
    out = []
    for i, (seg, start_sec) in enumerate(starts):
        if i + 1 < len(starts):
            end_sec = starts[i + 1][1]
        else:
            end_sec = max(last_end, start_sec)
        out.append({
            "start":    _fmt_time_str(start_sec),
            "end":      _fmt_time_str(end_sec),
            "title":    seg.get("title", "").strip(),
            "duration_sec": max(0.0, end_sec - start_sec),
        })
    return out


# ── Pack-derived runners (titles / chapters / chapter_refined) ───────────────
#
# These three share a single AI call (generate_subtitle_pack returns titles +
# segments[time_str/title/refined] in one shot). To avoid 3× cost when the user
# clicks them in sequence, each runner — when it runs the pack — also writes
# the sibling artifacts. The artifact the user explicitly asked for is the
# return value; the bonus writes are best-effort and silent.

def _source_dir_for(subtitles_dir: str) -> str:
    """Sibling source/ given the project's subtitles/ dir."""
    return os.path.join(os.path.dirname(subtitles_dir), "source")


def _context_block(subtitles_dir: str) -> str:
    """Read source/context.json and render as a prompt prefix block."""
    try:
        ctx = _read_context(_source_dir_for(subtitles_dir))
    except Exception:
        return ""
    return ctx.as_prompt_block()


def _run_pack(srt_path: str, subtitles_dir: str,
              progress_cb, cancel_token) -> dict:
    """Call generate_subtitle_pack with progress + cancel plumbing.

    Prepends the project's source context (if any) to the prompt so the
    AI has situational signal (topic, host, audience) when picking
    titles and chapter boundaries.
    """
    from core import prompts as _prompts
    from core.srt_ops import generate_subtitle_pack
    _say(progress_cb, "transcribing", "正在调用 AI 生成结构化分析...", None)
    ctx_block = _context_block(subtitles_dir)
    if ctx_block:
        base = _prompts.get("subtitle.pack")
        prompt = ctx_block + "\n\n" + base
        return generate_subtitle_pack(srt_path, prompt=prompt,
                                      cancel_token=cancel_token)
    return generate_subtitle_pack(srt_path, cancel_token=cancel_token)


def _persist_pack(pack: dict, srt_path: str, subtitles_dir: str, lang_iso: str,
                  requested: str) -> str:
    """Write titles.json + chapters.json + chapter_refined.md from one pack
    payload. Returns the path of the artifact the caller asked for."""
    from core.subtitle_analysis import analysis_path

    titles = pack.get("titles") or []
    segments = pack.get("segments") or []
    chapters = _derive_chapters(segments, srt_path)

    titles_path = analysis_path(subtitles_dir, lang_iso, "titles")
    chapters_path = analysis_path(subtitles_dir, lang_iso, "chapters")
    refined_path = analysis_path(subtitles_dir, lang_iso, "chapter_refined")

    _atomic_write_json(titles_path, {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "source_subtitle": f"{lang_iso}.srt",
        "titles": [str(t).strip() for t in titles if t],
    })

    _atomic_write_json(chapters_path, {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "source_subtitle": f"{lang_iso}.srt",
        "chapters": chapters,
    })

    md_lines = [f"# 分章节精炼 ({lang_iso})", ""]
    for seg in segments:
        md_lines.append(f"## {seg.get('time_str', '').strip()} {seg.get('title', '').strip()}")
        md_lines.append("")
        md_lines.append(str(seg.get("refined", "")).strip())
        md_lines.append("")
    _atomic_write_text(refined_path, "\n".join(md_lines))

    return {
        "titles": titles_path,
        "chapters": chapters_path,
        "chapter_refined": refined_path,
    }[requested]


def run_titles(srt_path: str, subtitles_dir: str, lang_iso: str,
               progress_cb, cancel_token) -> dict:
    pack = _run_pack(srt_path, subtitles_dir, progress_cb, cancel_token)
    _say(progress_cb, "transcribing", "正在写入产物...", 95)
    path = _persist_pack(pack, srt_path, subtitles_dir, lang_iso, "titles")
    return {"path": path, "kind": "titles"}


def run_chapters(srt_path: str, subtitles_dir: str, lang_iso: str,
                 progress_cb, cancel_token) -> dict:
    pack = _run_pack(srt_path, subtitles_dir, progress_cb, cancel_token)
    _say(progress_cb, "transcribing", "正在写入产物...", 95)
    path = _persist_pack(pack, srt_path, subtitles_dir, lang_iso, "chapters")
    return {"path": path, "kind": "chapters"}


def run_chapter_refined(srt_path: str, subtitles_dir: str, lang_iso: str,
                        progress_cb, cancel_token) -> dict:
    pack = _run_pack(srt_path, subtitles_dir, progress_cb, cancel_token)
    _say(progress_cb, "transcribing", "正在写入产物...", 95)
    path = _persist_pack(pack, srt_path, subtitles_dir, lang_iso, "chapter_refined")
    return {"path": path, "kind": "chapter_refined"}


# ── Non-AI runners (transcript / chapter_transcript) ─────────────────────────

def run_transcript(srt_path: str, subtitles_dir: str, lang_iso: str,
                   progress_cb, cancel_token) -> dict:
    """Plain text dump, one cue per line. Non-AI; near-instant."""
    from core.srt_ops import extract_all_subtitles
    from core.subtitle_analysis import analysis_path

    _say(progress_cb, "transcribing", "正在提取全文...", 50)
    text = extract_all_subtitles(srt_path)
    path = analysis_path(subtitles_dir, lang_iso, "transcript")
    header = f"# 全文文字稿 ({lang_iso})\n\n"
    _atomic_write_text(path, header + text + "\n")
    return {"path": path, "kind": "transcript"}


def run_chapter_transcript(srt_path: str, subtitles_dir: str, lang_iso: str,
                           progress_cb, cancel_token) -> dict:
    """Group cues into the existing chapter boundaries. Requires chapters.json;
    if missing, runs the AI pack first to produce it (cascade).
    """
    from core.subtitle_analysis import analysis_path
    chapters_path = analysis_path(subtitles_dir, lang_iso, "chapters")

    if not os.path.isfile(chapters_path):
        _say(progress_cb, "transcribing",
             "未发现章节，先调用 AI 生成章节...", None)
        pack = _run_pack(srt_path, subtitles_dir, progress_cb, cancel_token)
        _persist_pack(pack, srt_path, subtitles_dir, lang_iso, "chapters")

    with open(chapters_path, "r", encoding="utf-8") as f:
        ch_data = json.load(f)
    chapters = ch_data.get("chapters") or []
    if not chapters:
        raise ValueError("chapters.json 没有有效章节")

    _say(progress_cb, "transcribing", "按章节切分字幕...", 70)
    subs = list(srt.parse(read_srt(srt_path)))

    # For each chapter, collect cues whose start falls within [start, end).
    grouped: list[tuple[dict, list[str]]] = [(c, []) for c in chapters]
    for sub in subs:
        t = sub.start.total_seconds()
        text = sub.content.replace("\n", " ").strip()
        if not text:
            continue
        for ch, bucket in grouped:
            start = _parse_time_str(ch.get("start", ""))
            end = _parse_time_str(ch.get("end", ""))
            if start <= t < end if end > start else t >= start:
                bucket.append(text)
                break

    out_path = analysis_path(subtitles_dir, lang_iso, "chapter_transcript")
    lines = [f"# 分章节全文 ({lang_iso})", ""]
    for ch, bucket in grouped:
        lines.append(f"## {ch.get('start', '')} {ch.get('title', '').strip()}")
        lines.append("")
        if bucket:
            lines.append(" ".join(bucket))
        else:
            lines.append("（此章节内无字幕）")
        lines.append("")
    _atomic_write_text(out_path, "\n".join(lines))
    return {"path": out_path, "kind": "chapter_transcript"}


# ── Dispatch table ───────────────────────────────────────────────────────────

RUNNERS: dict[str, Callable[..., dict]] = {
    "titles":             run_titles,
    "chapters":           run_chapters,
    "transcript":         run_transcript,
    "chapter_transcript": run_chapter_transcript,
    "chapter_refined":    run_chapter_refined,
    # "hotclips": run_hotclips,   # P4
}


def run(kind: str, srt_path: str, subtitles_dir: str, lang_iso: str,
        progress_cb, cancel_token) -> dict:
    """Run a registered analysis kind. Raises KeyError on unknown kind."""
    runner = RUNNERS.get(kind)
    if runner is None:
        raise KeyError(f"No runner for analysis kind: {kind}")
    return runner(srt_path, subtitles_dir, lang_iso, progress_cb, cancel_token)
