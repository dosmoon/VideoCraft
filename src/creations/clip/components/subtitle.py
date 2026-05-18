"""Clip subtitle component — one language per instance.

Each subtitle component is bound to ONE language code (e.g. "en", "zh").
Want a bilingual clip? Add two subtitle components, each picking a
different language. Style/position are independent per component.

Unlike news_desk subtitles (which snapshot a user-picked SRT file into
the instance dir), clip subtitles never store a path: the SRT comes
from the bound material's hotclips pool, looked up by language code at
compile time. `composer.expand_for_candidate` stamps `srt_path` into a
deep-copied instance dict before each spec.compile invocation.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

import srt as _srt

from core.composition.compile import ClipRange, CompileContext
from core.composition.style import CompositionStyle
from core.composition.timeline import Element
from creations.news_desk.components import ComponentSpec, ProjectContext

from . import add_color_picker, register


KIND = "clip_subtitle"


# ── default_instance ───────────────────────────────────────────────────────

def _default_instance(_duration: float) -> dict:
    """Used by [+ Add Subtitle]. `language` is filled by the host
    (style_panel._on_add) after creation so it can default to the
    active Tab-1 language pick."""
    return {
        "kind": KIND,
        "id": "sub1",
        "name": "subtitle",
        "enabled": True,
        # Language code — host fills on add, user changes via property
        # panel dropdown. composer.expand_for_candidate resolves this
        # against the material's SRT pool to stamp `srt_path`.
        "language": "",
        # Per-line style. fontsize_pct / stroke_pct are FRACTIONS OF THE
        # SHORT EDGE (canonical 1080) — see core/composition/layout.py.
        # That single convention is what keeps preview ≡ render for
        # font sizing across the engine. 0.05 ≈ 54px at 1080 short edge,
        # a normal subtitle size.
        "fontsize_pct": 0.05,
        "color": "#FFFFFF",
        "bold": False,
        "is_chinese": False,
        "bg_color": "#000000",
        "bg_opacity": 0,
        "bg_padding_x_pct": 0.0,
        # Position / stroke shared style. stroke_pct also fraction of
        # short edge; 0.002 ≈ 2px.
        "stroke_color": "#000000",
        "stroke_pct": 0.002,
        "position": "bottom",
        "block_margin_pct": 0.09,
    }


# ── compile — instance dict + ctx → Elements ───────────────────────────────

def _compile(instance: dict, clip_range: ClipRange,
             _ctx: CompileContext) -> list[Element]:
    """Pure: parse SRT, slice to [clip_range], rebase to 0, emit one
    subtitle_cue Element per surviving cue. Mirrors the byte-shape that
    timeline_builder._srt_to_subtitle_elements produced pre-5.1."""
    srt_path = instance.get("srt_path") or ""
    if not srt_path or not os.path.isfile(srt_path):
        return []
    try:
        with open(srt_path, "r", encoding="utf-8", errors="replace") as f:
            cues = list(_srt.parse(f.read()))
    except (OSError, ValueError):
        return []

    style_dict = {
        # Sizes carried as short-edge fractions; consumers (libass force
        # style, preview canvas) multiply by short_edge to get pixels.
        "fontsize_pct": float(instance.get("fontsize_pct", 0.05)),
        "color": instance.get("color", "#FFFFFF"),
        "bold": bool(instance.get("bold", False)),
        "is_chinese": bool(instance.get("is_chinese", False)),
        "bg_color": instance.get("bg_color", "#000000"),
        "bg_opacity": int(instance.get("bg_opacity", 0)),
        "bg_padding_x_pct": float(instance.get("bg_padding_x_pct", 0.0)),
        "stroke_color": instance.get("stroke_color", "#000000"),
        "stroke_pct": float(instance.get("stroke_pct", 0.002)),
        "position": instance.get("position", "bottom"),
        "block_margin_pct": float(instance.get("block_margin_pct", 0.09)),
    }
    # Composer.expand_for_candidate stamps `effective_block_margin_pct`
    # with the post-stacking edge offset. Render (libass MarginV) and
    # preview (canvas edge) both multiply this single pct by their own
    # frame height — no separate margin_v cache needed now that libass
    # script units equal target pixels (see subtitle_cue.original_size).
    if "effective_block_margin_pct" in instance:
        style_dict["effective_block_margin_pct"] = float(
            instance["effective_block_margin_pct"])

    base = float(clip_range.start_sec)
    eff_end = float(clip_range.end_sec)
    out: list[Element] = []
    for cue in cues:
        cs = cue.start.total_seconds()
        ce = cue.end.total_seconds()
        if ce <= base or cs >= eff_end:
            continue
        new_start = max(base, cs) - base
        new_end = min(eff_end, ce) - base
        if new_end <= new_start:
            continue
        out.append(Element(
            kind="subtitle_cue",
            start_sec=new_start,
            end_sec=new_end,
            style=style_dict,
            data={"text": cue.content},
        ))
    return out


# ── Migration — extract template dicts from legacy CompositionStyle ────────

def template_from_style(style: CompositionStyle) -> list[dict]:
    """One-shot bootstrap from legacy CompositionStyle.subtitle (pre-5.5
    config shape). Only sub1's visual style is preserved; dual-track
    (sub2) is dropped — users who had bilingual clips re-add a second
    subtitle component via the new language picker. `language` is left
    empty for the host to fill on first open."""
    sub = style.subtitle
    if not sub.sub1.enabled:
        return []
    # Legacy CompositionStyle.subtitle stores fontsize / stroke_width
    # as integers. Pre-alpha: lossy convert to pct by dividing by the
    # canonical 1080 short-edge baseline — user can re-tune in the
    # property panel if the visual size is off.
    line = sub.sub1
    return [{
        "kind": KIND,
        "id": "sub1",
        "name": "sub1",
        "enabled": True,
        "language": "",
        "fontsize_pct": int(line.fontsize) / 1080.0,
        "color": line.color,
        "bold": bool(line.bold),
        "is_chinese": bool(line.is_chinese),
        "bg_color": line.bg_color,
        "bg_opacity": int(line.bg_opacity),
        "bg_padding_x_pct": float(line.bg_padding_x_pct),
        "stroke_color": sub.stroke_color,
        "stroke_pct": int(sub.stroke_width) / 1080.0,
        "position": sub.position,
        "block_margin_pct": float(sub.block_margin_pct),
    }]


# ── property panel ─────────────────────────────────────────────────────────

def _build_property_panel(parent: ttk.Frame, instance: dict,
                           ctx: ProjectContext, on_change) -> None:
    name_v = tk.StringVar(value=instance.get("name", ""))
    enabled_v = tk.BooleanVar(value=bool(instance.get("enabled", True)))
    lang_v = tk.StringVar(value=instance.get("language", ""))

    # Identity row
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="名称", width=10).pack(side="left")
    ttk.Entry(row, textvariable=name_v).pack(
        side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Checkbutton(row, text="启用", variable=enabled_v).pack(side="left")
    ttk.Label(row, text="语言").pack(side="left", padx=(12, 4))
    # Available languages come from the bound material's SRT pool; host
    # passes them through ProjectContext. Empty list = no material bound
    # or no extracted subtitles yet — combobox stays editable as a
    # fallback so the value isn't lost on display.
    langs = list(getattr(ctx, "subtitle_languages", None) or [])
    cur = lang_v.get()
    if cur and cur not in langs:
        langs.append(cur)
    lang_combo = ttk.Combobox(row, textvariable=lang_v, values=langs,
                                state="readonly" if langs else "normal",
                                width=12)
    lang_combo.pack(side="left", padx=(2, 0))

    # Position
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="位置",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    pos_v = tk.StringVar(value=instance.get("position", "bottom"))
    bm_v = tk.IntVar(value=int(
        float(instance.get("block_margin_pct", 0.09)) * 100))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="对齐", width=10).pack(side="left")
    for label, val in (("⬆ 顶部", "top"), ("⬇ 底部", "bottom")):
        ttk.Radiobutton(row, text=label, variable=pos_v, value=val
                        ).pack(side="left", padx=(2, 0))
    ttk.Label(row, text="边距").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=40, width=4, textvariable=bm_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    # Font
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="字体",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    # fontsize / stroke shown to user as "px at 1080 short edge" — the
    # natural intuition. Internally stored as fraction of short edge so
    # render and preview use the same pct (see layout.font_size_px).
    fs_v = tk.IntVar(value=int(round(
        float(instance.get("fontsize_pct", 0.05)) * 1080)))
    color_v = tk.StringVar(value=instance.get("color", "#FFFFFF"))
    bold_v = tk.BooleanVar(value=bool(instance.get("bold", False)))
    cn_v = tk.BooleanVar(value=bool(instance.get("is_chinese", False)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="字号", width=10).pack(side="left")
    ttk.Spinbox(row, from_=10, to=200, width=4, textvariable=fs_v
                 ).pack(side="left")
    ttk.Label(row, text="px").pack(side="left")
    ttk.Label(row, text="颜色").pack(side="left", padx=(8, 2))
    add_color_picker(row, color_v)
    ttk.Checkbutton(row, text="粗体", variable=bold_v
                     ).pack(side="left", padx=(8, 0))
    ttk.Checkbutton(row, text="中文字体", variable=cn_v
                     ).pack(side="left", padx=(8, 0))

    # Stroke
    sc_v = tk.StringVar(value=instance.get("stroke_color", "#000000"))
    sw_v = tk.IntVar(value=int(round(
        float(instance.get("stroke_pct", 0.002)) * 1080)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="描边", width=10).pack(side="left")
    add_color_picker(row, sc_v)
    ttk.Label(row, text="宽度").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=20, width=4, textvariable=sw_v
                 ).pack(side="left")
    ttk.Label(row, text="px").pack(side="left")

    # Backdrop
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="背景框",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    bg_color_v = tk.StringVar(value=instance.get("bg_color", "#000000"))
    bg_op_v = tk.IntVar(value=int(instance.get("bg_opacity", 0)))
    bg_pad_v = tk.IntVar(value=int(
        float(instance.get("bg_padding_x_pct", 0.0)) * 100))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="颜色", width=10).pack(side="left")
    add_color_picker(row, bg_color_v)
    ttk.Label(row, text="不透明度").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=100, width=4, textvariable=bg_op_v
                 ).pack(side="left")
    ttk.Label(row, text="% 横向 padding").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=20, width=4, textvariable=bg_pad_v
                 ).pack(side="left")
    ttk.Label(row, text="%").pack(side="left")

    def _commit(*_):
        instance["name"] = name_v.get()
        instance["enabled"] = bool(enabled_v.get())
        instance["language"] = lang_v.get()
        instance["position"] = pos_v.get() or "bottom"
        try:
            instance["block_margin_pct"] = float(bm_v.get()) / 100.0
            instance["fontsize_pct"] = float(fs_v.get()) / 1080.0
            instance["stroke_pct"] = float(sw_v.get()) / 1080.0
            instance["bg_opacity"] = int(bg_op_v.get())
            instance["bg_padding_x_pct"] = float(bg_pad_v.get()) / 100.0
        except (tk.TclError, ValueError):
            return
        instance["color"] = color_v.get() or "#FFFFFF"
        instance["bold"] = bool(bold_v.get())
        instance["is_chinese"] = bool(cn_v.get())
        instance["stroke_color"] = sc_v.get() or "#000000"
        instance["bg_color"] = bg_color_v.get() or "#000000"
        on_change()

    for v in (name_v, enabled_v, lang_v, pos_v, bm_v, fs_v, color_v,
               bold_v, cn_v, sc_v, sw_v, bg_color_v, bg_op_v, bg_pad_v):
        v.trace_add("write", _commit)


# ── register ───────────────────────────────────────────────────────────────

register(ComponentSpec(
    kind=KIND,
    name_key="clip.component.subtitle.name",
    add_label_key="clip.component.subtitle.add",
    multi_instance=True,
    default_z=10,
    default_instance=_default_instance,
    build_property_panel=_build_property_panel,
    compile=_compile,
))
