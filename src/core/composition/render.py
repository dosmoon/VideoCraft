"""ffmpeg + libass + drawtext render pipeline.

One call to ffmpeg per output clip. All overlays — subtitle tracks,
watermark, hook/outro text, plus any user-provided OverlaySpec entries —
flow through a single dispatch table:

    [0:v] crop → scale+pad → <overlay 1> → <overlay 2> → ... → [vout]

The named style sections (style.subtitle / style.watermark /
style.hook_outro + req.hook_text / req.outro_text) are converted to
internal _OverlayJob records by _named_overlay_jobs(); future news_desk
overlay kinds (chapter_card / lower_third / ...) drop in as additional
registered renderers without touching the main loop.

Per-word karaoke, smart-crop face_center, and audio mixing are not in
this layer yet.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Optional

import srt as _srt

from core.subtitle_ops import (
    escape_ffmpeg_path, hex_color_to_ass, read_srt, process_srt_split,
)

from .style import CompositionStyle, SubtitleStyle, SubtitleLineStyle, \
    WatermarkStyle, HookOutroStyle, compute_subtitle_max_chars
from .overlays import OverlaySpec
from .fonts import (
    hook_outro_font_path, y_expr_for_position, ass_alignment_for_position,
)
from .text_layout import wrap_hook_outro, wrap_overlay_text


ProgressCallback = Callable[[str, int], None]   # (stage, percent 0-100)


# ── Public dataclasses ──────────────────────────────────────────────────────

@dataclass
class CompositionRequest:
    """All inputs needed for one render_composition() call.

    Built by the consumer (e.g. AI Clip workbench, subtitle burn) from a
    hotclip entry / SRT pair + the user's current CompositionStyle + the
    project's source video.
    """
    source_video: str
    start_sec: float
    end_sec: float
    output_path: str
    style: CompositionStyle
    source_srt: Optional[str] = None    # primary subtitle (sub1); None = no burn
    source_srt_secondary: Optional[str] = None    # secondary subtitle (sub2); None = no burn
    hook_text: str = ""                 # rendered as top overlay during hook window
    outro_text: str = ""                # rendered as bottom overlay during outro window
    crop_rect: Optional[dict] = None    # {x,y,w,h} normalized; None = center crop
    overlays: list = field(default_factory=list)    # list[OverlaySpec] — future news_desk overlays


@dataclass
class CompositionResult:
    output_path: str
    duration_sec: float
    width: int
    height: int


# ── ffmpeg helpers ──────────────────────────────────────────────────────────

def _probe_resolution(video_path: str) -> tuple[int, int]:
    """ffprobe → (width, height); (0, 0) on any failure."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             video_path],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
        if out.returncode != 0:
            return (0, 0)
        w, h = out.stdout.strip().split(",")
        return (int(w), int(h))
    except Exception:
        return (0, 0)


def _center_crop_rect(video_w: int, video_h: int,
                       aspect_ratio: tuple[int, int]) -> dict:
    """Largest centered crop at `aspect_ratio` that fits the source.
    Returns normalized {x, y, w, h} in [0, 1]."""
    if video_w <= 0 or video_h <= 0:
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    aw, ah = aspect_ratio
    target_ar = max(0.001, aw / ah)
    cur_ar = video_w / video_h
    if cur_ar > target_ar:
        new_w = video_h * target_ar
        x = (video_w - new_w) / 2.0
        return {"x": x / video_w, "y": 0.0,
                "w": new_w / video_w, "h": 1.0}
    new_h = video_w / target_ar
    y = (video_h - new_h) / 2.0
    return {"x": 0.0, "y": y / video_h,
            "w": 1.0, "h": new_h / video_h}


