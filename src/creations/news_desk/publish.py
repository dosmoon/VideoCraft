"""News-desk derivative publish.md template.

Built for press-briefing / speech / news-show outputs. Consumes
source/context.json (the AI-verified canonical record — all 15 fields
including the 5 anchors AI re-checked from basic_info hints):

  - Episode header: topic, host, host_bio, host_affiliation, event date /
    time / location, show type
  - Event summary + key points + background (AI-grounded)
  - Chapter table (YouTube description format, 00:00 first chapter
    guaranteed by chapters_io normalization)
  - Adapted SRT pointer

Empty fields are silently omitted. If AI Fill hasn't run yet, context
is blank and publish.md degrades to a chapters-only doc — that's the
correct UX signal (run AI Fill), not a place to silently inject raw
user hints from basic_info.

Pure template (no Tk, no I/O): the render orchestrator (export.py
commit_render) gathers instance state into plain dicts/lists and writes
the result. Co-located in the creation plugin like clip's publish.py.
"""

from __future__ import annotations

from typing import Optional

from core.markdown_fmt import t


def render_news_desk_publish(
    *,
    project_title: Optional[str],
    source_url: Optional[str],
    context: dict,
    chapters: list[dict],
    adapted_srts: list[str],
    rendered_at: str,
    lang_iso: str,
    transcript_srt_path: Optional[str] = None,
    candidate_titles: Optional[list[str]] = None,
) -> str:
    """Markdown for the creation instance's publish.md.

    All inputs are plain dicts / lists so this function stays pure and
    independent of the workbench's dataclasses. Caller (export.py)
    converts instance state to dicts before invoking.

    `context`: SourceContext.to_dict() shape — all 15 fields. Empty
        dict (AI Fill not run) yields a chapters-only publish.md.
    """
    ctx = context or {}

    # Title preference: episode_topic (it's the editorial topic of THIS
    # episode) → project_title (filename / source video title) → fallback.
    title = (ctx.get("episode_topic") or "").strip() \
        or (project_title or "").strip() \
        or t(lang_iso, "（无标题）", "(no title)")

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    if source_url:
        lines.append(f"> Source: {source_url}")
    lines.append(f"> Rendered: {rendered_at}")
    lines.append("")

    # Candidate titles — first section so the user picking a YouTube
    # title sees these immediately on opening publish.md. Empty list
    # → section silently omitted. Snapshotted on the chapter component
    # (same upstream source as chapters; see ADR-0003).
    titles = [str(tt).strip() for tt in (candidate_titles or []) if str(tt).strip()]
    if titles:
        lines.append("## " + t(lang_iso, "候选标题", "Candidate Titles"))
        lines.append("")
        for tt in titles:
            lines.append(f"- {tt}")
        lines.append("")

    # Episode metadata block — single tight section the user can scan in
    # one glance before writing the description.
    meta_pairs: list[tuple[str, str]] = []

    def _add(label_zh: str, label_en: str, value: str) -> None:
        v = (value or "").strip()
        if v:
            meta_pairs.append((t(lang_iso, label_zh, label_en), v))

    _add("主讲人",   "Host",          ctx.get("host", ""))
    _add("身份",     "Bio",           ctx.get("host_bio", ""))
    _add("所属机构", "Affiliation",   ctx.get("host_affiliation", ""))
    _add("嘉宾",     "Guests",        ctx.get("guests", ""))
    _add("事件日期", "Date",          ctx.get("event_date", ""))
    _add("事件时间", "Time",          ctx.get("event_time", ""))
    _add("事件地点", "Location",      ctx.get("event_location", ""))
    _add("节目类型", "Show type",     ctx.get("show_type", ""))

    if meta_pairs:
        lines.append("## " + t(lang_iso, "节目概况", "Episode Info"))
        lines.append("")
        for label, value in meta_pairs:
            lines.append(f"- **{label}**: {value}")
        lines.append("")

    # YouTube description scaffold + AI-grounded copy ready for paste.
    summary = (ctx.get("event_summary") or "").strip()
    key_points = (ctx.get("key_points") or "").strip()
    background = (ctx.get("background") or "").strip()

    if summary or key_points or background:
        lines.append("## " + t(lang_iso, "YouTube 描述", "YouTube Description"))
        lines.append("")
        lines.append("```")
        if summary:
            lines.append(summary)
            lines.append("")
        if key_points:
            lines.append(t(lang_iso, "核心要点：", "Key points:"))
            for kp in key_points.splitlines():
                kp = kp.strip().lstrip("-•·").strip()
                if kp:
                    lines.append(f"- {kp}")
            lines.append("")
        if background:
            lines.append(t(lang_iso, "背景：", "Background:"))
            lines.append(background)
            lines.append("")
        lines.append("```")
        lines.append("")

    # Chapter block — standard YouTube description format,
    # users can append verbatim to the description.
    lines.append("## " + t(lang_iso, "章节", "Chapters"))
    lines.append("")
    if chapters:
        lines.append("```")
        for ch in chapters:
            start = (ch.get("start") or "").strip()
            ch_title = (ch.get("title") or "").strip()
            if not start:
                continue
            lines.append(f"{start} {ch_title}")
        lines.append("```")
    else:
        lines.append(t(lang_iso, "（无章节）", "(no chapters)"))
    lines.append("")

    # Notes from context (production hints, sensitive topics).
    notes = (ctx.get("notes") or "").strip()
    if notes:
        lines.append("## " + t(lang_iso, "制作备注", "Production Notes"))
        lines.append("")
        lines.append(notes)
        lines.append("")

    if adapted_srts:
        lines.append("## " + t(lang_iso, "字幕文件", "Adapted SRTs"))
        lines.append("")
        for name in adapted_srts:
            lines.append(f"- `{name}`")
        lines.append("")

    # Per-chapter detail: refined + key_points + verbatim transcript.
    # Folded into publish.md (vs a separate chapters.md) so everything
    # the user needs lives in one place. Requires both a chapter list
    # and the snapshotted SRT (transcript source).
    if chapters and transcript_srt_path:
        detail = _build_chapter_detail_section(
            chapters, transcript_srt_path, lang_iso)
        if detail:
            lines.append("---")
            lines.append("")
            lines.extend(detail)

    return "\n".join(lines).rstrip() + "\n"


