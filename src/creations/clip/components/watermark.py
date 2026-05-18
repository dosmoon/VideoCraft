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

import tkinter as tk
from tkinter import filedialog, ttk

from core.composition.compile import ClipRange, CompileContext
from core.composition.style import CompositionStyle
from core.composition.timeline import Element
from creations.news_desk.components import ComponentSpec, ProjectContext

from . import add_color_picker, register


_POSITIONS = ["top-left", "top-right", "bottom-left", "bottom-right"]


KIND_TEXT = "clip_text_watermark"
KIND_IMAGE = "clip_image_watermark"


# ── default_instance ───────────────────────────────────────────────────────

def _default_text_instance(_duration: float) -> dict:
    # text_fontsize_pct is a fraction of the short edge (see
    # core/composition/layout.py). 0.033 ≈ 36px at 1080 short edge.
    return {
        "kind": KIND_TEXT,
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
        "text_fontsize_pct": float(instance.get("text_fontsize_pct", 0.033)),
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


# ── Migration — extract template dict from legacy WatermarkStyle ──────────

def template_from_style(style: CompositionStyle) -> list[dict]:
    """One-time bootstrap: turn a legacy CompositionStyle.watermark into
    the matching component instance dict (text or image based on
    `wm.type`). Disabled or empty content → []. Pure template; used
    only by clip_tool startup migration.
    """
    wm = style.watermark
    if not wm.enabled:
        return []
    common = {
        "id": "wm",
        "name": "watermark",
        "enabled": True,
        "position": wm.position,
        "margin_x_pct": float(wm.margin_x_pct),
        "margin_y_pct": float(wm.margin_y_pct),
        "text_fontsize_pct": int(wm.text_fontsize) / 1080.0,
        "text_color": wm.text_color,
        "text_opacity": int(wm.text_opacity),
        "image_scale": float(wm.image_scale),
        "image_opacity": int(wm.image_opacity),
    }
    if wm.type == "image":
        return [{**common, "kind": KIND_IMAGE,
                  "image_path": wm.image_path or ""}]
    return [{**common, "kind": KIND_TEXT, "text": wm.text or ""}]


# ── property panels ────────────────────────────────────────────────────────

def _build_text_panel(parent: ttk.Frame, instance: dict,
                       _ctx: ProjectContext, on_change) -> None:
    name_v = tk.StringVar(value=instance.get("name", ""))
    enabled_v = tk.BooleanVar(value=bool(instance.get("enabled", True)))
    text_v = tk.StringVar(value=instance.get("text", ""))
    fs_v = tk.IntVar(value=int(round(
        float(instance.get("text_fontsize_pct", 0.033)) * 1080)))
    color_v = tk.StringVar(value=instance.get("text_color", "#FFFFFF"))
    op_v = tk.IntVar(value=int(instance.get("text_opacity", 70)))
    pos_v = tk.StringVar(value=instance.get("position", "top-right"))
    mx_v = tk.IntVar(value=int(
        float(instance.get("margin_x_pct", 0.025)) * 100))
    my_v = tk.IntVar(value=int(
        float(instance.get("margin_y_pct", 0.025)) * 100))

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="名称", width=10).pack(side="left")
    ttk.Entry(row, textvariable=name_v).pack(
        side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Checkbutton(row, text="启用", variable=enabled_v).pack(side="left")

    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="内容",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="文本", width=10).pack(side="left")
    ttk.Entry(row, textvariable=text_v).pack(
        side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="字号", width=10).pack(side="left")
    ttk.Spinbox(row, from_=8, to=200, width=4, textvariable=fs_v
                 ).pack(side="left")
    ttk.Label(row, text="px").pack(side="left")
    ttk.Label(row, text="颜色").pack(side="left", padx=(8, 2))
    add_color_picker(row, color_v)
    ttk.Label(row, text="不透明").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=100, width=4, textvariable=op_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="位置",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="锚点", width=10).pack(side="left")
    ttk.Combobox(row, textvariable=pos_v, values=_POSITIONS,
                  state="readonly", width=14).pack(side="left")
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="X 边距", width=10).pack(side="left")
    ttk.Spinbox(row, from_=0, to=20, width=4, textvariable=mx_v
                 ).pack(side="left")
    ttk.Label(row, text="%  Y 边距").pack(side="left", padx=(2, 2))
    ttk.Spinbox(row, from_=0, to=20, width=4, textvariable=my_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    def _commit(*_):
        instance["name"] = name_v.get()
        instance["enabled"] = bool(enabled_v.get())
        instance["text"] = text_v.get()
        try:
            instance["text_fontsize_pct"] = float(fs_v.get()) / 1080.0
            instance["text_opacity"] = int(op_v.get())
            instance["margin_x_pct"] = float(mx_v.get()) / 100.0
            instance["margin_y_pct"] = float(my_v.get()) / 100.0
        except (tk.TclError, ValueError):
            return
        instance["text_color"] = color_v.get() or "#FFFFFF"
        instance["position"] = pos_v.get() or "top-right"
        on_change()

    for v in (name_v, enabled_v, text_v, fs_v, color_v, op_v,
               pos_v, mx_v, my_v):
        v.trace_add("write", _commit)


def _build_image_panel(parent: ttk.Frame, instance: dict,
                        _ctx: ProjectContext, on_change) -> None:
    name_v = tk.StringVar(value=instance.get("name", ""))
    enabled_v = tk.BooleanVar(value=bool(instance.get("enabled", True)))
    path_v = tk.StringVar(value=instance.get("image_path", ""))
    scale_v = tk.IntVar(value=int(
        float(instance.get("image_scale", 0.15)) * 100))
    op_v = tk.IntVar(value=int(instance.get("image_opacity", 100)))
    pos_v = tk.StringVar(value=instance.get("position", "top-right"))
    mx_v = tk.IntVar(value=int(
        float(instance.get("margin_x_pct", 0.025)) * 100))
    my_v = tk.IntVar(value=int(
        float(instance.get("margin_y_pct", 0.025)) * 100))

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="名称", width=10).pack(side="left")
    ttk.Entry(row, textvariable=name_v).pack(
        side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Checkbutton(row, text="启用", variable=enabled_v).pack(side="left")

    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="图片",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Entry(row, textvariable=path_v).pack(
        side="left", fill="x", expand=True)

    def _browse() -> None:
        p = filedialog.askopenfilename(
            parent=parent.winfo_toplevel(),
            filetypes=[("Image", "*.png *.jpg *.jpeg *.bmp"),
                        ("All", "*.*")])
        if p:
            path_v.set(p)
    ttk.Button(row, text="...", command=_browse, width=3
                ).pack(side="left", padx=(4, 0))

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="缩放", width=10).pack(side="left")
    ttk.Spinbox(row, from_=1, to=80, width=4, textvariable=scale_v
                 ).pack(side="left")
    ttk.Label(row, text="% 不透明").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=100, width=4, textvariable=op_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="位置",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="锚点", width=10).pack(side="left")
    ttk.Combobox(row, textvariable=pos_v, values=_POSITIONS,
                  state="readonly", width=14).pack(side="left")
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="X 边距", width=10).pack(side="left")
    ttk.Spinbox(row, from_=0, to=20, width=4, textvariable=mx_v
                 ).pack(side="left")
    ttk.Label(row, text="%  Y 边距").pack(side="left", padx=(2, 2))
    ttk.Spinbox(row, from_=0, to=20, width=4, textvariable=my_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    def _commit(*_):
        instance["name"] = name_v.get()
        instance["enabled"] = bool(enabled_v.get())
        instance["image_path"] = path_v.get()
        try:
            instance["image_scale"] = float(scale_v.get()) / 100.0
            instance["image_opacity"] = int(op_v.get())
            instance["margin_x_pct"] = float(mx_v.get()) / 100.0
            instance["margin_y_pct"] = float(my_v.get()) / 100.0
        except (tk.TclError, ValueError):
            return
        instance["position"] = pos_v.get() or "top-right"
        on_change()

    for v in (name_v, enabled_v, path_v, scale_v, op_v,
               pos_v, mx_v, my_v):
        v.trace_add("write", _commit)


# ── register ───────────────────────────────────────────────────────────────

register(ComponentSpec(
    kind=KIND_TEXT,
    name_key="clip.component.text_watermark.name",
    add_label_key="clip.component.text_watermark.add",
    multi_instance=True,
    default_z=75,
    default_instance=_default_text_instance,
    build_property_panel=_build_text_panel,
    compile=_compile_text,
))

register(ComponentSpec(
    kind=KIND_IMAGE,
    name_key="clip.component.image_watermark.name",
    add_label_key="clip.component.image_watermark.add",
    multi_instance=True,
    default_z=75,
    default_instance=_default_image_instance,
    build_property_panel=_build_image_panel,
    compile=_compile_image,
))