def _crop_rect_to_pixels(rect: dict, video_w: int, video_h: int
                          ) -> tuple[int, int, int, int]:
    """Normalized rect → (cw, ch, cx, cy) in pixels, even dimensions for x264."""
    cw = max(2, int(round(rect["w"] * video_w)))
    ch = max(2, int(round(rect["h"] * video_h)))
    cx = max(0, int(round(rect["x"] * video_w)))
    cy = max(0, int(round(rect["y"] * video_h)))
    cw -= cw % 2
    ch -= ch % 2
    return (cw, ch, cx, cy)


def _target_dims_for_aspect(aspect_ratio: tuple[int, int],
                              short_edge: int = 1080) -> tuple[int, int]:
    """Pick output (w, h) at a 1080-class short edge. Even dims for x264."""
    aw, ah = aspect_ratio
    if aw < ah:
        w, h = short_edge, round(short_edge * ah / aw)
    else:
        h, w = short_edge, round(short_edge * aw / ah)
    return ((w + 1) // 2 * 2, (h + 1) // 2 * 2)


# ── SRT slicing (per-clip rebased to t=0) ──────────────────────────────────

def _load_cues(srt_path: str) -> list[_srt.Subtitle]:
    return list(_srt.parse(read_srt(srt_path)))


def _slice_srt_for_clip(cues: list[_srt.Subtitle],
                         start_sec: float, end_sec: float,
                         out_path: str) -> str:
    """Write a sub-SRT for [start_sec, end_sec] with timestamps rebased to 0."""
    sliced: list[_srt.Subtitle] = []
    for cue in cues:
        cs = cue.start.total_seconds()
        ce = cue.end.total_seconds()
        if ce <= start_sec or cs >= end_sec:
            continue
        new_start = max(0.0, cs - start_sec)
        new_end = min(end_sec - start_sec, ce - start_sec)
        if new_end <= new_start:
            continue
        sliced.append(_srt.Subtitle(
            index=len(sliced) + 1,
            start=timedelta(seconds=new_start),
            end=timedelta(seconds=new_end),
            content=cue.content,
        ))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_srt.compose(sliced) if sliced else "")
    return out_path


# ── drawtext / subtitle filter strings ─────────────────────────────────────

def _escape_drawtext(text: str) -> str:
    """Escape user text for ffmpeg drawtext text='...'."""
    if not text:
        return ""
    # Note on '%': bare '%' is a valid literal for drawtext (only '%{...}'
    # is special). Escaping it as '\%' makes ffmpeg silently drop the entire
    # drawtext filter — hooks like "失业率4.3%" hit this exact path.
    # We rely on expansion=none below to keep '%' literal.
    return (text.replace("\\", "\\\\")
                .replace(":", "\\:")
                .replace("'", "’"))    # straight → curly to dodge quoting hell


def _drawtext_filter(text: str, *, role: str, ho: HookOutroStyle,
                      duration: float, aspect_ratio: tuple[int, int],
                      tmp_files: list[str], short_edge: int = 1080) -> str:
    """Build a drawtext snippet for hook (first hook_duration_sec) or outro
    (last outro_duration_sec). role ∈ {'hook', 'outro'}.

    Multi-line behaviour: text is wrapped to fit the target frame width
    via core.composition.text_layout.wrap_hook_outro (same call as the
    WebView preview), then written to a temp file consumed by drawtext's
    `textfile=` parameter. `text=` doesn't reliably accept newlines, so
    going through a file is the only escape-safe path. The temp file is
    appended to tmp_files for the caller to clean up after ffmpeg returns.

    `short_edge` lets passthrough renders pass the actual source short
    edge so wrap budgets scale with the real frame width.
    """
    if not text:
        return ""

    font_path = hook_outro_font_path(ho.font)
    lines = wrap_hook_outro(text, aspect_ratio, font_path, ho.size,
                              short_edge=short_edge)
    if not lines:
        return ""
    wrapped = "\n".join(lines)

    tmp_path = os.path.join(
        tempfile.gettempdir(),
        f"composition-{role}-{os.getpid()}-{id(text)}.txt",
    )
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(wrapped)
    except OSError:
        return ""
    tmp_files.append(tmp_path)

    if role == "hook":
        position = ho.hook_position
        enable = f"between(t,0,{ho.hook_duration_sec})"
    else:
        position = ho.outro_position
        start = max(0.0, duration - ho.outro_duration_sec)
        enable = f"between(t,{start},{duration})"

    fontfile_ff = font_path.replace(":", "\\:")
    textfile_ff = tmp_path.replace("\\", "/").replace(":", "\\:")
    y_expr = y_expr_for_position(position)
    parts = [
        f"drawtext=textfile='{textfile_ff}'",
        f"fontfile='{fontfile_ff}'",
        f"fontcolor={ho.color}",
        f"fontsize={ho.size}",
        "x=(w-text_w)/2",
        f"y={y_expr}",
    ]
    if ho.stroke_width > 0:
        parts.append(f"borderw={int(ho.stroke_width)}")
        parts.append(f"bordercolor={ho.stroke_color}")
    if ho.bg_opacity > 0:
        parts.append("box=1")
        opacity = max(0.0, min(1.0, ho.bg_opacity / 100.0))
        parts.append(f"boxcolor={ho.bg_color}@{opacity:.2f}")
        parts.append(f"boxborderw={int(ho.box_padding)}")
    parts.append(f"enable='{enable}'")
    return ":".join(parts)


