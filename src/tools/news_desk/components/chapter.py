"""Chapter component — singleton, bound to analysis.json chapters.

Each chapter row holds (start, end, title, refined, key_points). Two
visual modes share this data, multi-select per instance:
  - top_strip   — top banner, uses `title`
  - start_card  — chapter-start hero card, uses title + refined
  - end_summary — chapter-end recap (DEFERRED — needs paragraph overlay)

key_points is text-only enrichment (chapter cards / publish.md /
hotclip selection inputs). Earlier we tried to render per-point
popups inside chapters, but asking AI to emit per-point timestamps
ballooned prompt complexity for negligible UX value — the popups
themselves were also visually noisy.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import messagebox, ttk

from i18n import tr
from core import chapters_io
from core.composition.overlays import (
    ChapterHeroCardOverlay, TopicStripOverlay,
)

from . import ComponentSpec, ImportSource, ProjectContext, register


# Visual mode keys — order matters for default rendering and panel layout.
MODES = ("top_strip", "start_card", "end_summary")


def _fmt_hms(sec) -> str:
    """Seconds → 'H:MM:SS' (or 'M:SS' under 1 hour). Used in chapter list
    cells so the user reads time, not raw seconds."""
    s = max(0, int(round(float(sec or 0))))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _parse_hms(text: str) -> float:
    """'H:MM:SS' / 'M:SS' / 'S' → seconds. Raises ValueError on bad input."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty")
    parts = text.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"bad time: {text}")


