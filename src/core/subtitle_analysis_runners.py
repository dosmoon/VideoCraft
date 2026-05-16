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
import srt
from datetime import datetime, timezone
from typing import Callable, Optional

from core.io_utils import atomic_write_text, atomic_write_json
from core.chapters_io import (
    normalize_chapters,
    save_analysis,
    parse_time_str as _parse_time_str,
    fmt_time_str as _fmt_time_str,
)
from core.subtitle_pipeline import ProgressInfo
from core.ai.cancellation import CancellationToken
from core.subtitle_ops import read_srt, srt_end_seconds as _srt_end_seconds
# TODO(ADR-0004): core/ should not import from a specific material plugin.
# Cleanest fix: parameterize the runner so callers (which know the material
# type) inject the context prompt block. Documented wart until a second
# material type lands and forces the abstraction.
from materials.news_video.schema import context_prompt_block as _context_prompt_block


# ── Shared output helpers ────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _say(progress_cb, phase: str, status: str, percent: float | None = None) -> None:
    """Push one progress tick via the modal's callback."""
    if progress_cb is not None:
        progress_cb(ProgressInfo(phase=phase, percent=percent, status_text=status))


# ── Chapter derivation ───────────────────────────────────────────────────────
#
# parse/fmt helpers live in core.chapters_io; SRT end probing lives in
# core.subtitle_ops. Both are re-imported above to keep this module's
# existing private names.

def _derive_chapters(pack_segments: list[dict], srt_path: str,
                     lang_iso: str) -> list[dict]:
    """Map an AI 'segments' payload to the normalized chapter list.

    Each segment carries `time_str` (start), `title`, `refined`, and
    `key_points`. End timestamps and the synthetic 00:00 intro (when
    first start > 0) are produced by `normalize_chapters`, which is also
    the UI save-path's normalizer — so AI-generated and user-edited
    chapters cannot drift apart. refined + key_points are carried
    through the normalize pass so they survive subsequent edits.
    """
    items = []
    for seg in pack_segments:
        t = (seg.get("time_str") or "").strip()
        if not t:
            continue
        items.append({
            "start":      t,
            "title":      (seg.get("title") or "").strip(),
            "refined":    (seg.get("refined") or "").strip(),
            "key_points": seg.get("key_points") or [],
        })
    if not items:
        return []
    return normalize_chapters(items, _srt_end_seconds(srt_path), lang_iso)


# ── Pack-derived runner (analysis.json) ─────────────────────────────────────
#
# titles + chapters (with per-chapter refined + key_points) all come from
# ONE AI call (generate_subtitle_pack). They live in a single envelope
# `<iso>.analysis.json` — see core.chapters_io.save_analysis. The legacy
# split into titles.json + chapters.json + chapter_refined.md is gone.

def _source_dir_for(subtitles_dir: str) -> str:
    """Sibling source/ given the project's subtitles/ dir."""
    return os.path.join(os.path.dirname(subtitles_dir), "source")


def _context_block(subtitles_dir: str) -> str:
    """Render context.json as a prompt prefix block. Empty when AI Fill
    hasn't run (context.json missing or blank)."""
    try:
        return _context_prompt_block(_source_dir_for(subtitles_dir))
    except Exception:
        return ""


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


def run_pack_analysis(srt_path: str, subtitles_dir: str, lang_iso: str,
                       progress_cb, cancel_token) -> dict:
    """Run the AI subtitle pack and persist a single analysis.json envelope
    (titles + chapters with refined + key_points). One AI call, one file."""
    from core.subtitle_analysis import analysis_path

    pack = _run_pack(srt_path, subtitles_dir, progress_cb, cancel_token)
    _say(progress_cb, "transcribing", "正在写入产物...", 95)

    titles = pack.get("titles") or []
    segments = pack.get("segments") or []
    chapters = _derive_chapters(segments, srt_path, lang_iso)
    out_path = analysis_path(subtitles_dir, lang_iso, "analysis")
    save_analysis(
        out_path,
        titles=[str(t).strip() for t in titles if t],
        chapters=chapters,
        srt_end_sec=_srt_end_seconds(srt_path),
        lang_iso=lang_iso,
        source_subtitle=f"{lang_iso}.srt",
    )
    return {"path": out_path, "kind": "analysis"}