def _build_subtitle_force_style(line: SubtitleLineStyle,
                                  subtitle: SubtitleStyle,
                                  *, margin_v: int) -> str:
    """ASS force_style string for one subtitle track."""
    font_name = "Microsoft YaHei" if line.is_chinese else "Arial"
    return (f"Fontname={font_name},"
            f"Fontsize={line.fontsize},"
            f"PrimaryColour={hex_color_to_ass(line.color)},"
            f"OutlineColour={hex_color_to_ass(subtitle.stroke_color)},"
            f"BorderStyle=1,"
            f"Outline={max(0, int(subtitle.stroke_width))},"
            f"Shadow=0,"
            f"Bold={1 if line.bold else 0},"
            f"Alignment={ass_alignment_for_position(subtitle.position)},"
            f"MarginV={margin_v}")


def _track_margins(subtitle: SubtitleStyle) -> tuple[int, int]:
    """Vertical MarginV for (sub1, sub2) so the two tracks stack without
    overlapping. Output-pixel space at 1080 short edge.

    sub1 is the primary (typically source-language) track and sits visually
    closer to the frame center than sub2 (translation). For position=top,
    sub1 anchors near the top and sub2 drops below; for bottom, sub1 sits
    above and sub2 anchors near the edge. position=middle uses Alignment=5
    where MarginV is ignored, so stacking is not supported there — the two
    tracks will overlap; callers should use top/bottom for bilingual work.

    The 4.0× fontsize gap is empirical: libass with no PlayResY uses video
    height as its coordinate space, so script-pixel MarginV ≈ output px,
    and one rendered line is ~fontsize×4.0 px tall at 1080 short edge.
    """
    base = 60
    pos = subtitle.position
    if pos == "top":
        return (base, base + int(subtitle.sub1.fontsize * 4.0))
    if pos == "bottom":
        return (base + int(subtitle.sub2.fontsize * 4.0), base)
    return (base, base)


def _hex_to_drawtext_rgba(hex_color: str, alpha: float) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    a = max(0.0, min(1.0, alpha))
    if len(h) == 6:
        return f"#{h.upper()}@{a:.2f}"
    return f"white@{a:.2f}"


