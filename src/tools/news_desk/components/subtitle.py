"""Subtitle component — one SRT track + its visual style.

Each instance binds to ONE SRT file. Project may have 0..N subtitle
components — render layer currently uses the first 2 enabled ones
(maps to sub1 / sub2 in CompositionStyle). Beyond 2 are silently
ignored at render time; UI surfaces a hint.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from i18n import tr

from . import ComponentSpec, ProjectContext, register


def _default_instance(_duration: float) -> dict:
    return {
        "kind": "subtitle",
        "name": tr("tool.news_desk.subtitle.default_name"),
        "enabled": True,
        "srt_path": "",                # project-relative
        "position": "bottom",          # "top" | "bottom"
        "block_margin_pct": 9,         # % from anchored edge
        "fontsize": 28,
        "color": "#FFFF00",
        "is_chinese": True,
        "stroke_color": "#000000",
        "stroke_width": 2,
        "bg_enabled": True,
        "bg_color": "#000000",
        "bg_opacity": 55,              # 0..100
    }


def _add_color_picker(parent, var: tk.StringVar) -> None:
    from tkinter import colorchooser
    ttk.Entry(parent, textvariable=var, width=10).pack(side="left")
    swatch = tk.Label(parent, text="🎨", width=2)
    swatch.pack(side="left", padx=(2, 0))

    def _pick(_evt=None):
        rgb, hexv = colorchooser.askcolor(
            color=var.get() or "#FFFFFF",
            parent=parent.winfo_toplevel())
        if hexv:
            var.set(hexv.upper())
    swatch.bind("<Button-1>", _pick)


def _build_property_panel(parent: ttk.Frame, instance: dict,
                           ctx: ProjectContext, on_change) -> None:
    name_v = tk.StringVar(value=instance.get("name", ""))
    enabled_v = tk.BooleanVar(value=bool(instance.get("enabled", True)))

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.name"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=name_v).pack(side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Checkbutton(row, text=tr("tool.news_desk.field.enabled"),
                     variable=enabled_v).pack(side="left")

    # Source — SRT picker.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.field.section_source"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    srt_v = tk.StringVar(value=instance.get("srt_path", ""))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="SRT", width=10).pack(side="left")
    ttk.Entry(row, textvariable=srt_v).pack(side="left", fill="x", expand=True)

    def _pick_srt() -> None:
        initial = ctx.project.subtitles_dir
        p = filedialog.askopenfilename(
            parent=parent.winfo_toplevel(),
            initialdir=initial if os.path.isdir(initial) else ctx.project.folder,
            title=tr("tool.news_desk.sub.pick"),
            filetypes=[("SRT", "*.srt"), ("All", "*.*")])
        if p:
            try:
                rel = os.path.relpath(p, ctx.project.folder).replace("\\", "/")
            except ValueError:
                rel = p
            srt_v.set(rel)
    ttk.Button(row, text="…", width=2, command=_pick_srt
               ).pack(side="left", padx=(2, 0))

    # Style — position / size / color / chinese / stroke.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.field.section_style"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    pos_v = tk.StringVar(value=instance.get("position", "bottom"))
    bm_v = tk.IntVar(value=int(instance.get("block_margin_pct", 9)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.position"), width=10
              ).pack(side="left")
    for label, val in (("⬆ top", "top"), ("⬇ bottom", "bottom")):
        ttk.Radiobutton(row, text=label, variable=pos_v, value=val
                        ).pack(side="left", padx=(2, 0))
    ttk.Label(row, text=tr("tool.news_desk.subtitle.block_margin")
              ).pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=40, width=4, textvariable=bm_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    fs_v = tk.IntVar(value=int(instance.get("fontsize", 28)))
    color_v = tk.StringVar(value=instance.get("color", "#FFFF00"))
    cn_v = tk.BooleanVar(value=bool(instance.get("is_chinese", True)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.fontsize"), width=10
              ).pack(side="left")
    ttk.Spinbox(row, from_=10, to=72, width=4, textvariable=fs_v
                 ).pack(side="left")
    ttk.Label(row, text=tr("tool.news_desk.field.text_color")
              ).pack(side="left", padx=(8, 2))
    _add_color_picker(row, color_v)
    ttk.Checkbutton(row, text=tr("tool.news_desk.subtitle.is_chinese"),
                     variable=cn_v).pack(side="left", padx=(8, 0))

    sc_v = tk.StringVar(value=instance.get("stroke_color", "#000000"))
    sw_v = tk.IntVar(value=int(instance.get("stroke_width", 2)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.subtitle.stroke"), width=10
              ).pack(side="left")
    _add_color_picker(row, sc_v)
    ttk.Label(row, text=tr("tool.news_desk.subtitle.stroke_width")
              ).pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=8, width=4, textvariable=sw_v
                 ).pack(side="left")

    # Backdrop (libass opaque box mode).
    bg_en_v = tk.BooleanVar(value=bool(instance.get("bg_enabled", True)))
    bg_color_v = tk.StringVar(value=instance.get("bg_color", "#000000"))
    bg_op_v = tk.IntVar(value=int(instance.get("bg_opacity", 55)))

    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.subtitle.backdrop"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Checkbutton(row, text=tr("tool.news_desk.field.enabled"),
                     variable=bg_en_v).pack(side="left")
    ttk.Label(row, text=tr("tool.news_desk.subtitle.bg_color")
              ).pack(side="left", padx=(8, 2))
    _add_color_picker(row, bg_color_v)
    ttk.Label(row, text=tr("tool.news_desk.field.opacity")
              ).pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=100, width=4, textvariable=bg_op_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    # Hint about render layer limit.
    ttk.Label(parent, text=tr("tool.news_desk.subtitle.render_hint"),
              foreground="#888", wraplength=240, justify="left"
              ).pack(anchor="w", pady=(8, 0))

    def _commit(*_):
        instance["name"] = name_v.get()
        instance["enabled"] = bool(enabled_v.get())
        instance["srt_path"] = srt_v.get()
        instance["position"] = pos_v.get() or "bottom"
        try:
            instance["block_margin_pct"] = int(bm_v.get())
            instance["fontsize"] = int(fs_v.get())
            instance["stroke_width"] = int(sw_v.get())
            instance["bg_opacity"] = int(bg_op_v.get())
        except (tk.TclError, ValueError):
            return
        instance["color"] = color_v.get() or "#FFFF00"
        instance["is_chinese"] = bool(cn_v.get())
        instance["stroke_color"] = sc_v.get() or "#000000"
        instance["bg_enabled"] = bool(bg_en_v.get())
        instance["bg_color"] = bg_color_v.get() or "#000000"
        on_change()

    for v in (name_v, enabled_v, srt_v, pos_v, bm_v, fs_v, color_v, cn_v,
               sc_v, sw_v, bg_en_v, bg_color_v, bg_op_v):
        v.trace_add("write", _commit)


def _to_render_fragment(instance: dict, ctx: ProjectContext) -> dict:
    """Subtitle contributes (srt_path, SubtitleLineStyle) — host collects
    all enabled instances and feeds the first two into render layer's
    sub1 / sub2 slots."""
    from core.composition.style import SubtitleLineStyle
    if not instance.get("enabled", True) or not instance.get("srt_path"):
        return {"subtitle": None}
    rel = instance.get("srt_path", "")
    abs_path = os.path.normpath(os.path.join(ctx.project.folder, rel)) \
                if rel and not os.path.isabs(rel) else rel
    line = SubtitleLineStyle(
        enabled=True,
        fontsize=int(instance.get("fontsize", 28)),
        color=instance.get("color", "#FFFFFF"),
        is_chinese=bool(instance.get("is_chinese", False)),
        bg_color=instance.get("bg_color", "#000000"),
        bg_opacity=(int(instance.get("bg_opacity", 0))
                     if instance.get("bg_enabled", True) else 0),
    )
    return {
        "subtitle": {
            "srt_path": abs_path,
            "line": line,
            "position": instance.get("position", "bottom"),
            "block_margin_pct": float(instance.get("block_margin_pct", 9)) / 100.0,
        }
    }


register(ComponentSpec(
    kind="subtitle",
    name_key="tool.news_desk.kind.subtitle",
    add_label_key="tool.news_desk.add.subtitle",
    multi_instance=True,
    default_z=90,                       # subtitles render above most things
    default_instance=_default_instance,
    build_property_panel=_build_property_panel,
    to_overlays=_to_render_fragment,
    import_sources=[],
))
