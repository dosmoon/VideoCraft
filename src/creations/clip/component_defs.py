"""Clip component definitions — pure, headless component metadata.

The new-arch (Electron + headless sidecar) twin of the Tk component specs in
`creations/clip/components/*`. Those spec modules import tkinter at module top
(they carry the property-panel builders), so the UI-free sidecar can't import
them. This module re-states only the *pure* parts the workbench's "add
component" flow needs — the addable-kind list (registration order +
`multi_instance` gating) and each kind's default instance dict.

The default instance dicts are copied verbatim from the Tk specs'
`_default_*` functions:
  - subtitle      → creations/clip/components/subtitle.py::_default_instance
  - text/image wm → creations/clip/components/watermark.py::_default_*_instance
  - hook/outro    → creations/clip/components/hook_outro.py::_default_*_instance

⚠️ Temporary duplication (pre-alpha): the Tk specs are the soon-to-retire twin.
When the Tk workbench is removed, this module becomes the single source and the
spec modules' `_default_*` go away with them. Keep the two in sync until then.
"""

from __future__ import annotations

from typing import Callable


# ── default instance factories (verbatim from the Tk specs) ─────────────────

def _subtitle(_duration: float) -> dict:
    return {
        "kind": "clip_subtitle",
        "id": "sub1",
        "name": "subtitle",
        "enabled": True,
        "language": "",
        "fontsize_pct": 0.05,
        "color": "#FFFFFF",
        "bold": False,
        "is_chinese": False,
        "bg_color": "#000000",
        "bg_opacity": 0,
        "bg_padding_x_pct": 0.0,
        "stroke_color": "#000000",
        "stroke_pct": 0.002,
        "position": "bottom",
        "block_margin_pct": 0.09,
    }


def _text_watermark(_duration: float) -> dict:
    return {
        "kind": "clip_text_watermark",
        "id": "wm_text",
        "name": "text watermark",
        "enabled": True,
        "text": "",
        "text_fontsize_pct": 0.033,
        "text_color": "#FFFFFF",
        "text_opacity": 70,
        "position": "top-right",
        "margin_x_pct": 0.025,
        "margin_y_pct": 0.025,
    }


def _image_watermark(_duration: float) -> dict:
    return {
        "kind": "clip_image_watermark",
        "id": "wm_image",
        "name": "image watermark",
        "enabled": True,
        "image_path": "",
        "image_scale": 0.15,
        "image_opacity": 100,
        "position": "top-right",
        "margin_x_pct": 0.025,
        "margin_y_pct": 0.025,
    }


def _hook_card(_duration: float) -> dict:
    return {
        "kind": "clip_hook_card",
        "id": "hook",
        "name": "hook card",
        "enabled": True,
        "text": "",
        "font": "Microsoft YaHei",
        "size_pct": 0.05,
        "color": "#FFFFFF",
        "bg_color": "#000000",
        "bg_opacity": 70,
        "stroke_color": "#000000",
        "stroke_pct": 0.003,
        "box_padding_pct": 0.012,
        "position": "upper-third",
        "duration_sec": 5.0,
    }


def _outro_card(_duration: float) -> dict:
    return {
        "kind": "clip_outro_card",
        "id": "outro",
        "name": "outro card",
        "enabled": True,
        "text": "",
        "font": "Microsoft YaHei",
        "size_pct": 0.05,
        "color": "#FFFFFF",
        "bg_color": "#000000",
        "bg_opacity": 70,
        "stroke_color": "#000000",
        "stroke_pct": 0.003,
        "box_padding_pct": 0.012,
        "position": "lower-third",
        "duration_sec": 5.0,
    }


# ── addable-kind registry (registration order = [+ Add] menu order) ─────────

_FACTORIES: dict[str, Callable[[float], dict]] = {
    "clip_subtitle": _subtitle,
    "clip_text_watermark": _text_watermark,
    "clip_image_watermark": _image_watermark,
    "clip_hook_card": _hook_card,
    "clip_outro_card": _outro_card,
}

# `multi_instance` mirrors each spec's register(...) call. Subtitle and both
# watermarks allow multiple instances; hook/outro are single-instance, so the
# [+ Add] menu disables them once one exists.
ADDABLE: list[dict] = [
    {"kind": "clip_subtitle", "multi_instance": True},
    {"kind": "clip_text_watermark", "multi_instance": True},
    {"kind": "clip_image_watermark", "multi_instance": True},
    {"kind": "clip_hook_card", "multi_instance": False},
    {"kind": "clip_outro_card", "multi_instance": False},
]


def default_instance(kind: str, duration: float = 0.0) -> dict:
    """A fresh default instance dict for `kind`. Raises on an unknown kind
    (catches typos at the call site, like the Tk spec lookup did)."""
    factory = _FACTORIES.get(kind)
    if factory is None:
        raise ValueError(f"unknown component kind: {kind!r}")
    return factory(duration)