# ── Non-AI runners (transcript / chapter_transcript) ─────────────────────────

def build_transcript_text(srt_path: str, lang_iso: str) -> str:
    """Return the markdown text for a full transcript. Pure function — no
    file IO. Callers (legacy run_transcript, news_desk export) write the
    string wherever they need."""
    from core.srt_ops import extract_all_subtitles
    text = extract_all_subtitles(srt_path)
    return f"# 全文文字稿 ({lang_iso})\n\n{text}\n"


def build_chapter_transcript_text(srt_path: str, chapters: list[dict],
                                    lang_iso: str,
                                    *, titles: list[str] | None = None) -> str:
    """Return the markdown text for the per-chapter transcript +
    analysis bundle. For each chapter we emit:

      ## start–end  Chapter Title
      **摘要 / Summary**: refined paragraph (if present)
      **要点 / Key points**:
        - bullet
        - bullet
      <verbatim transcript text>

    `titles` is the candidate-title list from analysis.json — rendered
    as a top-of-file section so the user can pick one for the upload
    title. Pure function — no file IO."""
    if not chapters:
        raise ValueError("chapters list is empty")
    is_zh = (lang_iso or "").lower().startswith("zh")
    summary_label = "摘要" if is_zh else "Summary"
    keypoints_label = "要点" if is_zh else "Key points"
    empty_label = "（此章节内无字幕）" if is_zh else "(no subtitle in this chapter)"
    titles_label = "候选标题" if is_zh else "Candidate titles"
    body_label = "文字稿" if is_zh else "Transcript"

    subs = list(srt.parse(read_srt(srt_path)))
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

    lines: list[str] = [f"# 分章节全文 ({lang_iso})", ""]

    # Candidate titles section — show as a simple list so the user can
    # copy-paste one into the upload form.
    clean_titles = [str(t).strip() for t in (titles or []) if str(t).strip()]
    if clean_titles:
        lines.append(f"## {titles_label}")
        lines.append("")
        for t in clean_titles:
            lines.append(f"- {t}")
        lines.append("")

    for ch, bucket in grouped:
        start = (ch.get("start") or "").strip()
        end = (ch.get("end") or "").strip()
        title = (ch.get("title") or "").strip()
        timeline = f"{start}–{end}" if end else start
        lines.append(f"## {timeline}  {title}".rstrip())
        lines.append("")

        refined = (ch.get("refined") or "").strip()
        if refined:
            lines.append(f"**{summary_label}**: {refined}")
            lines.append("")

        kps = ch.get("key_points") or []
        clean_kps = [str(p).strip() for p in kps if str(p).strip()]
        if clean_kps:
            lines.append(f"**{keypoints_label}**:")
            for p in clean_kps:
                lines.append(f"- {p}")
            lines.append("")

        lines.append(f"**{body_label}**:")
        lines.append("")
        if bucket:
            lines.append(" ".join(bucket))
        else:
            lines.append(empty_label)
        lines.append("")

    return "\n".join(lines)


def run_transcript(srt_path: str, subtitles_dir: str, lang_iso: str,
                   progress_cb, cancel_token) -> dict:
    """Plain text dump, one cue per line. Non-AI; near-instant."""
    from core.subtitle_analysis import analysis_path
    _say(progress_cb, "transcribing", "正在提取全文...", 50)
    path = analysis_path(subtitles_dir, lang_iso, "transcript")
    atomic_write_text(path, build_transcript_text(srt_path, lang_iso))
    return {"path": path, "kind": "transcript"}


def run_chapter_transcript(srt_path: str, subtitles_dir: str, lang_iso: str,
                           progress_cb, cancel_token) -> dict:
    """Group cues into the existing chapter boundaries. Requires
    analysis.json (which contains the chapter list); if missing, cascade
    through the AI pack to produce it.
    """
    from core.subtitle_analysis import analysis_path
    analysis_pth = analysis_path(subtitles_dir, lang_iso, "analysis")

    if not os.path.isfile(analysis_pth):
        _say(progress_cb, "transcribing",
             "未发现章节，先调用 AI 生成...", None)
        run_pack_analysis(srt_path, subtitles_dir, lang_iso,
                            progress_cb, cancel_token)

    with open(analysis_pth, "r", encoding="utf-8") as f:
        ch_data = json.load(f)
    chapters = ch_data.get("chapters") or []
    if not chapters:
        raise ValueError("analysis.json 没有有效章节")

    _say(progress_cb, "transcribing", "按章节切分字幕...", 70)
    out_path = analysis_path(subtitles_dir, lang_iso, "chapter_transcript")
    atomic_write_text(
        out_path,
        build_chapter_transcript_text(srt_path, chapters, lang_iso))
    return {"path": out_path, "kind": "chapter_transcript"}