def _build_text_watermark_drawtext(watermark: WatermarkStyle,
                                      target_w: int,
                                      tmp_files: list[str]) -> str:
    """Text-mode watermark via textfile so long strings wrap consistently
    with the preview. Wraps at 40% of target width — watermarks should be
    small / corner-anchored, not banner-width."""
    if not watermark.enabled or watermark.type != "text":
        return ""
    raw = (watermark.text or "").strip()
    if not raw:
        return ""

    font_path = "C:/Windows/Fonts/msyh.ttc"
    lines = wrap_overlay_text(
        raw, max(40.0, target_w * 0.40),
        font_path, watermark.text_fontsize)
    if not lines:
        return ""
    wrapped = "\n".join(lines)

    tmp_path = os.path.join(
        tempfile.gettempdir(),
        f"composition-watermark-{os.getpid()}-{id(watermark)}.txt",
    )
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(wrapped)
    except OSError:
        return ""
    tmp_files.append(tmp_path)

    margin = max(20, int(target_w * 0.025))
    pos = watermark.position or "top-right"
    x = f"w-text_w-{margin}" if pos.endswith("right") else f"{margin}"
    y = f"h-text_h-{margin}" if pos.startswith("bottom") else f"{margin}"
    opacity = max(0.0, min(1.0, (watermark.text_opacity or 70) / 100.0))
    textfile_ff = tmp_path.replace("\\", "/").replace(":", "\\:")
    return (f"drawtext=textfile='{textfile_ff}':"
            f"fontfile='{font_path.replace(':', chr(92)+':')}':"
            f"fontcolor={_hex_to_drawtext_rgba(watermark.text_color, opacity)}:"
            f"fontsize={watermark.text_fontsize}:"
            f"x={x}:y={y}:"
            f"borderw=2:bordercolor=black@{opacity*0.5:.2f}")


def _build_image_watermark_chain(watermark: WatermarkStyle,
                                    target_w: int,
                                    prev_label: str,
                                    src_label: str,
                                    out_label: str,
                                    ) -> tuple[list[str], str]:
    """Image watermark needs a `movie` source + overlay pair (drawtext can't
    render external images). Returns (extra_nodes, new_chain_head)."""
    if not watermark.enabled or watermark.type != "image":
        return [], prev_label
    img_path = (watermark.image_path or "").strip()
    if not img_path or not os.path.exists(img_path):
        return [], prev_label
    img_ff = escape_ffmpeg_path(img_path)
    wm_w = max(1, int(target_w * max(0.01, watermark.image_scale or 0.15)))
    opacity = max(0.0, min(1.0, (watermark.image_opacity or 100) / 100.0))
    pos = watermark.position or "top-right"
    margin = max(20, int(target_w * 0.025))
    # overlay W/H = main video dims, w/h = overlay dims
    x = f"W-w-{margin}" if pos.endswith("right") else f"{margin}"
    y = f"H-h-{margin}" if pos.startswith("bottom") else f"{margin}"
    return ([
        f"movie='{img_ff}',scale={wm_w}:-1,"
        f"format=rgba,colorchannelmixer=aa={opacity:.3f}{src_label}",
        f"{prev_label}{src_label}overlay={x}:{y}{out_label}",
    ], out_label)


# ── Overlay dispatch — converts named style sections + req.overlays into
#    a unified job list, then runs registered renderers to extend the
#    filter_complex chain. New overlay kinds plug in via register_renderer.

@dataclass
class _RenderCtx:
    target_w: int
    target_h: int
    duration: float
    aspect: tuple[int, int]
    short_edge: int
    style: CompositionStyle
    tmp_files: list[str]
    _label_seq: int = 0

    def next_label(self) -> str:
        self._label_seq += 1
        return f"[ovl{self._label_seq}]"


@dataclass
class _OverlayJob:
    """Internal render job — discriminated by `kind`, dispatched to a
    registered renderer. `data` carries kind-specific inputs (already
    resolved against style + request)."""
    kind: str
    z_order: int = 100
    data: dict = field(default_factory=dict)


# Renderer signature: (job, prev_label, ctx) → (filter_complex_parts, new_label)
_OverlayRenderer = Callable[[_OverlayJob, str, _RenderCtx],
                              tuple[list[str], str]]

_OVERLAY_RENDERERS: dict[str, _OverlayRenderer] = {}


