"""Source video acquisition: link download (yt-dlp) or local file import.

Used by the new-project flow to populate <project>/source/video.mp4
from a user-supplied URL or local file path. Supports an optional
time range (download / cut a sub-section only) and a cooperative
cancel token so the source-prepare modal can abort cleanly.

Single entry point: acquire(...). The function dispatches to one of
two internal paths based on Source.origin and reports progress via
the callback.

Failures are wrapped in AcquireError with a category so the modal can
present a useful error + recovery action ([重试] / [改 URL] / etc).

This module is pure logic — no Tk imports. The UI driver runs it in
a worker thread and marshals progress/results back to the main thread.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from core.project_schema import Source, ClipRange, ORIGIN_LINK, ORIGIN_LOCAL


# ── Public types ──────────────────────────────────────────────────────────────

# Error categories used by the modal to choose the right recovery hint.
ERR_NETWORK = "network"
ERR_URL_INVALID = "url_invalid"
ERR_JS_RUNTIME = "js_runtime"
ERR_COOKIES = "cookies"
ERR_DISK = "disk"
ERR_FFMPEG = "ffmpeg"
ERR_CANCELLED = "cancelled"
ERR_OTHER = "other"


class AcquireError(Exception):
    """Categorized failure from acquire(). The category is one of the
    ERR_* constants and drives modal UI choices; details is the raw
    upstream message for logs."""

    def __init__(self, category: str, message: str, details: str = "") -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.details = details


class CancelToken:
    """Thread-safe cooperative cancel signal. The worker thread polls
    .cancelled at progress callback boundaries; subprocess-based paths
    also terminate the child process when set."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


@dataclass
class ProgressInfo:
    """One progress tick. percent may be None (unknown), 0~100 otherwise."""
    phase: str  # "fetching info" | "downloading" | "copying" | "cutting" | "probing"
    percent: float | None
    speed_bps: float | None = None  # bytes/sec
    eta_sec: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    status_text: str | None = None  # free-form override for status line


@dataclass
class AcquireResult:
    """Returned on success. Caller writes these into project.meta.source."""
    title: str | None
    duration_sec: float | None
    width: int | None
    height: int | None
    info_json: dict  # full yt-dlp info or ffprobe output, for source/meta.json


# ── Public API ────────────────────────────────────────────────────────────────

ProgressCb = Optional[Callable[[ProgressInfo], None]]


def acquire(
    source: Source,
    dest_video_path: str,
    dest_meta_path: str | None = None,
    *,
    progress_cb: ProgressCb = None,
    cancel_token: CancelToken | None = None,
) -> AcquireResult:
    """Acquire the source video from `source` into dest_video_path.

    For link origin: yt-dlp download (with optional --download-sections).
    For local origin: copy (or ffmpeg-cut if clip_range is set).

    Args:
        source: Source dataclass (origin / url / imported_from / clip_range).
        dest_video_path: target file path, parent dir must exist.
        dest_meta_path: optional, where to write source/meta.json.
        progress_cb: callback receiving ProgressInfo (any thread).
        cancel_token: optional CancelToken; check before/after operations.

    Returns:
        AcquireResult with metadata.

    Raises:
        AcquireError on any failure (including user cancel → ERR_CANCELLED).
    """
    os.makedirs(os.path.dirname(dest_video_path), exist_ok=True)

    # Stage into a sibling temp file so a failed/cancelled (re-)import can NEVER
    # destroy the existing source video. We download/copy into `staging` and only
    # replace the live file on full success; on any failure the original is
    # untouched. (Previously the acquire wrote straight to dest_video_path and
    # _cleanup_partial() removed it on cancel — a cancelled re-import wiped the
    # user's source. This is the fix.)
    base, ext = os.path.splitext(dest_video_path)
    staging = f"{base}.incoming{ext or '.mp4'}"
    _cleanup_partial(staging)  # clear any stale staging from a prior aborted run

    try:
        if source.origin == ORIGIN_LINK:
            if not source.url:
                raise AcquireError(ERR_URL_INVALID, "未提供视频链接", "Source.url is empty")
            result = _acquire_link(source.url, staging, dest_meta_path,
                                   source.clip_range, progress_cb, cancel_token)
        elif source.origin == ORIGIN_LOCAL:
            if not source.imported_from:
                raise AcquireError(ERR_OTHER, "未指定本地文件",
                                   "Source.imported_from is empty")
            result = _acquire_local(source.imported_from, staging,
                                    dest_meta_path, source.clip_range,
                                    progress_cb, cancel_token)
        else:
            raise AcquireError(ERR_OTHER, f"未知源类型: {source.origin}",
                               "Source.origin must be 'link' or 'local'")
    except BaseException:
        # Any failure/cancel: drop only the staging artifacts, leave dest intact.
        _cleanup_partial(staging)
        raise

    # Success → atomically swap the new file in. os.replace is atomic on the same
    # filesystem (staging is a sibling). If dest is locked (e.g. the renderer is
    # previewing the old video) the swap raises and the ORIGINAL stays intact — a
    # recoverable failure, never a lost source.
    try:
        os.replace(staging, dest_video_path)
    except OSError as e:
        _cleanup_partial(staging)
        raise AcquireError(ERR_DISK, "无法替换原视频(文件可能正被占用)", str(e)) from e
    return result