def _default_instance(_duration: float) -> dict:
    return {
        "kind": "chapter",
        "name": tr("tool.news_desk.chapter.default_name"),
        "enabled": True,
        "modes": {
            "top_strip": True,
            "start_card": False,
            "end_summary": False,
        },
        "style": {
            "top_strip": {
                "bg_color": "#1E40AF",
                "text_color": "#FFFFFF",
                "fontsize": 26,
            },
            "start_card": {
                "title_color": "#FFFFFF",
                "title_fontsize": 56,
                "body_color": "#E5E7EB",
                "body_fontsize": 28,
                "bg_color": "#000000",
                "bg_opacity": 75,
                "duration_sec": 6,
            },
            "end_summary": {
                "text_color": "#FFFFFF",
                "fontsize": 22,
                "bg_color": "#000000",
                "bg_opacity": 70,
                "duration_sec": 5,
            },
        },
        # Schedule is the chapters list snapshotted from analysis.json.
        "schedule": [],
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


def _build_mode_style_panel(parent: ttk.Frame, mode: str,
                              style_dict: dict, on_change) -> None:
    """Build a per-mode style sub-form. Each mode has its own fields —
    we render whichever the dict has."""
    fields = {
        "bg_color":      ("color",   tr("tool.news_desk.field.bg_color")),
        "text_color":    ("color",   tr("tool.news_desk.field.text_color")),
        "title_color":   ("color",   tr("tool.news_desk.chapter.title_color")),
        "body_color":    ("color",   tr("tool.news_desk.chapter.body_color")),
        "fontsize":      ("int",     tr("tool.news_desk.field.fontsize")),
        "title_fontsize":("int",     tr("tool.news_desk.chapter.title_fontsize")),
        "body_fontsize": ("int",     tr("tool.news_desk.chapter.body_fontsize")),
        "bg_opacity":    ("int",     tr("tool.news_desk.field.opacity")),
        "duration_sec":  ("int",     tr("tool.news_desk.chapter.duration")),
    }
    vars_map: dict = {}
    for key, val in style_dict.items():
        if key not in fields:
            continue
        ftype, label = fields[key]
        row = ttk.Frame(parent); row.pack(fill="x", pady=1)
        ttk.Label(row, text=label, width=12).pack(side="left")
        if ftype == "color":
            v = tk.StringVar(value=str(val))
            _add_color_picker(row, v)
        else:
            v = tk.IntVar(value=int(val))
            ttk.Spinbox(row, from_=0, to=200, width=6,
                         textvariable=v).pack(side="left")
        vars_map[key] = v

    def _commit(*_):
        for k, v in vars_map.items():
            try:
                if isinstance(v, tk.IntVar):
                    style_dict[k] = int(v.get())
                else:
                    style_dict[k] = v.get()
            except (tk.TclError, ValueError):
                continue
        on_change()
    for v in vars_map.values():
        v.trace_add("write", _commit)


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

    # Visual modes — checkboxes + collapsible style blocks.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.chapter.modes_section"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    mode_vars: dict = {}
    for mode in MODES:
        active = bool(instance.setdefault("modes", {}).get(mode, False))
        v = tk.BooleanVar(value=active)
        mode_vars[mode] = v

        wrap = ttk.Frame(parent); wrap.pack(fill="x", pady=2)
        ttk.Checkbutton(wrap,
                         text=tr(f"tool.news_desk.chapter.mode.{mode}"),
                         variable=v
                         ).pack(side="top", anchor="w")

        # Indented style sub-frame — hidden when mode disabled.
        sub = ttk.Frame(wrap)
        if active:
            sub.pack(fill="x", padx=(20, 0))
        _build_mode_style_panel(
            sub, mode,
            instance.setdefault("style", {}).setdefault(mode, {}),
            on_change)

        def _toggle(*_, mode=mode, var=v, sub=sub):
            instance["modes"][mode] = bool(var.get())
            if var.get():
                sub.pack(fill="x", padx=(20, 0))
            else:
                sub.pack_forget()
            on_change()
        v.trace_add("write", _toggle)

    # Chapter list — click row to seek the preview, double-click a cell
    # to edit start/end/title inline. Snapshotted from analysis.json via
    # the import button; live edits land back in instance["schedule"].
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.chapter.list_section"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    chapters = instance.setdefault("schedule", [])
    if chapters:
        tree = ttk.Treeview(parent, columns=("start", "end", "title"),
                              show="headings", height=10)
        tree.heading("start", text="起")
        tree.heading("end", text="止")
        tree.heading("title", text="标题")
        tree.column("start", width=80, anchor="e", stretch=False)
        tree.column("end", width=80, anchor="e", stretch=False)
        tree.column("title", width=300, anchor="w")
        tree.pack(fill="x", pady=2)
        for idx, ch in enumerate(chapters):
            tree.insert("", "end", iid=str(idx), values=(
                _fmt_hms(ch.get("start_sec", 0)),
                _fmt_hms(ch.get("end_sec", 0)),
                ch.get("title", "")))

        def _on_select(_evt=None):
            sel = tree.selection()
            if not sel or not ctx.seek_to:
                return
            try:
                idx = int(sel[0])
                ctx.seek_to(float(chapters[idx].get("start_sec", 0)))
            except (ValueError, IndexError, Exception):
                pass
        tree.bind("<<TreeviewSelect>>", _on_select)

        def _start_edit(event):
            region = tree.identify("region", event.x, event.y)
            if region != "cell":
                return
            rowid = tree.identify_row(event.y)
            colid = tree.identify_column(event.x)
            if not rowid or not colid:
                return
            try:
                idx = int(rowid)
            except ValueError:
                return
            if not (0 <= idx < len(chapters)):
                return
            col_idx = int(colid.replace("#", "")) - 1
            col_name = ("start", "end", "title")[col_idx]
            bbox = tree.bbox(rowid, colid)
            if not bbox:
                return

            ch = chapters[idx]
            if col_name == "title":
                init = ch.get("title", "")
            else:
                init = _fmt_hms(ch.get(f"{col_name}_sec", 0))

            entry_var = tk.StringVar(value=init)
            entry = tk.Entry(tree, textvariable=entry_var)
            entry.place(x=bbox[0], y=bbox[1],
                          width=bbox[2], height=bbox[3])
            entry.focus_set()
            entry.select_range(0, "end")

            committed = {"done": False}
            def _commit(*_):
                if committed["done"]:
                    return
                committed["done"] = True
                new_val = entry_var.get()
                if col_name == "title":
                    ch["title"] = new_val
                    tree.set(rowid, "title", new_val)
                else:
                    try:
                        sec = _parse_hms(new_val)
                    except ValueError:
                        entry.destroy()
                        return
                    ch[f"{col_name}_sec"] = sec
                    tree.set(rowid, col_name, _fmt_hms(sec))
                entry.destroy()
                on_change()
            def _cancel(*_):
                if committed["done"]:
                    return
                committed["done"] = True
                entry.destroy()

            entry.bind("<Return>", _commit)
            entry.bind("<FocusOut>", _commit)
            entry.bind("<Escape>", _cancel)
        tree.bind("<Double-Button-1>", _start_edit)
    else:
        ttk.Label(parent,
                  text=tr("tool.news_desk.chapter.list_empty"),
                  foreground="#666"
                  ).pack(anchor="w", pady=4)

    def _commit_meta(*_):
        instance["name"] = name_v.get()
        instance["enabled"] = bool(enabled_v.get())
        on_change()
    name_v.trace_add("write", _commit_meta)
    enabled_v.trace_add("write", _commit_meta)


def _import_from_analysis(instance: dict, ctx: ProjectContext) -> None:
    """[⇩ from analysis.json] — load chapters into the schedule."""
    subs_dir = ctx.project.subtitles_dir
    if not os.path.isdir(subs_dir):
        return
    for fn in sorted(os.listdir(subs_dir)):
        if fn.endswith(".analysis.json"):
            try:
                env = chapters_io.load_analysis(os.path.join(subs_dir, fn))
            except (OSError, json.JSONDecodeError):
                continue
            chs = env.get("chapters") if isinstance(env, dict) else []
            if isinstance(chs, list):
                # Snapshot only the fields we use.
                instance["schedule"] = [{
                    "start_sec": float(ch.get("start_sec", 0.0)
                                        or chapters_io.parse_time_str(ch.get("start", ""))),
                    "end_sec":   float(ch.get("end_sec", 0.0)
                                        or chapters_io.parse_time_str(ch.get("end", ""))),
                    "title":     str(ch.get("title", "")),
                    "refined":   str(ch.get("refined", "")),
                    "key_points": list(ch.get("key_points") or []),
                } for ch in chs]
                return


def _to_render_fragment(instance: dict, _ctx: ProjectContext) -> dict:
    """Translate enabled visual modes into render overlays. Returns
    {'overlays': [...]} ; empty if disabled or nothing to render."""
    if not instance.get("enabled", True):
        return {"overlays": []}
    schedule = instance.get("schedule") or []
    if not schedule:
        return {"overlays": []}
    modes = instance.get("modes") or {}
    style = instance.get("style") or {}
    overlays: list = []

    for ch in schedule:
        s = float(ch.get("start_sec", 0))
        e = float(ch.get("end_sec", 0))
        title = str(ch.get("title", "")).strip()
        refined = str(ch.get("refined", "")).strip()
        if e <= s:
            continue

        # top_strip — banner across whole chapter showing title.
        if modes.get("top_strip") and title:
            overlays.append(TopicStripOverlay(
                topic_text=title, start_sec=s, end_sec=e,
            ))

        # start_card — hero card at chapter start (centered, large title +
        # multi-line refined body on a dark backdrop). Per-instance style
        # overrides ride along via inline_style so the property panel's
        # edits actually drive the render.
        if modes.get("start_card") and (title or refined):
            sc = style.get("start_card", {}) or {}
            dur = float(sc.get("duration_sec", 6))
            inline = {k: v for k, v in sc.items() if k != "duration_sec"}
            overlays.append(ChapterHeroCardOverlay(
                title=title, body=refined,
                start_sec=s, end_sec=min(e, s + dur),
                inline_style=inline,
            ))

        # end_summary — DEFERRED (renderer doesn't have a recap card kind
        # yet; would route to a future EndSummaryOverlay).

    return {"overlays": overlays}


register(ComponentSpec(
    kind="chapter",
    name_key="tool.news_desk.kind.chapter",
    add_label_key="tool.news_desk.add.chapter",
    multi_instance=False,                # singleton — bound to analysis.json
    default_z=40,                        # below subtitles + watermarks
    default_instance=_default_instance,
    build_property_panel=_build_property_panel,
    to_overlays=_to_render_fragment,
    import_sources=[
        ImportSource(
            label_key="tool.news_desk.chapter.import_analysis",
            handler=_import_from_analysis,
        ),
    ],
))
