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
    sub2 = secondary (Latin, regular).

    Per-line backdrop (bg_*): when bg_opacity > 0 the cue is rendered in
    libass "opaque box" mode (BorderStyle=3) — a fitted translucent
    rectangle behind each line. Lets subtitles stay readable on top of
    source-baked banners / chyrons without touching the source frame."""
    enabled: bool = True
    fontsize: int = 24
    color: str = "#FFFFFF"
    bold: bool = False
    is_chinese: bool = False         # affects glyph-width / line-break logic
    # Per-line backdrop. opacity=0 keeps legacy outline-only rendering.
    bg_color: str = "#000000"
    bg_opacity: int = 0              # 0-100; 0 disables the box mode
    bg_padding_x_pct: float = 0.006  # extra padding around glyphs (fraction of frame height)


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


# ── Overlay style classes (named library, used by news_desk overlays) ──────
#
# CompositionStyle.overlay_styles is a dict keyed by `style_class` name
# (e.g. "default", "breaking", "interview"). Each value is one of these
# style dataclasses, picked at render time by matching the overlay's
# `kind` to the dataclass type. Storage on disk is dict-of-dicts (asdict
# round-trips); the typed loader in presets.py coerces back to dataclass.

@dataclass
class LowerThirdStyle:
    """Visual style for LowerThirdOverlay — title + subtitle on a colored
    bar anchored to the bottom safe area.

    Industry defaults: bar height ~10-15% of frame; title font 4-6% of
    frame height; subtitle ~60% of title size. Margin ≥ 5% from bottom
    edge keeps the bar inside title-safe area on broadcast displays.
    """
    # Bar background.
    bg_color: str = "#0F172A"
    bg_opacity: int = 88              # 0-100
    accent_color: str = "#C8102E"     # left-edge accent bar (broadcast convention)
    accent_width_pct: float = 0.006   # fraction of frame width; 0 disables

    # Title (large name).
    title_color: str = "#FFFFFF"
    title_fontsize: int = 38
    title_bold: bool = True
    # Subtitle (role / affiliation).
    subtitle_color: str = "#E2E8F0"
    subtitle_fontsize: int = 24
    subtitle_bold: bool = False

    font: str = "Microsoft YaHei"

    # Position — fraction of frame dimension. margin_x_pct from the
    # anchored side edge, margin_y_pct from the bottom edge.
    margin_x_pct: float = 0.05
    margin_y_pct: float = 0.10        # ≥ 0.05 keeps inside title-safe
    # Bar inner padding (fraction of frame height).
    padding_pct: float = 0.012
    # Title-to-subtitle vertical gap (fraction of frame height).
    line_gap_pct: float = 0.005


@dataclass
class TopicStripStyle:
    """Visual style for TopicStripOverlay — top-edge labeled strip."""
    bg_color: str = "#1E40AF"
    bg_opacity: int = 90
    text_color: str = "#FFFFFF"
    fontsize: int = 26
    bold: bool = True
    font: str = "Microsoft YaHei"

    # Strip geometry. height_pct = strip thickness as fraction of frame height.
    height_pct: float = 0.055
    # Distance from top edge (lets you leave a sliver of source video
    # showing above the strip if desired).
    top_margin_pct: float = 0.0
    # Horizontal text alignment within the strip.
    text_align: str = "left"          # "left" | "center" | "right"
    # Inner left/right text padding (fraction of frame width).
    text_padding_pct: float = 0.025


@dataclass
class ChapterPointCardStyle:
    """Broadcast lower-third style — text on a fitted semi-transparent
    dark band with a left red accent stripe (CNN / Reuters / 央视 L3
    convention).

    Default position is the lower-third zone (y_pct=0.70), above the
    subtitle band. The band auto-sizes to text width + padding so it
    reads as a framed graphic, not a full-width ticker.
    """
    # Text.
    text_color: str = "#FFFFFF"
    fontsize: int = 40
    bold: bool = True
    # SimHei (黑体) reads squarer / more "news-y" than YaHei's rounder
    # shape. Fallback chain handled by the font engine.
    font: str = "SimHei"

    # Background band — semi-transparent dark fill behind the text.
    bg_color: str = "#0F172A"
    bg_opacity: int = 78

    # Left accent stripe (broadcast convention). 0 = stripe off.
    accent_color: str = "#C8102E"
    accent_width_pct: float = 0.004    # fraction of frame width

    # Inner padding — fraction of frame dim. Padding is what gives the
    # band its visible "card" feel rather than tight text-hugging.
    padding_x_pct: float = 0.020
    padding_y_pct: float = 0.014

    # Vertical center of the band, as fraction of frame height. 0.70 sits
    # in the broadcast lower-third zone, above the subtitle band
    # (subtitle outer track baseline ≈ 92%, inner ≈ 80%).
    y_pct: float = 0.70
    # Line-to-line vertical gap when text wraps to 2 lines.
    line_gap_pct: float = 0.005
    # Pre-wrap budget for the text.
    max_chars_per_line: int = 22

    # Entrance animation. fade_in / fade_out durations in milliseconds;
    # slide_in_px = the band+text lift up by this many pixels on entry.
    fade_in_ms: int = 350
    fade_out_ms: int = 300
    slide_in_px: int = 24


@dataclass
class ChapterHeroCardStyle:
    """Hero/intro card — large centered card carrying a chapter title +
    multi-line body. Bigger than ChapterPointCardStyle (a thin L3 band)
    and centered rather than lower-third anchored.

    Card auto-sizes to fit text + padding, capped at max_width_pct of
    the frame width. Body text wraps to body_max_lines lines (surplus
    truncated with …).
    """
    # Title (large, top of card).
    title_color: str = "#FFFFFF"
    title_fontsize: int = 56
    title_bold: bool = True
    # Body (smaller, multi-line under title).
    body_color: str = "#E5E7EB"
    body_fontsize: int = 28
    body_bold: bool = False
    # Card backdrop.
    bg_color: str = "#000000"
    bg_opacity: int = 75
    # Card geometry — fractions of frame dim.
    max_width_pct: float = 0.72
    padding_x_pct: float = 0.035
    padding_y_pct: float = 0.030
    title_body_gap_pct: float = 0.020
    y_pct: float = 0.45               # vertical center; 0.45 sits slightly above middle
    # Body wrap budget.
    body_max_chars_per_line: int = 36
    body_max_lines: int = 4
    # Animation.
    fade_in_ms: int = 400
    fade_out_ms: int = 350
    font: str = "Microsoft YaHei"


@dataclass
class DateStampStyle:
    """Visual style for DateStampOverlay — small persistent corner label.

    Compact by default (Bloomberg-style bug): small font, optional dark
    backdrop for legibility on busy backgrounds. Pin to a corner via
    DateStampOverlay.position; this style only controls look + offsets.
    """
    text_color: str = "#FFFFFF"
    fontsize: int = 22
    bold: bool = False
    font: str = "SimHei"

    # Optional backdrop. bg_opacity=0 → no rectangle (clean text only).
    bg_color: str = "#0F172A"
    bg_opacity: int = 60
    padding_x_pct: float = 0.008
    padding_y_pct: float = 0.004

    # Distance from the anchored corner — fraction of frame dim.
    margin_x_pct: float = 0.025
    margin_y_pct: float = 0.025


# Registry of typed overlay-style classes by `kind` discriminator. Render
# and preview look up the matching class to coerce dict → dataclass.
OVERLAY_STYLE_CLASSES: dict[str, type] = {
    "lower_third": LowerThirdStyle,
    "topic_strip": TopicStripStyle,
    "chapter_point_card": ChapterPointCardStyle,
    "chapter_hero_card": ChapterHeroCardStyle,
    "date_stamp": DateStampStyle,
}


def resolve_overlay_style(overlay_styles: dict, kind: str,
                            style_class: str = "default"):
    """Look up an overlay style instance from the dict library.

    `overlay_styles` schema on disk:
        {
            "lower_third": {"default": {...LowerThirdStyle dict...}, ...},
            "topic_strip": {"default": {...TopicStripStyle dict...}, ...},
        }

    Returns a typed dataclass instance. Falls back to default-constructed
    style if the requested class is missing — so missing-preset never
    breaks the render.
    """
    cls = OVERLAY_STYLE_CLASSES.get(kind)
    if cls is None:
        return None
    by_kind = (overlay_styles or {}).get(kind) or {}
    raw = by_kind.get(style_class)
    if raw is None and style_class != "default":
        raw = by_kind.get("default")
    if not isinstance(raw, dict):
        return cls()
    fields = cls.__dataclass_fields__
    kwargs = {k: v for k, v in raw.items() if k in fields}
    try:
        return cls(**kwargs)
    except TypeError:
        return cls()


def default_overlay_styles() -> dict:
    """Build the seed overlay_styles dict — one default class per known
    overlay kind. Presets that want custom looks override entries here."""
    from dataclasses import asdict
    return {
        kind: {"default": asdict(cls())}
        for kind, cls in OVERLAY_STYLE_CLASSES.items()
    }


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
    """Resolve a line's max_chars by computing from aspect + fontsize."""
    return compute_subtitle_max_chars(
        aspect, line.fontsize, line.is_chinese, font_path=font_path)
