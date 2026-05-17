"""topic_strip primitive — top-edge labeled strip.

A thin always-on strip showing the current chapter or topic title.
Auto-derivable from analysis.json (one strip per chapter, time window
= chapter [start, end]); also user-editable in news_desk.

Bundles: Spec dataclass (data) + Style dataclass (visuals) +
build_dialogues() helper that emits libass dialogue strings the
news_desk_ass orchestrator merges into the per-render .ass file.

After Axis 7.4/7.5 the typed Overlay class moved here; legacy import
sites still see `TopicStripOverlay` via the shim in
`core.composition.overlays`. PR 5 (timeline migration) drops that
alias when callers update.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..libass_helpers import rect_dialogue, text_dialogue


# ── Spec (per-render content data) ──────────────────────────────────────────

@dataclass
class TopicStripSpec:
    """Top-edge labeled strip — chapter marker / topic bar.

    style_class: key into CompositionStyle.overlay_styles → TopicStripStyle.
    """
    topic_text: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    style_class: str = "default"
    kind: str = "topic_strip"
    z_order: int = 40
    zone: str = "banner_top"


# Legacy alias — overlays.py shim re-exports this name during PR 2~5.
TopicStripOverlay = TopicStripSpec


# ── Style (visual fields) ───────────────────────────────────────────────────

@dataclass
class TopicStripStyle:
    """Visual style for TopicStripSpec — top-edge labeled strip."""
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


# ── Dialogue builder (consumed by news_desk_ass orchestrator) ──────────────

def build_dialogues(spec: TopicStripSpec, style: TopicStripStyle,
                     *, target_w: int, target_h: int) -> list[str]:
    """Top-edge full-width strip with a single text run inside."""
    if not spec.topic_text:
        return []

    strip_h = max(8, int(style.height_pct * target_h))
    strip_y = max(0, int(style.top_margin_pct * target_h))
    strip_x = 0
    strip_w = target_w
    pad_px = max(8, int(style.text_padding_pct * target_w))

    lines: list[str] = []
    lines.append(rect_dialogue(
        spec.start_sec, spec.end_sec,
        x=strip_x, y=strip_y, w=strip_w, h=strip_h,
        color_hex=style.bg_color, opacity=style.bg_opacity, layer=0,
    ))

    # Text vertically centered in the strip.
    text_y = strip_y + strip_h // 2
    if style.text_align == "center":
        text_x = target_w // 2
        anchor = 5    # middle-center
    elif style.text_align == "right":
        text_x = target_w - pad_px
        anchor = 6    # middle-right
    else:
        text_x = pad_px
        anchor = 4    # middle-left
    lines.append(text_dialogue(
        spec.start_sec, spec.end_sec,
        x=text_x, y=text_y, anchor=anchor,
        text=spec.topic_text, fontname=style.font,
        fontsize=style.fontsize, color_hex=style.text_color,
        bold=style.bold,
    ))
    return lines
