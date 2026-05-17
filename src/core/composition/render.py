"""ffmpeg + libass + drawtext render pipeline.

One call to ffmpeg per output clip. All overlays — subtitle tracks,
watermark, hook/outro text, plus any user-provided OverlaySpec entries —
flow through a single dispatch table:

    [0:v] crop → scale+pad → <overlay 1> → <overlay 2> → ... → [vout]

The named style sections (style.subtitle / style.watermark /
style.hook_outro + req.hook_text / req.outro_text) are converted to
internal _OverlayJob records by _named_overlay_jobs(); news_desk overlay
kinds (topic_strip / chapter_hero_card) drop in as additional registered
renderers without touching the main loop.

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
from .overlays import (
    ChapterHeroCardOverlay, OverlaySpec, TopicStripOverlay,
)
from .layout import libass_margin_v, pixel_offset
from .fonts import (
    hook_outro_font_path, y_expr_for_position, ass_alignment_for_position,
)
from .text_layout import wrap_hook_outro, wrap_overlay_text


ProgressCallback = Callable[[str, int], None]   # (stage, percent 0-100)


# ── Public dataclasses ──────────────────────────────────────────────────────

@dataclass
class ExtraSubtitleSpec:
    """One additional subtitle track beyond the legacy sub1/sub2 slots.

    Each spec carries its own SRT, SubtitleLineStyle, position and
    block_margin — i.e. each track is fully independent (no shared
    track_gap layout). news_desk consumes this path because every
    subtitle component is a free-standing instance with its own anchor.

    `z_order` is the absolute render layer (higher = on top). Consumers
    should pass list-position-derived values; default 10 matches the
    legacy kind-based hardcode.
    """
    srt_path: str
    line: "SubtitleLineStyle"
    position: str = "bottom"            # "top" | "bottom"
    block_margin_pct: float = 0.09      # fraction of frame height
    z_order: int = 10


@dataclass
class ExtraWatermarkSpec:
    """One additional watermark beyond the legacy `style.watermark` slot.

    Wraps a WatermarkStyle with an explicit z_order so the consumer
    (news_desk) can drive layer ordering from its component list
    position. Default 60 matches the legacy kind-based hardcode.
    """
    watermark: "WatermarkStyle"
    z_order: int = 60


@dataclass
class CompositionRequest:
    """All inputs needed for one render_composition() call.

    Built by the consumer (e.g. AI Clip workbench, subtitle burn) from a
    hotclip entry / SRT pair + the user's current CompositionStyle + the
    project's source video.

    Subtitle tracks come in via two paths:
      - Legacy 2-track shared-layout path: `source_srt` / `source_srt_secondary`
        plus `style.subtitle.sub1` / `sub2` (clip + bilingual subtitle burn).
      - N-track independent path: `extra_subtitles` — each entry is an
        ExtraSubtitleSpec carrying its own SRT/style/position (news_desk).
    Both paths can coexist in one render; jobs render in declared order.

    Watermarks: legacy `style.watermark` is the singular slot
    (clip / subtitle); `extra_watermarks` carries any additional
    WatermarkStyle entries (news_desk emits all of them here).
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
    extra_subtitles: list = field(default_factory=list)    # list[ExtraSubtitleSpec]
    extra_watermarks: list = field(default_factory=list)   # list[ExtraWatermarkSpec]


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
    track_margins as _track_margins,
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
    subtitle_cue as _subtitle_cue,       # noqa: F401 — registers "subtitle_libass"
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
                              overlay_styles: dict) -> str | None:
    """Pure ASS-content builder for all TopicStrip + ChapterHeroCard
    overlays in one render. Returns the full .ass file content as a str,
    or None if no overlays produced dialogues (caller skips the filter).

    Separated from the temp-file write so PR 2's primitive-split refactor
    can byte-equality test against this output via the golden suite.
    """
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


