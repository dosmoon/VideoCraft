"""News-desk derivative publish.md template.

Built for press-briefing / speech / news-show outputs. The schema is
considerably richer than bilingual_video's because news_desk consumes
both anchor data (source/basic_info.json) and AI-extracted context
(source/context.json):

  - Episode header: topic, host, host_bio, host_affiliation, event date /
    time / location, show type
  - Event summary + key points + background (AI-grounded)
  - Chapter table (YouTube description format, 00:00 first chapter
    guaranteed by chapters_io normalization)
  - LowerThird roster — who appeared on screen and when, derived from
    the instance's overlay list
  - Adapted SRT pointer

Empty fields are silently omitted, so a news_desk render with only
basic_info filled still produces a usable publish.md (the AI context
sections just stay blank).
"""

from __future__ import annotations

from typing import Optional

from core.markdown_fmt import fmt_dur, t


def render_news_desk_publish(
    *,
    project_title: Optional[str],
    source_url: Optional[str],
    basic_info: dict,
    context: dict,
    chapters: list[dict],
    lower_thirds: list[dict],
    adapted_srts: list[str],
    rendered_at: str,
    lang_iso: str,
    transcript_srt_path: Optional[str] = None,
) -> str:
    """Markdown for derivatives/news_desk/<instance>/publish.md.

    All inputs are plain dicts / lists so this function stays pure and
    independent of the workbench's dataclasses. Caller (news_desk_tool)
    converts dataclasses to dicts before invoking.

    `basic_info`: SourceBasicInfo.to_dict() shape — host / host_bio /
        event_date / event_location / episode_topic.
    `context`: SourceContext.to_dict() shape — host_affiliation /
        guests / event_time / show_type / event_summary / key_points /
        background / audience / platform_tone / notes.
    `lower_thirds`: list of {title, subtitle, start_sec, end_sec} dicts
        (LowerThirdOverlay → overlay_to_dict subset).
    """
    bi = basic_info or {}
    ctx = context or {}

    # Title preference: episode_topic (it's the editorial topic of THIS
    # episode) → project_title (filename / source video title) → fallback.
    title = (bi.get("episode_topic") or "").strip() \
        or (project_title or "").strip() \
        or t(lang_iso, "（无标题）", "(no title)")

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    if source_url:
        lines.append(f"> Source: {source_url}")
    lines.append(f"> Rendered: {rendered_at}")
    lines.append("")

    # Episode metadata block — single tight section the user can scan in
    # one glance before writing the description.
    meta_pairs: list[tuple[str, str]] = []

    def _add(label_zh: str, label_en: str, value: str) -> None:
        v = (value or "").strip()
        if v:
            meta_pairs.append((t(lang_iso, label_zh, label_en), v))

    _add("主讲人",   "Host",          bi.get("host", ""))
    _add("身份",     "Bio",           bi.get("host_bio", ""))
    _add("所属机构", "Affiliation",   ctx.get("host_affiliation", ""))
    _add("嘉宾",     "Guests",        ctx.get("guests", ""))
    _add("事件日期", "Date",          bi.get("event_date", ""))
    _add("事件时间", "Time",          ctx.get("event_time", ""))
    _add("事件地点", "Location",      bi.get("event_location", ""))
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

    # Chapter block — same YouTube description format the bilingual
    # template uses, so users can append it verbatim.
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

    # LowerThird roster — who appeared on screen and when.
    if lower_thirds:
        lines.append("## " + t(lang_iso,
                                 "出场名牌（LowerThird）",
                                 "Lower-Third Roster"))
        lines.append("")
        for ov in lower_thirds:
            ov_title = (ov.get("title") or "").strip()
            ov_sub = (ov.get("subtitle") or "").strip()
            start_s = float(ov.get("start_sec") or 0.0)
            end_s = float(ov.get("end_sec") or 0.0)
            who = ov_title if not ov_sub else f"{ov_title} · {ov_sub}"
            lines.append(f"- {fmt_dur(start_s)}–{fmt_dur(end_s)}  {who}")
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
