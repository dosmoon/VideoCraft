"""Centralized YouTube download facade — single source of truth for yt-dlp.

UI tools (legacy yt_dlp_tool, project_workbench manifest step1, future
batch tools) all funnel through here so cross-cutting concerns — JS
runtime injection, opt defaults, network presets — live in one place.

Two public functions:
  - extract_info(url, *, flat=False, force_ipv4=False) -> dict
        Fetch metadata for a URL or playlist.
  - download_video(url, out_template, *, ...) -> dict
        Run an actual download. Returns the info dict from extract_info.

Both apply js_runtimes/remote_components when Node is detected (via
core.env), so newer YouTube formats (m3u8/HLS) are reachable from every
caller without each tool wiring it up itself.
"""

from __future__ import annotations

from typing import Callable, Optional

import yt_dlp


# ── Network presets ──────────────────────────────────────────────────────────
# Default (network_preset=None) means: don't override yt-dlp's own settings.
# yt-dlp uses single-stream TCP without http_chunk_size, which is the fastest
# path on stable broadband (Happy Eyeballs picks IPv4/IPv6 automatically).
#
# The previous "fast / medium / slow" trio applied http_chunk_size + buffersize
# + concurrent_fragment_downloads as if they were throughput knobs, but they
# aren't: http_chunk_size is documented as a workaround for per-connection
# server throttling (irrelevant for YouTube), and forcing it fragments a
# continuous TCP stream into N separate Range requests — measurably slower
# on most networks. Removed in favor of yt-dlp defaults.
#
# Only the "throttled" preset survives: smaller chunks for hotel WiFi / mobile
# tethering / satellite where connections drop frequently and resuming from a
# small chunk boundary beats re-downloading megabytes.

NETWORK_PRESETS: dict[str, dict] = {
    "throttled": {
        "http_chunk_size": 5242880,    # 5 MB — small enough to resume cheaply
        "buffersize":      4194304,    # 4 MB
        "concurrent_fragment_downloads": 3,
    },
}


# ── Internal: shared opt builder ─────────────────────────────────────────────

def _apply_jsruntime_opts(opts: dict) -> None:
    """Inject js_runtimes + remote_components when a Node runtime is reachable.

    Without these YouTube's challenge solver fails and yt-dlp drops
    m3u8/HLS streams (~6 fewer formats per video). Silent no-op when
    Node is missing — yt-dlp falls back to the limited android-vr API."""
    from core import env
    res = env.detect_one("node")
    if res.available and res.path:
        opts["js_runtimes"] = {"node": {"path": res.path}}
        opts["remote_components"] = ["ejs:github"]


def jsruntime_status_line() -> str:
    """One-line status string for UI logs explaining JS runtime state."""
    from core import env
    res = env.detect_one("node")
    if res.available:
        return (f"JS runtime: Node.js {res.version or '?'} "
                f"({res.source or '?'}) — full YouTube format support")
    return ("JS runtime: NOT DETECTED — high-quality HLS formats may be missing. "
            "Open Settings → Environment → Setup Node.js to fix.")


def _base_opts(*, force_ipv4: bool = False) -> dict:
    """Common ydl_opts shared by extract + download paths.

    Aligned with the historically faster manifest path: silent stdout
    (yt-dlp's progress bar through Hub stdout was a measured bottleneck),
    moderate retries, no extra postprocessor passes."""
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 5,
        "fragment_retries": 5,
        "skip_unavailable_fragments": True,
        "socket_timeout": 30,
        "ignoreerrors": False,
    }
    if force_ipv4:
        opts["source_address"] = "0.0.0.0"
    _apply_jsruntime_opts(opts)
    return opts


# ── Public API ───────────────────────────────────────────────────────────────

def extract_info(
    url: str,
    *,
    flat: bool = False,
    force_ipv4: bool = False,
) -> dict:
    """Fetch metadata. Raises whatever yt-dlp raises (DownloadError, etc.)."""
    opts = _base_opts(force_ipv4=force_ipv4)
    opts["extract_flat"] = flat
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def download_video(
    url: str,
    out_template: str,
    *,
    format: str = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    merge_output_format: str = "mp4",
    network_preset: Optional[str] = None,
    progress_hook: Optional[Callable[[dict], None]] = None,
    force_ipv4: bool = False,
    playlist_index: Optional[int] = None,
    file_access_retries: int = 5,
) -> tuple[dict, str]:
    """Run a download. Returns (info_dict, resolved_filepath).

    The filepath is computed by yt-dlp's prepare_filename so caller doesn't
    need to redo template interpolation. For merged output, the actual file
    on disk may have a different extension than info['ext'] — caller should
    swap to the merge_output_format extension if needed.

    Args:
        url: video or playlist URL
        out_template: yt-dlp outtmpl pattern (e.g. "%(title)s.%(ext)s")
        format: yt-dlp format selector
        merge_output_format: container (default mp4)
        network_preset: one of "fast" / "medium" / "slow" / None (yt-dlp default)
        progress_hook: callback receiving yt-dlp's progress dict
        force_ipv4: if True, bind to 0.0.0.0 (IPv4-only)
        playlist_index: when set, restrict to this 1-based playlist item
        file_access_retries: yt-dlp's `file_access_retries` for filesystem locks
    """
    opts = _base_opts(force_ipv4=force_ipv4)
    opts.update({
        "format": format,
        "outtmpl": out_template,
        "merge_output_format": merge_output_format,
        "file_access_retries": file_access_retries,
    })
    if network_preset:
        preset = NETWORK_PRESETS.get(network_preset.lower())
        if preset:
            opts.update(preset)
    if progress_hook is not None:
        opts["progress_hooks"] = [progress_hook]
    if playlist_index is not None:
        opts["noplaylist"] = False
        opts["playlist_items"] = str(playlist_index)
    else:
        opts["noplaylist"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        fpath = ydl.prepare_filename(info)
    return info, fpath


def summarize_formats(info: dict) -> Optional[str]:
    """Short fingerprint of a video's formats for UI logs.

    Returns None when format info is unavailable (e.g. extract_flat fallback)."""
    fmts = info.get("formats") or []
    if not fmts:
        return None
    has_hls = any((f.get("protocol") or "").startswith("m3u8") for f in fmts)
    heights = [f.get("height") for f in fmts if f.get("height")]
    max_h = max(heights) if heights else 0
    best = next((f for f in fmts if f.get("height") == max_h and f.get("vcodec")), None)
    codec = (best.get("vcodec") if best else "") or ""
    codec_short = codec.split(".")[0] if codec else "?"
    hls_mark = "✓" if has_hls else "✗"
    res_str = f"{max_h}p" if max_h else "audio-only"
    return f"  → {len(fmts)} formats, max {res_str} ({codec_short}), HLS {hls_mark}"
