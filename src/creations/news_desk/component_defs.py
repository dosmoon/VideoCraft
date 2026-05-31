"""News-desk component definitions — pure, headless component metadata.

The new-arch (Electron + headless sidecar) twin of the Tk component specs in
`creations/news_desk/components/*`. Those spec modules import tkinter at module
top (they carry the property-panel builders), so the UI-free sidecar can't
import them. This module re-states only the *pure* parts the workbench's "add
component" flow needs — the addable-kind list (registration order +
`multi_instance` gating) and each kind's default instance dict.

⚠️ One deliberate deviation from the Tk specs' `_default_instance` (NOT a
verbatim copy, unlike clip's component_defs):

  The Tk specs emit subtitle/text-watermark font + stroke sizes as ABSOLUTE
  pixels (`fontsize: 28`, `stroke_width: 2`). The new engine is
  resolution-independent — every visual size is a fraction of target height
  (the dogfood invariant "所有视觉尺寸量归一化为 pct of target_h"). So this
  module emits the CANONICAL fraction shape the already-merged TS layer
  consumes (`fontsize_pct`/`stroke_pct`, and `text_fontsize_pct`/`text_color`/
  `text_opacity` for the text watermark — see desktop/src/creations/news_desk/
  types.ts + mapping.ts). The defaults are the 1080p-baseline conversions of the
  Tk values (28/1080 ≈ 0.026, 2/1080 ≈ 0.002), so a fresh component looks the
  same. Fields that news_desk keeps as integers on purpose (block_margin_pct,
  bg_opacity, scale_pct, margins, chapter strip fontsize) match the Tk specs
  verbatim — the TS mapping normalises those.

  The Python render path never reads these visual fields (the GPU compositor in
  the renderer does), so this shape change is opaque to the sidecar — it just
  stores/forwards the dicts.

⚠️ Temporary duplication (pre-alpha): the Tk specs are the soon-to-retire twin.
When the Tk workbench is removed, this module becomes the single source and the
spec modules' `_default_instance` go away with them.
"""

from __future__ import annotations

from typing import Callable


# ── default instance factories (canonical shape; see module docstring) ──────

def _subtitle(_duration: float) -> dict:
    return {
        "kind": "subtitle",
        "name": "字幕",
        "enabled": True,
        "srt_path": "",
        "position": "bottom",
        "block_margin_pct": 9,       # int percent of target_h (TS /100)
        "fontsize_pct": 0.026,       # fraction of target_h (28px @ 1080)
        "color": "#FFFF00",
        "is_chinese": True,
        "stroke_color": "#000000",
        "stroke_pct": 0.002,         # fraction of target_h (2px @ 1080)
        "bg_enabled": True,
        "bg_color": "#000000",
        "bg_opacity": 55,            # int 0–100
    }


def _text_watermark(_duration: float) -> dict:
    return {
        "kind": "text_watermark",
        "name": "文字水印",
        "enabled": True,
        "text": "",
        "text_fontsize_pct": 0.026,  # fraction of target_h (28px @ 1080)
        "text_color": "#FFFFFF",
        "text_opacity": 70,          # int 0–100
        "position": "top-right",
        "margin_x_pct": 2.5,         # int-ish percent (TS /100)
        "margin_y_pct": 2.5,
    }


def _image_watermark(_duration: float) -> dict:
    return {
        "kind": "image_watermark",
        "name": "图片水印",
        "enabled": True,
        "image_path": "",
        "scale_pct": 15,             # int percent (TS /100)
        "opacity": 100,              # int 0–100
        "position": "top-right",
        "margin_x_pct": 2.5,
        "margin_y_pct": 2.5,
    }


def _chapter(_duration: float) -> dict:
    return {
        "kind": "chapter",
        "name": "章节",
        "enabled": True,
        "modes": {"top_strip": True, "start_card": False},
        "style": {
            "top_strip": {
                "bg_color": "#1E40AF",
                "text_color": "#FFFFFF",
                "fontsize": 26,      # int px @ 1080 baseline (TS scales it)
            },
            "start_card": {
                "title_color": "#FFFFFF",
                "title_fontsize": 40,
                "body_color": "#E5E7EB",
                "body_fontsize": 22,
                "bg_color": "#0F1B2C",
                "bg_opacity": 55,
                "accent_color": "#DC2626",
                "duration_sec": 6,
            },
        },
        "schedule": [],              # filled from material chapters at preview/render
    }


# ── addable-kind registry (registration order = [+ Add] menu order) ─────────
# Mirrors components/__init__.py's side-effect import order (chapter, subtitle,
# text_watermark, image_watermark) and each spec's `multi_instance`. Chapter is
# a singleton (bound to the source's analysis.json chapters); the rest allow
# multiple instances (e.g. bilingual = two subtitle components).

_FACTORIES: dict[str, Callable[[float], dict]] = {
    "chapter": _chapter,
    "subtitle": _subtitle,
    "text_watermark": _text_watermark,
    "image_watermark": _image_watermark,
}

ADDABLE: list[dict] = [
    {"kind": "chapter", "multi_instance": False},
    {"kind": "subtitle", "multi_instance": True},
    {"kind": "text_watermark", "multi_instance": True},
    {"kind": "image_watermark", "multi_instance": True},
]


def default_instance(kind: str, duration: float = 0.0) -> dict:
    """A fresh default instance dict for `kind`. Raises on an unknown kind
    (catches typos at the call site, like the Tk spec lookup did). The owner
    assigns the unique `id` (component_defs intentionally omits it)."""
    factory = _FACTORIES.get(kind)
    if factory is None:
        raise ValueError(f"unknown component kind: {kind!r}")
    return factory(duration)
