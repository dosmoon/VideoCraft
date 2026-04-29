"""
core/video_ops.py - 视频/音频 FFmpeg 纯逻辑操作

无任何 UI 依赖，失败 raise RuntimeError，进度通过 callback 传出。
"""

import os
import re
import subprocess
from typing import Callable, Optional


def _run_ffmpeg(cmd: list, progress_callback: Optional[Callable] = None) -> None:
    """执行 FFmpeg 命令，解析进度，失败 raise RuntimeError。"""
    process = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        encoding="utf-8",
        errors="ignore",
    )
    duration = None
    for line in process.stderr:
        if "Duration:" in line:
            m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", line)
            if m:
                h, mn, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                duration = h * 3600 + mn * 60 + s
        if "time=" in line and duration and progress_callback:
            m = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
            if m:
                h, mn, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                pct = min((h * 3600 + mn * 60 + s) / duration * 100, 100)
                progress_callback(f"{pct:.0f}%")
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg 退出码 {process.returncode}")


def extract_mp3(video_path: str, output_path: str = None,
                bitrate: str = "192k",
                progress_callback: Optional[Callable] = None) -> str:
    """
    从视频/音频文件提取 MP3，返回输出路径。
    output_path 为 None 时，在输入文件同目录生成同名 .mp3。
    """
    if output_path is None:
        base = os.path.splitext(video_path)[0]
        output_path = base + ".mp3"

    if progress_callback:
        progress_callback("开始提取 MP3...")

    cmd = [
        "ffmpeg", "-i", video_path,
        "-b:a", bitrate, "-acodec", "libmp3lame",
        output_path, "-y",
    ]
    _run_ffmpeg(cmd, progress_callback)

    if progress_callback:
        progress_callback("完成")

    return output_path


def _hms_to_seconds(s: str) -> float:
    """Parse 'HH:MM:SS', 'HH:MM:SS.mmm', 'MM:SS', or seconds → float seconds."""
    parts = (s or "").strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0]) if parts and parts[0] else 0.0


def extract_clip(video_path: str, start: str, end: str,
                 output_path: str = None,
                 progress_callback: Optional[Callable] = None) -> str:
    """
    快速提取视频片段（stream copy，无重编码）。
    start / end 格式：HH:MM:SS 或 HH:MM:SS.mmm
    返回输出路径。

    实现注意：用 ``-t <duration>`` 而非 ``-to <end>``。当 ``-ss`` 在 ``-i``
    之前时（input seeking，速度快），``-to`` 是相对**输出**起点的时间，会
    导致最终长度等于 end - 0，而不是 end - start。``-t`` 始终是持续时间，
    无歧义。video_tools.py:270 也是这么写的。
    """
    if output_path is None:
        base, ext = os.path.splitext(video_path)
        safe_start = start.replace(":", "-")
        safe_end = end.replace(":", "-")
        output_path = f"{base}_{safe_start}_{safe_end}{ext}"

    if progress_callback:
        progress_callback("开始提取片段...")

    duration = max(0.0, _hms_to_seconds(end) - _hms_to_seconds(start))
    cmd = [
        "ffmpeg",
        "-ss", start, "-i", video_path,
        "-t", f"{duration:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path, "-y",
    ]
    _run_ffmpeg(cmd, progress_callback)

    if progress_callback:
        progress_callback("完成")

    return output_path
