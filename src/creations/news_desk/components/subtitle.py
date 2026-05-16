"""Subtitle component — one snapshotted SRT track + its visual style.

Per ADR-0003 derivatives own their data. Each subtitle instance:

  - has a stable `id` (UUID-ish hex slug)
  - snapshots the user-picked SRT into
    `<instance_dir>/subtitles/<id>.srt` at import time
  - stores a derivative-relative `srt_path` ("subtitles/<id>.srt")
    instead of pointing at the source layer

Legacy instances (srt_path pointing at `subtitles/zh.srt` in the
project folder) keep rendering — `_resolve_srt_path` looks at the
path shape to decide which root to resolve against. Upgrading a
legacy instance to a snapshot is an explicit user action (click
[↻ 重新导入]); we don't auto-rewrite on load.
"""

from __future__ import annotations

import os
import shutil
import uuid
import tkinter as tk
from tkinter import filedialog, ttk

from i18n import tr

from . import ComponentSpec, ProjectContext, register


def _new_comp_id() -> str:
    """8-char hex slug — enough entropy for per-instance uniqueness, short
    enough to read in filenames."""
    return uuid.uuid4().hex[:8]


def _default_instance(_duration: float) -> dict:
    return {
        "kind": "subtitle",
        "id": _new_comp_id(),
        "name": tr("tool.news_desk.subtitle.default_name"),
        "enabled": True,
        "srt_path": "",                # snapshot-relative once imported
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


def _ensure_id(instance: dict) -> str:
    """Backfill an id onto legacy instances that predate ADR-0003."""
    cid = instance.get("id")
    if not cid:
        cid = _new_comp_id()
        instance["id"] = cid
    return cid


def _snapshot_rel_path(instance: dict) -> str:
    """Derivative-relative path for this instance's snapshotted SRT."""
    return f"subtitles/{_ensure_id(instance)}.srt"


def _is_local_snapshot(rel_path: str) -> bool:
    """True if `rel_path` looks like a per-instance snapshot inside
    `<instance_dir>/subtitles/`. Legacy paths point at the source layer
    (`subtitles/<iso>.srt` rooted at project folder) so they share the
    `subtitles/` prefix but a different parent — we disambiguate by the
    `.srt` filename: snapshots are named by id (hex), legacy by iso."""
    p = (rel_path or "").replace("\\", "/")
    if not p.startswith("subtitles/") or not p.endswith(".srt"):
        return False
    stem = p[len("subtitles/"):-len(".srt")]
    # Snapshot ids are 8-char hex; legacy stems are lang isos like "zh"
    # or "zh-Hans". Hex-only + length 8 distinguishes safely.
    if len(stem) != 8:
        return False
    try:
        int(stem, 16)
        return True
    except ValueError:
        return False


def _resolve_srt_path(instance: dict, ctx: ProjectContext) -> str:
    """Absolute filesystem path for the configured SRT, resolved against
    the instance dir (snapshot) or the project folder (legacy reference).
    Empty string when nothing's configured."""
    rel = (instance.get("srt_path") or "").strip()
    if not rel:
        return ""
    if os.path.isabs(rel):
        return rel
    root = ctx.instance_dir if _is_local_snapshot(rel) else ctx.project.folder
    if not root:
        return rel
    return os.path.normpath(os.path.join(root, rel))


def _probe_srt_summary(abs_path: str) -> tuple[int, float]:
    """Return (cue_count, duration_sec) for an SRT, or (0, 0) on failure."""
    if not abs_path or not os.path.isfile(abs_path):
        return (0, 0.0)
    try:
        import srt as _srt
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            cues = list(_srt.parse(f.read()))
        if not cues:
            return (0, 0.0)
        return (len(cues), cues[-1].end.total_seconds())
    except Exception:
        return (0, 0.0)


def _fmt_duration(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


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

    # Source — SRT snapshot button + status line.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.field.section_source"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    status_var = tk.StringVar()

    def _refresh_status() -> None:
        rel = instance.get("srt_path", "")
        if not rel:
            status_var.set(tr("tool.news_desk.subtitle.no_srt"))
            return
        abs_path = _resolve_srt_path(instance, ctx)
        n, dur = _probe_srt_summary(abs_path)
        if n <= 0:
            status_var.set(tr("tool.news_desk.subtitle.srt_missing",
                              path=rel))
            return
        if _is_local_snapshot(rel):
            status_var.set(tr("tool.news_desk.subtitle.snapshot_ok",
                              count=n, dur=_fmt_duration(dur)))
        else:
            status_var.set(tr("tool.news_desk.subtitle.legacy_ref",
                              path=rel, count=n, dur=_fmt_duration(dur)))

    def _import_srt() -> None:
        initial = ctx.project.subtitles_dir
        src = filedialog.askopenfilename(
            parent=parent.winfo_toplevel(),
            initialdir=initial if os.path.isdir(initial) else ctx.project.folder,
            title=tr("tool.news_desk.sub.pick"),
            filetypes=[("SRT", "*.srt"), ("All", "*.*")])
        if not src:
            return
        if not ctx.instance_dir:
            return    # host hasn't set us up yet
        rel = _snapshot_rel_path(instance)
        dst = os.path.join(ctx.instance_dir, rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        except OSError as e:
            from tkinter import messagebox
            messagebox.showerror(
                "VideoCraft",
                tr("tool.news_desk.subtitle.import_failed", err=str(e)),
                parent=parent.winfo_toplevel())
            return
        instance["srt_path"] = rel
        _refresh_status()
        _load_cues()
        on_change()

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Button(row,
               text=tr("tool.news_desk.subtitle.import_btn"),
               command=_import_srt
               ).pack(side="left")
    ttk.Label(row, textvariable=status_var, foreground="#444",
              wraplength=520, justify="left"
              ).pack(side="left", padx=(8, 0), fill="x", expand=True)
    _refresh_status()

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

    def _commit(*_):
        instance["name"] = name_v.get()
        instance["enabled"] = bool(enabled_v.get())
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

    for v in (name_v, enabled_v, pos_v, bm_v, fs_v, color_v, cn_v,
               sc_v, sw_v, bg_en_v, bg_color_v, bg_op_v):
        v.trace_add("write", _commit)

    # Cue list — read-only Treeview at the bottom of the panel. Click
    # a row to seek the preview to that cue. Editing comes in a later
    # phase; for now this is just a what-you-imported confirmation.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.subtitle.cues_section"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    tree_wrap = ttk.Frame(parent)
    tree_wrap.pack(fill="both", expand=False, pady=(2, 4))
    cue_tree = ttk.Treeview(tree_wrap,
                             columns=("start", "end", "text"),
                             show="headings", height=10)
    cue_tree.heading("start",
                      text=tr("tool.news_desk.subtitle.cue_col_start"))
    cue_tree.heading("end",
                      text=tr("tool.news_desk.subtitle.cue_col_end"))
    cue_tree.heading("text",
                      text=tr("tool.news_desk.subtitle.cue_col_text"))
    cue_tree.column("start", width=70, anchor="e", stretch=False)
    cue_tree.column("end",   width=70, anchor="e", stretch=False)
    cue_tree.column("text",  width=400, anchor="w", stretch=True)
    vsb = ttk.Scrollbar(tree_wrap, orient="vertical",
                         command=cue_tree.yview)
    cue_tree.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    cue_tree.pack(side="left", fill="both", expand=True)

    def _load_cues() -> None:
        cue_tree.delete(*cue_tree.get_children())
        abs_path = _resolve_srt_path(instance, ctx)
        if not abs_path or not os.path.isfile(abs_path):
            return
        try:
            import srt as _srt
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                cues = list(_srt.parse(f.read()))
        except Exception:
            return
        for i, c in enumerate(cues):
            text = c.content.replace("\n", " ").strip()
            cue_tree.insert(
                "", "end", iid=str(i),
                values=(_fmt_duration(c.start.total_seconds()),
                        _fmt_duration(c.end.total_seconds()),
                        text))

    def _on_cue_click(_e=None) -> None:
        if ctx.seek_to is None:
            return
        sel = cue_tree.selection()
        if not sel:
            return
        # Read displayed start back into seconds; cheap re-parse so we
        # don't keep a parallel cue array around.
        start_str = cue_tree.set(sel[0], "start")
        parts = start_str.split(":")
        try:
            if len(parts) == 3:
                h, m, s = parts
                sec = int(h) * 3600 + int(m) * 60 + int(s)
            else:
                m, s = parts
                sec = int(m) * 60 + int(s)
        except ValueError:
            return
        ctx.seek_to(float(sec))
    cue_tree.bind("<<TreeviewSelect>>", _on_cue_click)

    _load_cues()


def _to_render_fragment(instance: dict, ctx: ProjectContext) -> dict:
    """Subtitle contributes (srt_path, SubtitleLineStyle, position,
    block_margin_pct). Host packs all enabled instances into the
    renderer's extra_subtitles list — each rides as an independent
    libass track."""
    from core.composition.style import SubtitleLineStyle
    if not instance.get("enabled", True) or not instance.get("srt_path"):
        return {"subtitle": None}
    abs_path = _resolve_srt_path(instance, ctx)
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
            "block_margin_pct": int(
                instance.get("block_margin_pct", 9)) / 100.0,
        }
    }


register(ComponentSpec(
    kind="subtitle",
    name_key="tool.news_desk.kind.subtitle",
    add_label_key="tool.news_desk.add.subtitle",
    multi_instance=True,
    default_z=90,
    default_instance=_default_instance,
    build_property_panel=_build_property_panel,
    to_overlays=_to_render_fragment,
))
