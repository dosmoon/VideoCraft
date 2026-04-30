"""
Video split and merge helpers for the split workbench.

`split_segments` writes one file per segment, with selectable cut mode
(fast / keyframe_snap / accurate) routed through core.video_split.split_one.
`merge_segments` re-encodes each selected segment then concatenates them into
one output, so non-contiguous segments can be stitched into a single cut.
`concat_videos` is the underlying ffmpeg concat-demuxer call, also used as a
standalone utility.

The low-level ffmpeg helpers (run_ffmpeg, stream_copy_segment,
reencode_segment) are exported so that core.video_split can reuse them
without reaching into private names.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Callable, TYPE_CHECKING

from core.segment_model import Segment, duration_of, end_of, safe_filename

if TYPE_CHECKING:
    from core.video_split import SplitMode

ProgressCb = Callable[[int, int], None]  # (done, total)


def run_ffmpeg(cmd: list[str]) -> None:
    """Run ffmpeg and raise RuntimeError with stderr on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip().splitlines()[-10:]
        raise RuntimeError("ffmpeg failed: " + " | ".join(stderr))


def probe_video(path: str) -> dict:
    """One-shot ffprobe for the fields the concat tool cares about.

    Returns {duration, width, height, fps, vcodec, acodec}. Missing or
    unparseable fields come back as None / 0; callers display "?" for those.
    """
    import json as _json
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    out = {"duration": 0.0, "width": 0, "height": 0,
           "fps": 0.0, "vcodec": None, "acodec": None}
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        data = _json.loads(res.stdout or "{}")
    except (OSError, ValueError):
        return out
    fmt = data.get("format") or {}
    try:
        out["duration"] = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        pass
    for s in (data.get("streams") or []):
        ctype = s.get("codec_type")
        if ctype == "video" and out["vcodec"] is None:
            out["vcodec"] = s.get("codec_name")
            out["width"] = int(s.get("width") or 0)
            out["height"] = int(s.get("height") or 0)
            # avg_frame_rate is "30000/1001" or "30/1" or "0/0"
            rate = s.get("avg_frame_rate") or "0/0"
            try:
                num, den = rate.split("/")
                out["fps"] = (float(num) / float(den)) if float(den) else 0.0
            except (ValueError, ZeroDivisionError):
                pass
        elif ctype == "audio" and out["acodec"] is None:
            out["acodec"] = s.get("codec_name")
    return out


def concat_videos_reencode(
    files: list[str],
    output: str,
    target: dict,
    progress_cb: Callable[[float], None] | None = None,
) -> None:
    """Re-encode + concat videos with mismatched formats.

    Each input is normalized (scale+pad to target resolution, target fps,
    44.1kHz audio resample) then concatenated via filter_complex. Slower
    than stream copy but handles arbitrary input mix (different codecs,
    resolutions, frame rates).

    target = {"width": int, "height": int, "fps": float|int,
              "vcodec": str, "acodec": str}
    progress_cb gets a 0..100 percentage. Total duration is summed via
    probe_video; ffmpeg's `-progress pipe:1` reports out_time_us we then
    convert to a percentage."""
    if len(files) < 2:
        raise ValueError("concat_videos_reencode: need at least 2 files")

    width = int(target.get("width") or 1920)
    height = int(target.get("height") or 1080)
    fps = target.get("fps") or 30
    vcodec = target.get("vcodec") or "libx264"
    acodec = target.get("acodec") or "aac"

    # Per-input normalization filters: scale (preserve aspect) + pad to fit
    # exact target box + setsar=1 + fps. Audio resampled to a common rate.
    parts = []
    for i in range(len(files)):
        parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}];"
            f"[{i}:a]aresample=44100[a{i}]"
        )
    streams = "".join(f"[v{i}][a{i}]" for i in range(len(files)))
    parts.append(f"{streams}concat=n={len(files)}:v=1:a=1[outv][outa]")
    filter_complex = ";".join(parts)

    cmd = ["ffmpeg", "-y"]
    for f in files:
        cmd.extend(["-i", f])
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", vcodec, "-c:a", acodec,
        "-preset", "medium",
        output,
    ])

    if progress_cb is None:
        run_ffmpeg(cmd)
        return

    # Live percentage via `-progress pipe:1`. Total = sum of input durations.
    total_us = 0
    for f in files:
        info = probe_video(f)
        total_us += int(float(info.get("duration") or 0) * 1_000_000)
    cmd.insert(-1, "-progress")
    cmd.insert(-1, "pipe:1")

    # IMPORTANT: must drain stderr in a background thread, otherwise the
    # OS pipe buffer (~64KB) fills with ffmpeg's verbose encoding chatter,
    # ffmpeg blocks writing to stderr → it stops writing -progress to
    # stdout → our progress loop hangs forever. Same applies if we ever
    # forget to read both pipes when both are PIPE.
    import threading as _threading
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    stderr_lines: list[str] = []

    def _drain_stderr():
        if proc.stderr is None:
            return
        for line in proc.stderr:
            stderr_lines.append(line)
            # Keep memory bounded — a long re-encode can otherwise grow
            # this list to 100k+ lines. Last 200 lines is plenty for
            # error diagnosis.
            if len(stderr_lines) > 400:
                del stderr_lines[:200]

    drainer = _threading.Thread(target=_drain_stderr, daemon=True)
    drainer.start()
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                if line.startswith("out_time_us=") and total_us > 0:
                    try:
                        cur_us = int(line.split("=", 1)[1].strip())
                        progress_cb(min(100.0, cur_us / total_us * 100))
                    except ValueError:
                        pass
        proc.wait()
        drainer.join(timeout=2)
        if proc.returncode != 0:
            tail = "".join(stderr_lines).strip().splitlines()[-10:]
            raise RuntimeError("ffmpeg failed: " + " | ".join(tail))
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()


