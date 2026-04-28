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
                    "time_str": {"type": "string"},
                    "title": {"type": "string"},
                    "refined": {"type": "string"},
                },
                "required": ["time_str", "title", "refined"],
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
    Used by SrtExtractSubtitlesApp.
    """
    subs = list(srt.parse(read_srt(srt_path)))
    lines = []
    for sub in subs:
        content = sub.content.replace('\n', ' ').strip()
        if content:
            lines.append(content)
    return "\n".join(lines)


def get_stats(srt_path: str) -> dict:
    """Return {"count", "duration_sec", "has_chinese"} for a SRT."""
    content = read_srt(srt_path)

    lines = content.splitlines()
    count = 0
    last_end_sec = 0.0
    has_chinese = False

    for line in lines:
        line = line.strip()
        if line.isdigit():
            count += 1
        elif "-->" in line:
            m = re.search(r"-->\s*(\d+):(\d+):(\d+)[,\.](\d+)", line)
            if m:
                h, mn, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                last_end_sec = h * 3600 + mn * 60 + s + ms / 1000
        elif line and not line.isdigit() and "-->" not in line:
            if re.search(r"[\u4e00-\u9fff]", line):
                has_chinese = True

    return {
        "count": count,
        "duration_sec": last_end_sec,
        "has_chinese": has_chinese,
    }


# ── AI-powered SRT post-processing ───────────────────────────────────────────

def generate_youtube_segments(srt_path, prompt=None, tier=None):
    """Generate YouTube timestamp-segment description from an SRT.

    Args:
        srt_path: Path to source .srt.
        prompt:   Optional custom prompt template. Must contain
                  {subtitle_content} placeholder. If None, uses the inline
                  default. Phase 1 accepts the parameter for backward
                  compatibility; Phase 2 with Prompt hub (L16) will ignore
                  it and load by task key.
        tier:     AI tier string. Defaults to TIER_PREMIUM.

    Returns:
        AI-generated segment description text.

    Raises:
        FileNotFoundError: SRT missing.
        ValueError:        SRT empty or unparseable.
        RuntimeError:      AI call failed.
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

    template = prompt if prompt is not None else _prompts.get("subtitle.segments")
    final_prompt = template.replace("{subtitle_content}", subtitle_content)

    _tier = tier or TIER_PREMIUM
    try:
        return ai.complete(final_prompt, task="subtitle.post", tier=_tier)
    except Exception as e:
        raise RuntimeError(f"调用AI生成失败 (tier={_tier}): {e}")


def extract_paragraphs_from_segments(srt_path, segments_path):
    """Split SRT content into segments per the timestamps in segments_path.

    No AI involved — pure slice-by-time on the SRT entries.
    """
    subs = list(srt.parse(read_srt(srt_path)))

    segments_lines = read_srt(segments_path).splitlines(keepends=True)

    segments = []
    for line in segments_lines:
        line = line.strip()
        if line and ' ' in line:
            time_str, title = line.split(' ', 1)
            try:
                time_parts = list(map(int, time_str.split(':')))
                if len(time_parts) == 2:
                    m, s = time_parts
                    timestamp = m * 60 + s
                elif len(time_parts) == 3:
                    h, m, s = time_parts
                    timestamp = h * 3600 + m * 60 + s
                else:
                    continue
                segments.append({'timestamp': timestamp, 'time_str': time_str,
                                 'title': title, 'content': []})
            except ValueError:
                continue

    if not segments:
        raise ValueError("时间戳分割文件中没有找到有效的时间戳")

    current_segment_idx = 0
    for sub in subs:
        sub_start = sub.start.total_seconds()
        content = sub.content.replace('\n', ' ')
        while current_segment_idx < len(segments) - 1:
            if sub_start < segments[current_segment_idx + 1]['timestamp']:
                break
            current_segment_idx += 1
        if current_segment_idx < len(segments) - 1:
            if sub_start < segments[current_segment_idx + 1]['timestamp']:
                segments[current_segment_idx]['content'].append(content)
        else:
            segments[current_segment_idx]['content'].append(content)

    output = ""
    for segment in segments:
        output += f"{segment['time_str']} {segment['title']}\n"
        if segment['content']:
            output += f"{' '.join(segment['content'])}\n\n"
        else:
            output += "(此时间段内无字幕内容)\n\n"

    return output.strip()


def generate_video_titles(subs_path, prompt=None, tier=None):
    """Generate video title suggestions from a segment-description file.

    Args:
        subs_path: Path to segment-description text file (output of
                   generate_youtube_segments or user-authored).
        prompt:    Optional custom prompt. If None, uses the inline default.
        tier:      AI tier; defaults to TIER_PREMIUM.

    Returns:
        AI-generated title text.
    """
    subs_content = read_srt(subs_path)
    base_prompt = prompt if prompt is not None else _prompts.get("subtitle.titles")
    full_prompt = (
        f"{base_prompt}\n\n"
        f"以下是视频的分段描述内容：\n\n{subs_content}\n\n"
        "请根据以上内容生成合适的视频标题。"
    )

    _tier = tier or TIER_PREMIUM
    try:
        return ai.complete(full_prompt, task="subtitle.post", tier=_tier)
    except Exception as e:
        raise RuntimeError(f"调用AI生成失败 (tier={_tier}): {e}")


def _is_valid_segment_timestamp(time_str):
    """True if string is mm:ss or hh:mm:ss shaped."""
    return re.match(r'^\d{1,2}:\d{2}(?::\d{2})?$', time_str) is not None


