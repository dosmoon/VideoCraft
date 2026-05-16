"""Text watermark component — small text overlay pinned to a corner.

Doubles as the date stamp use case (with [⇩ from event_date] import).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from i18n import tr
from materials.news_video import schema as source_context

from . import ComponentSpec, ImportSource, ProjectContext, register


_POSITIONS = ["top-left", "top-right", "bottom-left", "bottom-right"]


def _default_instance(_duration: float) -> dict:
    return {
        "kind": "text_watermark",
        "name": tr("tool.news_desk.text_wm.default_name"),
        "enabled": True,
        "text": "",
        "fontsize": 36,
        "color": "#FFFFFF",
        "opacity": 70,
        "position": "top-right",
        "margin_x_pct": 2.5,
        "margin_y_pct": 2.5,
    }


def _add_color_picker(parent, var: tk.StringVar) -> None:
    """Inline color swatch + entry. Click swatch → colorchooser."""
    from tkinter import colorchooser
    ent = ttk.Entry(parent, textvariable=var, width=10)
    ent.pack(side="left")
    swatch = tk.Label(parent, text="🎨", width=2)
    swatch.pack(side="left", padx=(2, 0))

    def _pick(_evt=None):
        rgb, hexv = colorchooser.askcolor(
            color=var.get() or "#FFFFFF",
            parent=parent.winfo_toplevel(),
            title=tr("tool.news_desk.style.color_picker_title"))
        if hexv:
            var.set(hexv.upper())
    swatch.bind("<Button-1>", _pick)


def _build_property_panel(parent: ttk.Frame, instance: dict,
                           _ctx: ProjectContext, on_change) -> None:
    name_v = tk.StringVar(value=instance.get("name", ""))
    enabled_v = tk.BooleanVar(value=bool(instance.get("enabled", True)))

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.name"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=name_v).pack(side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Checkbutton(row, text=tr("tool.news_desk.field.enabled"),
                     variable=enabled_v).pack(side="left")

    # Content — text + size + color + opacity.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.field.section_content"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    text_v = tk.StringVar(value=instance.get("text", ""))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.text_wm.text"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=text_v).pack(side="left", fill="x", expand=True)

    fs_v = tk.IntVar(value=int(instance.get("fontsize", 36)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.fontsize"), width=10
              ).pack(side="left")
    ttk.Spinbox(row, from_=8, to=96, width=5, textvariable=fs_v
                 ).pack(side="left")

    color_v = tk.StringVar(value=instance.get("color", "#FFFFFF"))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.text_color"), width=10
              ).pack(side="left")
    _add_color_picker(row, color_v)

    op_v = tk.IntVar(value=int(instance.get("opacity", 70)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.opacity"), width=10
              ).pack(side="left")
    ttk.Spinbox(row, from_=0, to=100, width=5, textvariable=op_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    # Position + margins.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.field.section_position"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    pos_v = tk.StringVar(value=instance.get("position", "top-right"))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.position"), width=10
              ).pack(side="left")
    ttk.Combobox(row, textvariable=pos_v, values=_POSITIONS,
                  state="readonly", width=14).pack(side="left")

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

    def _commit(*_):
        instance["name"] = name_v.get()
        instance["enabled"] = bool(enabled_v.get())
        instance["text"] = text_v.get()
        try:
            instance["fontsize"] = int(fs_v.get())
            instance["opacity"] = int(op_v.get())
            instance["margin_x_pct"] = int(mx_v.get())
            instance["margin_y_pct"] = int(my_v.get())
        except (tk.TclError, ValueError):
            return
        instance["color"] = color_v.get() or "#FFFFFF"
        instance["position"] = pos_v.get() or "top-right"
        on_change()

    for v in (name_v, enabled_v, text_v, fs_v, color_v,
               op_v, pos_v, mx_v, my_v):
        v.trace_add("write", _commit)


def _to_render_fragment(instance: dict, _ctx: ProjectContext) -> dict:
    """Text watermark contributes a WatermarkStyle in text mode. Host
    packs all enabled watermarks (text + image) into the renderer's
    extra_watermarks list — each chains as its own drawtext / overlay."""
    from core.composition.style import WatermarkStyle
    if not instance.get("enabled", True) or not instance.get("text", "").strip():
        return {"watermark": None}
    wm = WatermarkStyle(
        enabled=True,
        type="text",
        text=instance.get("text", ""),
        text_fontsize=max(8, int(instance.get("fontsize", 36))),
        text_color=instance.get("color", "#FFFFFF"),
        text_opacity=max(0, min(100, int(instance.get("opacity", 70)))),
        position=instance.get("position", "top-right"),
        margin_x_pct=max(0.0, min(0.20,
            float(instance.get("margin_x_pct", 2)) / 100.0)),
        margin_y_pct=max(0.0, min(0.20,
            float(instance.get("margin_y_pct", 2)) / 100.0)),
    )
    return {"watermark": wm}


def _import_event_date(instance: dict, ctx: ProjectContext) -> None:
    """[⇩ Import event date] — pull date from the canonical combined view
    (context.json's AI-corrected value wins, basic_info as fallback) and
    nudge defaults toward the date-stamp look (smaller, bottom-left)."""
    merged = source_context.combined_dict(ctx.project.source_dir)
    date = (merged.get("event_date") or "").strip()
    if not date:
        return
    instance["text"] = date
    # Datestamp look: smaller font, bottom-left, more transparent.
    instance["fontsize"] = 28
    instance["position"] = "bottom-left"
    if not instance.get("name") or instance["name"] == tr(
            "tool.news_desk.text_wm.default_name"):
        instance["name"] = tr("tool.news_desk.text_wm.imported_date_name")


register(ComponentSpec(
    kind="text_watermark",
    name_key="tool.news_desk.kind.text_watermark",
    add_label_key="tool.news_desk.add.text_watermark",
    multi_instance=True,
    default_z=75,
    default_instance=_default_instance,
    build_property_panel=_build_property_panel,
    to_overlays=_to_render_fragment,
    import_sources=[
        ImportSource(
            label_key="tool.news_desk.text_wm.import_event_date",
            handler=_import_event_date,
        ),
    ],
))