def concat_videos(files: list[str], output: str) -> None:
    """Concatenate compatible video files using ffmpeg concat demuxer."""
    if not files:
        raise ValueError("concat_videos: empty file list")
    lf = tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".txt", encoding="utf-8"
    )
    try:
        for f in files:
            escaped = f.replace("'", r"'\''")
            lf.write(f"file '{escaped}'\n")
        lf.close()
        run_ffmpeg([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", lf.name, "-c", "copy", output,
        ])
    finally:
        try:
            os.unlink(lf.name)
        except OSError:
            pass


def stream_copy_segment(
    video_path: str,
    start_sec: float,
    duration_sec: float,
    output: str,
) -> None:
    """Fast stream-copy cut. Start is seeked BEFORE -i so ffmpeg jumps to the
    nearest prior keyframe; snap-to-keyframe is handled at the SplitMode level
    in core.video_split (KEYFRAME_SNAP mode pre-snaps start explicitly)."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.3f}",
        "-i", video_path,
        "-t", f"{duration_sec:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        "-loglevel", "error",
        output,
    ]
    run_ffmpeg(cmd)


def reencode_segment(
    video_path: str,
    start_sec: float,
    duration_sec: float,
    output: str,
) -> None:
    """Accurate cut by re-encoding. Needed for merge so that cut points are
    frame-accurate and every piece has matching codec params for concat."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.3f}",
        "-i", video_path,
        "-t", f"{duration_sec:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        "-loglevel", "error",
        output,
    ]
    run_ffmpeg(cmd)


def split_segments(
    video_path: str,
    all_segments: list[Segment],
    selected_indices: list[int],
    video_duration: float,
    output_dir: str,
    progress_cb: ProgressCb | None = None,
    mode: "SplitMode | None" = None,
    on_probe_start: Callable[[], None] | None = None,
) -> list[str]:
    """Export each selected segment to its own file.

    `selected_indices` refers to positions inside `all_segments` — the caller
    passes the full list so that each segment's end is derived from the
    ORIGINAL next segment, not the next *selected* one.

    `mode` selects the cut strategy (see core.video_split.SplitMode).
    Defaults to KEYFRAME_SNAP when omitted — the professional-workbench
    stance: no re-encode, but boundaries land on I-frames.

    `on_probe_start` is invoked once before the (potentially slow) ffprobe
    scan so the UI can show a "Probing keyframes…" status. Skipped when mode
    doesn't need probing or when the cache is already warm.

    Returns the list of written file paths.
    """
    from core.video_split import SplitMode, probe_keyframes, split_one, _KEYFRAME_CACHE

    if mode is None:
        mode = SplitMode.KEYFRAME_SNAP

    keyframes: list[float] | None = None
    if mode == SplitMode.KEYFRAME_SNAP:
        abs_path = os.path.abspath(video_path)
        cache_hit = False
        cached = _KEYFRAME_CACHE.get(abs_path)
        if cached:
            try:
                if cached[0] == os.path.getmtime(abs_path):
                    cache_hit = True
            except OSError:
                pass
        if not cache_hit and on_probe_start is not None:
            on_probe_start()
        keyframes = probe_keyframes(video_path)

    os.makedirs(output_dir, exist_ok=True)
    total = len(selected_indices)
    outputs: list[str] = []
    for done, idx in enumerate(selected_indices):
        seg = all_segments[idx]
        duration = duration_of(all_segments, idx, video_duration)
        if duration <= 0:
            continue
        name = f"{idx + 1:03d}_{safe_filename(seg.title)}.mp4"
        out_path = os.path.join(output_dir, name)
        if progress_cb:
            progress_cb(done, total)
        split_one(
            video_path, seg.start_sec, duration, out_path,
            mode=mode, keyframes=keyframes,
        )
        outputs.append(out_path)
    if progress_cb:
        progress_cb(total, total)
    return outputs


def merge_segments(
    video_path: str,
    all_segments: list[Segment],
    selected_indices: list[int],
    video_duration: float,
    output_path: str,
    progress_cb: ProgressCb | None = None,
) -> None:
    """Re-encode each selected segment to a temp file, then concat to one mp4.

    Handles non-contiguous selections (jump cuts) — segments are stitched in
    the order given by `selected_indices`.
    """
    if not selected_indices:
        raise ValueError("merge_segments: no segments selected")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    # Steps: N re-encodes + 1 concat = total N+1 units of progress
    total = len(selected_indices) + 1
    tmp_dir = tempfile.mkdtemp(prefix="vc_merge_")
    tmp_files: list[str] = []
    try:
        for done, idx in enumerate(selected_indices):
            seg = all_segments[idx]
            duration = duration_of(all_segments, idx, video_duration)
            if duration <= 0:
                continue
            piece = os.path.join(tmp_dir, f"piece_{done:03d}.mp4")
            if progress_cb:
                progress_cb(done, total)
            reencode_segment(video_path, seg.start_sec, duration, piece)
            tmp_files.append(piece)

        if not tmp_files:
            raise RuntimeError("merge_segments: all selected segments had zero duration")

        if progress_cb:
            progress_cb(len(selected_indices), total)
        concat_videos(tmp_files, output_path)
        if progress_cb:
            progress_cb(total, total)
    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


__all__ = [
    "run_ffmpeg",
    "concat_videos",
    "stream_copy_segment",
    "reencode_segment",
    "split_segments",
    "merge_segments",
    "end_of",
]