def register_overlay_renderer(kind: str, fn: _OverlayRenderer) -> None:
    """Register a renderer for an overlay kind. Future news_desk kinds
    (chapter_card, lower_third, ...) call this from their own module."""
    _OVERLAY_RENDERERS[kind] = fn


# ── Built-in renderers (named overlays) ─────────────────────────────────────

def _renderer_subtitle_libass(job: _OverlayJob, prev_label: str,
                                ctx: _RenderCtx) -> tuple[list[str], str]:
    srt_path = job.data.get("srt_path")
    force_style = job.data.get("force_style")
    if not (srt_path and os.path.exists(srt_path)
            and os.path.getsize(srt_path) > 0):
        return [], prev_label
    srt_ff = escape_ffmpeg_path(srt_path)
    out_label = ctx.next_label()
    return ([f"{prev_label}subtitles=filename='{srt_ff}':"
             f"force_style='{force_style}'{out_label}"],
            out_label)


def _renderer_image_watermark(job: _OverlayJob, prev_label: str,
                                ctx: _RenderCtx) -> tuple[list[str], str]:
    wm: WatermarkStyle = job.data["watermark"]
    src_label = ctx.next_label()
    out_label = ctx.next_label()
    return _build_image_watermark_chain(
        wm, ctx.target_w, prev_label, src_label, out_label)


def _renderer_text_watermark(job: _OverlayJob, prev_label: str,
                               ctx: _RenderCtx) -> tuple[list[str], str]:
    wm: WatermarkStyle = job.data["watermark"]
    snippet = _build_text_watermark_drawtext(wm, ctx.target_w, ctx.tmp_files)
    if not snippet:
        return [], prev_label
    out_label = ctx.next_label()
    return [f"{prev_label}{snippet}{out_label}"], out_label


def _renderer_hook_text(job: _OverlayJob, prev_label: str,
                          ctx: _RenderCtx) -> tuple[list[str], str]:
    snippet = _drawtext_filter(
        job.data["text"], role="hook", ho=ctx.style.hook_outro,
        duration=ctx.duration, aspect_ratio=ctx.aspect,
        tmp_files=ctx.tmp_files, short_edge=ctx.short_edge)
    if not snippet:
        return [], prev_label
    out_label = ctx.next_label()
    return [f"{prev_label}{snippet}{out_label}"], out_label


def _renderer_outro_text(job: _OverlayJob, prev_label: str,
                           ctx: _RenderCtx) -> tuple[list[str], str]:
    snippet = _drawtext_filter(
        job.data["text"], role="outro", ho=ctx.style.hook_outro,
        duration=ctx.duration, aspect_ratio=ctx.aspect,
        tmp_files=ctx.tmp_files, short_edge=ctx.short_edge)
    if not snippet:
        return [], prev_label
    out_label = ctx.next_label()
    return [f"{prev_label}{snippet}{out_label}"], out_label


register_overlay_renderer("subtitle_libass", _renderer_subtitle_libass)
register_overlay_renderer("image_watermark", _renderer_image_watermark)
register_overlay_renderer("text_watermark",  _renderer_text_watermark)
register_overlay_renderer("hook_text",       _renderer_hook_text)
register_overlay_renderer("outro_text",      _renderer_outro_text)