def _build_chapter_detail_section(chapters: list[dict],
                                    srt_path: str,
                                    lang_iso: str) -> list[str]:
    """Build the "章节详情 / Chapter Details" section. Each chapter
    becomes a `### start–end title` block with refined + key_points +
    verbatim transcript pulled from the SRT. Returns an empty list on
    any failure (missing srt, etc) — never raises."""
    import os
    if not srt_path or not os.path.isfile(srt_path):
        return []
    try:
        import srt as _srt
        from core.chapters_io import parse_time_str
        with open(srt_path, "r", encoding="utf-8", errors="replace") as f:
            subs = list(_srt.parse(f.read()))
    except Exception:
        return []

    # Group cues into chapter buckets by start time.
    buckets: list[tuple[dict, list[str]]] = [(c, []) for c in chapters]
    for sub in subs:
        tt = sub.start.total_seconds()
        text = sub.content.replace("\n", " ").strip()
        if not text:
            continue
        for ch, bucket in buckets:
            s = float(ch.get("start_sec")
                      or parse_time_str(str(ch.get("start", ""))) or 0.0)
            e = float(ch.get("end_sec")
                      or parse_time_str(str(ch.get("end", ""))) or 0.0)
            in_range = (s <= tt < e) if e > s else (tt >= s)
            if in_range:
                bucket.append(text)
                break

    section_label = t(lang_iso, "章节详情", "Chapter Details")
    summary_label = t(lang_iso, "摘要", "Summary")
    keypoints_label = t(lang_iso, "要点", "Key points")
    body_label = t(lang_iso, "文字稿", "Transcript")
    empty_body = t(lang_iso, "（此章节内无字幕）",
                    "(no subtitle in this chapter)")

    out: list[str] = [f"## {section_label}", ""]
    for i, (ch, bucket) in enumerate(buckets):
        start = (ch.get("start") or "").strip()
        end = (ch.get("end") or "").strip()
        title = (ch.get("title") or "").strip()
        timeline = f"{start}–{end}" if end else start
        out.append(f"### {timeline}  {title}".rstrip())
        out.append("")

        refined = (ch.get("refined") or "").strip()
        if refined:
            out.append(f"**{summary_label}**: {refined}")
            out.append("")

        kps = ch.get("key_points") or []
        clean_kps = [str(p).strip() for p in kps if str(p).strip()]
        if clean_kps:
            out.append(f"**{keypoints_label}**:")
            for p in clean_kps:
                out.append(f"- {p}")
            out.append("")

        out.append(f"**{body_label}**:")
        out.append("")
        if bucket:
            out.append(" ".join(bucket))
        else:
            out.append(empty_body)
        out.append("")
        if i < len(buckets) - 1:
            out.append("---")
            out.append("")
    return out