# ── Hotclips runner (P4a) ────────────────────────────────────────────────────
#
# Chapter scoping strategy (design §2.5):
#   - "auto"        — use chapters when chapters.json exists, else full
#   - "per_chapter" — require chapters; fail loud if missing
#   - "full"        — single AI call on the whole transcript
# Chapters only do prompt-window slicing; they don't participate in final
# ranking. All slice outputs merge into one pool, sorted by start time.

# Schema validates the AI's response. `transcript` is NOT requested from AI
# (would invite hallucination); it's injected post-call by slicing the source
# SRT in run_hotclips and ends up in the written hotclips.json all the same.
HOTCLIPS_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start":         {"type": "string"},
                    "end":           {"type": "string"},
                    "duration_sec":  {"type": "number"},
                    "hook":          {"type": "string"},
                    "outro":         {"type": "string"},
                    "why_viral":     {"type": "string"},
                    "score":         {"type": "integer", "minimum": 1, "maximum": 10},
                    "suggested_title":   {"type": "string"},
                    "suggested_hashtags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["start", "end", "hook", "outro", "score",
                              "suggested_title"],
            },
        }
    },
    "required": ["clips"],
}


def _srt_to_slice_text(subs: list, t_start_sec: float, t_end_sec: float) -> str:
    """Render a contiguous block of SRT cues into the `[HH:MM:SS] text\n` form
    used by AI prompts. `t_end_sec=0` means open-ended (take everything from
    t_start_sec onward)."""
    out = []
    for sub in subs:
        start = sub.start.total_seconds()
        if start < t_start_sec:
            continue
        if t_end_sec > 0 and start >= t_end_sec:
            break
        ts = str(sub.start)[:8]
        text = sub.content.replace("\n", " ").strip()
        if text:
            out.append(f"[{ts}] {text}")
    return "\n".join(out)


def _slice_transcript(subs: list, t_start_sec: float, t_end_sec: float) -> str:
    """Plain-text transcript of cues within [start, end). Space-joined, no
    timestamps. Used to inject ground-truth subtitle content into each
    hotclip — AI doesn't return this (would invite paraphrase / hallucination)."""
    parts = []
    for sub in subs:
        start = sub.start.total_seconds()
        if start < t_start_sec:
            continue
        if t_end_sec > 0 and start >= t_end_sec:
            break
        text = sub.content.replace("\n", " ").strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _call_hotclips_ai(slice_text: str, ctx_block: str,
                      desired_count: int, target_min_sec: int, target_max_sec: int,
                      cancel_token) -> list[dict]:
    """One AI call for one slice. Returns raw clip dicts (may include
    bogus entries — caller validates)."""
    from core import ai as _ai, prompts as _prompts
    from core.ai.tiers import TIER_PREMIUM
    from core.ai.errors import AIError as _AIError

    base = _prompts.get("subtitle.hotclips")
    body = base.replace("{subtitle_content}", slice_text) \
               .replace("{desired_count}", str(desired_count)) \
               .replace("{target_min_sec}", str(target_min_sec)) \
               .replace("{target_max_sec}", str(target_max_sec))
    prompt = (ctx_block + "\n\n" + body) if ctx_block else body
    try:
        result = _ai.complete_json(
            prompt, schema=HOTCLIPS_SCHEMA,
            task="subtitle.post", tier=TIER_PREMIUM,
            cancel_token=cancel_token,
        )
    except Exception as e:
        if isinstance(e, _AIError):
            raise
        raise RuntimeError(f"调用 AI 生成热点失败: {e}")
    if not isinstance(result, dict):
        return []
    clips = result.get("clips")
    return clips if isinstance(clips, list) else []


