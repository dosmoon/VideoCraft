"""Clip watermark components — text and image, one each.

Two registered specs (clip_text_watermark / clip_image_watermark),
matching the engine's two primitive kinds. Clip's legacy
WatermarkStyle is a single dataclass with a `type` field that picks
between text and image at render time; the seeder dispatches to one
spec or the other, but never both at once.

Per docs/draft/clip-component-migration.md §2.6 we intentionally
write our own copies here rather than reuse news_desk's; the shared-
library refactor is a deferred follow-up.

Step 5.2 — render path only. UI rewrite ships with Step 5.5.
"""

from __future__ import annotations

from core.composition.compile import ClipRange, CompileContext
from core.composition.style import CompositionStyle
from core.composition.timeline import Element
from creations.news_desk.components import ComponentSpec

from . import ComponentDictAdapter, register


KIND_TEXT = "clip_text_watermark"
KIND_IMAGE = "clip_image_watermark"


# ── default_instance ───────────────────────────────────────────────────────

def _default_text_instance(_duration: float) -> dict:
    return {
        "kind": KIND_TEXT,
        "id": "wm_text",
        "name": "text watermark",
        "enabled": True,
        "text": "",
        "text_fontsize": 36,
        "text_color": "#FFFFFF",
        "text_opacity": 70,
        "position": "top-right",
        "margin_x_pct": 0.025,
        "margin_y_pct": 0.025,
    }


def _default_image_instance(_duration: float) -> dict:
    return {
        "kind": KIND_IMAGE,
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


# ── Shared style-dict packer — byte-equal to the legacy inline builder ────

def _style_dict(instance: dict) -> dict:
    """Pack the style fields into the dict shape that drawtext_filter /
    overlay_filter expect at render time. Mirrors the dict the pre-5.2
    inline watermark branch emitted so byte-shape stays stable."""
    return {
        "text_fontsize": int(instance.get("text_fontsize", 36)),
        "text_color": instance.get("text_color", "#FFFFFF"),
        "text_opacity": int(instance.get("text_opacity", 70)),
        "image_scale": float(instance.get("image_scale", 0.15)),
        "image_opacity": int(instance.get("image_opacity", 100)),
        "position": instance.get("position", "top-right"),
        "margin_x_pct": float(instance.get("margin_x_pct", 0.025)),
        "margin_y_pct": float(instance.get("margin_y_pct", 0.025)),
    }


# ── compile() — text watermark ─────────────────────────────────────────────

def _compile_text(instance: dict, clip_range: ClipRange,
                   _ctx: CompileContext) -> list[Element]:
    text = (instance.get("text") or "").strip()
    if not text:
        return []
    return [Element(
        kind="text_watermark",
        start_sec=0.0,
        end_sec=clip_range.duration_sec,
        style=_style_dict(instance),
        data={"text": instance.get("text", ""), "image_path": ""},
    )]


# ── compile() — image watermark ────────────────────────────────────────────

def _compile_image(instance: dict, clip_range: ClipRange,
                    _ctx: CompileContext) -> list[Element]:
    path = (instance.get("image_path") or "").strip()
    if not path:
        return []
    return [Element(
        kind="image_watermark",
        start_sec=0.0,
        end_sec=clip_range.duration_sec,
        style=_style_dict(instance),
        data={"text": "", "image_path": instance.get("image_path", "")},
    )]


# ── Seeder — legacy WatermarkStyle → at most one adapter ───────────────────

def watermark_adapters_from_style(
    style: CompositionStyle,
) -> list[ComponentDictAdapter]:
    """Translate the legacy CompositionStyle.watermark into at most one
    transient watermark component adapter (text or image based on
    `wm.type`). Disabled or empty content → no adapter.

    Step 5.2 — temporary bridge. Retires with Step 5.5 alongside
    StylePanel's watermark form.
    """
    wm = style.watermark
    if not wm.enabled:
        return []
    is_image = (wm.type == "image")
    if is_image:
        instance = {
            "kind": KIND_IMAGE,
            "id": "wm",
            "name": "watermark",
            "enabled": True,
            "image_path": wm.image_path or "",
            "image_scale": float(wm.image_scale),
            "image_opacity": int(wm.image_opacity),
            "position": wm.position,
            "margin_x_pct": float(wm.margin_x_pct),
            "margin_y_pct": float(wm.margin_y_pct),
            # carry text-side fields too so _style_dict has consistent
            # shape regardless of mode (byte-equal with legacy)
            "text_fontsize": int(wm.text_fontsize),
            "text_color": wm.text_color,
            "text_opacity": int(wm.text_opacity),
        }
    else:
        instance = {
            "kind": KIND_TEXT,
            "id": "wm",
            "name": "watermark",
            "enabled": True,
            "text": wm.text or "",
            "text_fontsize": int(wm.text_fontsize),
            "text_color": wm.text_color,
            "text_opacity": int(wm.text_opacity),
            "position": wm.position,
            "margin_x_pct": float(wm.margin_x_pct),
            "margin_y_pct": float(wm.margin_y_pct),
            # image fields too — same reason
            "image_scale": float(wm.image_scale),
            "image_opacity": int(wm.image_opacity),
        }
    return [ComponentDictAdapter(instance)]


# ── register ───────────────────────────────────────────────────────────────

register(ComponentSpec(
    kind=KIND_TEXT,
    name_key="clip.component.text_watermark.name",
    add_label_key="clip.component.text_watermark.add",
    multi_instance=True,
    default_z=75,
    default_instance=_default_text_instance,
    build_property_panel=None,    # lands with 5.5
    compile=_compile_text,
))

register(ComponentSpec(
    kind=KIND_IMAGE,
    name_key="clip.component.image_watermark.name",
    add_label_key="clip.component.image_watermark.add",
    multi_instance=True,
    default_z=75,
    default_instance=_default_image_instance,
    build_property_panel=None,    # lands with 5.5
    compile=_compile_image,
))
