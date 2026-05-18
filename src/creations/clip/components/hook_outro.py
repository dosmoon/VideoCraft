"""Clip hook & outro components — separate specs, shared style helper.

Two registered specs: clip_hook_card (compiles to hook_text primitive)
and clip_outro_card (compiles to outro_text primitive). Each instance
dict carries its own text and the full style field set; the renderer
reads the same flat style dict shape the pre-5.3 inline hook/outro
branch emitted, so byte-shape stays stable.

Per-candidate text (the AI-generated or user-edited hook / outro
text) is filled into the instance dict by `hookoutro_adapters_from_style`
at render time — there is no engine-level ctx side-channel.

Both specs share `_card_style_dict()` for the font / color / bg /
stroke fields (matches HookOutroStyle for hook AND outro). The
position field differs (hook_position vs outro_position) and the
time-window math differs ([0, duration] vs [end-duration, end]).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core.composition.compile import ClipRange, CompileContext
from core.composition.style import CompositionStyle
from core.composition.timeline import Element
from creations.news_desk.components import ComponentSpec, ProjectContext

from . import add_color_picker, register


_HOOK_POSITIONS = ["upper-third", "center", "lower-third"]
_OUTRO_POSITIONS = ["upper-third", "center", "lower-third"]


KIND_HOOK = "clip_hook_card"
KIND_OUTRO = "clip_outro_card"


# ── default_instance ───────────────────────────────────────────────────────

def _default_hook_instance(_duration: float) -> dict:
    # size_pct / stroke_pct / box_padding_pct are FRACTIONS OF THE SHORT
    # EDGE — see core/composition/layout.py. 0.05 ≈ 54px at 1080
    # short-edge target. drawtext on render and canvas on preview both
    # multiply pct by their own frame's short edge to get pixels.
    return {
        "kind": KIND_HOOK,
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


def _default_outro_instance(_duration: float) -> dict:
    return {
        "kind": KIND_OUTRO,
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


# ── style dict — matches what the pre-5.3 inline branch emitted ─────────

def _card_style_dict(instance: dict, position_role: str) -> dict:
    """Pack flat style dict the renderer's drawtext_filter consumes.
    Sizes ride as fractions of the short edge — drawtext_filter
    multiplies by short_edge to get the actual fontsize / borderw /
    boxborderw in target pixels.

    `position_role` is "hook" or "outro"; the renderer expects
    hook_position / outro_position keys (not a generic "position"),
    so we stamp both — only the role-matching one is actually read.
    """
    return {
        "font": instance.get("font", "Microsoft YaHei"),
        "size_pct": float(instance.get("size_pct", 0.05)),
        "color": instance.get("color", "#FFFFFF"),
        "bg_color": instance.get("bg_color", "#000000"),
        "bg_opacity": int(instance.get("bg_opacity", 70)),
        "stroke_color": instance.get("stroke_color", "#000000"),
        "stroke_pct": float(instance.get("stroke_pct", 0.003)),
        "box_padding_pct": float(instance.get("box_padding_pct", 0.012)),
        # Stamp the role-specific position the renderer looks up
        "hook_position": (instance.get("position", "upper-third")
                            if position_role == "hook" else "upper-third"),
        "outro_position": (instance.get("position", "lower-third")
                             if position_role == "outro" else "lower-third"),
        "hook_duration_sec": (float(instance.get("duration_sec", 5.0))
                                if position_role == "hook" else 5.0),
        "outro_duration_sec": (float(instance.get("duration_sec", 5.0))
                                 if position_role == "outro" else 5.0),
    }


# ── compile — hook ─────────────────────────────────────────────────────────

def _compile_hook(instance: dict, clip_range: ClipRange,
                   _ctx: CompileContext) -> list[Element]:
    text = (instance.get("text") or "").strip()
    duration = float(instance.get("duration_sec", 0.0))
    if not text or duration <= 0:
        return []
    end = min(clip_range.duration_sec, duration)
    if end <= 0:
        return []
    # Per timeline.py convention: visual fields → Element.style, content
    # fields → Element.data. Older versions of this compile fn nested
    # style inside data["style"]; that violated the convention and made
    # render.py silently fall back to defaults (preview had a hack to
    # accommodate it). All consumers now read Element.style uniformly.
    return [Element(
        kind="hook_text",
        start_sec=0.0,
        end_sec=end,
        style=_card_style_dict(instance, "hook"),
        data={"text": instance.get("text", "")},
    )]


# ── compile — outro ────────────────────────────────────────────────────────

def _compile_outro(instance: dict, clip_range: ClipRange,
                    _ctx: CompileContext) -> list[Element]:
    text = (instance.get("text") or "").strip()
    duration = float(instance.get("duration_sec", 0.0))
    if not text or duration <= 0:
        return []
    start = max(0.0, clip_range.duration_sec - duration)
    if clip_range.duration_sec <= start:
        return []
    return [Element(
        kind="outro_text",
        start_sec=start,
        end_sec=clip_range.duration_sec,
        style=_card_style_dict(instance, "outro"),
        data={"text": instance.get("text", "")},
    )]


# ── Migration — extract template dicts from legacy HookOutroStyle ─────────

def template_from_style(style: CompositionStyle) -> list[dict]:
    """One-time bootstrap: turn HookOutroStyle into hook + outro
    component templates. text="" — composer.expand_for_candidate fills
    it per candidate. Both components enabled by default if their
    duration is positive.
    """
    # Legacy HookOutroStyle stored sizes as integer pixels. Pre-alpha
    # lossy convert: pct = px / 1080 (1080 is the canonical short-edge
    # baseline). User can re-tune in the property panel.
    ho = style.hook_outro
    common = {
        "font": ho.font,
        "size_pct": int(ho.size) / 1080.0,
        "color": ho.color,
        "bg_color": ho.bg_color,
        "bg_opacity": int(ho.bg_opacity),
        "stroke_color": ho.stroke_color,
        "stroke_pct": int(ho.stroke_width) / 1080.0,
        "box_padding_pct": int(ho.box_padding) / 1080.0,
        "text": "",
    }
    out: list[dict] = []
    if ho.hook_duration_sec > 0:
        out.append({**common, "kind": KIND_HOOK, "id": "hook", "name": "hook",
                     "enabled": True, "position": ho.hook_position,
                     "duration_sec": float(ho.hook_duration_sec)})
    if ho.outro_duration_sec > 0:
        out.append({**common, "kind": KIND_OUTRO, "id": "outro",
                     "name": "outro", "enabled": True,
                     "position": ho.outro_position,
                     "duration_sec": float(ho.outro_duration_sec)})
    return out


# ── property panels (hook + outro share the same shape) ───────────────────

def _build_card_panel(parent: ttk.Frame, instance: dict,
                       _ctx: ProjectContext, on_change,
                       *, positions: list[str]) -> None:
    name_v = tk.StringVar(value=instance.get("name", ""))
    enabled_v = tk.BooleanVar(value=bool(instance.get("enabled", True)))
    dur_v = tk.IntVar(value=int(float(instance.get("duration_sec", 5.0))))
    font_v = tk.StringVar(value=instance.get("font", "Microsoft YaHei"))
    # size / stroke / padding shown to user as px @1080 short edge; the
    # underlying schema field is the pct fraction.
    size_v = tk.IntVar(value=int(round(
        float(instance.get("size_pct", 0.05)) * 1080)))
    color_v = tk.StringVar(value=instance.get("color", "#FFFFFF"))
    bg_color_v = tk.StringVar(value=instance.get("bg_color", "#000000"))
    bg_op_v = tk.IntVar(value=int(instance.get("bg_opacity", 70)))
    sc_v = tk.StringVar(value=instance.get("stroke_color", "#000000"))
    sw_v = tk.IntVar(value=int(round(
        float(instance.get("stroke_pct", 0.003)) * 1080)))
    pad_v = tk.IntVar(value=int(round(
        float(instance.get("box_padding_pct", 0.012)) * 1080)))
    pos_v = tk.StringVar(value=instance.get(
        "position",
        "upper-third" if "upper-third" in positions else positions[0]))

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="名称", width=10).pack(side="left")
    ttk.Entry(row, textvariable=name_v).pack(
        side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Checkbutton(row, text="启用", variable=enabled_v).pack(side="left")
    ttk.Label(row, text="时长").pack(side="left", padx=(12, 4))
    ttk.Spinbox(row, from_=1, to=30, width=4, textvariable=dur_v
                 ).pack(side="left")
    ttk.Label(row, text="秒").pack(side="left")

    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="字体",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="字体", width=10).pack(side="left")
    ttk.Entry(row, textvariable=font_v, width=22).pack(side="left")
    ttk.Label(row, text="字号").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=12, to=300, width=4, textvariable=size_v
                 ).pack(side="left")
    ttk.Label(row, text="px").pack(side="left")

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="颜色", width=10).pack(side="left")
    add_color_picker(row, color_v)

    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="描边 / 背景",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="描边", width=10).pack(side="left")
    add_color_picker(row, sc_v)
    ttk.Label(row, text="宽度").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=20, width=4, textvariable=sw_v
                 ).pack(side="left")
    ttk.Label(row, text="px").pack(side="left")

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="背景色", width=10).pack(side="left")
    add_color_picker(row, bg_color_v)
    ttk.Label(row, text="不透明").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=100, width=4, textvariable=bg_op_v
                 ).pack(side="left")
    ttk.Label(row, text="padding").pack(side="left", padx=(8, 2))
    ttk.Spinbox(row, from_=0, to=60, width=4, textvariable=pad_v
                 ).pack(side="left")
    ttk.Label(row, text="px").pack(side="left")

    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text="位置",
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text="位置", width=10).pack(side="left")
    ttk.Combobox(row, textvariable=pos_v, values=positions,
                  state="readonly", width=14).pack(side="left")

    def _commit(*_):
        instance["name"] = name_v.get()
        instance["enabled"] = bool(enabled_v.get())
        try:
            instance["duration_sec"] = float(dur_v.get())
            instance["size_pct"] = float(size_v.get()) / 1080.0
            instance["bg_opacity"] = int(bg_op_v.get())
            instance["stroke_pct"] = float(sw_v.get()) / 1080.0
            instance["box_padding_pct"] = float(pad_v.get()) / 1080.0
        except (tk.TclError, ValueError):
            return
        instance["font"] = font_v.get() or "Microsoft YaHei"
        instance["color"] = color_v.get() or "#FFFFFF"
        instance["bg_color"] = bg_color_v.get() or "#000000"
        instance["stroke_color"] = sc_v.get() or "#000000"
        instance["position"] = pos_v.get() or positions[0]
        on_change()

    for v in (name_v, enabled_v, dur_v, font_v, size_v, color_v,
               bg_color_v, bg_op_v, sc_v, sw_v, pad_v, pos_v):
        v.trace_add("write", _commit)


def _build_hook_panel(parent, instance, ctx, on_change):
    _build_card_panel(parent, instance, ctx, on_change,
                       positions=_HOOK_POSITIONS)


def _build_outro_panel(parent, instance, ctx, on_change):
    _build_card_panel(parent, instance, ctx, on_change,
                       positions=_OUTRO_POSITIONS)


# ── register ───────────────────────────────────────────────────────────────

register(ComponentSpec(
    kind=KIND_HOOK,
    name_key="clip.component.hook_card.name",
    add_label_key="clip.component.hook_card.add",
    multi_instance=False,
    default_z=90,
    default_instance=_default_hook_instance,
    build_property_panel=_build_hook_panel,
    compile=_compile_hook,
))

register(ComponentSpec(
    kind=KIND_OUTRO,
    name_key="clip.component.outro_card.name",
    add_label_key="clip.component.outro_card.add",
    multi_instance=False,
    default_z=90,
    default_instance=_default_outro_instance,
    build_property_panel=_build_outro_panel,
    compile=_compile_outro,
))