def fetch_link_info(url: str) -> dict:
    """Light-weight metadata-only fetch for the [获取视频信息] button.

    Returns the yt-dlp info dict; the dialog uses .title to pre-fill
    the project-name field. Raises AcquireError on failure with the
    same category scheme as acquire().
    """
    try:
        from core import youtube_download
        return youtube_download.extract_info(url, flat=False)
    except Exception as e:
        raise _classify_ytdlp_error(e) from e


# ── Link path ─────────────────────────────────────────────────────────────────

def _acquire_link(
    url: str,
    dest_video_path: str,
    dest_meta_path: str | None,
    clip_range: ClipRange | None,
    progress_cb: ProgressCb,
    cancel_token: CancelToken | None,
) -> AcquireResult:
    """Download via yt-dlp into dest_video_path (fixed filename)."""
    import yt_dlp
    from core import youtube_download

    # Inform the modal we're starting.
    _emit(progress_cb, ProgressInfo(
        phase="fetching info", percent=None,
        status_text="正在解析链接...",
    ))
    _check_cancel(cancel_token)

    # Always download the FULL stream with yt-dlp's native downloader (has real
    # progress + is the proven path). We do NOT use yt-dlp's download_ranges for
    # clipping: for YouTube it routes through the ffmpeg section downloader
    # (FFmpegFD), which reports no progress through our hook and is slow — it looks
    # frozen. Instead we clip the finished file locally below (fast stream-copy,
    # with progress).
    opts = _build_link_opts(dest_video_path, progress_cb, cancel_token)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except _CancelledByHook:
        # Cooperative cancel raised from inside the progress hook.
        _cleanup_partial(dest_video_path)
        raise AcquireError(ERR_CANCELLED, "已取消", "User cancelled")
    except Exception as e:
        _cleanup_partial(dest_video_path)
        raise _classify_ytdlp_error(e) from e

    # yt-dlp may have written `<dest>.mp4` even when we asked for `<dest>`
    # (or vice versa). Resolve.
    actual = _resolve_yt_dlp_output(dest_video_path, info)
    if actual != dest_video_path:
        try:
            shutil.move(actual, dest_video_path)
        except OSError as e:
            raise AcquireError(ERR_DISK, "无法重命名下载文件", str(e)) from e

    # Clip the downloaded file to the requested range (fast keyframe stream-copy).
    if clip_range is not None:
        cut_tmp = dest_video_path + ".cut.mp4"
        try:
            _ffmpeg_cut(dest_video_path, cut_tmp, clip_range, progress_cb, cancel_token)
        except BaseException:
            try:
                os.remove(cut_tmp)
            except OSError:
                pass
            _cleanup_partial(dest_video_path)
            raise
        os.replace(cut_tmp, dest_video_path)

    # Persist info.json next to the video for downstream tools.
    if dest_meta_path:
        _write_info_json(info, dest_meta_path)

    # When clipped, re-probe so duration/dimensions reflect the CLIP, not the
    # full video that yt-dlp's info describes.
    if clip_range is not None:
        probe = _ffprobe(dest_video_path)
        fmt = probe.get("format") or {}
        vstream = next((s for s in (probe.get("streams") or [])
                        if s.get("codec_type") == "video"), {})
        return AcquireResult(
            title=info.get("title"),
            duration_sec=_coerce_float(fmt.get("duration")),
            width=_coerce_int(vstream.get("width")),
            height=_coerce_int(vstream.get("height")),
            info_json=info if isinstance(info, dict) else {},
        )

    return AcquireResult(
        title=info.get("title"),
        duration_sec=_coerce_float(info.get("duration")),
        width=_coerce_int(info.get("width")),
        height=_coerce_int(info.get("height")),
        info_json=info if isinstance(info, dict) else {},
    )


