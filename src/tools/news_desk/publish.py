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

    return "\n".join(lines).rstrip() + "\n"
