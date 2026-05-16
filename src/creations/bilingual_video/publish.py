"""Bilingual subtitle-burn derivative publish.md template.

One pure function: given the source title, source URL, normalized chapter
list, and adapted SRT filenames, produce the markdown that lives next to
output.mp4 as a YouTube-ready description + chapter block.

Lives next to subtitle_tool.py because the schema (which fields, what
sections) is a product decision specific to the bilingual_video derivative
— core/ stays derivative-agnostic.
"""

from __future__ import annotations

from typing import Optional

from core.markdown_fmt import t


def render_bilingual_publish(
    *,
    project_title: Optional[str],
    source_url: Optional[str],
    chapters: list[dict],
    adapted_srts: list[str],
    burned_at: str,
    lang_iso: str,
) -> str:
    """Markdown for derivatives/bilingual_video/<instance>/publish.md."""
    title = (project_title or "").strip() or t(lang_iso, "（无标题）", "(no title)")

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    if source_url:
        lines.append(f"> Source: {source_url}")
    lines.append(f"> Rendered: {burned_at}")
    lines.append("")

    lines.append("## " + t(lang_iso, "YouTube 描述", "YouTube Description"))
    lines.append("")
    lines.append(t(lang_iso,
        "（在这里填写视频描述。下面的章节段可以直接附在描述末尾。）",
        "(Fill in the video description here. The chapters block "
        "below can be appended verbatim to the description.)"))
    lines.append("")

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

    lines.append("## " + t(lang_iso, "标签", "Tags"))
    lines.append("")
    lines.append(t(lang_iso, "（待填）", "(to fill)"))
    lines.append("")

    if adapted_srts:
        lines.append("## " + t(lang_iso, "字幕文件", "Adapted SRTs"))
        lines.append("")
        for name in adapted_srts:
            lines.append(f"- `{name}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