def _named_overlay_jobs(req: CompositionRequest,
                          sub1_srt: Optional[str],
                          sub2_srt: Optional[str]) -> list[_OverlayJob]:
    """Convert the named style sections + req.hook_text/outro_text into
    _OverlayJob records. z_order chosen so the visible stacking matches
    the legacy hand-coded order: subtitles → image_wm → text_wm → hook/outro.
    """
    style = req.style
    jobs: list[_OverlayJob] = []

    # Subtitle tracks.
    margin_v1, margin_v2 = _track_margins(style.subtitle)
    if style.subtitle.sub1.enabled and sub1_srt:
        jobs.append(_OverlayJob(kind="subtitle_libass", z_order=10, data={
            "srt_path": sub1_srt,
            "force_style": _build_subtitle_force_style(
                style.subtitle.sub1, style.subtitle, margin_v=margin_v1),
        }))
    if style.subtitle.sub2.enabled and sub2_srt:
        jobs.append(_OverlayJob(kind="subtitle_libass", z_order=11, data={
            "srt_path": sub2_srt,
            "force_style": _build_subtitle_force_style(
                style.subtitle.sub2, style.subtitle, margin_v=margin_v2),
        }))

    # Watermark — image or text (mutually exclusive).
    if style.watermark.enabled:
        if style.watermark.type == "image":
            jobs.append(_OverlayJob(kind="image_watermark", z_order=20,
                                      data={"watermark": style.watermark}))
        else:
            jobs.append(_OverlayJob(kind="text_watermark", z_order=21,
                                      data={"watermark": style.watermark}))

    # Hook + Outro card.
    if req.hook_text:
        jobs.append(_OverlayJob(kind="hook_text", z_order=30,
                                  data={"text": req.hook_text}))
    if req.outro_text:
        jobs.append(_OverlayJob(kind="outro_text", z_order=31,
                                  data={"text": req.outro_text}))

    # User-supplied overlays (future news_desk kinds). z_order from spec,
    # defaulting to 100 so they stack above the named overlays unless the
    # caller explicitly orders them in between.
    for spec in req.overlays:
        if not isinstance(spec, OverlaySpec):
            continue
        jobs.append(_OverlayJob(
            kind=spec.kind,
            z_order=spec.z_order,
            data={"spec": spec},
        ))

    jobs.sort(key=lambda j: j.z_order)
    return jobs


# ── Public entry point ─────────────────────────────────────────────────────