def parse_segments_paragraphs_content(content):
    """Parse "paragraph extraction" output text into structured segments."""
    segments = []
    current_segment = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(' ', 1)
        if len(parts) == 2 and _is_valid_segment_timestamp(parts[0]):
            if current_segment:
                current_segment['content'] = ' '.join(current_segment['content']).strip()
                segments.append(current_segment)
            current_segment = {'time_str': parts[0], 'title': parts[1].strip(), 'content': []}
        elif current_segment is not None:
            current_segment['content'].append(line)
    if current_segment:
        current_segment['content'] = ' '.join(current_segment['content']).strip()
        segments.append(current_segment)
    return segments


def refine_segment_descriptions(paragraphs_path, prompt=None, tier=None):
    """Refine paragraph-extracted segments via AI.

    Args:
        paragraphs_path: Output from extract_paragraphs_from_segments().
        prompt:          Optional custom prompt template. May include
                         {all_segments_content} / {segments_content}
                         placeholders. If None, uses the inline default.
        tier:            AI tier; defaults to TIER_PREMIUM.

    Returns:
        Refined segment text.
    """
    if not os.path.exists(paragraphs_path):
        raise FileNotFoundError(f"段落内容文件 '{paragraphs_path}' 不存在")

    paragraphs_content = read_srt(paragraphs_path)

    segments = parse_segments_paragraphs_content(paragraphs_content)
    if not segments:
        raise ValueError(
            '未能从输入文件中解析到有效分段，请确认文件为"提取段落内容"标签页输出格式'
        )

    combined_segments = []
    for idx, segment in enumerate(segments, start=1):
        segment_content = segment['content'] or '(此时间段内无字幕内容)'
        combined_segments.append(
            f"[分段{idx}]\n分段时间戳：{segment['time_str']}\n"
            f"分段标题：{segment['title']}\n分段内容：\n{segment_content}\n"
        )
    all_segments_content = '\n'.join(combined_segments).strip()

    template = prompt if prompt is not None else _prompts.get("subtitle.refine")

    full_prompt = template
    full_prompt = full_prompt.replace('{all_segments_content}', all_segments_content)
    full_prompt = full_prompt.replace('{segments_content}', all_segments_content)

    # Backward compatibility: legacy per-segment placeholders mean the user
    # is using an old prompt that expected per-segment substitution. Swap to
    # a safe all-in-one prompt.
    if any(t in full_prompt for t in ('{segment_time}', '{segment_title}', '{segment_content}')):
        full_prompt = (
            "请一次性精炼以下全部分段内容。\n"
            "要求：每个分段不超过128字；问答段落保留问答视角；\n"
            "输出格式为：\"时间戳 标题\\n精炼内容\"，分段之间空一行，不要额外解释。\n\n"
            f"{all_segments_content}"
        )
    elif all_segments_content not in full_prompt:
        full_prompt = f"{full_prompt}\n\n以下是全部分段内容：\n{all_segments_content}"

    _tier = tier or TIER_PREMIUM
    refined_text = ai.complete(full_prompt, task="subtitle.post", tier=_tier)
    if not refined_text:
        raise RuntimeError("AI返回为空，未生成精炼结果")
    return refined_text


def generate_subtitle_pack(srt_path, prompt=None, tier=None) -> dict:
    """One-shot AI call: SRT -> {titles, segments[time_str/title/refined]}.

    Combines the work of generate_youtube_segments + refine_segment_descriptions
    + generate_video_titles into a single structured call. Returns the parsed
    JSON dict directly; downstream callers decide how to write it to disk
    (see write_subtitle_pack).
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
        )
    except Exception as e:
        raise RuntimeError(f"调用AI生成失败 (tier={_tier}): {e}")

    if not isinstance(result, dict):
        raise RuntimeError("AI返回不是JSON对象")
    titles = result.get("titles") or []
    segments = result.get("segments") or []
    if not titles or not segments:
        raise RuntimeError("AI返回缺少 titles 或 segments 字段")
    return result


def write_subtitle_pack(pack: dict, base_path: str) -> dict:
    """Persist a subtitle pack as 1 JSON + 3 plain-text companions.

    base_path may include or omit an extension; the suffix is stripped and
    four sibling files are written:
      - <base>.json            full structured payload
      - <base>-titles.txt      one candidate title per line
      - <base>-segments.txt    "HH:MM:SS title" per line
      - <base>-refined.txt     "HH:MM:SS title\\n<refined>\\n\\n" blocks

    Returns a dict mapping kind -> absolute path.
    """
    root, _ext = os.path.splitext(base_path)
    json_path = root + ".json"
    titles_path = root + "-titles.txt"
    segments_path = root + "-segments.txt"
    refined_path = root + "-refined.txt"

    parent = os.path.dirname(root)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(pack, f, ensure_ascii=False, indent=2)

    titles = pack.get("titles") or []
    with open(titles_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(str(t).strip() for t in titles) + "\n")

    segments = pack.get("segments") or []
    with open(segments_path, 'w', encoding='utf-8') as f:
        for seg in segments:
            f.write(f"{seg.get('time_str', '').strip()} "
                    f"{seg.get('title', '').strip()}\n")

    with open(refined_path, 'w', encoding='utf-8') as f:
        for seg in segments:
            f.write(f"{seg.get('time_str', '').strip()} "
                    f"{seg.get('title', '').strip()}\n")
            f.write(f"{seg.get('refined', '').strip()}\n\n")

    return {
        "json": json_path,
        "titles": titles_path,
        "segments": segments_path,
        "refined": refined_path,
    }
