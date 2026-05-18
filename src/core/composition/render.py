"""ffmpeg + libass + drawtext render pipeline.

One call to ffmpeg per output clip. All "what to draw" comes in via
req.timeline (a CompositionTimeline); _timeline_to_overlay_jobs turns
the tracks/elements into per-kind jobs that the primitive registry
dispatches into filter_complex nodes:

    [0:v] crop → scale+pad → <element 1> → <element 2> → ... → [vout]

Per-word karaoke, smart-crop face_center, and audio mixing are not in
this layer yet.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

try:
    from hub_logger import logger
except ImportError:  # core module imported in tests without UI layer
    import logging
    logger = logging.getLogger(__name__)
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Optional

import srt as _srt

from core.subtitle_ops import (
    escape_ffmpeg_path, hex_color_to_ass, read_srt, process_srt_split,
)

from .style import CompositionStyle, SubtitleStyle, SubtitleLineStyle, \
    WatermarkStyle, HookOutroStyle, compute_subtitle_max_chars
# overlays.py shim is retained for legacy creations imports; render.py
# itself doesn't need typed overlay classes anymore — Element kind
# strings drive dispatch.
from .layout import libass_margin_v, pixel_offset
from .fonts import (
    hook_outro_font_path, y_expr_for_position, ass_alignment_for_position,
)
from .text_layout import wrap_hook_outro, wrap_overlay_text


ProgressCallback = Callable[[str, int], None]   # (stage, percent 0-100)


# ── Public dataclasses ──────────────────────────────────────────────────────

@dataclass
class CompositionRequest:
    """All inputs needed for one render_composition() call.

    Engine API speaks purely "what to render" — `timeline` carries the
    visual content (each Element holds its own style/data dict), and
    `output_geometry` / `encode_preset` are the only knobs the engine
    needs about HOW to write the mp4. CompositionStyle (clip's UI
    editor dataclass) is no longer part of the engine API; both clip
    and news_desk build their CompositionRequest from their own
    per-creation config.
    """
    source_video: str
    start_sec: float
    end_sec: float
    output_path: str
    output_geometry: "OutputGeometry"                # crop + scale + aspect
    timeline: "CompositionTimeline"                  # required; "what to draw"
    encode_preset: str = "veryfast"                  # ffmpeg x264 preset
    crop_rect: Optional[dict] = None                 # {x,y,w,h} normalized; None = center crop


@dataclass
class CompositionResult:
    output_path: str
    duration_sec: float
    width: int
    height: int


# ── ffmpeg helpers ──────────────────────────────────────────────────────────

def probe_video_resolution(video_path: str) -> tuple[int, int]:
    """ffprobe → (width, height); (0, 0) on any failure.

    Public helper for any consumer that needs real source dims to feed
    prepare_subtitle_cues / compute_subtitle_max_chars (subtitle wrap
    budget is driven by actual pixel width, not assumed aspect)."""
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


# ── SRT slicing + wrapping (shared between render and preview) ──────────────

def _load_cues(srt_path: str) -> list[_srt.Subtitle]:
    return list(_srt.parse(read_srt(srt_path)))


def _slice_and_wrap_cues(
    srt_path: str,
    line: SubtitleLineStyle,
    *,
    aspect: str,
    short_edge: int,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
) -> list[_srt.Subtitle]:
    """Load + optionally slice [start, end] + max_chars-wrap a SRT file.

    Single source of truth for the cue list both the ffmpeg burn and the
    preview WebView consume. process_srt_split policy lives here and only
    here, so a new consumer can't accidentally bypass it.

    When start_sec=0 and end_sec=None the result keeps original absolute
    timestamps (preview / full-video burn use case). Otherwise the window
    is sliced AND rebased so the first cue starts at 0 (clip burn use
    case — required because ffmpeg `-ss start` shifts the clip's t=0).

    Returns [] on any failure / when the line is disabled.
    """
    if not (line.enabled and srt_path and os.path.isfile(srt_path)):
        return []
    try:
        cues = _load_cues(srt_path)
    except Exception:
        return []

    max_chars = compute_subtitle_max_chars(
        aspect, line.fontsize, line.is_chinese, short_edge=short_edge)

    # Slice + rebase only when a window was requested.
    rebase = start_sec > 0.0 or end_sec is not None
    eff_end = end_sec if end_sec is not None else float("inf")
    sliced: list[_srt.Subtitle] = []
    for cue in cues:
        cs = cue.start.total_seconds()
        ce = cue.end.total_seconds()
        if ce <= start_sec or cs >= eff_end:
            continue
        new_start = max(start_sec, cs) - (start_sec if rebase else 0.0)
        new_end = min(eff_end, ce) - (start_sec if rebase else 0.0)
        if new_end <= new_start:
            continue
        sliced.append(_srt.Subtitle(
            index=len(sliced) + 1,
            start=timedelta(seconds=new_start),
            end=timedelta(seconds=new_end),
            content=cue.content,
        ))
    if not sliced:
        return []

    # Run through process_srt_split via a temp file (it takes a path,
    # not a list — refactoring that signature is out of scope).
    tmp = os.path.join(tempfile.gettempdir(),
                        f"composition-wrap-{os.getpid()}-{id(sliced)}.srt")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(_srt.compose(sliced))
        return list(process_srt_split(
            tmp, max_chars, is_chinese=line.is_chinese))
    except Exception:
        return sliced
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def prepare_subtitle_cues(
    srt_path: str,
    line: SubtitleLineStyle,
    *,
    aspect: str,
    short_edge: int,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
) -> list[dict]:
    """Public preview-side helper: same slice+wrap logic the ffmpeg render
    runs, but returns a JSON-friendly cue dict list instead of writing a
    file. Use this from any preview consumer so what the user sees in
    the WebView lines up with the burn output (max_chars enforced, long
    cues split into shorter time-windowed cues, never visual wrap).

    Returns [{start, end, text}, ...]; empty list on failure / disabled.
    """
    return [{"start": s.start.total_seconds(),
             "end": s.end.total_seconds(),
             "text": s.content}
            for s in _slice_and_wrap_cues(
                srt_path, line, aspect=aspect, short_edge=short_edge,
                start_sec=start_sec, end_sec=end_sec)]


# ── drawtext / subtitle filter strings ─────────────────────────────────────
#
# Per-kind drawtext / libass builders moved to primitives/<kind>.py and
# drawtext_helpers.py in PR 2 split. _escape_drawtext kept here as it's
# a generic helper not tied to any primitive (currently unused; pending
# removal in a later cleanup pass).

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


# The per-kind builders + renderers were moved to primitive modules
# during the PR 2 split — see primitives/subtitle_cue.py (force_style +
# track_margins), primitives/text_watermark.py, primitives/image_watermark.py,
# primitives/hook_text.py, primitives/outro_text.py, and the shared
# drawtext_helpers / libass_helpers modules. render.py orchestrates them
# via the registry; it doesn't know per-kind specifics anymore.

# Re-export bindings for in-module callers (_named_overlay_jobs still
# needs build_force_style + track_margins from the subtitle_cue
# primitive — those are subtitle-track plumbing, not per-element
# renderer concerns). Underscore-aliased to keep diffs minimal.
from .primitives.subtitle_cue import (
    build_force_style as _build_subtitle_force_style,
)


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

# PR 2: registry consolidated into primitives/__init__.py. Each primitive
# module registers its renderer at import time via primitives.
# register_overlay_renderer; render.py looks them up via
# primitives.get_overlay_renderer during dispatch.
from . import primitives as _primitives

register_overlay_renderer = _primitives.register_overlay_renderer


# ── Built-in renderer registration ──────────────────────────────────────────
#
# Each primitive module registers its renderer at import time. We import
# them explicitly here so the registrations happen as part of render
# module load — order matters for "renderer not registered" early errors,
# not for behaviour. After PR 2 the 5 entries below mirror what used to
# be 5 local _renderer_X / register pairs in this file.

from .primitives import (
    hook_text as _hook_text,            # noqa: F401  — registers "hook_text"
    image_watermark as _image_watermark, # noqa: F401 — registers "image_watermark"
    outro_text as _outro_text,           # noqa: F401 — registers "outro_text"
    subtitle_cue as _subtitle_cue,       # noqa: F401 — registers "subtitle_cue"
    text_watermark as _text_watermark,   # noqa: F401 — registers "text_watermark"
)


# ── News-desk merged ASS orchestrator ───────────────────────────────────────
#
# topic_strip + chapter_hero_card primitives both emit libass dialogue
# strings (rather than ffmpeg filter snippets). They are merged into a
# single per-render .ass file consumed by one `subtitles=` filter — keeps
# the filter_complex chain shallow and reuses the libass engine that
# already handles bilingual subtitle tracks (font/anti-aliasing parity).
#
# The orchestrator dispatches by isinstance to pick the right primitive's
# build_dialogues(). When timeline IR ships (PR 4/5) each Element will
# carry its own kind string and this isinstance switch disappears.

from .libass_helpers import ASS_HEADER_TMPL
from .primitives import chapter_hero_card as _chapter_hero_card
from .primitives import topic_strip as _topic_strip
from .style import resolve_overlay_style
from typing import Iterable


def build_news_desk_ass_str(specs: Iterable, *,
                              target_w: int, target_h: int,
                              overlay_styles: dict | None = None) -> str | None:
    """Pure ASS-content builder for all TopicStrip + ChapterHeroCard
    overlays in one render. Returns the full .ass file content as a str,
    or None if no overlays produced dialogues (caller skips the filter).

    `overlay_styles` is the named-style library; when None / empty we
    fall back to default_overlay_styles() so callers don't need to
    thread the library through engine APIs.

    Separated from the temp-file write so PR 2's primitive-split refactor
    can byte-equality test against this output via the golden suite.
    """
    from .style import default_overlay_styles
    if not overlay_styles:
        overlay_styles = default_overlay_styles()
    dialogues: list[str] = []
    for spec in specs:
        if isinstance(spec, _topic_strip.TopicStripSpec):
            style = resolve_overlay_style(
                overlay_styles, "topic_strip", spec.style_class)
            if style is None:
                style = _topic_strip.TopicStripStyle()
            dialogues.extend(_topic_strip.build_dialogues(
                spec, style, target_w=target_w, target_h=target_h))
        elif isinstance(spec, _chapter_hero_card.ChapterHeroCardSpec):
            style = resolve_overlay_style(
                overlay_styles, "chapter_hero_card", spec.style_class)
            if style is None:
                style = _chapter_hero_card.ChapterHeroCardStyle()
            # Per-spec inline overrides — chapter component routes its
            # property panel edits here so changes take effect without
            # touching the project-wide overlay_styles dict.
            for k, v in (spec.inline_style or {}).items():
                if k in _chapter_hero_card.ChapterHeroCardStyle.__dataclass_fields__:
                    setattr(style, k, v)
            dialogues.extend(_chapter_hero_card.build_dialogues(
                spec, style, target_w=target_w, target_h=target_h))

    if not dialogues:
        return None

    return ASS_HEADER_TMPL.format(w=target_w, h=target_h) + \
        "\n".join(dialogues) + "\n"


def build_news_desk_ass(specs: Iterable, *,
                          target_w: int, target_h: int,
                          overlay_styles: dict) -> str | None:
    """Thin write-to-tempfile wrapper around build_news_desk_ass_str.
    Returns the file path so ffmpeg's subtitles= filter can consume it,
    or None when there's nothing to render.
    """
    body = build_news_desk_ass_str(
        specs, target_w=target_w, target_h=target_h,
        overlay_styles=overlay_styles,
    )
    if body is None:
        return None
    out_path = os.path.join(
        tempfile.gettempdir(),
        f"composition-newsdesk-{os.getpid()}-{id(body)}.ass",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    return out_path


def _renderer_news_desk_ass(job: _OverlayJob, prev_label: str,
                              ctx: _RenderCtx) -> tuple[list[str], str]:
    """Build the merged .ass on demand (now that ctx.target_w/h are known),
    then chain a single subtitles= filter. Temp file is registered with
    ctx.tmp_files so the parent render() cleans it up after ffmpeg returns.
    """
    specs = job.data.get("specs") or []
    overlay_styles = job.data.get("overlay_styles") or {}
    ass_path = build_news_desk_ass(
        specs, target_w=ctx.target_w, target_h=ctx.target_h,
        overlay_styles=overlay_styles,
    )
    if not ass_path:
        return [], prev_label
    ctx.tmp_files.append(ass_path)
    ass_ff = escape_ffmpeg_path(ass_path)
    out_label = ctx.next_label()
    return ([f"{prev_label}subtitles=filename='{ass_ff}'{out_label}"],
            out_label)


register_overlay_renderer("news_desk_ass", _renderer_news_desk_ass)


# ── Timeline → _OverlayJob translation ─────────────────────────────────────
#
# Walks a compiled timeline and emits the _OverlayJob list the render
# main loop dispatches through the primitive registry. Single entry
# point — PR 5 retired the parallel "legacy 5-channel" path.

def _timeline_to_overlay_jobs(
    timeline,
    req: CompositionRequest,
    *,
    aspect_str: str,
    short_edge: int,
    tmp_files: list[str],
    target_w: int,
    target_h: int,
) -> list[_OverlayJob]:
    from .primitives.chapter_hero_card import (
        ChapterHeroCardSpec, ChapterHeroCardStyle,
    )
    from .layout import libass_margin_v
    from .primitives.subtitle_cue import build_force_style as _bfs
    from .primitives.topic_strip import TopicStripSpec

    jobs: list[_OverlayJob] = []
    news_desk_specs: list = []
    news_desk_z: int = 0

    for track in timeline.tracks:
        if not track.enabled:
            continue
        z_base = track.z_base

        elements_by_kind: dict[str, list] = {}
        for e in track.elements:
            elements_by_kind.setdefault(e.kind, []).append(e)

        for kind, elements in elements_by_kind.items():
            if kind == "subtitle_cue":
                wrapped = wrap_subtitle_elements(
                    elements, aspect_str=aspect_str, short_edge=short_edge)
                if not wrapped:
                    continue
                # All cues in one track share the same style dict (set
                # by the producing component). Margin: prefer the
                # composer-supplied effective pct (multi-track stacking
                # pre-computed); else use the plain per-component pct.
                style_dict = elements[0].style
                position = style_dict.get("position", "bottom")
                pct_from_edge = float(style_dict.get(
                    "effective_block_margin_pct",
                    style_dict.get("block_margin_pct", 0.09)))
                margin_v = libass_margin_v(pct_from_edge, target_h)
                force_style = _bfs(
                    fontsize_pct=float(style_dict.get("fontsize_pct", 0.05)),
                    color=style_dict.get("color", "#FFFFFF"),
                    bold=bool(style_dict.get("bold", False)),
                    is_chinese=bool(style_dict.get("is_chinese", False)),
                    bg_color=style_dict.get("bg_color", "#000000"),
                    bg_opacity=int(style_dict.get("bg_opacity", 0)),
                    bg_padding_x_pct=float(
                        style_dict.get("bg_padding_x_pct", 0.0)),
                    stroke_color=style_dict.get("stroke_color", "#000000"),
                    stroke_pct=float(style_dict.get("stroke_pct", 0.002)),
                    position=position,
                    margin_v=margin_v,
                    short_edge=short_edge,
                    target_h=target_h)
                # Write a complete ASS file with explicit PlayRes so
                # libass renders font/stroke at the pixel sizes the pct
                # math intended. Bare SRT + force_style lets libass fall
                # back to PlayResY=288 and inflates everything ~6.7x.
                from .primitives.subtitle_cue import build_subtitle_ass
                ass_body = build_subtitle_ass(
                    wrapped, force_style=force_style,
                    target_w=target_w, target_h=target_h)
                ass_path = os.path.join(
                    tempfile.gettempdir(),
                    f"composition-timeline-{track.id}-"
                    f"{os.getpid()}-{id(ass_body)}.ass")
                try:
                    with open(ass_path, "w", encoding="utf-8") as f:
                        f.write(ass_body)
                except OSError:
                    continue
                tmp_files.append(ass_path)
                jobs.append(_OverlayJob(
                    kind="subtitle_cue", z_order=z_base,
                    data={"ass_path": ass_path}))

            elif kind in ("text_watermark", "image_watermark"):
                for e in elements:
                    wm = _element_to_watermark_style(e, short_edge=short_edge)
                    jobs.append(_OverlayJob(
                        kind=kind, z_order=z_base + e.z_offset,
                        data={"watermark": wm}))

            elif kind == "hook_text":
                for e in elements:
                    txt = e.data.get("text", "")
                    if txt:
                        jobs.append(_OverlayJob(
                            kind="hook_text", z_order=z_base + e.z_offset,
                            data={"text": txt, "style": e.style}))

            elif kind == "outro_text":
                for e in elements:
                    txt = e.data.get("text", "")
                    if txt:
                        jobs.append(_OverlayJob(
                            kind="outro_text", z_order=z_base + e.z_offset,
                            data={"text": txt, "style": e.style}))

            elif kind == "topic_strip":
                for e in elements:
                    news_desk_specs.append(TopicStripSpec(
                        topic_text=e.data.get("topic_text", ""),
                        start_sec=e.start_sec, end_sec=e.end_sec,
                        style_class=e.data.get("style_class", "default"),
                    ))
                news_desk_z = max(news_desk_z, z_base)

            elif kind == "chapter_hero_card":
                for e in elements:
                    news_desk_specs.append(ChapterHeroCardSpec(
                        title=e.data.get("title", ""),
                        body=e.data.get("body", ""),
                        start_sec=e.start_sec, end_sec=e.end_sec,
                        style_class=e.data.get("style_class", "default"),
                        inline_style=e.data.get("inline_style", {}) or {},
                    ))
                news_desk_z = max(news_desk_z, z_base)

    if news_desk_specs:
        # Match legacy behaviour: caller-driven z + sort-by-input-z so the
        # merged ASS preserves the relative stacking the timeline encoded.
        news_desk_specs.sort(key=lambda s: s.z_order if hasattr(s, "z_order") else 0)
        # The overlay-style library is a news_desk-internal default; the
        # orchestrator resolves missing entries via default_overlay_styles()
        # so callers never need to thread it through req.
        jobs.append(_OverlayJob(
            kind="news_desk_ass", z_order=news_desk_z,
            data={"specs": news_desk_specs, "overlay_styles": {}}))

    return jobs


def wrap_subtitle_elements(
    elements: list, *, aspect_str: str, short_edge: int,
) -> list[_srt.Subtitle]:
    """Single source of subtitle-wrap policy for the timeline path.

    Build raw cues from a subtitle_cue track's Elements (already
    clip-relative timing), run them through process_srt_split with a
    max_chars budget derived from aspect / fontsize / short_edge, and
    return the wrapped _srt.Subtitle list. Both render (writes to temp
    SRT for libass) and preview (converts to JSON for the JS bridge)
    call this helper — guaranteeing same wrap on both sides.

    Returns [] on empty input or wrap failure.
    """
    if not elements:
        return []
    style_dict = elements[0].style
    max_chars = compute_subtitle_max_chars(
        aspect_str,
        int(style_dict.get("fontsize", 24)),
        bool(style_dict.get("is_chinese", False)),
        short_edge=short_edge,
    )
    raw_cues = [
        _srt.Subtitle(
            index=i + 1,
            start=timedelta(seconds=float(e.start_sec)),
            end=timedelta(seconds=float(e.end_sec)),
            content=str(e.data.get("text", "")),
        )
        for i, e in enumerate(elements)
        if e.end_sec > e.start_sec
    ]
    if not raw_cues:
        return []
    # process_srt_split takes a path (legacy signature) — pipe through
    # a transient tmp file. The wrap output is what we return.
    raw_tmp = os.path.join(
        tempfile.gettempdir(),
        f"composition-wrap-{os.getpid()}-{id(raw_cues)}.srt")
    try:
        with open(raw_tmp, "w", encoding="utf-8") as f:
            f.write(_srt.compose(raw_cues))
        return list(process_srt_split(
            raw_tmp, max_chars,
            is_chinese=bool(style_dict.get("is_chinese", False))))
    except Exception:
        return []
    finally:
        try:
            os.unlink(raw_tmp)
        except OSError:
            pass


def _element_to_watermark_style(e, *, short_edge: int) -> "WatermarkStyle":
    """Reconstruct a unified WatermarkStyle dataclass from a text_watermark
    or image_watermark Element. Component schema carries text_fontsize as
    pct of short edge; we materialize the int-pixel field on the
    dataclass here so the text_watermark renderer keeps its old API."""
    from .layout import font_size_px
    style_dict = e.style
    data = e.data
    is_image = (e.kind == "image_watermark")
    return WatermarkStyle(
        enabled=True,
        type="image" if is_image else "text",
        text=data.get("text", "") if not is_image else "",
        text_fontsize=font_size_px(
            float(style_dict.get("text_fontsize_pct", 0.033)),
            short_edge),
        text_color=style_dict.get("text_color", "#FFFFFF"),
        text_opacity=int(style_dict.get("text_opacity", 70)),
        image_path=data.get("image_path", "") if is_image else "",
        image_scale=float(style_dict.get("image_scale", 0.15)),
        image_opacity=int(style_dict.get("image_opacity", 100)),
        position=style_dict.get("position", "top-right"),
        margin_x_pct=float(style_dict.get("margin_x_pct", 0.025)),
        margin_y_pct=float(style_dict.get("margin_y_pct", 0.025)),
    )

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
    geom = req.output_geometry

    src_w, src_h = probe_video_resolution(req.source_video)
    if src_w == 0 or src_h == 0:
        raise RuntimeError(f"Cannot probe video resolution: {req.source_video}")

    # Resolve effective output geometry. In passthrough mode the canvas
    # matches the source verbatim (no crop, no scale); in reframe mode
    # the canvas is derived from geom.aspect + short_edge and the source
    # is center-cropped (or per-request crop_rect) to fit.
    if geom.mode == "passthrough":
        target_w, target_h = src_w, src_h
        effective_aspect = (src_w, src_h)
        effective_short_edge = min(src_w, src_h)
        rect = None
        cw = ch = cx = cy = 0    # unused
    else:
        target_w, target_h = _target_dims_for_aspect(
            geom.aspect_ratio(),
            short_edge=geom.short_edge,
        )
        effective_aspect = geom.aspect_ratio()
        effective_short_edge = geom.short_edge
        rect = req.crop_rect or _center_crop_rect(
            src_w, src_h, aspect_ratio=geom.aspect_ratio())
        cw, ch, cx, cy = _crop_rect_to_pixels(rect, src_w, src_h)

    duration = max(0.0, req.end_sec - req.start_sec)
    if duration <= 0:
        raise ValueError(
            f"Composition has non-positive duration: "
            f"{req.start_sec}..{req.end_sec}")

    os.makedirs(os.path.dirname(os.path.abspath(req.output_path)) or ".",
                exist_ok=True)

    effective_aspect_str = f"{effective_aspect[0]}:{effective_aspect[1]}"

    if req.timeline is None:
        raise ValueError(
            "CompositionRequest.timeline is required since PR 5; "
            "callers must compile a CompositionTimeline before render.")

    # ── Build filter_complex via overlay dispatch ─────────────────────────
    parts: list[str] = []
    if geom.mode == "passthrough":
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
        tmp_files=tmp_text_files,
    )

    jobs = _timeline_to_overlay_jobs(
        req.timeline, req,
        aspect_str=effective_aspect_str,
        short_edge=effective_short_edge,
        tmp_files=tmp_text_files,
        target_w=target_w,
        target_h=target_h,
    )
    for job in jobs:
        if not _primitives.is_registered(job.kind):
            # Unknown kind (e.g. future overlay with no renderer registered
            # yet) — skip silently rather than fail the render.
            continue
        renderer = _primitives.get_overlay_renderer(job.kind)
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
        "-c:v", "libx264", "-preset", req.encode_preset, "-crf", str(crf),
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
        for p in list(tmp_text_files):
            if p and os.path.exists(p):
                try:
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
