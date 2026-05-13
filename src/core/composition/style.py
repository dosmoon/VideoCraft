"""CompositionStyle schema — pure dataclasses, no migration shims.

The single source of truth for "how should the output video look": aspect,
subtitle layout, watermark, hook/outro card, plus a reusable `overlay_styles`
class library for future news-desk style elements (lower-thirds, chapter
cards, etc.). Consumed by render.py (ffmpeg side) and preview.py (WebView
side); both layers see the exact same field set.

Schema is intentionally flat and unversioned. We don't carry compatibility
code for the old ClipProjectConfig — JSON that doesn't match the current
dataclass shape is rejected at load time, not silently migrated.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Subtitle ────────────────────────────────────────────────────────────────

@dataclass
class SubtitleLineStyle:
    """One subtitle track's per-line style. Two lines (sub1 / sub2) per
    composition — typically sub1 = primary language (CJK, bold, larger),
    sub2 = secondary (Latin, regular)."""
    enabled: bool = True
    fontsize: int = 24
    color: str = "#FFFFFF"
    bold: bool = False
    is_chinese: bool = False         # affects glyph-width / line-break logic
    auto_max_chars: bool = True      # compute from aspect+fontsize at runtime
    manual_max_chars: int = 20       # used only when auto_max_chars is False


@dataclass
class SubtitleStyle:
    sub1: SubtitleLineStyle = field(default_factory=lambda: SubtitleLineStyle(
        enabled=True, fontsize=24, color="#FFFF00",
        bold=True, is_chinese=True))
    sub2: SubtitleLineStyle = field(default_factory=lambda: SubtitleLineStyle(
        enabled=False, fontsize=24, color="#FFFFFF",
        bold=False, is_chinese=False))
    stroke_color: str = "#000000"
    stroke_width: int = 2
    position: str = "bottom"          # "top" | "middle" | "bottom" (anchor edge)
    # Normalized layout — fraction of frame height. Both libass and the
    # WebView preview consume these via core.composition.layout helpers,
    # so visual positions match across engines.
    block_margin_pct: float = 0.08    # outer track baseline distance from anchored edge
    track_gap_pct: float = 0.12       # baseline gap between sub1 and sub2


# ── Watermark ───────────────────────────────────────────────────────────────

@dataclass
class WatermarkStyle:
    enabled: bool = False
    type: str = "image"               # "image" | "text"
    # Image-mode fields
    image_path: str = ""
    image_scale: float = 0.15         # fraction of video width (0.0-1.0)
    image_opacity: int = 100          # 0-100
    # Text-mode fields
    text: str = ""
    text_fontsize: int = 36
    text_color: str = "#FFFFFF"
    text_opacity: int = 70
    # Common
    position: str = "top-right"       # top-left | top-right | bottom-left | bottom-right
    # Normalized margin from the anchored corner — fraction of frame dim.
    # Both renderers consume via core.composition.layout.pixel_offset so
    # the visual gap from the corner matches across engines.
    margin_x_pct: float = 0.025
    margin_y_pct: float = 0.025


# ── Hook / Outro card ───────────────────────────────────────────────────────

@dataclass
class HookOutroStyle:
    font: str = "Microsoft YaHei"     # font NAME; resolved via fonts.hook_outro_font_path
    size: int = 48
    color: str = "#FFFFFF"
    bg_color: str = "#000000"
    bg_opacity: int = 70              # 0-100; 0 disables the background box
    stroke_color: str = "#000000"
    stroke_width: int = 3             # 0 disables the outline
    box_padding: int = 10             # drawtext boxborderw
    hook_position: str = "upper-third"   # see fonts.y_expr_for_position
    outro_position: str = "lower-third"
    hook_duration_sec: float = 5.0
    outro_duration_sec: float = 5.0


# ── Output geometry ─────────────────────────────────────────────────────────

@dataclass
class OutputGeometry:
    """How source frames map to the output canvas.

    Two modes:
    - `reframe`: crop the source to `aspect` then scale to `short_edge`.
      Clip derivative uses this — short-form vertical output at 1080p.
    - `passthrough`: keep source dimensions verbatim, skip crop/scale/pad.
      Bilingual subtitle burn uses this — preserve 4K, 4:3, anything.

    For passthrough, the `aspect` and `short_edge` fields are ignored at
    render time (effective values are derived from the probed source).
    They're persisted anyway so toggling back to reframe restores the
    user's last reframe choice.
    """
    mode: str = "reframe"             # "reframe" | "passthrough"
    aspect: str = "9:16"              # reframe-only: "9:16"|"16:9"|"1:1"|"4:5"
    short_edge: int = 1080            # reframe-only: output short edge (px)

    def aspect_ratio(self) -> tuple[int, int]:
        """Parse aspect string into (width_ratio, height_ratio).
        For passthrough mode the caller should use probed source dims
        instead — this only reflects the persisted reframe choice."""
        try:
            w, h = self.aspect.split(":", 1)
            return (max(1, int(w)), max(1, int(h)))
        except (ValueError, AttributeError):
            return (9, 16)


# ── Top-level CompositionStyle ─────────────────────────────────────────────

@dataclass
class CompositionStyle:
    """Project-level output style — one CompositionStyle drives one clip
    (or batch of clips) through the render pipeline.

    `overlay_styles` is the named class library for future overlay kinds
    (lower-third, chapter-card, ticker, breaking-news bug, ...). Concrete
    classes are not yet defined — the dict slot reserves the schema seat
    so news_desk derivatives can grow into it without breaking presets.
    """
    output: OutputGeometry = field(default_factory=OutputGeometry)
    encode_preset: str = "veryfast"   # ffmpeg x264 preset
    subtitle: SubtitleStyle = field(default_factory=SubtitleStyle)
    watermark: WatermarkStyle = field(default_factory=WatermarkStyle)
    hook_outro: HookOutroStyle = field(default_factory=HookOutroStyle)
    overlay_styles: dict = field(default_factory=dict)

    def aspect_ratio(self) -> tuple[int, int]:
        """Delegate to output. Kept on the top-level style for
        ergonomic access by consumers that haven't been updated to read
        `style.output.aspect_ratio()` directly."""
        return self.output.aspect_ratio()


# ── Auto max-chars per subtitle line ────────────────────────────────────────

def compute_subtitle_max_chars(aspect: str, fontsize: int, is_chinese: bool,
                                 *, density: float = 1.0,
                                 font_path: str | None = None,
                                 short_edge: int = 1080) -> int:
    """How many chars per line before the subtitle visually overflows when
    burned via ffmpeg's `subtitles=` (libass) filter.

    libass renders an SRT against a default PlayResX/Y of ~384 while the
    video is 1080-class, so a `Fontsize=24` style is actually rendered at
    roughly 24×(1080/384)≈4.7x its nominal pixel size. The empirical scale
    factor was reverse-engineered from the legacy LAYOUT_DEFAULTS table.

    `short_edge` defaults to 1080 (clip / standard reframe output). For
    passthrough renders preserving source resolution (e.g. 4K bilingual
    burn) the caller passes the actual source short edge so wrap budgets
    scale with the real frame width.
    """
    try:
        w_str, h_str = aspect.split(":", 1)
        w_ratio, h_ratio = max(1, int(w_str)), max(1, int(h_str))
    except (ValueError, AttributeError):
        w_ratio, h_ratio = 9, 16
    if w_ratio < h_ratio:
        video_width = short_edge
    else:
        video_width = int(short_edge * w_ratio / h_ratio)
    safe_margin = 0.92
    available_px = video_width * safe_margin

    ass_render_scale = 4.7
    glyph_w_nominal = _measure_glyph_width(fontsize, is_chinese, font_path)
    if glyph_w_nominal <= 0:
        glyph_w_nominal = fontsize * (1.0 if is_chinese else 0.55)
    glyph_w = glyph_w_nominal * ass_render_scale
    return max(8, int(available_px / glyph_w * density))


def _measure_glyph_width(fontsize: int, is_chinese: bool,
                          font_path: str | None) -> float:
    """Best-effort PIL-based glyph width measurement. Returns 0.0 on miss
    so the caller can fall back to an empirical ratio."""
    try:
        from PIL import ImageFont
    except ImportError:
        return 0.0
    candidates: list[str] = []
    if font_path:
        candidates.append(font_path)
    candidates += [
        "C:/Windows/Fonts/msyh.ttc",
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
    """Resolve a line's actual max_chars: auto-computed or manual."""
    if line.auto_max_chars:
        return compute_subtitle_max_chars(
            aspect, line.fontsize, line.is_chinese, font_path=font_path)
    return max(1, int(line.manual_max_chars))