class _CancelledByHook(Exception):
    """Internal: raised from yt-dlp progress hook on cancel. Not exported."""


def _build_link_opts(
    dest_path: str,
    progress_cb: ProgressCb,
    cancel_token: CancelToken | None,
) -> dict:
    """Compose yt-dlp opts: fixed outtmpl, JS runtime, progress hook.

    Always a FULL download — clipping is done locally after (see _acquire_link),
    not via yt-dlp's download_ranges (the FFmpegFD section downloader has no
    progress + is slow for YouTube).
    """
    from core import youtube_download

    opts = youtube_download._base_opts()  # reuses JS runtime injection etc.
    opts.update({
        # Fixed filename — no template interpolation, dest_path is literal.
        "outtmpl": dest_path,
        # Pin AAC (m4a) audio; leave the video codec UNCONSTRAINED so YouTube
        # serves its best stream at <=1080p (typically AV1, ~1/3 smaller than
        # H.264). The whole decode path is codec-agnostic: the renderer's <video>
        # preview decodes AV1 natively, the WebCodecs compositor (Demuxer accepts
        # av01 + an isConfigSupported guard), and export re-encodes to H.264
        # regardless of source. The earlier H.264 pin blamed AV1 for a preview
        # crash that was actually the Win11 26200 sandbox bug (fixed app-wide with
        # --no-sandbox), so that justification is gone. Audio stays AAC: the
        # browser's decodeAudioData silently yields no sound for Opus-in-mp4, and
        # the audio stream is only a few MB either way. Degrade progressively if
        # m4a audio isn't offered.
        "format": (
            "bestvideo[height<=1080]+bestaudio[ext=m4a]/"
            "bestvideo[height<=1080]+bestaudio/"
            "best[height<=1080]/best"
        ),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "file_access_retries": 5,
        # Re-import must actually re-download: without this yt-dlp sees the
        # existing video.mp4 and skips with "already downloaded" (no progress,
        # stale file) — the "re-import seems skipped" bug. Local/ffmpeg paths
        # already overwrite (shutil copy / ffmpeg -y).
        "overwrites": True,
    })

    # Progress hook bridge: translate yt-dlp's progress dict into ProgressInfo.
    def _hook(d: dict) -> None:
        if cancel_token is not None and cancel_token.cancelled:
            raise _CancelledByHook()
        if progress_cb is None:
            return
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes")
            pct = (100.0 * done / total) if total and done is not None else None
            _emit(progress_cb, ProgressInfo(
                phase="downloading",
                percent=pct,
                speed_bps=d.get("speed"),
                eta_sec=d.get("eta"),
                downloaded_bytes=done,
                total_bytes=total,
            ))
        elif status == "finished":
            _emit(progress_cb, ProgressInfo(
                phase="downloading",
                percent=100.0,
                status_text="正在合并音视频...",
            ))

    opts["progress_hooks"] = [_hook]
    return opts


def _resolve_yt_dlp_output(dest_template: str, info: dict) -> str:
    """yt-dlp may rewrite the output extension after merge. Find the actual
    file on disk that matches the basename."""
    if os.path.isfile(dest_template):
        return dest_template
    base, _ext = os.path.splitext(dest_template)
    # Try common merged extensions
    for ext in (".mp4", ".mkv", ".webm", ".m4a"):
        candidate = base + ext
        if os.path.isfile(candidate):
            return candidate
    # Fall back to prepare_filename-derived name
    requested = info.get("_filename") or info.get("filepath")
    if requested and os.path.isfile(requested):
        return requested
    raise AcquireError(ERR_DISK, "下载完成但找不到输出文件",
                       f"Expected near {dest_template!r}")


