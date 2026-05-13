"""Markdown publish sidecars for derivative exports.

Solves the "exported file is just a numbered .mp4, where do I get the
title / chapters / transcript for publishing" pain.

Three renderers, all pure functions that return markdown text:

    render_bilingual_publish() — one publish.md beside output.mp4
        carrying the source title, the chapter table in YouTube
        description format (00:00 first chapter guaranteed by
        chapters_io normalization), and a pointer to the adapted
        SRTs.

    render_clip_publish() — one publish.md per exported clip with a
        copy-paste-ready Caption block (title + full transcript +
        hashtags) sized for X / TikTok publish forms.

    render_clip_index() — one index.md per clip instance, a quick
        table mapping clip_001..N to their titles + scores, so the
        user can stop opening JSON files in VSCode to figure out
        which numbered file is what.

Language: sidecar content follows the *source project's* language
(zh-* -> Chinese, else English). Tracking UI language here would
mismatch the video's spoken language and produce broken publish
copy when users switch UI to English for an EN-spoken project.
"""

from __future__ import annotations

import os
from typing import Iterable, Optional


# ── Language picker ──────────────────────────────────────────────────────────

def _is_zh(lang_iso: str) -> bool:
    return (lang_iso or "").lower().split("-")[0].startswith("zh")


def _t(lang_iso: str, zh: str, en: str) -> str:
    return zh if _is_zh(lang_iso) else en


# ── Formatting helpers ───────────────────────────────────────────────────────

