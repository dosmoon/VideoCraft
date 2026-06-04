"""
core/subtitle_ops.py - SRT read / split utilities

No UI dependency. The ffmpeg subtitle-burn styling helpers were removed with
the retired Python compose path (video_compose.py); burning now lives in the TS
composition engine.
"""

import os
import re
import srt
from datetime import timedelta

# ── 编码自动检测 ──────────────────────────────────────────────────────────────

_ENCODINGS = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'big5', 'latin-1']


def read_srt(path: str) -> str:
    """自动检测编码读取 SRT 文件，依次尝试常见编码，失败则 raise。"""
    for enc in _ENCODINGS:
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法识别文件编码：{path}")


def srt_end_seconds(path: str) -> float:
    """End timestamp of the last cue in seconds, or 0.0 on failure."""
    try:
        subs = list(srt.parse(read_srt(path)))
    except Exception:
        return 0.0
    if not subs:
        return 0.0
    return subs[-1].end.total_seconds()


# ── 字幕分割 ─────────────────────────────────────────────────────────────────

def split_subtitle(sub, max_chars: int, is_chinese: bool = False):
    """
    将单条字幕按 max_chars 分割为多条。
    - 优先在标点处断开
    - 英文额外在空格处断开
    - 直接从 sub.start 按累计字符比例计算每段时间，避免浮点累加漂移
    """
    content = sub.content.strip()
    if len(content) <= max_chars:
        return [sub]

    end = sub.end
    total_duration = (end - sub.start).total_seconds()
    if total_duration <= 0:
        return [sub]

    if is_chinese:
        breaks = [m.start() for m in re.finditer(r'[，。？！；]', content)]
    else:
        breaks = [m.start() for m in re.finditer(r'[.?!,]', content)]

    new_subs = []
    chars_so_far = 0      # 累计已处理字符数（整数，无浮点误差）
    current_pos = 0
    n = len(content)

    while current_pos < n:
        split_pos = current_pos + max_chars
        if split_pos >= n:
            split_pos = n
        else:
            candidates = [b + 1 for b in breaks if current_pos < b + 1 <= split_pos]
            if candidates:
                split_pos = max(candidates)
            elif not is_chinese:
                last_space = content.rfind(' ', current_pos, split_pos)
                if last_space > current_pos:
                    split_pos = last_space + 1

        slice_len = split_pos - current_pos
        part = content[current_pos:split_pos].strip()

        # 直接从 sub.start 计算，完全消除浮点累加误差
        t_start = sub.start + timedelta(seconds=chars_so_far / n * total_duration)
        chars_so_far += slice_len
        t_end   = sub.start + timedelta(seconds=chars_so_far / n * total_duration)

        if part:                          # 纯空白切片跳过，但位置和时间比例照常推进
            new_subs.append(srt.Subtitle(
                index=len(new_subs) + 1,
                start=t_start,
                end=t_end,
                content=part,
            ))

        current_pos = split_pos

    if new_subs:
        new_subs[-1].end = end            # 最后一段精确对齐原始结束时间
    return new_subs if new_subs else [sub]


def process_srt_split(input_path: str, max_chars: int,
                      is_chinese: bool = False) -> list:
    """
    读取 SRT 文件，对每条字幕执行分割，重新编号后返回字幕列表。
    """
    subs = list(srt.parse(read_srt(input_path)))
    result = []
    for sub in subs:
        result.extend(split_subtitle(sub, max_chars, is_chinese))
    for i, sub in enumerate(result, 1):
        sub.index = i
    return result


def split_srt_to_file(input_path: str, max_chars: int,
                      is_chinese: bool = False,
                      output_path: str = None) -> str:
    """
    分割 SRT 并写出文件。output_path 为 None 时写到同目录 _split.srt。
    返回输出文件路径。
    """
    subs = process_srt_split(input_path, max_chars, is_chinese)
    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = base + "_split" + ext
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(srt.compose(subs))
    return output_path
