"""Clip subtitle component — one track per instance.

Each clip uses up to two subtitle tracks (primary + secondary language).
Each track is one ClipSubtitleSpec instance. The host (composer or the
future component-list UI) decides how many tracks exist and seeds each
instance with its SRT path + the margin_v that reflects whether the
other track is also enabled (so the two tracks stack correctly).

This spec exists ALONGSIDE news_desk's subtitle spec, not as a
replacement. News_desk's subtitle is single-track with a snapshot SRT
in instance_dir; clip's is dual-capable with a dynamic SRT path
resolved from the active language at render time.

Step 5.1 — render path: composer.compile_for_candidate calls
`subtitle_adapters_from_style()` to translate the legacy
CompositionStyle.subtitle into transient instance dicts; once Step 5.5
swaps the UI to a component list, those dicts will live in
ClipInstanceConfig.components and this seeder retires.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

import srt as _srt

from core.composition.compile import ClipRange, CompileContext
from core.composition.primitives.subtitle_cue import track_margins
from core.composition.style import CompositionStyle, SubtitleLineStyle, SubtitleStyle
from core.composition.timeline import Element
from creations.news_desk.components import ComponentSpec, ProjectContext

from . import ComponentDictAdapter, add_color_picker, register


KIND = "clip_subtitle"


# ── default_instance ───────────────────────────────────────────────────────

def _default_instance(_duration: float) -> dict:
    """Used by [+ Add Subtitle]. Sane mid-range defaults; first add
    gets the primary track, subsequent adds slot in as secondary."""
    return {
        "kind": KIND,
        "id": "sub1",
        "name": "subtitle",
        "enabled": True,
        # Which language stream the composer wires this track to.
        # "primary" → resolve_source_srt(lang_var); "secondary" → the
        # bilingual second track. Default first-add = primary.
        "track": "primary",
        # Source SRT — composer fills at compile time based on `track`.
        "srt_path": "",
        # Per-line style
        "fontsize": 24,
        "color": "#FFFFFF",
        "bold": False,
        "is_chinese": False,
        "bg_color": "#000000",
        "bg_opacity": 0,
        "bg_padding_x_pct": 0.0,
        # Track-shared style
        "stroke_color": "#000000",
        "stroke_width": 2,
        "position": "bottom",
        "block_margin_pct": 0.09,
        # Pre-computed by seeder so compile() stays pure (single-track view)
        "margin_v": 0,
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
        "fontsize": int(instance.get("fontsize", 24)),
        "color": instance.get("color", "#FFFFFF"),
        "bold": bool(instance.get("bold", False)),
        "is_chinese": bool(instance.get("is_chinese", False)),
        "bg_color": instance.get("bg_color", "#000000"),
        "bg_opacity": int(instance.get("bg_opacity", 0)),
        "bg_padding_x_pct": float(instance.get("bg_padding_x_pct", 0.0)),
        "stroke_color": instance.get("stroke_color", "#000000"),
        "stroke_width": int(instance.get("stroke_width", 2)),
        "position": instance.get("position", "bottom"),
        "block_margin_pct": float(instance.get("block_margin_pct", 0.09)),
        "margin_v": int(instance.get("margin_v", 0)),
    }

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


# ── Seeder — legacy CompositionStyle → transient instance adapters ─────────

def subtitle_adapters_from_style(
    style: CompositionStyle,
    *,
    source_srt: str = "",
    source_srt_secondary: str = "",
) -> list[ComponentDictAdapter]:
    """Translate the legacy CompositionStyle.subtitle into transient
    subtitle component adapters for compile_timeline().

    Both tracks are inspected; disabled tracks or tracks without a
    bound SRT return no adapter. margin_v is pre-computed via
    track_margins(subtitle_style) so each compile() call stays pure.

    Step 5.1 — temporary bridge. Step 5.5 will replace this with
    ClipInstanceConfig.components-driven discovery.
    """
    sub = style.subtitle
    margin_v1, margin_v2 = track_margins(sub)
    adapters: list[ComponentDictAdapter] = []

    if sub.sub1.enabled and source_srt:
        adapters.append(ComponentDictAdapter(
            _line_to_instance(sub.sub1, sub, "sub1", source_srt, margin_v1)))
    if sub.sub2.enabled and source_srt_secondary:
        adapters.append(ComponentDictAdapter(
            _line_to_instance(sub.sub2, sub, "sub2", source_srt_secondary,
                               margin_v2)))
    return adapters


def _line_to_instance(line: SubtitleLineStyle, subtitle_style: SubtitleStyle,
                       track_id: str, srt_path: str, margin_v: int) -> dict:
    return {
        "kind": KIND,
        "id": track_id,
        "name": track_id,
        "enabled": True,
        "track": "primary" if track_id == "sub1" else "secondary",
        "srt_path": srt_path,
        "fontsize": int(line.fontsize),
        "color": line.color,
        "bold": bool(line.bold),
        "is_chinese": bool(line.is_chinese),
        "bg_color": line.bg_color,
        "bg_opacity": int(line.bg_opacity),
        "bg_padding_x_pct": float(line.bg_padding_x_pct),
        "stroke_color": subtitle_style.stroke_color,
        "stroke_width": int(subtitle_style.stroke_width),
        "position": subtitle_style.position,
        "block_margin_pct": float(subtitle_style.block_margin_pct),
        "margin_v": int(margin_v),
    }


# ── property panel ─────────────────────────────────────────────────────────

def _build_property_panel(parent: ttk.Frame, instance: dict,
                           _ctx: ProjectContext, on_change) -> None:
    name_v = tk.StringVar(value=instance.get("name", ""))
    enabled_v = tk.BooleanVar(value=bool(instance.get("enabled", True)))
    track_v = tk.StringVar(value=instance.get("track", "primary"))

    # Identity row
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="名称", width=10).pack(side="left")
    ttk.Entry(row, textvariable=name_v).pack(
        side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Checkbutton(row, text="启用", variable=enabled_v).pack(side="left")
    ttk.Label(row, text="轨道").pack(side="left", padx=(12, 4))
    for label, val in (("主语言", "primary"), ("副语言", "secondary")):
        ttk.Radiobutton(row, text=label, variable=track_v, value=val
                        ).pack(side="left", padx=(2, 0))

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

    fs_v = tk.IntVar(value=int(instance.get("fontsize", 24)))
    color_v = tk.StringVar(value=instance.get("color", "#FFFFFF"))
    bold_v = tk.BooleanVar(value=bool(instance.get("bold", False)))
    cn_v = tk.BooleanVar(value=bool(instance.get("is_chinese", False)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="字号", width=10).pack(side="left")
    ttk.Spinbox(row, from_=10, to=96, width=4, textvariable=fs_v
                 ).pack(side="left")
    ttk.Label(row, text="颜色").pack(side="left", padx=(8, 2))
    add_color_picker(row, color_v)
    ttk.Checkbutton(row, text="粗体", variable=bold_v
                     ).pack(side="left", padx=(8, 0))
    ttk.Checkbutton(row, text="中文字体", variable=cn_v
                     ).pack(side="left", padx=(8, 0))

    # Stroke
    sc_v = tk.StringVar(value=instance.get("stroke_color", "#000000"))
    sw_v = tk.IntVar(value=int(instance.get("stroke_width", 2)))
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="描边", width=10).pack(side="left")
    add_color_picker(row, sc_v)
    ttk.Label(row, text="宽度").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=8, width=4, textvariable=sw_v
                 ).pack(side="left")

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
        instance["track"] = track_v.get() or "primary"
        instance["position"] = pos_v.get() or "bottom"
        try:
            instance["block_margin_pct"] = float(bm_v.get()) / 100.0
            instance["fontsize"] = int(fs_v.get())
            instance["stroke_width"] = int(sw_v.get())
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

    for v in (name_v, enabled_v, track_v, pos_v, bm_v, fs_v, color_v,
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