def _fmt_dur(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def _fmt_hashtags(tags) -> str:
    """Render as a single space-joined line, each hashtag prefixed `#`
    if not already. Empty / non-list → empty string."""
    if not isinstance(tags, (list, tuple)):
        return ""
    parts = []
    for t in tags:
        s = str(t).strip().lstrip("#")
        if s:
            parts.append("#" + s)
    return " ".join(parts)


# ── Bilingual video publish.md ───────────────────────────────────────────────

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
    title = (project_title or "").strip() or _t(lang_iso, "（无标题）", "(no title)")

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    if source_url:
        lines.append(f"> Source: {source_url}")
    lines.append(f"> Rendered: {burned_at}")
    lines.append("")

    lines.append("## " + _t(lang_iso, "YouTube 描述", "YouTube Description"))
    lines.append("")
    lines.append(_t(lang_iso,
        "（在这里填写视频描述。下面的章节段可以直接附在描述末尾。）",
        "(Fill in the video description here. The chapters block "
        "below can be appended verbatim to the description.)"))
    lines.append("")

    lines.append("## " + _t(lang_iso, "章节", "Chapters"))
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
        lines.append(_t(lang_iso, "（无章节）", "(no chapters)"))
    lines.append("")

    lines.append("## " + _t(lang_iso, "标签", "Tags"))
    lines.append("")
    lines.append(_t(lang_iso, "（待填）", "(to fill)"))
    lines.append("")

    if adapted_srts:
        lines.append("## " + _t(lang_iso, "字幕文件", "Adapted SRTs"))
        lines.append("")
        for name in adapted_srts:
            lines.append(f"- `{name}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── Single clip publish.md ───────────────────────────────────────────────────

def render_clip_publish(
    *,
    project_title: Optional[str],
    sidecar: dict,
    lang_iso: str,
) -> str:
    """Markdown for derivatives/clip/<instance>/clip_NNN.md.

    The Caption section is the centerpiece — user copies that single
    block into the X / TikTok publish form.
    """
    title = (sidecar.get("title") or "").strip() \
        or _t(lang_iso, "（无标题）", "(no title)")
    hook = (sidecar.get("hook") or "").strip()
    outro = (sidecar.get("outro") or "").strip()
    transcript = (sidecar.get("transcript") or "").strip()
    why = (sidecar.get("why_viral") or "").strip()
    dur = sidecar.get("duration_sec") or 0.0
    score = sidecar.get("score")
    start_sec = sidecar.get("start_sec")
    end_sec = sidecar.get("end_sec")
    out_idx = sidecar.get("output_index")
    hashtags_line = _fmt_hashtags(sidecar.get("hashtags"))

    meta_bits = []
    meta_bits.append(_t(lang_iso, f"时长 {_fmt_dur(dur)}",
                              f"Duration {_fmt_dur(dur)}"))
    if score is not None:
        meta_bits.append(_t(lang_iso, f"评分 {score}/10",
                                  f"Score {score}/10"))

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("**" + " · ".join(meta_bits) + "**")
    lines.append("")

    if hook:
        lines.append("## " + _t(lang_iso, "钩子文案", "Hook"))
        lines.append("")
        lines.append(hook)
        lines.append("")

    lines.append("## " + _t(lang_iso,
                            "发布稿（一键复制到 X / TikTok）",
                            "Caption (copy to X / TikTok)"))
    lines.append("")
    lines.append("```")
    lines.append(title)
    if transcript:
        lines.append("")
        lines.append(transcript)
    if hashtags_line:
        lines.append("")
        lines.append(hashtags_line)
    lines.append("```")
    lines.append("")

    if outro:
        lines.append("## " + _t(lang_iso, "结尾 CTA", "Outro"))
        lines.append("")
        lines.append(outro)
        lines.append("")

    if why:
        lines.append("## " + _t(lang_iso, "为什么这段会火", "Why this clip"))
        lines.append("")
        lines.append(why)
        lines.append("")

    # Footer with provenance.
    lines.append("---")
    lines.append("")
    src_bits = []
    if out_idx is not None:
        src_bits.append(f"clip_{int(out_idx):03d}.mp4")
    if start_sec is not None and end_sec is not None:
        src_bits.append(f"{_fmt_dur(start_sec)} – {_fmt_dur(end_sec)}")
    if project_title:
        src_bits.append(project_title)
    if src_bits:
        lines.append(_t(lang_iso, "来源", "Source") + ": " + " · ".join(src_bits))

    return "\n".join(lines).rstrip() + "\n"


# ── Clip instance index.md ───────────────────────────────────────────────────

def render_clip_index(
    *,
    project_title: Optional[str],
    instance_name: str,
    sidecars: list[dict],
    rendered_at: Optional[str],
    lang_iso: str,
) -> str:
    """Overview table for an entire clip instance."""
    title = (project_title or "").strip() \
        or _t(lang_iso, "（无标题）", "(no title)")

    lines: list[str] = []
    lines.append(f"# {title} — Clips ({instance_name})")
    lines.append("")
    count_line = _t(lang_iso,
                    f"共 {len(sidecars)} 个切片",
                    f"{len(sidecars)} clips")
    if rendered_at:
        count_line += " · " + _t(lang_iso, f"渲染于 {rendered_at}",
                                       f"rendered {rendered_at}")
    lines.append(f"> {count_line}")
    lines.append("")

    if not sidecars:
        lines.append(_t(lang_iso, "（暂无切片）", "(no clips yet)"))
        return "\n".join(lines).rstrip() + "\n"

    # Sort by output_index for stable display
    sidecars = sorted(sidecars,
                      key=lambda s: int(s.get("output_index") or 0))

    hdr = _t(lang_iso,
        "| #   | 标题                            | 时长   | 评分 | 文件 | 发布稿 |\n"
        "|-----|--------------------------------|--------|------|------|--------|",
        "| #   | Title                          | Dur    | Score| File | Publish |\n"
        "|-----|--------------------------------|--------|------|------|---------|")
    lines.append(hdr)

    for s in sidecars:
        idx = int(s.get("output_index") or 0)
        t = (s.get("title") or "").replace("|", "\\|").strip() or "—"
        dur = _fmt_dur(s.get("duration_sec") or 0)
        score = s.get("score")
        score_s = "—" if score is None else str(score)
        # Prefer the sidecar's `filename` (records the hook-bearing
        # name picked at render time). Fall back to the legacy
        # clip_NNN.mp4 convention for older sidecars without it.
        mp4 = (s.get("filename") or "").strip() or f"clip_{idx:03d}.mp4"
        md = os.path.splitext(mp4)[0] + ".md"
        lines.append(f"| {idx:03d} | {t} | {dur} | {score_s} "
                     f"| [{mp4}]({mp4}) | [{md}]({md}) |")

    return "\n".join(lines).rstrip() + "\n"


# ── Discovery helper ─────────────────────────────────────────────────────────

def collect_clip_sidecars(instance_dir: str) -> list[dict]:
    """Read every clip_*.json in an instance dir. Returns sidecar dicts
    sorted by output_index. Errors on individual files are swallowed —
    the index renders best-effort over what loaded cleanly."""
    import json
    import os
    out: list[dict] = []
    try:
        entries = os.listdir(instance_dir)
    except OSError:
        return out
    for name in entries:
        if not (name.startswith("clip_") and name.endswith(".json")):
            continue
        path = os.path.join(instance_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            continue
    out.sort(key=lambda s: int(s.get("output_index") or 0))
    return out
