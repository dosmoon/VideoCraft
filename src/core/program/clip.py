"""Clip Script — long video → N short vertical clips.

Phase A (walking skeleton, no AI): consume `subtitle.pack` postprocess.json,
let user manually pick chapter ranges, manually frame crop on a still
keyframe, and export 1080x1920 mp4 clips with burned subtitles + hook/outro
overlays.

Phase B will add AI: rank_chapters / find_peaks / package_clip layered on
top of the same data model. See docs/draft/program-script-clip.md.

Architecture: this is the *feature* layer (per principle 1). UI imports
this module; this module owns ffmpeg invocation and pack parsing. AI
calls (Phase B) will route through `core.ai.complete_json`.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Callable

import srt as _srt

from core.segment_model import format_timestamp, parse_timestamp, safe_filename
from core.subtitle_ops import (
    LAYOUT_DEFAULTS, escape_ffmpeg_path, hex_color_to_ass, read_srt,
    process_srt_split,
)


ProgressCallback = Callable[[str, int], None]   # (status, percent 0-100)


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class ClipDraft:
    """One short video being assembled. Pre-export fields filled by UI;
    crop_rect / output_path filled by export step."""
    id: int
    chapter_idx: int
    chapter_title: str
    start_sec: float
    end_sec: float
    original_excerpt: str = ""
    hook: str = ""
    outro: str = ""
    title: str = ""
    hashtags: list[str] = field(default_factory=list)
    crop_rect: dict | None = None       # {x, y, w, h} normalized 0..1
    status: str = "draft"               # draft / reviewed / exported / skipped
    output_path: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


# ── Project-level output style ──────────────────────────────────────────────
#
# Style is project-scoped: one cut file = one set of output style settings
# shared by all clips. Per-clip we only store the framing rect (crop_rect)
# and copy text (hook / outro / title / hashtags). Aspect/subtitle/watermark
# / hook-outro card / BGM all live here.

@dataclass
class SubtitleLineStyle:
    """One subtitle track's per-line style. Two lines (sub1 / sub2) per
    project — typically sub1 = primary language (CJK, bold, larger), sub2
    = secondary (Latin, regular)."""
    enabled: bool = True
    fontsize: int = 24
    color: str = "#FFFFFF"
    bold: bool = False
    is_chinese: bool = False        # affects glyph-width / line-break logic
    auto_max_chars: bool = True     # compute from aspect+fontsize at run time
    manual_max_chars: int = 20      # used only when auto_max_chars is False


@dataclass
class SubtitleStyle:
    sub1: SubtitleLineStyle = field(
        default_factory=lambda: SubtitleLineStyle(
            enabled=True, fontsize=24, color="#FFFF00",
            bold=True, is_chinese=True))
    sub2: SubtitleLineStyle = field(
        default_factory=lambda: SubtitleLineStyle(
            enabled=False, fontsize=24, color="#FFFFFF",
            bold=False, is_chinese=False))
    stroke_color: str = "#000000"
    stroke_width: int = 2
    position: str = "bottom"        # "top" | "middle" | "bottom"


@dataclass
class WatermarkStyle:
    enabled: bool = False
    type: str = "image"             # "image" | "text"
    # Image-mode fields
    image_path: str = ""
    image_scale: float = 0.15       # fraction of video width (0.0-1.0)
    image_opacity: int = 100        # 0-100
    # Text-mode fields
    text: str = ""
    text_fontsize: int = 36
    text_color: str = "#FFFFFF"
    text_opacity: int = 70
    # Common
    position: str = "top-right"     # "top-left"|"top-right"|"bottom-left"|"bottom-right"


@dataclass
class HookOutroStyle:
    font: str = "Microsoft YaHei"   # font NAME, resolved via _hook_outro_font_path
    size: int = 48
    color: str = "#FFFFFF"
    bg_color: str = "#000000"
    bg_opacity: int = 70           # 0-100. 0 disables the box entirely.
    stroke_color: str = "#000000"
    stroke_width: int = 3          # 0 disables the outline
    box_padding: int = 10          # drawtext boxborderw
    hook_position: str = "upper-third"   # see HOOK_OUTRO_POSITIONS
    outro_position: str = "lower-third"
    hook_duration_sec: float = 5.0
    outro_duration_sec: float = 5.0


# Vertical anchor presets — mapped to ffmpeg drawtext y= expressions in
# _y_expr_for_position(). Keys are the canonical names persisted in cfg.
HOOK_OUTRO_POSITIONS: tuple[str, ...] = (
    "top", "upper-third", "center", "lower-third", "bottom"
)


# Windows-bundled font name → file path map. Names are what the user
# picks in the Tab 0 dropdown; lookup is case-insensitive. Unknown names
# fall back to msyh.ttc (Microsoft YaHei) which is always installed on
# zh-CN Windows. Latin-only fonts (Arial / Times New Roman) won't render
# CJK; the dropdown should warn the user but we don't enforce.
_HOOK_OUTRO_FONT_MAP: dict[str, str] = {
    "microsoft yahei":   "C:/Windows/Fonts/msyh.ttc",
    "微软雅黑":          "C:/Windows/Fonts/msyh.ttc",
    "simhei":            "C:/Windows/Fonts/simhei.ttf",
    "黑体":              "C:/Windows/Fonts/simhei.ttf",
    "simsun":            "C:/Windows/Fonts/simsun.ttc",
    "宋体":              "C:/Windows/Fonts/simsun.ttc",
    "kaiti":             "C:/Windows/Fonts/simkai.ttf",
    "楷体":              "C:/Windows/Fonts/simkai.ttf",
    "dengxian":          "C:/Windows/Fonts/Deng.ttf",
    "等线":              "C:/Windows/Fonts/Deng.ttf",
    "arial":             "C:/Windows/Fonts/arial.ttf",
    "times new roman":   "C:/Windows/Fonts/times.ttf",
}


def _hook_outro_font_path(font_name: str) -> str:
    """Resolve a user-facing font name to an absolute Windows path. Falls
    back to Microsoft YaHei when the name isn't recognized or the file is
    absent (so a typo doesn't kill the render)."""
    fallback = "C:/Windows/Fonts/msyh.ttc"
    if not font_name:
        return fallback
    raw = font_name.strip()
    # If user gave an absolute path that exists, use it directly.
    if os.path.isfile(raw):
        return raw.replace("\\", "/")
    path = _HOOK_OUTRO_FONT_MAP.get(raw.lower())
    if path and os.path.isfile(path):
        return path
    return fallback


def _y_expr_for_position(position: str) -> str:
    """Translate a position preset to an ffmpeg drawtext y= expression."""
    return {
        "top":          "h*0.08",
        "upper-third":  "h*0.25",
        "center":       "(h-text_h)/2",
        "lower-third":  "h*0.65",
        "bottom":       "h*0.85",
    }.get(position, "h*0.25")


@dataclass
class BgmConfig:
    path: str = ""
    volume: int = 50               # 0-100; placeholder, not yet wired


@dataclass
class ClipProjectConfig:
    """Output-style settings shared by all clips in a cut file."""
    aspect: str = "9:16"            # "9:16"|"16:9"|"1:1"|"4:5"
    encode_preset: str = "veryfast"  # ffmpeg x264 preset
    subtitle: SubtitleStyle = field(default_factory=SubtitleStyle)
    watermark: WatermarkStyle = field(default_factory=WatermarkStyle)
    hook_outro: HookOutroStyle = field(default_factory=HookOutroStyle)
    bgm: BgmConfig = field(default_factory=BgmConfig)

    def aspect_ratio(self) -> tuple[int, int]:
        """Parse aspect string. Falls back to 9:16 on any oddity."""
        try:
            w, h = self.aspect.split(":", 1)
            return (max(1, int(w)), max(1, int(h)))
        except Exception:
            return (9, 16)

    @classmethod
    def from_dict(cls, d: dict | None) -> "ClipProjectConfig":
        """Build from a JSON-loaded dict.

        Schema-aware migration: detects v3 (mode + flat subtitle, scale/opacity
        watermark) and v4 (sub1/sub2 + watermark.type) and rebuilds the right
        shape. Unknown keys ignored; type errors fall back to defaults.
        """
        if not isinstance(d, dict):
            return cls()
        sub_d = d.get("subtitle") if isinstance(d.get("subtitle"), dict) else {}
        wm_d  = d.get("watermark") if isinstance(d.get("watermark"), dict) else {}
        ho_d  = d.get("hook_outro") if isinstance(d.get("hook_outro"), dict) else {}
        bg_d  = d.get("bgm") if isinstance(d.get("bgm"), dict) else {}

        # ── Subtitle ──
        if "sub1" in sub_d or "sub2" in sub_d:
            # v4 native
            def _line(raw: dict) -> SubtitleLineStyle:
                if not isinstance(raw, dict):
                    return SubtitleLineStyle()
                return SubtitleLineStyle(**{
                    k: v for k, v in raw.items()
                    if k in SubtitleLineStyle.__dataclass_fields__})
            sub_style = SubtitleStyle(
                sub1=_line(sub_d.get("sub1") or {}),
                sub2=_line(sub_d.get("sub2") or {}),
                stroke_color=str(sub_d.get("stroke_color", "#000000")),
                stroke_width=int(sub_d.get("stroke_width", 2)),
                position=str(sub_d.get("position", "bottom")),
            )
        else:
            # v3 → v4 migration
            v3_size = int(sub_d.get("size", 24))
            v3_color = str(sub_d.get("color", "#FFFFFF"))
            bilingual = sub_d.get("mode", "single") == "bilingual"
            sub_style = SubtitleStyle(
                sub1=SubtitleLineStyle(
                    enabled=True, fontsize=v3_size, color=v3_color,
                    is_chinese=True, bold=True),
                sub2=SubtitleLineStyle(
                    enabled=bilingual, fontsize=v3_size, color=v3_color,
                    is_chinese=False, bold=False),
                stroke_color=str(sub_d.get("stroke_color", "#000000")),
                stroke_width=int(sub_d.get("stroke_width", 2)),
                position=str(sub_d.get("position", "bottom")),
            )

        # ── Watermark ──
        if "type" in wm_d:
            wm_style = WatermarkStyle(**{k: v for k, v in wm_d.items()
                                          if k in WatermarkStyle.__dataclass_fields__})
        else:
            # v3 had: enabled / image_path / position / opacity (0-100) /
            # scale (0-100 percent).
            wm_style = WatermarkStyle(
                enabled=bool(wm_d.get("enabled", False)),
                type="image",
                image_path=str(wm_d.get("image_path", "")),
                image_scale=float(wm_d.get("scale", 15)) / 100.0,
                image_opacity=int(wm_d.get("opacity", 100)),
                position=str(wm_d.get("position", "top-right")),
            )

        return cls(
            aspect=str(d.get("aspect", "9:16")),
            encode_preset=str(d.get("encode_preset", "veryfast")),
            subtitle=sub_style,
            watermark=wm_style,
            hook_outro=HookOutroStyle(**{k: v for k, v in ho_d.items()
                                         if k in HookOutroStyle.__dataclass_fields__}),
            bgm=BgmConfig(**{k: v for k, v in bg_d.items()
                             if k in BgmConfig.__dataclass_fields__}),
        )


# ── Auto max-chars per subtitle line ────────────────────────────────────────

def compute_subtitle_max_chars(aspect: str, fontsize: int, is_chinese: bool,
                                 *, density: float = 1.0,
                                 font_path: str | None = None) -> int:
    """How many chars per line before the subtitle visually overflows when
    burned via ffmpeg's `subtitles=` (libass) filter.

    The catch: libass renders an SRT against a default PlayResX/Y of ~384
    while the video is 1080-class — so a "Fontsize=24" style is rendered at
    roughly 24×(1080/384)≈4.7x its nominal pixel size. PIL or empirical
    glyph widths at the nominal fontsize under-estimate the actual on-
    screen glyph by that same factor, leading to lines that overflow.

    The empirical scale factor `ASS_RENDER_SCALE` was reverse-engineered
    from the legacy LAYOUT_DEFAULTS: 9:16 + fontsize=20 → max_chars_zh=10
    implies effective glyph_w ≈ 99 px, i.e. ~5× the nominal fontsize.
    """
    short_edge = 1080
    try:
        w_str, h_str = aspect.split(":", 1)
        w_ratio, h_ratio = max(1, int(w_str)), max(1, int(h_str))
    except Exception:
        w_ratio, h_ratio = 9, 16
    # Vertical / square share the same width; horizontal is wider.
    if w_ratio < h_ratio:
        video_width = short_edge
    else:
        video_width = int(short_edge * w_ratio / h_ratio)
    safe_margin = 0.92
    available_px = video_width * safe_margin

    ASS_RENDER_SCALE = 4.7
    glyph_w_nominal = _measure_glyph_width(fontsize, is_chinese, font_path)
    if glyph_w_nominal <= 0:
        glyph_w_nominal = fontsize * (1.0 if is_chinese else 0.55)
    glyph_w = glyph_w_nominal * ASS_RENDER_SCALE
    return max(8, int(available_px / glyph_w * density))


def _measure_glyph_width(fontsize: int, is_chinese: bool,
                          font_path: str | None) -> float:
    """Best-effort PIL-based glyph width measurement. Returns 0.0 on miss
    so caller can fall back to empirical ratios."""
    try:
        from PIL import ImageFont
    except ImportError:
        return 0.0
    candidates: list[str] = []
    if font_path:
        candidates.append(font_path)
    candidates += [
        "C:/Windows/Fonts/msyh.ttc",      # Microsoft YaHei (CJK-capable)
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    sample = ("中文示例字幕一二三四五" if is_chinese
              else "The quick brown fox jumps over a lazy dog")
    for p in candidates:
        if not p:
            continue
        try:
            font = ImageFont.truetype(p, size=fontsize)
            total = font.getlength(sample)
            if total > 0:
                return total / len(sample)
        except Exception:
            continue
    return 0.0


def effective_max_chars(line: SubtitleLineStyle, aspect: str,
                          *, font_path: str | None = None) -> int:
    """Resolve the line's actual max_chars: auto-computed or manual."""
    if line.auto_max_chars:
        return compute_subtitle_max_chars(
            aspect, line.fontsize, line.is_chinese, font_path=font_path)
    return max(1, int(line.manual_max_chars))


# ── Pack ingestion ──────────────────────────────────────────────────────────

def load_pack(postprocess_json_path: str) -> dict:
    """Read a subtitle.pack postprocess.json into memory."""
    with open(postprocess_json_path, "r", encoding="utf-8") as f:
        pack = json.load(f)
    if not isinstance(pack, dict):
        raise ValueError(f"Pack file is not a JSON object: {postprocess_json_path}")
    if not pack.get("segments"):
        raise ValueError(f"Pack file has no 'segments': {postprocess_json_path}")
    return pack


def list_chapters(pack: dict, video_duration: float | None = None) -> list[dict]:
    """Convert pack's segments[] into chapter dicts with start_sec/end_sec.

    end_sec is derived: next chapter's start, or video_duration for the last.
    If video_duration is None, the last chapter's end_sec is left as
    start_sec + 600 (10min) as a coarse fallback — caller should pass a real
    duration via probe_duration() when available.
    """
    raw = pack.get("segments") or []
    chapters: list[dict] = []
    for idx, seg in enumerate(raw):
        time_str = (seg.get("time_str") or "").strip()
        start_sec = parse_timestamp(time_str)
        if start_sec is None:
            continue
        chapters.append({
            "idx": idx,
            "title": (seg.get("title") or "").strip(),
            "refined": (seg.get("refined") or "").strip(),
            "time_str": time_str,
            "start_sec": float(start_sec),
            "end_sec": 0.0,    # filled below
        })
    fallback_end = video_duration if video_duration else 0.0
    for i, ch in enumerate(chapters):
        if i + 1 < len(chapters):
            ch["end_sec"] = chapters[i + 1]["start_sec"]
        elif fallback_end and fallback_end > ch["start_sec"]:
            ch["end_sec"] = float(fallback_end)
        else:
            ch["end_sec"] = ch["start_sec"] + 600.0
    return chapters


def chapter_paragraphs(paragraphs_txt_path: str, chapter_idx: int,
                       chapters: list[dict]) -> str:
    """Extract the raw SRT slice block for one chapter from paragraphs.txt.

    paragraphs.txt format (from write_subtitle_pack):
      "<HH:MM:SS> <title>\n<raw SRT slice>\n\n" blocks.
    We split on blank lines and pick the block whose header matches the
    chapter's time_str + title. Returns empty string if not found.
    """
    if not os.path.exists(paragraphs_txt_path):
        return ""
    if chapter_idx < 0 or chapter_idx >= len(chapters):
        return ""
    target = chapters[chapter_idx]
    target_header_prefix = f"{target['time_str']} {target['title']}".strip()

    with open(paragraphs_txt_path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = re.split(r"\n\s*\n", content)
    for block in blocks:
        first_line = block.splitlines()[0] if block.strip() else ""
        if first_line.strip() == target_header_prefix:
            # body = everything after the first line
            return "\n".join(block.splitlines()[1:]).strip()
    return ""


# ── SRT slicing ─────────────────────────────────────────────────────────────

def load_cues(srt_path: str) -> list[_srt.Subtitle]:
    """Parse an SRT file into a list of Subtitle cues."""
    return list(_srt.parse(read_srt(srt_path)))


def snap_to_cue_boundaries(cues: list[_srt.Subtitle],
                           start_sec: float, end_sec: float
                           ) -> tuple[float, float]:
    """Round (start, end) to the nearest enclosing cue boundaries.

    start → previous cue start ≤ start_sec; end → next cue end ≥ end_sec.
    If no cue brackets the range, returns the input unchanged.
    """
    if not cues:
        return (start_sec, end_sec)
    snapped_start = start_sec
    snapped_end = end_sec
    for cue in cues:
        cs = cue.start.total_seconds()
        ce = cue.end.total_seconds()
        if cs <= start_sec:
            snapped_start = cs
        if ce >= end_sec and snapped_end == end_sec:
            snapped_end = ce
            break
    return (snapped_start, snapped_end)


def slice_srt_for_clip(cues: list[_srt.Subtitle],
                       start_sec: float, end_sec: float,
                       out_path: str) -> str:
    """Write a sub-SRT for the [start_sec, end_sec] window with timestamps
    rebased to start at 0. Returns out_path."""
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


# ── Probing ─────────────────────────────────────────────────────────────────

def probe_duration(video_path: str) -> float:
    """Return video duration in seconds, 0.0 if probe fails."""
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries",
               "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
               video_path]
        out = subprocess.run(cmd, capture_output=True,
                             encoding="utf-8", errors="replace", timeout=15)
        return float(out.stdout.strip()) if out.returncode == 0 else 0.0
    except Exception:
        return 0.0


def probe_resolution(video_path: str) -> tuple[int, int]:
    """Return (width, height) or (0, 0) if probe fails."""
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height", "-of", "csv=p=0",
               video_path]
        out = subprocess.run(cmd, capture_output=True,
                             encoding="utf-8", errors="replace", timeout=15)
        if out.returncode != 0:
            return (0, 0)
        w, h = out.stdout.strip().split(",")
        return (int(w), int(h))
    except Exception:
        return (0, 0)


def extract_keyframe(video_path: str, at_sec: float, out_path: str) -> str:
    """Extract a single JPEG keyframe at `at_sec`. Used by the crop UI to
    show a still frame to draw the rectangle on (Windows VLC HWND can't
    accept tk overlays, so crop is done on a thumbnail)."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    cmd = ["ffmpeg", "-y", "-ss", f"{max(0.0, at_sec):.3f}",
           "-i", video_path, "-vframes", "1",
           "-q:v", "2", out_path]
    proc = subprocess.run(cmd, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=30)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"ffmpeg keyframe extract failed: {proc.stderr[-400:]}")
    return out_path


# ── Crop helpers ────────────────────────────────────────────────────────────

def center_crop_rect(video_w: int, video_h: int,
                       aspect_ratio: tuple[int, int] = (9, 16)) -> dict:
    """Largest centered crop rect at the given aspect that fits in the
    source video. Returns normalized {x, y, w, h} 0..1."""
    if video_w <= 0 or video_h <= 0:
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    aw, ah = aspect_ratio
    target_ar = max(0.001, aw / ah)        # width / height
    cur_ar = video_w / video_h
    if cur_ar > target_ar:
        # Source wider than target → take vertical strip in middle
        new_w = video_h * target_ar
        x = (video_w - new_w) / 2.0
        return {"x": x / video_w, "y": 0.0,
                "w": new_w / video_w, "h": 1.0}
    # Source taller (or equal) → take horizontal strip in middle
    new_h = video_w / target_ar
    y = (video_h - new_h) / 2.0
    return {"x": 0.0, "y": y / video_h,
            "w": 1.0, "h": new_h / video_h}


def crop_rect_to_pixels(rect: dict, video_w: int, video_h: int
                        ) -> tuple[int, int, int, int]:
    """Convert normalized rect → (cw, ch, cx, cy) integer pixels."""
    cw = max(2, int(round(rect["w"] * video_w)))
    ch = max(2, int(round(rect["h"] * video_h)))
    cx = max(0, int(round(rect["x"] * video_w)))
    cy = max(0, int(round(rect["y"] * video_h)))
    # Ensure even dimensions for libx264
    cw -= cw % 2
    ch -= ch % 2
    return (cw, ch, cx, cy)


# ── Clips JSON persistence ──────────────────────────────────────────────────

CLIPS_JSON_VERSION = 1
CUT_FILE_VERSION = 4   # v4 split subtitle into sub1/sub2 + watermark.type;
                        # v3/v2 cuts still readable via from_dict migration


def _hydrate_clip(c: dict) -> ClipDraft:
    return ClipDraft(
        id=c.get("id", 0),
        chapter_idx=c.get("chapter_idx", -1),
        chapter_title=c.get("chapter_title", ""),
        start_sec=float(c.get("start_sec", 0.0)),
        end_sec=float(c.get("end_sec", 0.0)),
        original_excerpt=c.get("original_excerpt", ""),
        hook=c.get("hook", ""),
        outro=c.get("outro", ""),
        title=c.get("title", ""),
        hashtags=list(c.get("hashtags") or []),
        crop_rect=c.get("crop_rect"),
        status=c.get("status", "draft"),
        output_path=c.get("output_path", ""),
    )


def write_cut_file(path: str, *, name: str, sources: dict,
                    clips: list[ClipDraft], output_dir: str = "",
                    ranks: dict[int, dict] | None = None,
                    project_config: ClipProjectConfig | None = None) -> str:
    """Persist a self-contained clip-script project file.

    The cut file is the unit of persistence — a user-named .json that holds
    everything needed to reopen this edit later: source paths, output dir,
    project-level style config, the full clip list, and AI chapter ranks
    (if any).
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    cfg = project_config if project_config is not None else ClipProjectConfig()
    payload = {
        "version": CUT_FILE_VERSION,
        "name": name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "pack_path":  sources.get("pack_path", ""),
            "video_path": sources.get("video_path", ""),
            "srt_path":   sources.get("srt_path", ""),
        },
        "output_dir": output_dir or "",
        "project_config": asdict(cfg),
        # Ranks stored as a list (JSON dicts can't have int keys reliably).
        "ranks": [{"idx": int(idx), **{k: v for k, v in r.items() if k != "idx"}}
                   for idx, r in (ranks or {}).items()],
        "clips": [asdict(c) for c in clips],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_cut_file(path: str) -> dict:
    """Read a cut file. Returns dict with keys:
    name / sources / output_dir / clips (list[ClipDraft]) / ranks (dict) /
    project_config (ClipProjectConfig). v2 files (no project_config) load
    with default style."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    ranks_raw = payload.get("ranks") or []
    ranks: dict[int, dict] = {}
    for r in ranks_raw:
        if isinstance(r, dict) and "idx" in r:
            ranks[int(r["idx"])] = {
                "idx":    int(r["idx"]),
                "score":  int(r.get("score", 0)),
                "reason": str(r.get("reason", "")),
            }
    return {
        "name": payload.get("name", os.path.splitext(os.path.basename(path))[0]),
        "sources": payload.get("sources") or {},
        "output_dir": payload.get("output_dir", ""),
        "project_config": ClipProjectConfig.from_dict(
            payload.get("project_config")),
        "clips": [_hydrate_clip(c) for c in (payload.get("clips") or [])],
        "ranks": ranks,
    }


# Backward-compat aliases for the old write/read API. Older clips.json files
# (version 1) are still readable; new code writes v2 cut files exclusively.

def write_clips_json(clips: list[ClipDraft], video_path: str,
                     basename: str, out_dir: str) -> str:
    """Legacy: emit the v1 -clips.json layout. Kept for back-compat with
    callers that haven't migrated to the cut-file model."""
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{basename}-clips.json")
    payload = {
        "version": CLIPS_JSON_VERSION,
        "source_basename": basename,
        "source_video": os.path.abspath(video_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "clips": [asdict(c) for c in clips],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


def load_clips_json(path: str) -> list[ClipDraft]:
    """Legacy v1 reader. New code should use load_cut_file()."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return [_hydrate_clip(c) for c in (payload.get("clips") or [])]


# ── Export pipeline ─────────────────────────────────────────────────────────

# Drawtext escapes: ffmpeg drawtext text= needs special chars escaped.
# Single quotes can't appear in text='...' literally; use \\\\: for : and
# \\\\\\' for '. We keep the rules narrow because hooks are short user text.
def _escape_drawtext(text: str) -> str:
    if not text:
        return ""
    out = (
        text.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "’")    # convert straight quote to curly to avoid escaping hell
            .replace("%", "\\%")
    )
    return out


def _drawtext_filter(text: str, *, role: str, ho: "HookOutroStyle",
                     duration: float) -> str:
    """Build a drawtext filter for hook (first hook_duration_sec) or outro
    (last outro_duration_sec). `role` ∈ {'hook', 'outro'} drives both the
    enable= window and which position preset is read from `ho`."""
    txt = _escape_drawtext(text)
    if not txt:
        return ""
    if role == "hook":
        position = ho.hook_position
        enable = f"between(t,0,{ho.hook_duration_sec})"
    else:
        position = ho.outro_position
        start = max(0.0, duration - ho.outro_duration_sec)
        enable = f"between(t,{start},{duration})"

    fontfile = _hook_outro_font_path(ho.font).replace(":", "\\:")
    y_expr = _y_expr_for_position(position)
    parts = [
        f"drawtext=text='{txt}'",
        f"fontfile='{fontfile}'",
        f"fontcolor={ho.color}",
        f"fontsize={ho.size}",
        f"x=(w-text_w)/2",
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


def _target_dims_for_aspect(aspect_ratio: tuple[int, int],
                              short_edge: int = 1080) -> tuple[int, int]:
    """Pick output (w, h) honoring the requested aspect at a 1080-class
    short-edge. h264 requires even dimensions, so we round up."""
    aw, ah = aspect_ratio
    if aw < ah:        # vertical
        w, h = short_edge, round(short_edge * ah / aw)
    else:              # horizontal or square
        h, w = short_edge, round(short_edge * aw / ah)
    return ((w + 1) // 2 * 2, (h + 1) // 2 * 2)


def _ass_alignment_for_position(position: str) -> int:
    """ASS alignment code for a top/middle/bottom subtitle position."""
    return {"top": 8, "middle": 5, "bottom": 2}.get(position, 2)


def _build_subtitle_force_style(subtitle: "SubtitleStyle") -> str:
    """Translate the project-level SubtitleStyle into an ASS force_style
    string used by ffmpeg's subtitles= filter. Only sub1 is rendered for
    now — sub2 (bilingual second line) needs a separate SRT source which
    the current burn pipeline doesn't accept yet (M-H.5)."""
    sub1 = subtitle.sub1
    font_name = "Microsoft YaHei" if sub1.is_chinese else "Arial"
    margin_v = 60        # top/bottom margin in pixels at 1080 short-edge
    return (f"Fontname={font_name},"
            f"Fontsize={sub1.fontsize},"
            f"PrimaryColour={hex_color_to_ass(sub1.color)},"
            f"OutlineColour={hex_color_to_ass(subtitle.stroke_color)},"
            f"BorderStyle=1,"
            f"Outline={max(0, int(subtitle.stroke_width))},"
            f"Shadow=0,"
            f"Bold={1 if sub1.bold else 0},"
            f"Alignment={_ass_alignment_for_position(subtitle.position)},"
            f"MarginV={margin_v}")


def _build_text_watermark_drawtext(watermark: "WatermarkStyle",
                                      target_w: int) -> str:
    """Single drawtext snippet for a text-mode watermark, joined into the
    main filter chain. Returns '' when not applicable."""
    if not watermark.enabled or watermark.type != "text":
        return ""
    txt = _escape_drawtext(watermark.text)
    if not txt:
        return ""
    margin = max(20, int(target_w * 0.025))
    pos = watermark.position or "top-right"
    x = f"w-text_w-{margin}" if pos.endswith("right") else f"{margin}"
    y = f"h-text_h-{margin}" if pos.startswith("bottom") else f"{margin}"
    opacity = max(0.0, min(1.0, (watermark.text_opacity or 70) / 100.0))
    return (f"drawtext=text='{txt}':"
            f"fontfile='C\\:/Windows/Fonts/msyh.ttc':"
            f"fontcolor={hex_color_to_ass_rgba(watermark.text_color, opacity)}:"
            f"fontsize={watermark.text_fontsize}:"
            f"x={x}:y={y}:"
            f"borderw=2:bordercolor=black@{opacity*0.5:.2f}")


def _build_image_watermark_chain(watermark: "WatermarkStyle",
                                    target_w: int,
                                    prev_label: str) -> tuple[list[str], str]:
    """Image-mode watermark needs a separate `movie` source + `overlay`
    pair (drawtext can't render external images). Returns:
      (extra_filter_nodes, new_chain_head_label)
    The caller appends `extra_filter_nodes` to the filter_complex parts
    list and uses `new_chain_head_label` as input for downstream filters.
    `prev_label` is what the main chain currently exits as (e.g. "[v1]")."""
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
    # In overlay= expressions: W/H = main video dims, w/h = overlay dims.
    x = f"W-w-{margin}" if pos.endswith("right") else f"{margin}"
    y = f"H-h-{margin}" if pos.startswith("bottom") else f"{margin}"
    return ([
        f"movie='{img_ff}',scale={wm_w}:-1,"
        f"format=rgba,colorchannelmixer=aa={opacity:.3f}[vcwm]",
        f"{prev_label}[vcwm]overlay={x}:{y}[vcvw]",
    ], "[vcvw]")


def hex_color_to_ass_rgba(hex_color: str, alpha: float) -> str:
    """Like hex_color_to_ass but for drawtext (which takes #RRGGBB@alpha)."""
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) == 6:
        return f"#{h.upper()}@{max(0.0, min(1.0, alpha)):.2f}"
    return f"white@{max(0.0, min(1.0, alpha)):.2f}"


def export_clip(
    video_path: str,
    clip: ClipDraft,
    out_dir: str,
    *,
    source_srt: str | None = None,
    project_config: "ClipProjectConfig | None" = None,
    crf: int = 23,
    on_progress: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Render one clip to mp4: trim → crop → scale → burn subtitle →
    watermark → hook/outro. Single ffmpeg invocation via filter_complex.

    project_config drives aspect/encode/subtitle/watermark/hook-outro
    styling. When None, sensible 9:16 defaults are used (back-compat).

    Returns the output path. Raises RuntimeError on ffmpeg failure.
    """
    cfg = project_config or ClipProjectConfig()
    target_w, target_h = _target_dims_for_aspect(cfg.aspect_ratio())
    encode_preset = cfg.encode_preset

    src_w, src_h = probe_resolution(video_path)
    if src_w == 0 or src_h == 0:
        raise RuntimeError(f"Cannot probe video resolution: {video_path}")

    # Crop rect → pixels (default: center-fit at the project's aspect)
    rect = clip.crop_rect or center_crop_rect(src_w, src_h,
                                                aspect_ratio=cfg.aspect_ratio())
    cw, ch, cx, cy = crop_rect_to_pixels(rect, src_w, src_h)

    duration = clip.duration
    if duration <= 0:
        raise ValueError(f"Clip {clip.id} has non-positive duration")

    os.makedirs(out_dir, exist_ok=True)
    title_slug = safe_filename(clip.title or clip.chapter_title or f"clip-{clip.id}")[:40]
    out_name = f"clip-{clip.id:02d}-{title_slug}.mp4"
    out_path = os.path.join(out_dir, out_name)

    # Build temp clipped SRT (rebased to 0) if source SRT provided.
    tmp_srt_path: str | None = None
    if source_srt and os.path.exists(source_srt):
        try:
            cues = load_cues(source_srt)
            # Pre-split for layout to avoid overflow. Use max_chars from
            # cfg.subtitle.sub1 (auto-computed when enabled).
            sub1 = cfg.subtitle.sub1
            if sub1.auto_max_chars:
                max_chars = compute_subtitle_max_chars(
                    cfg.aspect, sub1.fontsize, sub1.is_chinese)
            else:
                max_chars = max(8, sub1.manual_max_chars)
            tmp_srt_path = os.path.join(
                tempfile.gettempdir(),
                f"clip-{clip.id}-{int(clip.start_sec)}.srt"
            )
            slice_srt_for_clip(cues, clip.start_sec, clip.end_sec, tmp_srt_path)
            try:
                split_subs = process_srt_split(
                    tmp_srt_path, max_chars, is_chinese=sub1.is_chinese)
                with open(tmp_srt_path, "w", encoding="utf-8") as f:
                    f.write(_srt.compose(split_subs))
            except Exception:
                pass    # leave un-split on failure; better than no subs
        except Exception:
            tmp_srt_path = None

    # Build filter_complex
    parts: list[str] = []
    cur = "[0:v]"
    parts.append(f"{cur}crop={cw}:{ch}:{cx}:{cy},"
                 f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                 f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
                 f"setsar=1[v0]")
    cur = "[v0]"

    burn_subs = (cfg.subtitle.sub1.enabled and tmp_srt_path
                 and os.path.exists(tmp_srt_path)
                 and os.path.getsize(tmp_srt_path) > 0)
    if burn_subs:
        srt_ff = escape_ffmpeg_path(tmp_srt_path)
        force_style = _build_subtitle_force_style(cfg.subtitle)
        parts.append(f"{cur}subtitles=filename='{srt_ff}':"
                     f"force_style='{force_style}'[v1]")
        cur = "[v1]"

    # Image watermark — separate `movie` source + overlay (cannot ride the
    # drawtext chain). When applicable, this advances `cur` to the post-
    # overlay label.
    img_wm_nodes, cur = _build_image_watermark_chain(
        cfg.watermark, target_w, cur)
    parts.extend(img_wm_nodes)

    # Text watermark + hook + outro — concatenated drawtext filters
    overlay_filters: list[str] = []
    text_wm = _build_text_watermark_drawtext(cfg.watermark, target_w)
    if text_wm:
        overlay_filters.append(text_wm)
    ho = cfg.hook_outro
    if clip.hook:
        overlay_filters.append(_drawtext_filter(
            clip.hook, role="hook", ho=ho, duration=duration))
    if clip.outro:
        overlay_filters.append(_drawtext_filter(
            clip.outro, role="outro", ho=ho, duration=duration))
    if overlay_filters:
        parts.append(f"{cur}{','.join(overlay_filters)}[vout]")
    else:
        parts.append(f"{cur}null[vout]")

    filter_complex = ";".join(parts)

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{clip.start_sec:.3f}",
        "-to", f"{clip.end_sec:.3f}",
        "-i", os.path.abspath(video_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", encode_preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        os.path.abspath(out_path),
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace")
    tail: list[str] = []
    last_pct = -1
    assert proc.stderr is not None
    try:
        for line in proc.stderr:
            tail.append(line)
            if len(tail) > 60:
                tail.pop(0)
            if cancel_check and cancel_check():
                proc.terminate()
                raise InterruptedError("Export cancelled")
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
        if tmp_srt_path and os.path.exists(tmp_srt_path):
            try:
                os.unlink(tmp_srt_path)
            except OSError:
                pass

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg export failed ({proc.returncode}): "
            f"{''.join(tail)[-800:]}"
        )

    clip.output_path = out_path
    clip.status = "exported"
    return out_path


# ── Convenience: bulk export ────────────────────────────────────────────────

def export_all(
    video_path: str,
    clips: list[ClipDraft],
    out_dir: str,
    *,
    source_srt: str | None = None,
    project_config: "ClipProjectConfig | None" = None,
    on_progress: Callable[[int, int, str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[str]:
    """Export each clip in order. on_progress(i, total, status, percent).
    Skips clips whose status == 'skipped'. Stops on cancel."""
    todo = [c for c in clips if c.status != "skipped"]
    total = len(todo)
    out_paths: list[str] = []
    for i, clip in enumerate(todo, 1):
        if cancel_check and cancel_check():
            break
        def _step_progress(status: str, pct: int, _i=i):
            if on_progress:
                on_progress(_i, total, status, pct)
        out_paths.append(export_clip(
            video_path, clip, out_dir,
            source_srt=source_srt,
            project_config=project_config,
            on_progress=_step_progress,
            cancel_check=cancel_check,
        ))
    return out_paths


# ── AI (Phase B) ────────────────────────────────────────────────────────────

# JSON schemas for the three AI calls. Each is a strict structured output
# that the prompt instructs the model to emit verbatim.

RANK_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idx": {"type": "integer"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["idx", "score", "reason"],
            },
        }
    },
    "required": ["ranked"],
}

PEAKS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "peaks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_id": {"type": "integer"},
                    "end_id":   {"type": "integer"},
                    "score":    {"type": "integer"},
                    "reason":   {"type": "string"},
                },
                "required": ["start_id", "end_id", "score", "reason"],
            },
        }
    },
    "required": ["peaks"],
}

PACKAGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "hook":     {"type": "string"},
        "outro":    {"type": "string"},
        "title":    {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "outro", "title", "hashtags"],
}


def _ai_call_json(prompt: str, *, schema: dict, task: str,
                   tier: str = None, cancel_token=None) -> dict:
    """Wrap ai.complete_json with the standard AIError unwrap pattern
    (mirror core/translate.py and core/srt_ops.py).

    Routing: clip.* tasks are aliased to "subtitle.post" so the user's
    existing AI Console config for subtitle pack work covers clip work
    too — no separate routing needed. If users later want to split them,
    add explicit clip.rank / clip.peak / clip.package entries in AI
    Console → Routing.
    """
    from core import ai
    from core.ai.tiers import TIER_STANDARD
    from core.ai.errors import AIError as _AIError

    _tier = tier or TIER_STANDARD
    routed_task = "subtitle.post" if task.startswith("clip.") else task
    try:
        return ai.complete_json(prompt, schema=schema, task=routed_task,
                                 tier=_tier, cancel_token=cancel_token)
    except Exception as e:
        if isinstance(e, _AIError):
            raise
        raise RuntimeError(f"AI call failed (task={task}, tier={_tier}): {e}")


def rank_chapters(pack: dict, paragraphs_txt_path: str = "",
                  video_duration: float | None = None, *,
                  cancel_token=None) -> list[dict]:
    """Score every chapter for highlight potential. Returns a list of
    dicts {idx, score, reason} sorted descending by score.

    Each chapter's full raw paragraphs (SRT slice) is sent to the model so
    scoring reflects actual content, not just AI-generated summaries.
    Falls back to refined summary when paragraphs.txt is absent.
    """
    from core import prompts as _prompts
    from core.ai.tiers import TIER_STANDARD

    chapters = list_chapters(pack, video_duration)
    raw = pack.get("segments") or []
    chapter_list = []
    for idx, seg in enumerate(raw):
        body = ""
        if paragraphs_txt_path and os.path.isfile(paragraphs_txt_path):
            body = chapter_paragraphs(paragraphs_txt_path, idx, chapters)
        if not body:
            body = (seg.get("refined") or "").strip()
        chapter_list.append({
            "idx": idx,
            "title": (seg.get("title") or "").strip(),
            "paragraphs": body,
        })
    if not chapter_list:
        return []

    template = _prompts.get("clip.rank-chapters")
    prompt = template.replace("{chapter_list}",
                               json.dumps(chapter_list, ensure_ascii=False, indent=2))
    result = _ai_call_json(prompt, schema=RANK_SCHEMA,
                            task="clip.rank", tier=TIER_STANDARD,
                            cancel_token=cancel_token)
    ranked_raw = result.get("ranked") or []
    by_idx: dict[int, dict] = {
        int(r["idx"]): {
            "idx": int(r["idx"]),
            "score": max(0, min(100, int(r.get("score", 0)))),
            "reason": str(r.get("reason", "")).strip(),
        }
        for r in ranked_raw if isinstance(r, dict) and "idx" in r
    }
    out: list[dict] = []
    for ch in chapter_list:
        out.append(by_idx.get(ch["idx"],
                               {"idx": ch["idx"], "score": 0, "reason": ""}))
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


def number_cues(cues: list["_srt.Subtitle"]) -> str:
    """Render cue list as numbered text the AI can pick from:
        [#1] [HH:MM:SS] content
        [#2] [HH:MM:SS] content
        ...
    Caller is responsible for keeping the cue list around — id `n` maps to
    cues[n-1]."""
    lines = []
    for i, c in enumerate(cues, start=1):
        total = int(c.start.total_seconds())
        ts = f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
        body = (c.content or "").replace("\n", " ").strip()
        lines.append(f"[#{i}] [{ts}] {body}")
    return "\n".join(lines)


def slice_chapter_cues(cues: list["_srt.Subtitle"],
                        chapter_start_sec: float,
                        chapter_end_sec: float) -> list["_srt.Subtitle"]:
    """Return the cues that overlap the [start, end] chapter window."""
    out = []
    for c in cues:
        cs = c.start.total_seconds()
        ce = c.end.total_seconds()
        if ce <= chapter_start_sec or cs >= chapter_end_sec:
            continue
        out.append(c)
    return out


def find_peaks(pack: dict, chapter_idx: int, cues: list["_srt.Subtitle"],
                video_duration: float | None = None, *,
                cancel_token=None) -> list[dict]:
    """Find 1-3 highlight clip ranges within one chapter.

    Contract: AI receives the chapter's cues numbered with explicit IDs
    and returns {start_id, end_id} pairs (cue indices) — never raw seconds.
    This eliminates AI time guesswork; the outer layer maps IDs back to
    exact cue.start / cue.end seconds.

    Returns [{start_sec, end_sec, score, reason}] derived from cue
    boundaries. Length policy 30 ≤ duration ≤ 90 enforced post-AI;
    out-of-range or invalid peaks are dropped.
    """
    from core import prompts as _prompts
    from core.ai.tiers import TIER_STANDARD

    chapters = list_chapters(pack, video_duration)
    if not (0 <= chapter_idx < len(chapters)):
        return []
    ch = chapters[chapter_idx]

    chapter_cues = slice_chapter_cues(cues, ch["start_sec"], ch["end_sec"])
    if not chapter_cues:
        return []

    numbered = number_cues(chapter_cues)
    template = _prompts.get("clip.find-peaks")
    prompt = template.replace("{chapter_paragraphs}", numbered)
    result = _ai_call_json(prompt, schema=PEAKS_SCHEMA,
                            task="clip.peak", tier=TIER_STANDARD,
                            cancel_token=cancel_token)

    peaks_raw = result.get("peaks") or []
    out: list[dict] = []
    n = len(chapter_cues)
    for p in peaks_raw:
        if not isinstance(p, dict):
            continue
        try:
            sid = int(p["start_id"])
            eid = int(p["end_id"])
        except (KeyError, ValueError, TypeError):
            continue
        if sid < 1 or eid > n or sid > eid:
            continue
        s = chapter_cues[sid - 1].start.total_seconds()
        e = chapter_cues[eid - 1].end.total_seconds()
        if e - s < 30 or e - s > 90:
            continue
        out.append({
            "start_sec": s,
            "end_sec":   e,
            "score":     max(0, min(100, int(p.get("score", 0)))),
            "reason":    str(p.get("reason", "")).strip(),
        })
    return out


def package_clip(clip: ClipDraft, pack: dict, *,
                  cancel_token=None) -> dict:
    """Generate hook / outro / title / hashtags for one clip.
    Returns {hook, outro, title, hashtags}."""
    from core import prompts as _prompts
    from core.ai.tiers import TIER_PREMIUM

    template = _prompts.get("clip.package")
    prompt = template.replace("{clip_excerpt}", clip.original_excerpt or "")
    result = _ai_call_json(prompt, schema=PACKAGE_SCHEMA,
                            task="clip.package", tier=TIER_PREMIUM,
                            cancel_token=cancel_token)
    return {
        "hook":     str(result.get("hook", "")).strip(),
        "outro":    str(result.get("outro", "")).strip(),
        "title":    str(result.get("title", "")).strip(),
        "hashtags": [str(t).strip() for t in (result.get("hashtags") or [])
                      if str(t).strip()],
    }


__all__ = [
    "ClipDraft",
    "ClipProjectConfig",
    "SubtitleStyle",
    "SubtitleLineStyle",
    "WatermarkStyle",
    "HookOutroStyle",
    "BgmConfig",
    "compute_subtitle_max_chars",
    "effective_max_chars",
    "load_pack",
    "list_chapters",
    "chapter_paragraphs",
    "load_cues",
    "snap_to_cue_boundaries",
    "slice_srt_for_clip",
    "probe_duration",
    "probe_resolution",
    "extract_keyframe",
    "center_crop_rect",
    "crop_rect_to_pixels",
    "write_cut_file",
    "load_cut_file",
    "write_clips_json",
    "load_clips_json",
    "export_clip",
    "export_all",
    "rank_chapters",
    "find_peaks",
    "package_clip",
]
