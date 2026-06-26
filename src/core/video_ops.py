"""
core/video_ops.py - 视频/音频 FFmpeg 纯逻辑操作

无任何 UI 依赖，失败 raise RuntimeError，进度通过 callback 传出。
"""

import json
import os
import re
import shutil
import subprocess
from typing import Callable, Optional, Sequence


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


# ── Audio probing / time-stretch / placed-mix (TTS dubbing) ──────────────────

def probe_duration_sec(path: str) -> float:
    """Return a media file's duration in seconds via ffprobe (0.0 on failure).

    ffprobe ships with ffmpeg; the repo already assumes it on PATH (see
    source_acquire._ffprobe). Used by the dubbing pipeline to measure each
    synthesized cue's natural length before fitting it to its subtitle slot.
    """
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError("ffprobe not on PATH; cannot measure audio duration") from e
    if result.returncode != 0:
        return 0.0
    try:
        fmt = (json.loads(result.stdout) or {}).get("format") or {}
        return float(fmt.get("duration") or 0.0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def atempo_chain(factor: float) -> str:
    """Build an ffmpeg `atempo` filter string for an arbitrary speed factor.

    A single `atempo` only accepts 0.5–2.0, so factors outside that range are
    decomposed into a chain of in-range steps (e.g. 2.5 → atempo=2.0,atempo=1.25).
    Returns "" for a no-op factor (≈1.0). Used as the time-stretch fallback for
    providers without native rate control (aistack / fish_audio).
    """
    if factor <= 0:
        raise ValueError(f"atempo factor must be > 0, got {factor}")
    if abs(factor - 1.0) < 1e-3:
        return ""
    steps: list[float] = []
    remaining = factor
    # Speed-ups: peel off ×2.0 steps until within range.
    while remaining > 2.0:
        steps.append(2.0)
        remaining /= 2.0
    # Slow-downs: peel off ×0.5 steps until within range.
    while remaining < 0.5:
        steps.append(0.5)
        remaining /= 0.5
    steps.append(remaining)
    return ",".join(f"atempo={s:.6f}" for s in steps)


def time_stretch_audio(in_path: str, out_path: str, factor: float,
                       *, bitrate: str = "192k") -> str:
    """Re-time an audio file by `factor` (>1 = faster/shorter) via ffmpeg atempo.

    The time-stretch fallback for TTS providers without native rate control:
    we synthesize at normal speed, then speed the result up to fit its slot.
    A no-op factor copies the input. Returns `out_path`.
    """
    chain = atempo_chain(factor)
    if not chain:
        shutil.copyfile(in_path, out_path)
        return out_path
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", in_path,
        "-filter:a", chain, "-b:a", bitrate, "-acodec", "libmp3lame",
        out_path,
    ]
    _run_ffmpeg(cmd)
    return out_path


def assemble_delayed_mix(
    inputs: Sequence[dict],
    total_sec: float,
    out_path: str,
    *,
    sample_rate: int = 44100,
    bitrate: str = "192k",
    progress_callback: Optional[Callable] = None,
) -> str:
    """Mix a set of audio clips onto one fixed-length track at absolute offsets.

    `inputs` = [{"path": str, "delay_sec": float}, ...]. Each clip is resampled
    to a common rate/layout, delayed to its `delay_sec` offset, then summed onto
    a full-length silent base (`anullsrc`) so gaps are silence and overlapping
    clips add (no amix volume normalization). The output is trimmed/padded to
    exactly `total_sec`. This is the dubbing assembler: clips = synthesized cues,
    base = the source-video timeline.

    Returns `out_path`. Raises RuntimeError on ffmpeg failure.
    """
    total = max(0.0, float(total_sec))
    cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "error"]
    # Input 0: silent base spanning the whole timeline.
    cmd += [
        "-f", "lavfi", "-t", f"{total:.3f}",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate={sample_rate}",
    ]
    clips = [c for c in inputs if c.get("path")]
    for c in clips:
        cmd += ["-i", c["path"]]

    filters: list[str] = []
    labels: list[str] = ["[0:a]"]  # base track
    for i, c in enumerate(clips, start=1):
        delay_ms = max(0, int(round(float(c.get("delay_sec", 0.0)) * 1000)))
        # Normalize each cue to the base rate/layout, then delay to its offset.
        filters.append(
            f"[{i}:a]aresample={sample_rate},"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"adelay={delay_ms}:all=1[a{i}]"
        )
        labels.append(f"[a{i}]")
    # Sum base + all delayed cues without amix's per-input volume division.
    filters.append(
        "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[mix]"
    )
    filter_complex = ";".join(filters)

    # Hand the (potentially huge) filtergraph to ffmpeg via a script file so we
    # never hit the Windows command-line length limit with many cues.
    script_path = out_path + ".filter.txt"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(filter_complex)

    cmd += [
        "-filter_complex_script", script_path,
        "-map", "[mix]",
        "-t", f"{total:.3f}",
        "-ar", str(sample_rate), "-ac", "2",
        "-b:a", bitrate, "-acodec", "libmp3lame",
        out_path,
    ]
    try:
        _run_ffmpeg(cmd, progress_callback)
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass
    return out_path


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
