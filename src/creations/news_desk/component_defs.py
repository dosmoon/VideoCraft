"""News-desk component definitions — pure, headless component metadata.

The SINGLE source of news_desk's addable-kind list (registration order +
`multi_instance` gating) and each kind's default instance dict, for the new-arch
(Electron + headless sidecar) workbench's "add component" flow. The Tk component
specs (`creations/news_desk/components/*`) that used to be the parallel twin were
retired with the Tk workbench — this module absorbed their `_default_instance`.

Shape note — the engine is resolution-independent: every visual size/offset is a
fraction (of target height/width; the dogfood invariant "所有视觉尺寸量归一化为
pct of target_h/w"). news_desk now uses the SAME canonical wire shape as clip
and the TS components (one shared edit-UI + mapping): all `*_pct` are float
fractions (`fontsize_pct`/`stroke_pct`/`text_fontsize_pct`/`block_margin_pct`/
`margin_*_pct`), the image watermark uses `image_scale`/`image_opacity` (not the
old `scale_pct`/`opacity`). Defaults are the 1080p-baseline values (28/1080 ≈
0.026, 2/1080 ≈ 0.002, 9% margin = 0.09). Only genuinely-integer fields stay
ints: `bg_opacity`/`text_opacity`/`image_opacity` (0–100) and the chapter strip
fontsizes (absolute px @ 1080 baseline, scaled at the TS layer). The Python
render path never reads these visual fields (the GPU compositor in the renderer
does); the sidecar just stores/forwards the dicts.
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
        "block_margin_pct": 0.09,    # fraction of target_h (9%)
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
        "margin_x_pct": 0.025,       # fraction of target_w (2.5%)
        "margin_y_pct": 0.025,       # fraction of target_h
    }


def _image_watermark(_duration: float) -> dict:
    return {
        "kind": "image_watermark",
        "name": "图片水印",
        "enabled": True,
        "image_path": "",
        "image_scale": 0.15,         # fraction of target_w (15%)
        "image_opacity": 100,        # int 0–100
        "position": "top-right",
        "margin_x_pct": 0.025,       # fraction of target_w
        "margin_y_pct": 0.025,       # fraction of target_h
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
