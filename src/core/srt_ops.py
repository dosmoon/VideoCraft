"""
core/srt_ops.py - SRT subtitle feature-layer operations.

UI-unaware. Failures raise exceptions; progress is reported via callbacks.
AI calls go through core.ai (not ai_router directly) per architecture
principle 1. Default prompts are inlined here; M3+ L16 Prompt hub will
replace these with file-backed templates without changing the public API.
"""

import json
import os
import re
import srt

from core import ai
from core import prompts as _prompts
from core.ai.tiers import TIER_PREMIUM
from core.subtitle_ops import read_srt


# JSON schema for the one-shot "subtitle pack" AI call: titles + segments
# (each with timestamp, title, ≤128-char refined summary). Used by
# generate_subtitle_pack() to enforce structured output.
SUBTITLE_PACK_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time_str":   {"type": "string"},
                    "title":      {"type": "string"},
                    "refined":    {"type": "string"},
                    # key_points: simple list of short bullet strings.
                    # Originally tried object items with timestamps but
                    # asking AI to compute per-point start/end from SRT
                    # cues blew up the prompt complexity (Sonnet thinking
                    # ballooned, Haiku undersegmented). key_points are
                    # text-only enrichment for chapter cards / publish.md
                    # / hotclip selection — they don't drive video popups.
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 0,
                    },
                },
                "required": ["time_str", "title", "refined", "key_points"],
            },
            "minItems": 1,
        },
    },
    "required": ["titles", "segments"],
}


# ── Subtitle → plain text helpers ────────────────────────────────────────────

def extract_text(srt_path: str, output_path: str = None,
                 progress_callback=None) -> str:
    """Extract plain text (strip indices, timestamps, blank lines); write .txt.

    Returns the output file path. Keeps per-line granularity from the SRT
    body. See extract_all_subtitles() for a per-subtitle variant.
    """
    if output_path is None:
        base = os.path.splitext(srt_path)[0]
        output_path = base + ".txt"

    if progress_callback:
        progress_callback("读取字幕文件...")

    content = read_srt(srt_path)

    lines = content.splitlines()
    text_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.isdigit():
            continue
        if "-->" in line:
            continue
        text_lines.append(line)

    output_text = "\n".join(text_lines)

    if progress_callback:
        progress_callback("写入文本文件...")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text)

    if progress_callback:
        progress_callback("完成")

    return output_path


def extract_all_subtitles(srt_path: str) -> str:
    """Collapse each subtitle entry into a single line of plain text.

    Differs from extract_text(): this one uses srt.parse() so multi-line
    subtitle content is joined with a space; outputs one-subtitle-per-line.
    """
    subs = list(srt.parse(read_srt(srt_path)))
    lines = []
    for sub in subs:
        content = sub.content.replace('\n', ' ').strip()
        if content:
            lines.append(content)
    return "\n".join(lines)


def generate_subtitle_pack(srt_path, prompt=None, tier=None,
                            cancel_token=None) -> dict:
    """One-shot AI call: SRT -> {titles, segments[time_str/title/refined]}.

    Returns the parsed JSON dict directly; downstream callers decide
    how to write it to disk (see core.chapters_io.save_analysis).
    """
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"SRT文件 '{srt_path}' 不存在")

    subs = list(srt.parse(read_srt(srt_path)))
    if not subs:
        raise ValueError("SRT文件为空或格式错误")

    subtitle_content = ''
    for sub in subs:
        time_str = str(sub.start)[:8]
        content = sub.content.replace('\n', ' ')
        subtitle_content += f'[{time_str}] {content}\n'

    template = prompt if prompt is not None else _prompts.get("subtitle.pack")
    final_prompt = template.replace("{subtitle_content}", subtitle_content)

    _tier = tier or TIER_PREMIUM
    try:
        result = ai.complete_json(
            final_prompt,
            schema=SUBTITLE_PACK_SCHEMA,
            task="subtitle.post",
            tier=_tier,
            cancel_token=cancel_token,
        )
    except Exception as e:
        # Let AIError (including CANCELLED) propagate untouched so the UI
        # can branch on .kind. Only wrap unexpected non-AIError exceptions.
        from core.ai.errors import AIError as _AIError
        if isinstance(e, _AIError):
            raise
        raise RuntimeError(f"调用AI生成失败 (tier={_tier}): {e}")

    if not isinstance(result, dict):
        raise RuntimeError("AI返回不是JSON对象")
    titles = result.get("titles") or []
    segments = result.get("segments") or []
    if not titles or not segments:
        raise RuntimeError("AI返回缺少 titles 或 segments 字段")
    return result


