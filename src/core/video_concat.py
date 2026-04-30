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
