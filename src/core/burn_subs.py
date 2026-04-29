"""Subtitle burn — pure-function port of subtitle_tool's _merge_videos.

Builds the same ffmpeg command the legacy GUI tool builds (single or dual
subs, text watermark, image watermark, date overlay, encode preset/CRF
ladder), but as a callable from any context (e.g. project-workbench's
step4_burn). The legacy tool stays in place for users who prefer its UI.

Key parity points with subtitle_tool.py:
  - Sub1 sits above Sub2 (MarginV=100 vs 50, Bold=1 vs 0)
  - Image watermark forces filter_complex pipeline; pure text/no watermark
    uses the simpler -vf path
  - Watermark + date sizes scale with video height (relative to 1080)
  - bufsize/maxrate ladder by resolution
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Callable

import srt as _srt

from core.subtitle_ops import (
    escape_ffmpeg_path, hex_color_to_ass, hex_color_to_drawtext,
    process_srt_split,
)


# Encode preset → CRF mapping (mirrors subtitle_tool's table)
_CRF_MAP = {
    "ultrafast": "28", "superfast": "26", "veryfast": "25",
    "faster": "24", "fast": "23", "medium": "23",
}


def _video_resolution(video_path: str) -> tuple[int | None, int | None]:
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height", "-of", "csv=p=0",
               video_path]
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                                errors="replace", timeout=10)
        if result.returncode == 0:
            w, h = map(int, result.stdout.strip().split(","))
            return w, h
    except Exception:
        pass
    return None, None


def _bitrate_for(width: int | None, height: int | None) -> str:
    if not (width and height):
        return "100M"
    pixels = width * height
    if pixels >= 3840 * 2160:
        return "150M"
    if pixels >= 2560 * 1440:
        return "80M"
    if pixels >= 1920 * 1080:
        return "50M"
    return "30M"


# MarginV ladders by orientation. Values are in px from the bottom of frame.
# "single" used when only one sub is shown; primary/secondary are sub1/sub2
# when both are shown (sub1 floats higher).
_MARGIN_LADDER = {
    "horizontal": {"single": 50, "primary_dual": 100, "secondary_dual": 50},
    "vertical":   {"single": 80, "primary_dual": 160, "secondary_dual": 80},
}


def _resolve_orientation(orientation: str, w: int | None, h: int | None) -> str:
    """'auto' → infer from video AR; explicit values pass through."""
    if orientation in ("horizontal", "vertical"):
        return orientation
    if w and h and h > w:
        return "vertical"
    return "horizontal"


def _sub_style(fontsize: int, color_hex: str, *, bold: bool, margin_v: int) -> str:
    color_ass = hex_color_to_ass(color_hex)
    bold_v = 1 if bold else 0
    return (f"Fontname=Microsoft YaHei,Fontsize={fontsize},"
            f"PrimaryColour={color_ass},OutlineColour=&H00000000&,"
            f"BorderStyle=1,Outline=2,Shadow=0,"
            f"Bold={bold_v},Alignment=2,MarginV={margin_v}")


def _maybe_split_srt(srt_path: str, do_split: bool, max_chars: int,
                     is_chinese: bool) -> str:
    """If splitting is enabled, write a `_split.srt` next to the source and
    return its path. Otherwise return the source path unchanged. Output goes
    next to the source so users can inspect / archive the wrapped version."""
    if not do_split:
        return srt_path
    subs = process_srt_split(srt_path, max_chars, is_chinese)
    base, _ = os.path.splitext(srt_path)
    out = base + "_split.srt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(_srt.compose(subs))
    return out


def burn_subtitles(
    video_path: str,
    output_path: str,
    *,
    sub1_path: str | None = None,
    sub1_fontsize: int = 32,
    sub1_color: str = "#FFFFFF",
    sub1_split: bool = True,
    sub1_max_chars: int = 18,
    sub1_is_chinese: bool = True,
    sub2_path: str | None = None,
    sub2_fontsize: int = 28,
    sub2_color: str = "#CCCCCC",
    sub2_split: bool = True,
    sub2_max_chars: int = 42,
    sub2_is_chinese: bool = False,
    orientation: str = "auto",   # "auto" | "horizontal" | "vertical"
    wm_text: str = "",
    wm_text_color: str = "#FFFFFF",
    wm_text_fontsize: int = 28,
    wm_text_alpha: int = 80,         # 0..100
    wm_image_path: str = "",
    wm_image_scale: float = 0.1,
    wm_image_alpha: int = 80,
    show_date: bool = False,
    date_text: str = "",
    date_color: str = "#FFFFFF",
    date_fontsize: int = 24,
    date_alpha: int = 80,
    encode_preset: str = "veryfast",
    on_status: Callable[[str], None] | None = None,
) -> None:
    """Burn subtitles, watermark, and date overlay into a video.

    See module docstring for parity notes with the legacy subtitle_tool.
    Empty/falsy inputs disable the corresponding feature."""

    def status(msg: str) -> None:
        if on_status is not None:
            on_status(msg)

    show_sub1 = bool(sub1_path)
    show_sub2 = bool(sub2_path)
    # No-subs path is allowed: caller may want only watermark/date burn-in.

    # Pre-split long lines so they don't overflow the frame. Without this,
    # one-liners that exceed the frame width get cropped — the burn looks
    # broken on every long sentence. Splitting writes <srt>_split.srt
    # alongside the source.
    # Status messages are English action keys; UI layer translates via tr().
    if show_sub1 and sub1_split:
        status("split_sub1")
        sub1_path = _maybe_split_srt(sub1_path, True,
                                     sub1_max_chars, sub1_is_chinese)
    elif show_sub1:
        sub1_path = _maybe_split_srt(sub1_path, False,
                                     sub1_max_chars, sub1_is_chinese)
    if show_sub2 and sub2_split:
        status("split_sub2")
        sub2_path = _maybe_split_srt(sub2_path, True,
                                     sub2_max_chars, sub2_is_chinese)
    elif show_sub2:
        sub2_path = _maybe_split_srt(sub2_path, False,
                                     sub2_max_chars, sub2_is_chinese)

    # Geometry-dependent values (font scaling, image height, date Y position).
    width, height = _video_resolution(video_path)

    orient = _resolve_orientation(orientation, width, height)
    ladder = _MARGIN_LADDER[orient]
    status(f"orient_{orient}")

    # When both subs shown, sub1 floats higher. When only one, lower position
    # so it doesn't crop into the middle of the frame.
    if show_sub1 and show_sub2:
        margin1, margin2 = ladder["primary_dual"], ladder["secondary_dual"]
    else:
        margin1, margin2 = ladder["single"], ladder["single"]

    style1 = _sub_style(sub1_fontsize, sub1_color, bold=True, margin_v=margin1)
    style2 = _sub_style(sub2_fontsize, sub2_color, bold=False, margin_v=margin2)

    sub1_ff = escape_ffmpeg_path(sub1_path) if show_sub1 else None
    sub2_ff = escape_ffmpeg_path(sub2_path) if show_sub2 else None

    # Watermark sizing: scale fontsize with video height (1080-relative)
    h_scale = (height / 1080) if height else 1.0
    wm_fs = max(1, int(wm_text_fontsize * h_scale))
    date_fs = max(1, int(date_fontsize * h_scale))

    txt_alpha = round(wm_text_alpha / 100, 2)
    img_alpha = round(wm_image_alpha / 100, 2)
    d_alpha = round(date_alpha / 100, 2)

    use_img_wm = bool(wm_image_path) and os.path.exists(wm_image_path)
    use_txt_wm = bool(wm_text.strip())

    # Date Y: directly under whichever watermark sits at the top-right.
    if use_img_wm:
        try:
            from PIL import Image as _PILImg
            with _PILImg.open(wm_image_path) as _im:
                img_w_orig, img_h_orig = _im.size
            img_w_px = int((width or 1920) * wm_image_scale)
            img_h_px = int(img_w_px * img_h_orig / img_w_orig)
        except Exception:
            img_w_px = int((width or 1920) * wm_image_scale)
            img_h_px = img_w_px
        date_y = 30 + img_h_px + 8
    else:
        img_w_px = 0
        date_y = 30 + wm_fs + 8

    txt_color_ff = hex_color_to_drawtext(wm_text_color)
    date_color_ff = hex_color_to_drawtext(date_color)

    def _txt_drawtext(y: int | str = 30) -> str:
        return (f"drawtext=text='{wm_text}':"
                f"fontcolor={txt_color_ff}@{txt_alpha}:"
                f"fontsize={wm_fs}:font='Microsoft YaHei':"
                f"x=w-tw-30:y={y}:borderw=2:bordercolor=black")

    def _date_drawtext(y: int) -> str:
        return (f"drawtext=text='{date_text}':"
                f"fontcolor={date_color_ff}@{d_alpha}:"
                f"fontsize={date_fs}:font='Microsoft YaHei':"
                f"x=w-tw-30:y={y}:borderw=2:bordercolor=black")

    # Image watermark needs filter_complex (movie source); other paths use -vf.
    use_filter_complex = use_img_wm
    filter_complex = None
    vf = None

    if use_filter_complex:
        fc_parts: list[str] = []
        cur = "[0:v]"
        # Apply sub2 first (lower), then sub1 (upper) so sub1 ends up on top.
        if show_sub2 and sub2_ff:
            fc_parts.append(f"{cur}subtitles=filename='{sub2_ff}':"
                            f"force_style='{style2}'[s2]")
            cur = "[s2]"
        if show_sub1 and sub1_ff:
            fc_parts.append(f"{cur}subtitles=filename='{sub1_ff}':"
                            f"force_style='{style1}'[s1]")
            cur = "[s1]"
        img_path_ff = wm_image_path.replace("\\", "/").replace(":", "\\:")
        fc_parts.append(
            f"movie='{img_path_ff}',scale={img_w_px}:-1,"
            f"format=rgba,colorchannelmixer=aa={img_alpha}[wm]")
        overlay_chain = f"{cur}[wm]overlay=W-w-30:30"
        if show_date and date_text:
            overlay_chain += "," + _date_drawtext(date_y)
        overlay_chain += "[out]"
        fc_parts.append(overlay_chain)
        filter_complex = ";".join(fc_parts)
    else:
        vf_filters: list[str] = []
        if show_sub2 and sub2_ff:
            vf_filters.append(f"subtitles=filename='{sub2_ff}':"
                              f"force_style='{style2}'")
        if show_sub1 and sub1_ff:
            vf_filters.append(f"subtitles=filename='{sub1_ff}':"
                              f"force_style='{style1}'")
        if use_txt_wm:
            vf_filters.append(_txt_drawtext(30))
        if show_date and date_text:
            vf_filters.append(_date_drawtext(date_y))
        vf = ",".join(vf_filters)

    bufsize = maxrate = _bitrate_for(width, height)
    crf = _CRF_MAP.get(encode_preset, "25")

    cmd = ["ffmpeg", "-y", "-i", os.path.abspath(video_path)]
    if use_filter_complex and filter_complex:
        cmd += ["-filter_complex", filter_complex,
                "-map", "[out]", "-map", "0:a?"]
    elif vf:
        cmd += ["-vf", vf]
    cmd += [
        "-c:v", "libx264", "-preset", encode_preset, "-crf", crf,
        "-threads", "0", "-bufsize", bufsize, "-maxrate", maxrate,
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", os.path.abspath(output_path),
    ]

    status("encoding")
    # Stream stderr so we can emit progress percentages. ffmpeg writes
    # `Duration: HH:MM:SS.xx` once, then `time=HH:MM:SS.xx` per progress tick.
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace")
    duration: float | None = None
    tail: list[str] = []
    last_pct = -1
    assert proc.stderr is not None
    for line in proc.stderr:
        tail.append(line)
        if len(tail) > 40:
            tail.pop(0)
        if duration is None:
            m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", line)
            if m:
                duration = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                            + float(m.group(3)))
        if duration and "time=" in line:
            m = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
            if m:
                cur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                       + float(m.group(3)))
                pct = max(0, min(100, int(cur / duration * 100)))
                if pct != last_pct:
                    last_pct = pct
                    status(f"encoding {pct}%")
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg burn failed ({proc.returncode}): "
            f"{''.join(tail)[-800:]}")