def run_hotclips(srt_path: str, subtitles_dir: str, lang_iso: str,
                 progress_cb, cancel_token,
                 *,
                 strategy: str = "auto",
                 desired_count: int = 10,
                 target_min_sec: int = 30,
                 target_max_sec: int = 90) -> dict:
    """Generate hotclip candidates. See module docstring for strategy semantics."""
    from core.subtitle_analysis import analysis_path

    subs = list(srt.parse(read_srt(srt_path)))
    if not subs:
        raise ValueError("SRT 为空，无法生成热点片段")

    analysis_pth = analysis_path(subtitles_dir, lang_iso, "analysis")
    has_chapters = os.path.isfile(analysis_pth)

    use_chapters = (
        strategy == "per_chapter" or (strategy == "auto" and has_chapters)
    )
    if strategy == "per_chapter" and not has_chapters:
        raise ValueError("strategy=per_chapter 但 analysis.json 不存在")

    ctx_block = _context_block(subtitles_dir)

    # Build (chapter_label, slice_text) pairs.
    slices: list[tuple[str, str]] = []
    if use_chapters:
        with open(analysis_pth, "r", encoding="utf-8") as f:
            chapters = (json.load(f).get("chapters") or [])
        for ch in chapters:
            t0 = _parse_time_str(ch.get("start", ""))
            t1 = _parse_time_str(ch.get("end", ""))
            slice_text = _srt_to_slice_text(subs, t0, t1)
            if slice_text:
                slices.append((ch.get("title", "")[:40] or "—", slice_text))
        if not slices:
            # Chapters present but yielded no text — fall back to full.
            slices = [("", _srt_to_slice_text(subs, 0.0, 0.0))]
            use_chapters = False
    else:
        slices = [("", _srt_to_slice_text(subs, 0.0, 0.0))]

    # Per-slice budget: split the total across chapters with a floor of 3 so
    # short chapters still get a fair shot at producing candidates.
    if use_chapters and len(slices) > 1:
        per_slice = max(3, desired_count // len(slices) + 1)
    else:
        per_slice = desired_count

    all_clips: list[dict] = []
    total = len(slices)
    for i, (label, slice_text) in enumerate(slices, 1):
        pct = (i - 1) / total * 90
        _say(progress_cb, "transcribing",
             f"挖掘热点（{i}/{total}{' · ' + label if label else ''}）...",
             pct)
        clips = _call_hotclips_ai(
            slice_text, ctx_block,
            per_slice, target_min_sec, target_max_sec,
            cancel_token,
        )
        all_clips.extend(clips)

    # Sort by start time (UI may re-sort by score).
    def _start_sec(c):
        return _parse_time_str(c.get("start", ""))
    all_clips.sort(key=_start_sec)

    # Inject ground-truth transcript per clip by slicing the source SRT.
    # Done after AI returns so a hallucinated/paraphrased transcript can't
    # sneak in via the model. Used by the card preview and (future) by the
    # clip render layer to burn subtitles onto the rendered short videos.
    for clip in all_clips:
        start = _parse_time_str(clip.get("start", ""))
        end = _parse_time_str(clip.get("end", ""))
        clip["transcript"] = _slice_transcript(subs, start, end)

    _say(progress_cb, "transcribing", "正在写入产物...", 95)
    out_path = analysis_path(subtitles_dir, lang_iso, "hotclips")
    atomic_write_json(out_path, {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "source_subtitle": f"{lang_iso}.srt",
        "strategy": "per_chapter" if use_chapters else "full",
        "params": {
            "desired_count": desired_count,
            "target_min_sec": target_min_sec,
            "target_max_sec": target_max_sec,
        },
        "clips": all_clips,
    })
    return {"path": out_path, "kind": "hotclips", "count": len(all_clips)}


# ── Dispatch table ───────────────────────────────────────────────────────────

RUNNERS: dict[str, Callable[..., dict]] = {
    "analysis":           run_pack_analysis,
    "transcript":         run_transcript,
    "chapter_transcript": run_chapter_transcript,
    "hotclips":           run_hotclips,
}


def run(kind: str, srt_path: str, subtitles_dir: str, lang_iso: str,
        progress_cb, cancel_token) -> dict:
    """Run a registered analysis kind. Raises KeyError on unknown kind."""
    runner = RUNNERS.get(kind)
    if runner is None:
        raise KeyError(f"No runner for analysis kind: {kind}")
    return runner(srt_path, subtitles_dir, lang_iso, progress_cb, cancel_token)