def _classify_ytdlp_error(e: Exception) -> AcquireError:
    """Map yt-dlp errors to categorized AcquireError for UI recovery hints."""
    import yt_dlp.utils as yu

    msg = str(e)
    low = msg.lower()
    if isinstance(e, yu.DownloadError) and "is not a valid url" in low:
        return AcquireError(ERR_URL_INVALID, "URL 无效", msg)
    if "unsupported url" in low or "no video formats found" in low:
        return AcquireError(ERR_URL_INVALID, "不支持的链接", msg)
    if "node" in low and ("not found" in low or "js" in low):
        return AcquireError(ERR_JS_RUNTIME, "缺少 Node.js JS 运行时", msg)
    if "cookies" in low or "sign in" in low or "private" in low or "members-only" in low:
        return AcquireError(ERR_COOKIES, "需要登录/cookies 才能访问", msg)
    if "timed out" in low or "timeout" in low or "connection" in low:
        return AcquireError(ERR_NETWORK, "网络超时,请重试", msg)
    if "no space" in low or "disk full" in low:
        return AcquireError(ERR_DISK, "磁盘空间不足", msg)
    return AcquireError(ERR_OTHER, "下载失败", msg)


def _cleanup_partial(dest_video_path: str) -> None:
    """Remove partial/temporary downloads after a failed/cancelled run."""
    base, _ = os.path.splitext(dest_video_path)
    candidates = [dest_video_path, base + ".mp4", base + ".part",
                  base + ".mkv", base + ".webm", base + ".f140.m4a",
                  base + ".f137.mp4"]
    for p in candidates:
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def _write_info_json(info: dict, path: str) -> None:
    """Persist yt-dlp info dict next to the video. Strips unpickleable
    internals so the file is human-readable + version-tolerant."""
    import json
    # Some keys are lambdas / non-serializable (e.g. extractor classes).
    # Use default=str so json.dump doesn't crash on stray objects.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2, default=str)


# ── Local path ────────────────────────────────────────────────────────────────

def _acquire_local(
    src_path: str,
    dest_video_path: str,
    dest_meta_path: str | None,
    clip_range: ClipRange | None,
    progress_cb: ProgressCb,
    cancel_token: CancelToken | None,
) -> AcquireResult:
    """Copy (or ffmpeg-cut) a local file into dest_video_path."""
    if not os.path.isfile(src_path):
        raise AcquireError(ERR_OTHER, "本地文件不存在", src_path)

    if clip_range is not None:
        _ffmpeg_cut(src_path, dest_video_path, clip_range,
                    progress_cb, cancel_token)
    else:
        _copy_with_progress(src_path, dest_video_path, progress_cb, cancel_token)

    _check_cancel(cancel_token)

    # Probe the result for metadata.
    _emit(progress_cb, ProgressInfo(phase="probing", percent=None,
                                    status_text="正在读取视频信息..."))
    info = _ffprobe(dest_video_path)
    if dest_meta_path:
        _write_info_json(info, dest_meta_path)

    fmt = info.get("format") or {}
    streams = info.get("streams") or []
    vstream = next((s for s in streams if s.get("codec_type") == "video"), {})
    return AcquireResult(
        title=os.path.splitext(os.path.basename(src_path))[0],
        duration_sec=_coerce_float(fmt.get("duration")),
        width=_coerce_int(vstream.get("width")),
        height=_coerce_int(vstream.get("height")),
        info_json=info,
    )


def _copy_with_progress(
    src: str, dst: str,
    progress_cb: ProgressCb,
    cancel_token: CancelToken | None,
) -> None:
    """Stream-copy src → dst with progress callbacks; respects cancel."""
    BUF = 4 * 1024 * 1024  # 4 MB
    total = os.path.getsize(src)
    copied = 0
    try:
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            while True:
                _check_cancel(cancel_token)
                chunk = fin.read(BUF)
                if not chunk:
                    break
                fout.write(chunk)
                copied += len(chunk)
                pct = (100.0 * copied / total) if total else None
                _emit(progress_cb, ProgressInfo(
                    phase="copying",
                    percent=pct,
                    downloaded_bytes=copied,
                    total_bytes=total,
                ))
    except AcquireError:
        _cleanup_partial(dst)
        raise
    except OSError as e:
        _cleanup_partial(dst)
        raise AcquireError(ERR_DISK, "拷贝失败", str(e)) from e