def render_composition(
    req: CompositionRequest,
    on_progress: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
    *,
    crf: int = 23,
) -> CompositionResult:
    """Render one composition: trim → crop → scale → burn subtitle →
    watermark → hook/outro. Single ffmpeg invocation via filter_complex.

    Raises RuntimeError on ffmpeg failure. Raises InterruptedError when
    cancel_check returns True mid-render.
    """
    style = req.style

    src_w, src_h = _probe_resolution(req.source_video)
    if src_w == 0 or src_h == 0:
        raise RuntimeError(f"Cannot probe video resolution: {req.source_video}")

    # Resolve effective output geometry. In passthrough mode the canvas
    # matches the source verbatim (no crop, no scale); in reframe mode
    # the canvas is derived from style.output.aspect + short_edge and the
    # source is center-cropped (or per-request crop_rect) to fit.
    if style.output.mode == "passthrough":
        target_w, target_h = src_w, src_h
        effective_aspect = (src_w, src_h)
        effective_short_edge = min(src_w, src_h)
        rect = None
        cw = ch = cx = cy = 0    # unused
    else:
        target_w, target_h = _target_dims_for_aspect(
            style.output.aspect_ratio(),
            short_edge=style.output.short_edge,
        )
        effective_aspect = style.output.aspect_ratio()
        effective_short_edge = style.output.short_edge
        rect = req.crop_rect or _center_crop_rect(
            src_w, src_h, aspect_ratio=style.output.aspect_ratio())
        cw, ch, cx, cy = _crop_rect_to_pixels(rect, src_w, src_h)

    duration = max(0.0, req.end_sec - req.start_sec)
    if duration <= 0:
        raise ValueError(
            f"Composition has non-positive duration: "
            f"{req.start_sec}..{req.end_sec}")

    os.makedirs(os.path.dirname(os.path.abspath(req.output_path)) or ".",
                exist_ok=True)

    # ── Slice each track's SRT to this window (rebased to 0) ──────────────
    effective_aspect_str = f"{effective_aspect[0]}:{effective_aspect[1]}"

    def _prepare_track_srt(src_path: str | None, line: SubtitleLineStyle,
                            tag: str) -> str | None:
        if not (src_path and os.path.exists(src_path) and line.enabled):
            return None
        try:
            cues = _load_cues(src_path)
            if line.auto_max_chars:
                max_chars = compute_subtitle_max_chars(
                    effective_aspect_str, line.fontsize, line.is_chinese,
                    short_edge=effective_short_edge)
            else:
                max_chars = max(8, line.manual_max_chars)
            out = os.path.join(
                tempfile.gettempdir(),
                f"composition-{tag}-{int(req.start_sec*1000)}-{os.getpid()}.srt"
            )
            _slice_srt_for_clip(cues, req.start_sec, req.end_sec, out)
            try:
                split_subs = process_srt_split(
                    out, max_chars, is_chinese=line.is_chinese)
                with open(out, "w", encoding="utf-8") as f:
                    f.write(_srt.compose(split_subs))
            except Exception:
                pass    # leave un-split on failure; better than no subs
            return out
        except Exception:
            return None

    tmp_srt_path = _prepare_track_srt(req.source_srt, style.subtitle.sub1, "sub1")
    tmp_srt2_path = _prepare_track_srt(
        req.source_srt_secondary, style.subtitle.sub2, "sub2")

    # ── Build filter_complex via overlay dispatch ─────────────────────────
    parts: list[str] = []
    if style.output.mode == "passthrough":
        # Source frame is the output frame — just normalize SAR.
        parts.append("[0:v]setsar=1[v0]")
    else:
        parts.append(f"[0:v]crop={cw}:{ch}:{cx}:{cy},"
                     f"scale={target_w}:{target_h}:"
                     f"force_original_aspect_ratio=decrease,"
                     f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
                     f"setsar=1[v0]")
    cur = "[v0]"

    tmp_text_files: list[str] = []
    ctx = _RenderCtx(
        target_w=target_w, target_h=target_h,
        duration=duration, aspect=effective_aspect,
        short_edge=effective_short_edge,
        style=style, tmp_files=tmp_text_files,
    )

    jobs = _named_overlay_jobs(req, tmp_srt_path, tmp_srt2_path)
    for job in jobs:
        renderer = _OVERLAY_RENDERERS.get(job.kind)
        if renderer is None:
            # Unknown kind (e.g. future news_desk overlay with no renderer
            # registered yet) — skip silently rather than fail the render.
            continue
        extra, cur = renderer(job, cur, ctx)
        parts.extend(extra)

    parts.append(f"{cur}null[vout]")
    filter_complex = ";".join(parts)

    # ── Invoke ffmpeg ──────────────────────────────────────────────────────
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{req.start_sec:.3f}",
        "-to", f"{req.end_sec:.3f}",
        "-i", os.path.abspath(req.source_video),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", style.encode_preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        os.path.abspath(req.output_path),
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace")
    tail: list[str] = []
    last_pct = -1
    was_cancelled = False
    assert proc.stderr is not None
    try:
        for line in proc.stderr:
            tail.append(line)
            if len(tail) > 60:
                tail.pop(0)
            if cancel_check and cancel_check():
                proc.terminate()
                was_cancelled = True
                break
            m = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
            if m and duration > 0:
                cur_sec = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                           + float(m.group(3)))
                pct = max(0, min(100, int(cur_sec / duration * 100)))
                if pct != last_pct:
                    last_pct = pct
                    if on_progress:
                        on_progress("encoding", pct)
        proc.wait()
    finally:
        for p in (tmp_srt_path, tmp_srt2_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass
        for p in tmp_text_files:
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except OSError:
                pass
        # Whether cancelled or crashed, leave no half-rendered mp4 behind.
        if (was_cancelled or proc.returncode != 0) \
                and os.path.exists(req.output_path):
            try:
                os.unlink(req.output_path)
            except OSError:
                pass

    if was_cancelled:
        raise InterruptedError("Render cancelled")
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg render failed ({proc.returncode}): "
            f"{''.join(tail)[-800:]}"
        )

    return CompositionResult(
        output_path=req.output_path,
        duration_sec=duration,
        width=target_w,
        height=target_h,
    )