def _named_overlay_jobs(req: CompositionRequest,
                          sub1_srt: Optional[str],
                          sub2_srt: Optional[str],
                          extra_sub_tmps: list[tuple[str, ExtraSubtitleSpec]],
                          *, target_h: int) -> list[_OverlayJob]:
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
                style.subtitle.sub1, style.subtitle,
                margin_v=margin_v1, target_h=target_h),
        }))
    if style.subtitle.sub2.enabled and sub2_srt:
        jobs.append(_OverlayJob(kind="subtitle_libass", z_order=11, data={
            "srt_path": sub2_srt,
            "force_style": _build_subtitle_force_style(
                style.subtitle.sub2, style.subtitle,
                margin_v=margin_v2, target_h=target_h),
        }))

    # Extra independent subtitle tracks (news_desk path). Each spec has its
    # own position + block_margin → its own MarginV + Alignment in libass.
    # z_order comes from the spec — caller (news_desk) drives layer
    # ordering from its component-list index.
    for tmp_path, espec in extra_sub_tmps:
        jobs.append(_OverlayJob(
            kind="subtitle_libass", z_order=espec.z_order,
            data={
                "srt_path": tmp_path,
                "force_style": _build_subtitle_force_style(
                    espec.line, style.subtitle,
                    margin_v=libass_margin_v(espec.block_margin_pct),
                    target_h=target_h, position=espec.position),
            }))

    # Watermark — image or text (mutually exclusive). High z_order so the
    # logo / channel bug paints on top of everything else (broadcast
    # convention: corner bugs override L3 banners + chapter strips).
    if style.watermark.enabled:
        if style.watermark.type == "image":
            jobs.append(_OverlayJob(kind="image_watermark", z_order=60,
                                      data={"watermark": style.watermark}))
        else:
            jobs.append(_OverlayJob(kind="text_watermark", z_order=61,
                                      data={"watermark": style.watermark}))

    # Extra watermarks (news_desk: N watermark components → N drawtext /
    # overlay filters chained together). Each one is independent — its own
    # position + opacity + margins. z_order comes from the spec — caller
    # drives layer ordering from its component-list index.
    for ews in req.extra_watermarks:
        wm = ews.watermark
        if not wm.enabled:
            continue
        kind = "image_watermark" if wm.type == "image" else "text_watermark"
        jobs.append(_OverlayJob(
            kind=kind, z_order=ews.z_order, data={"watermark": wm}))

    # Hook + Outro card.
    if req.hook_text:
        jobs.append(_OverlayJob(kind="hook_text", z_order=30,
                                  data={"text": req.hook_text}))
    if req.outro_text:
        jobs.append(_OverlayJob(kind="outro_text", z_order=31,
                                  data={"text": req.outro_text}))

    # User-supplied overlays — split into:
    #   - news_desk typed overlays (TopicStrip/ChapterHeroCard): merged
    #     into a single libass job (one .ass file regardless of count) so
    #     the filter chain stays shallow.
    #   - generic OverlaySpec entries: passed through individually for any
    #     kind that has its own registered renderer.
    news_desk_specs: list = []
    for spec in req.overlays:
        if isinstance(spec, (TopicStripOverlay, ChapterHeroCardOverlay)):
            news_desk_specs.append(spec)
        elif isinstance(spec, OverlaySpec):
            jobs.append(_OverlayJob(
                kind=spec.kind, z_order=spec.z_order,
                data={"spec": spec},
            ))

    if news_desk_specs:
        # All news_desk specs are merged into one libass job so the filter
        # chain stays shallow. The job's z_order = max of contained specs'
        # z_order — that way if the caller assigned a high list-position-
        # derived z (chapter component dragged above watermarks), the
        # whole merged group rises above the watermark layer. libass
        # internal Layer attribute still handles per-spec ordering inside
        # the merged .ass file.
        news_desk_specs.sort(key=lambda s: s.z_order)
        merged_z = max((s.z_order for s in news_desk_specs), default=40)
        jobs.append(_OverlayJob(
            kind="news_desk_ass", z_order=merged_z,
            data={
                "specs": news_desk_specs,
                "overlay_styles": req.style.overlay_styles,
            },
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

    src_w, src_h = probe_video_resolution(req.source_video)
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

    # ── Slice each track's SRT to this window (rebased to 0), then
    #    write the wrapped cues to a temp file for libass. The split
    #    policy lives in _slice_and_wrap_cues — never duplicated here.
    effective_aspect_str = f"{effective_aspect[0]}:{effective_aspect[1]}"

    def _prepare_track_srt(src_path: str | None, line: SubtitleLineStyle,
                            tag: str) -> str | None:
        subs = _slice_and_wrap_cues(
            src_path or "", line,
            aspect=effective_aspect_str,
            short_edge=effective_short_edge,
            start_sec=req.start_sec, end_sec=req.end_sec)
        if not subs:
            return None
        out = os.path.join(
            tempfile.gettempdir(),
            f"composition-{tag}-{int(req.start_sec*1000)}-{os.getpid()}.srt")
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(_srt.compose(subs))
            return out
        except OSError:
            return None

    tmp_srt_path = _prepare_track_srt(req.source_srt, style.subtitle.sub1, "sub1")
    tmp_srt2_path = _prepare_track_srt(
        req.source_srt_secondary, style.subtitle.sub2, "sub2")

    # Extra independent subtitle tracks (news_desk N-track path). Each
    # spec gets its own sliced+wrapped temp SRT keyed by index for cleanup.
    extra_sub_tmps: list[tuple[str, ExtraSubtitleSpec]] = []
    for i, espec in enumerate(req.extra_subtitles):
        tmp = _prepare_track_srt(espec.srt_path, espec.line, f"sub_extra_{i}")
        if tmp:
            extra_sub_tmps.append((tmp, espec))

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

    jobs = _named_overlay_jobs(req, tmp_srt_path, tmp_srt2_path,
                                extra_sub_tmps, target_h=target_h)
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
        cleanup_paths = [tmp_srt_path, tmp_srt2_path]
        cleanup_paths.extend(p for p, _ in extra_sub_tmps)
        for p in cleanup_paths:
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