def _ffmpeg_cut(
    src: str, dst: str, clip_range: ClipRange,
    progress_cb: ProgressCb,
    cancel_token: CancelToken | None,
) -> None:
    """Fast stream-copy cut of src[start:dur] → dst, run with NO pipes:
    stdin→devnull, stdout→devnull, stderr→a temp file.

    Why no pipes (this is the real fix for the "stuck at ~100%" hang): a long
    stream-copy floods ffmpeg's stderr with non-monotonous-DTS warnings. Reading
    that through a pipe deadlocks in the FROZEN sidecar — the job worker thread
    cannot keep the ~64KB pipe drained, so ffmpeg blocks mid-write and the whole
    job hangs forever (reproduces only with frozen sidecar + a long cut; dev,
    short clips, and non-frozen all drain fast enough to hide it). With no pipe
    to fill, ffmpeg can never block on us. The cut is a fast stream-copy so live
    progress isn't needed — the slow download already reported it.

    `-ss` before `-i` = fast keyframe seek; `-c copy` starts at the keyframe
    at-or-before `start` (≤ a few seconds lead-in, fine for a source clip);
    `-t` (duration) avoids the -ss/-to ambiguity; `-avoid_negative_ts make_zero`
    rebases timestamps to 0."""
    import tempfile

    duration = max(0, parse_hms(clip_range.end) - parse_hms(clip_range.start))
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", clip_range.start, "-i", src, "-t", str(duration),
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        dst,
    ]
    _emit(progress_cb, ProgressInfo(phase="cutting", percent=None,
                                    status_text="正在裁剪片段..."))
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errf:
        try:
            proc = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=errf, timeout=900,
            )
        except FileNotFoundError:
            raise AcquireError(ERR_FFMPEG, "ffmpeg 未安装或不在 PATH",
                               "PATH lookup failed for ffmpeg")
        except subprocess.TimeoutExpired:
            _cleanup_partial(dst)
            raise AcquireError(ERR_FFMPEG, "ffmpeg 切段超时", "cut exceeded 900s")
        if proc.returncode != 0:
            errf.seek(0)
            tail = errf.read()[-2000:]
            _cleanup_partial(dst)
            raise AcquireError(ERR_FFMPEG, "ffmpeg 切段失败", tail.strip())


def _ffprobe(path: str) -> dict:
    """Run ffprobe to fetch container + stream metadata as a dict."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
    except FileNotFoundError:
        raise AcquireError(ERR_FFMPEG, "ffprobe 未安装或不在 PATH",
                           "PATH lookup failed for ffprobe")
    if result.returncode != 0:
        raise AcquireError(ERR_FFMPEG, "ffprobe 读取失败", result.stderr.strip())
    import json as _json
    try:
        return _json.loads(result.stdout)
    except _json.JSONDecodeError:
        return {}


# ── Helpers ───────────────────────────────────────────────────────────────────

_HMS_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6}))?$")


def parse_hms(s: str) -> int:
    """Parse HH:MM:SS or MM:SS into seconds. Raises ValueError on bad input."""
    s = s.strip()
    m = _HMS_RE.match(s)
    if not m:
        raise ValueError(f"Invalid time format: {s!r} (expected HH:MM:SS or MM:SS)")
    a, b, c, _frac = m.groups()
    if c is None:
        # MM:SS form
        return int(a) * 60 + int(b)
    return int(a) * 3600 + int(b) * 60 + int(c)


def _hms_to_us(s: str) -> int:
    """HH:MM:SS → microseconds (used to compute ffmpeg progress percent)."""
    return parse_hms(s) * 1_000_000


def _emit(cb: ProgressCb, info: ProgressInfo) -> None:
    if cb is not None:
        try:
            cb(info)
        except Exception:
            # Never let a buggy UI callback abort acquisition.
            pass


def _check_cancel(token: CancelToken | None) -> None:
    if token is not None and token.cancelled:
        raise AcquireError(ERR_CANCELLED, "已取消", "User cancelled")


def _coerce_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
