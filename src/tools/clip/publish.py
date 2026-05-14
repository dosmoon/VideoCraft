"""Clip derivative publish.md + index.md templates.

Three pure functions covering the clip derivative's publishing surface:

  - render_clip_publish(): per-clip clip_NNN.md — the centerpiece is the
    Caption block (title + transcript + hashtags) sized for X / TikTok
    publish forms.
  - render_clip_index(): per-instance index.md — clickable table mapping
    clip_001..N to titles + scores + per-clip publish.md.
  - collect_clip_sidecars(): scan an instance dir for clip_*.json files.

The clip-specific schema (output_index, hook/outro, why_viral, score,
clip_NNN.mp4 naming) is encoded here, not in core/, since it's a product
decision tied to the clip workbench.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from core.markdown_fmt import fmt_dur, fmt_hashtags, t


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
        or t(lang_iso, "（无标题）", "(no title)")
    hook = (sidecar.get("hook") or "").strip()
    outro = (sidecar.get("outro") or "").strip()
    transcript = (sidecar.get("transcript") or "").strip()
    why = (sidecar.get("why_viral") or "").strip()
    dur = sidecar.get("duration_sec") or 0.0
    score = sidecar.get("score")
    start_sec = sidecar.get("start_sec")
    end_sec = sidecar.get("end_sec")
    out_idx = sidecar.get("output_index")
    hashtags_line = fmt_hashtags(sidecar.get("hashtags"))

    meta_bits = []
    meta_bits.append(t(lang_iso, f"时长 {fmt_dur(dur)}",
                              f"Duration {fmt_dur(dur)}"))
    if score is not None:
        meta_bits.append(t(lang_iso, f"评分 {score}/10",
                                  f"Score {score}/10"))

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("**" + " · ".join(meta_bits) + "**")
    lines.append("")

    if hook:
        lines.append("## " + t(lang_iso, "钩子文案", "Hook"))
        lines.append("")
        lines.append(hook)
        lines.append("")

    lines.append("## " + t(lang_iso,
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
        lines.append("## " + t(lang_iso, "结尾 CTA", "Outro"))
        lines.append("")
        lines.append(outro)
        lines.append("")

    if why:
        lines.append("## " + t(lang_iso, "为什么这段会火", "Why this clip"))
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
        src_bits.append(f"{fmt_dur(start_sec)} – {fmt_dur(end_sec)}")
    if project_title:
        src_bits.append(project_title)
    if src_bits:
        lines.append(t(lang_iso, "来源", "Source") + ": " + " · ".join(src_bits))

    return "\n".join(lines).rstrip() + "\n"


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
        or t(lang_iso, "（无标题）", "(no title)")

    lines: list[str] = []
    lines.append(f"# {title} — Clips ({instance_name})")
    lines.append("")
    count_line = t(lang_iso,
                    f"共 {len(sidecars)} 个切片",
                    f"{len(sidecars)} clips")
    if rendered_at:
        count_line += " · " + t(lang_iso, f"渲染于 {rendered_at}",
                                       f"rendered {rendered_at}")
    lines.append(f"> {count_line}")
    lines.append("")

    if not sidecars:
        lines.append(t(lang_iso, "（暂无切片）", "(no clips yet)"))
        return "\n".join(lines).rstrip() + "\n"

    # Sort by output_index for stable display
    sidecars = sorted(sidecars,
                      key=lambda s: int(s.get("output_index") or 0))

    hdr = t(lang_iso,
        "| #   | 标题                            | 时长   | 评分 | 文件 | 发布稿 |\n"
        "|-----|--------------------------------|--------|------|------|--------|",
        "| #   | Title                          | Dur    | Score| File | Publish |\n"
        "|-----|--------------------------------|--------|------|------|---------|")
    lines.append(hdr)

    for s in sidecars:
        idx = int(s.get("output_index") or 0)
        ttl = (s.get("title") or "").replace("|", "\\|").strip() or "—"
        dur = fmt_dur(s.get("duration_sec") or 0)
        score = s.get("score")
        score_s = "—" if score is None else str(score)
        # Prefer the sidecar's `filename` (records the hook-bearing
        # name picked at render time). Fall back to the legacy
        # clip_NNN.mp4 convention for older sidecars without it.
        mp4 = (s.get("filename") or "").strip() or f"clip_{idx:03d}.mp4"
        md = os.path.splitext(mp4)[0] + ".md"
        lines.append(f"| {idx:03d} | {ttl} | {dur} | {score_s} "
                     f"| [{mp4}]({mp4}) | [{md}]({md}) |")

    return "\n".join(lines).rstrip() + "\n"


def collect_clip_sidecars(instance_dir: str) -> list[dict]:
    """Read every clip_*.json in an instance dir. Returns sidecar dicts
    sorted by output_index. Errors on individual files are swallowed —
    the index renders best-effort over what loaded cleanly."""
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
