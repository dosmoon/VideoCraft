"""Image watermark component — pinned image overlay."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from i18n import tr

from . import ComponentSpec, ProjectContext, register


_POSITIONS = ["top-left", "top-right", "bottom-left", "bottom-right"]


def _default_instance(_duration: float) -> dict:
    return {
        "kind": "image_watermark",
        "name": tr("tool.news_desk.image_wm.default_name"),
        "enabled": True,
        "image_path": "",
        "scale_pct": 15,            # % of frame width
        "opacity": 100,             # 0..100
        "position": "top-right",
        "margin_x_pct": 2.5,        # % of frame width
        "margin_y_pct": 2.5,        # % of frame height
    }


def _build_property_panel(parent: ttk.Frame, instance: dict,
                           _ctx: ProjectContext, on_change) -> None:
    # Header — name + enabled.
    name_v = tk.StringVar(value=instance.get("name", ""))
    enabled_v = tk.BooleanVar(value=bool(instance.get("enabled", True)))

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.name"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=name_v).pack(side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Checkbutton(row, text=tr("tool.news_desk.field.enabled"),
                     variable=enabled_v).pack(side="left")

    # Content — image path + scale.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.field.section_content"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    img_v = tk.StringVar(value=instance.get("image_path", ""))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.image_wm.image_path"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=img_v).pack(side="left", fill="x", expand=True)

    def _pick_image() -> None:
        p = filedialog.askopenfilename(
            parent=parent.winfo_toplevel(),
            title=tr("tool.news_desk.image_wm.image_path"),
            filetypes=[("Image", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if p:
            img_v.set(p)
    ttk.Button(row, text="…", width=2, command=_pick_image
               ).pack(side="left", padx=(2, 0))

    scale_v = tk.IntVar(value=int(instance.get("scale_pct", 15)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.image_wm.scale"), width=10
              ).pack(side="left")
    ttk.Spinbox(row, from_=2, to=50, width=5, textvariable=scale_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    # Position + opacity + margins.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.field.section_position"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    pos_v = tk.StringVar(value=instance.get("position", "top-right"))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.position"), width=10
              ).pack(side="left")
    ttk.Combobox(row, textvariable=pos_v, values=_POSITIONS,
                  state="readonly", width=14).pack(side="left")

    op_v = tk.IntVar(value=int(instance.get("opacity", 100)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.opacity"), width=10
              ).pack(side="left")
    ttk.Spinbox(row, from_=0, to=100, width=5, textvariable=op_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    mx_v = tk.IntVar(value=int(instance.get("margin_x_pct", 2)))
    my_v = tk.IntVar(value=int(instance.get("margin_y_pct", 2)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.margin"), width=10
              ).pack(side="left")
    ttk.Label(row, text="X").pack(side="left", padx=(0, 2))
    ttk.Spinbox(row, from_=0, to=20, width=4, textvariable=mx_v
                 ).pack(side="left")
    ttk.Label(row, text="%  Y").pack(side="left", padx=(0, 2))
    ttk.Spinbox(row, from_=0, to=20, width=4, textvariable=my_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    # Wire live edits — every var write commits to instance + notifies host.
    def _commit(*_):
        instance["name"] = name_v.get()
        instance["enabled"] = bool(enabled_v.get())
        instance["image_path"] = img_v.get()
        try:
            instance["scale_pct"] = int(scale_v.get())
            instance["opacity"] = int(op_v.get())
            instance["margin_x_pct"] = int(mx_v.get())
            instance["margin_y_pct"] = int(my_v.get())
        except (tk.TclError, ValueError):
            return
        instance["position"] = pos_v.get() or "top-right"
        on_change()

    for v in (name_v, enabled_v, img_v, scale_v, op_v,
               pos_v, mx_v, my_v):
        v.trace_add("write", _commit)


def _to_render_fragment(instance: dict, _ctx: ProjectContext) -> dict:
    """Translate to a render fragment. Image watermark contributes a
    WatermarkStyle in image mode. Host packs all enabled watermarks
    (image + text) into the renderer's extra_watermarks list — each
    chains as its own movie / overlay pair in filter_complex."""
    from core.composition.style import WatermarkStyle
    if not instance.get("enabled", True) or not instance.get("image_path"):
        return {"watermark": None}
    wm = WatermarkStyle(
        enabled=True,
        type="image",
        image_path=instance.get("image_path", ""),
        image_scale=max(0.02, min(0.50,
            float(instance.get("scale_pct", 15)) / 100.0)),
        image_opacity=max(0, min(100, int(instance.get("opacity", 100)))),
        position=instance.get("position", "top-right"),
        margin_x_pct=max(0.0, min(0.20,
            float(instance.get("margin_x_pct", 2)) / 100.0)),
        margin_y_pct=max(0.0, min(0.20,
            float(instance.get("margin_y_pct", 2)) / 100.0)),
    )
    return {"watermark": wm}


def _compile(instance: dict, clip_range, _ctx) -> list:
    """Timeline-IR compile — emits at most one image_watermark Element
    spanning the full clip range. Empty path or disabled returns []."""
    from core.composition.timeline import Element
    if not instance.get("enabled", True) or not instance.get("image_path"):
        return []
    style_dict = {
        "image_scale": max(0.02, min(0.50,
            float(instance.get("scale_pct", 15)) / 100.0)),
        "image_opacity": max(0, min(100, int(instance.get("opacity", 100)))),
        "position": instance.get("position", "top-right"),
        "margin_x_pct": max(0.0, min(0.20,
            float(instance.get("margin_x_pct", 2)) / 100.0)),
        "margin_y_pct": max(0.0, min(0.20,
            float(instance.get("margin_y_pct", 2)) / 100.0)),
    }
    return [Element(
        kind="image_watermark",
        start_sec=0.0,
        end_sec=clip_range.duration_sec,
        style=style_dict,
        data={"image_path": instance.get("image_path", "")},
    )]


register(ComponentSpec(
    kind="image_watermark",
    name_key="tool.news_desk.kind.image_watermark",
    add_label_key="tool.news_desk.add.image_watermark",
    multi_instance=True,
    default_z=80,                      # high — sits near top of stack
    default_instance=_default_instance,
    build_property_panel=_build_property_panel,
    to_overlays=_to_render_fragment,
    compile=_compile,
    import_sources=[],
))
