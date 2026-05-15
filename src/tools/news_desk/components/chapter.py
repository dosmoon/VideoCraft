"""Chapter component — singleton.

Each chapter row holds (start, end, title, refined, key_points) — the
exact shape of an analysis.json chapter row, but owned by this
derivative (see ARCHITECTURE NOTE below for the snapshot model).

Visual modes are pure render filters on that one schema:
  - top_strip  — top banner derived from `title`
  - start_card — centered hero card derived from `title + refined`

A mode is just "render this chapter data this way too" — there's no
per-row "kind" or extra rows for cards. Adding a hero card means
ensuring a chapter row exists in the time window where you want the
hero to appear; toggling start_card on the component decides whether
heroes get rendered for ALL chapter rows.

key_points is text-only enrichment (publish.md / hotclip selection
inputs). Earlier we tried per-point popups inside chapters, but asking
AI to emit per-point timestamps ballooned prompt complexity for
negligible UX value — the popups themselves were also visually noisy.

═════════════════════════════════════════════════════════════════════
ARCHITECTURE NOTE — data ownership, current vs target
═════════════════════════════════════════════════════════════════════

CURRENT (transitional): the schedule entries reuse the analysis.json
chapter-row shape verbatim (start_sec / end_sec / title / refined /
key_points). `_import_from_analysis` snapshots that shape into
instance["schedule"], and the news_desk derivative persists it as-is.
After import the derivative no longer reads analysis.json — edits to
schedule live only on this instance.

TARGET: news_desk owns its own independent schema. analysis.json
becomes one OPTIONAL input among many (alongside SRT, context.json,
manual entry). Import becomes an explicit conversion step, NOT a
field-by-field copy. The derivative's data layout is free to diverge
from analysis.json (e.g. per-row mode toggles, hero/summary as their
own rows, per-row style overrides).

INDEPENDENCE GOAL: creating a fresh news_desk derivative MUST only
require a `source` video. SRT, analysis.json, context.json, AI calls —
all optional enrichments. The user must be able to hand-build a full
project (add chapters, add hero cards, add end summaries) from an
empty state and ship it.

KNOWN GAP: `_import_from_analysis` overwrites instance["schedule"]
wholesale, silently losing any user edits. A future revision needs a
confirmation prompt + partial-merge strategy (keep manually added
rows / preserve user-edited titles / detect orphaned rows).
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

from . import ComponentSpec, ProjectContext, register


# Visual modes — pure render filters on the same chapter data. Each mode
# decides whether the schedule rows get an additional overlay applied;
# rows themselves are the single source of truth (title / refined /
# key_points). Order matters for default rendering + panel layout.
MODES = ("top_strip", "start_card")


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
        },
        # Schedule is the chapter rows. Imported from analysis.json or
        # built by hand via the [+ Add chapter] button — analysis.json is
        # not required (the news_desk derivative only depends on `source`).
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

    # Chapter list — toolbar + tree + inline detail editor below.
    #   click row → seek preview to row.start_sec AND populate detail editor
    #   detail edits → live-write back into instance["schedule"]
    # Always rendered (even empty) so the toolbar's [+ Add] is reachable
    # without analysis.json. No modal dialog — the unused space below the
    # tree IS the editor surface.
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
    ttk.Label(parent, text=tr("tool.news_desk.chapter.list_section"),
              font=("TkDefaultFont", 9, "bold")).pack(anchor="w")

    chapters = instance.setdefault("schedule", [])

    toolbar = ttk.Frame(parent); toolbar.pack(fill="x", pady=(2, 0))
    add_btn = ttk.Button(toolbar, text=tr("tool.news_desk.chapter.add_chapter"))
    add_btn.pack(side="left")
    del_btn = ttk.Button(toolbar, text=tr("tool.news_desk.chapter.delete_selected"))
    del_btn.pack(side="left", padx=(4, 0))
    import_btn = ttk.Button(
        toolbar, text=tr("tool.news_desk.chapter.import_analysis"))
    import_btn.pack(side="left", padx=(12, 0))

    tree = ttk.Treeview(parent, columns=("start", "end", "title"),
                          show="headings", height=10)
    tree.heading("start", text="起")
    tree.heading("end", text="止")
    tree.heading("title", text="标题")
    tree.column("start", width=80, anchor="e", stretch=False)
    tree.column("end", width=80, anchor="e", stretch=False)
    tree.column("title", width=300, anchor="w")
    tree.pack(fill="x", pady=2)

    # ── Detail editor (inline, lives in the dead space below the tree) ──
    # Single set of widgets shared across rows. _show_row(idx) repopulates
    # them; user edits flow back via traces. A `loading` guard suppresses
    # write-traces during repopulation so switching rows isn't recorded
    # as an edit.
    detail_frame = ttk.Frame(parent)
    detail_frame.pack(fill="both", expand=True, pady=(8, 0))

    state = {"idx": None, "loading": False}

    placeholder = ttk.Label(
        detail_frame,
        text=tr("tool.news_desk.chapter.detail_placeholder"),
        foreground="#888")
    form = ttk.Frame(detail_frame)

    title_v = tk.StringVar()
    start_v = tk.StringVar()
    end_v = tk.StringVar()

    row = ttk.Frame(form); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.chapter.field.title"),
              width=8).pack(side="left")
    ttk.Entry(row, textvariable=title_v).pack(side="left", fill="x", expand=True)

    row = ttk.Frame(form); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.chapter.field.start"),
              width=8).pack(side="left")
    ttk.Entry(row, textvariable=start_v, width=12).pack(side="left")
    ttk.Label(row, text=tr("tool.news_desk.chapter.field.end"),
              width=4).pack(side="left", padx=(12, 0))
    ttk.Entry(row, textvariable=end_v, width=12).pack(side="left")
    ttk.Label(row, text="H:MM:SS / M:SS / S",
              foreground="#888").pack(side="left", padx=(8, 0))

    ttk.Label(form, text=tr("tool.news_desk.chapter.field.refined"),
              ).pack(anchor="w", pady=(6, 2))
    refined_text = tk.Text(form, height=4, wrap="word")
    refined_text.pack(fill="x")

    ttk.Label(form, text=tr("tool.news_desk.chapter.field.key_points"),
              ).pack(anchor="w", pady=(6, 2))
    kp_text = tk.Text(form, height=5, wrap="word")
    kp_text.pack(fill="both", expand=True)

    def _commit_field(*_):
        if state["loading"]:
            return
        idx = state["idx"]
        if idx is None or not (0 <= idx < len(chapters)):
            return
        ch = chapters[idx]
        ch["title"] = title_v.get()
        # Times: silently keep prior value when mid-edit string doesn't
        # parse (e.g. user is typing "1:" before adding minutes). Final
        # invalid input → tree row falls back to the last good value.
        try:
            ch["start_sec"] = _parse_hms(start_v.get())
        except ValueError:
            pass
        try:
            ch["end_sec"] = _parse_hms(end_v.get())
        except ValueError:
            pass
        ch["refined"] = refined_text.get("1.0", "end-1c")
        ch["key_points"] = [
            ln.strip()
            for ln in kp_text.get("1.0", "end-1c").splitlines()
            if ln.strip()
        ]
        tree.set(str(idx), "start", _fmt_hms(ch["start_sec"]))
        tree.set(str(idx), "end", _fmt_hms(ch["end_sec"]))
        tree.set(str(idx), "title", ch["title"])
        on_change()

    title_v.trace_add("write", _commit_field)
    start_v.trace_add("write", _commit_field)
    end_v.trace_add("write", _commit_field)

    def _on_text_modified(widget):
        if widget.edit_modified():
            widget.edit_modified(False)
            _commit_field()
    refined_text.bind(
        "<<Modified>>", lambda _e: _on_text_modified(refined_text))
    kp_text.bind(
        "<<Modified>>", lambda _e: _on_text_modified(kp_text))

    def _show_row(idx):
        state["idx"] = idx
        if idx is None or not (0 <= idx < len(chapters)):
            form.pack_forget()
            placeholder.pack(anchor="w", padx=4, pady=8)
            return
        placeholder.pack_forget()
        form.pack(fill="both", expand=True)
        ch = chapters[idx]
        state["loading"] = True
        try:
            title_v.set(ch.get("title", ""))
            start_v.set(_fmt_hms(ch.get("start_sec", 0)))
            end_v.set(_fmt_hms(ch.get("end_sec", 0)))
            refined_text.delete("1.0", "end")
            refined_text.insert("1.0", ch.get("refined", ""))
            refined_text.edit_modified(False)
            kp_text.delete("1.0", "end")
            kp_text.insert("1.0", "\n".join(
                str(s) for s in (ch.get("key_points") or [])))
            kp_text.edit_modified(False)
        finally:
            state["loading"] = False

    def _refresh_tree():
        for item in tree.get_children():
            tree.delete(item)
        for idx, ch in enumerate(chapters):
            tree.insert("", "end", iid=str(idx), values=(
                _fmt_hms(ch.get("start_sec", 0)),
                _fmt_hms(ch.get("end_sec", 0)),
                ch.get("title", "")))

    _refresh_tree()
    _show_row(None)

    def _on_select(_evt=None):
        sel = tree.selection()
        if not sel:
            _show_row(None)
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if ctx.seek_to:
            try:
                ctx.seek_to(float(chapters[idx].get("start_sec", 0)))
            except Exception:
                pass
        _show_row(idx)
    tree.bind("<<TreeviewSelect>>", _on_select)

    def _add_chapter():
        # Append a blank row right after the last one (or at t=0). Default
        # 30s window, capped to source duration when known.
        last_end = float(chapters[-1].get("end_sec", 0)) if chapters else 0.0
        dur = float(ctx.duration or 0)
        end = last_end + 30.0
        if dur > 0:
            end = min(end, dur)
        chapters.append({
            "start_sec": last_end,
            "end_sec": end,
            "title": tr("tool.news_desk.chapter.new_chapter_default"),
            "refined": "",
            "key_points": [],
        })
        new_idx = len(chapters) - 1
        _refresh_tree()
        on_change()
        tree.selection_set(str(new_idx))
        # Selection event will populate the detail editor for the new row.
    add_btn.config(command=_add_chapter)

    def _delete_selected():
        sel = tree.selection()
        if not sel:
            return
        if not messagebox.askyesno(
                "VideoCraft",
                tr("tool.news_desk.chapter.confirm_delete",
                    n=len(sel)),
                parent=parent.winfo_toplevel()):
            return
        for i in sorted((int(s) for s in sel), reverse=True):
            if 0 <= i < len(chapters):
                chapters.pop(i)
        _refresh_tree()
        _show_row(None)
        on_change()
    del_btn.config(command=_delete_selected)

    def _do_import_analysis():
        # Scan project's subtitles dir for analysis files first — drives
        # the dialog's "what we found" line.
        subs_dir = getattr(ctx.project, "subtitles_dir", "") or ""
        found: list[str] = []
        if subs_dir and os.path.isdir(subs_dir):
            for fn in sorted(os.listdir(subs_dir)):
                if fn.endswith(".analysis.json"):
                    found.append(fn)

        # Build the explanation dialog. ALWAYS show it (even when there's
        # nothing to import) so the user learns where the file would
        # come from.
        dlg = tk.Toplevel(parent)
        dlg.title(tr("tool.news_desk.chapter.import_dialog_title"))
        dlg.transient(parent.winfo_toplevel())
        dlg.grab_set()
        dlg.geometry("560x420")

        body = ttk.Frame(dlg); body.pack(fill="both", expand=True,
                                          padx=12, pady=10)

        # What this is.
        ttk.Label(body,
                   text=tr("tool.news_desk.chapter.import_what_label"),
                   font=("TkDefaultFont", 9, "bold")
                   ).pack(anchor="w")
        ttk.Label(body,
                   text=tr("tool.news_desk.chapter.import_what_body"),
                   wraplength=520, justify="left", foreground="#444"
                   ).pack(anchor="w", pady=(2, 8))

        # Where it lives.
        ttk.Label(body,
                   text=tr("tool.news_desk.chapter.import_where_label"),
                   font=("TkDefaultFont", 9, "bold")
                   ).pack(anchor="w")
        where_text = tr("tool.news_desk.chapter.import_where_body",
                         path=(subs_dir or "—"))
        ttk.Label(body, text=where_text, wraplength=520, justify="left",
                   foreground="#444"
                   ).pack(anchor="w", pady=(2, 8))

        # Scan result.
        ttk.Label(body,
                   text=tr("tool.news_desk.chapter.import_found_label"),
                   font=("TkDefaultFont", 9, "bold")
                   ).pack(anchor="w")
        if found:
            scan_text = tr("tool.news_desk.chapter.import_found_body",
                            n=len(found),
                            files=", ".join(found))
            scan_color = "#444"
        else:
            scan_text = tr("tool.news_desk.chapter.import_found_none")
            scan_color = "#a00"
        ttk.Label(body, text=scan_text, wraplength=520, justify="left",
                   foreground=scan_color
                   ).pack(anchor="w", pady=(2, 8))

        # What import will do (incl. overwrite warning when applicable).
        ttk.Label(body,
                   text=tr("tool.news_desk.chapter.import_effect_label"),
                   font=("TkDefaultFont", 9, "bold")
                   ).pack(anchor="w")
        if chapters:
            effect_text = tr(
                "tool.news_desk.chapter.import_effect_overwrite",
                n=len(chapters))
            effect_color = "#a00"
        else:
            effect_text = tr("tool.news_desk.chapter.import_effect_fresh")
            effect_color = "#444"
        ttk.Label(body, text=effect_text, wraplength=520, justify="left",
                   foreground=effect_color
                   ).pack(anchor="w", pady=(2, 8))

        # Buttons.
        btns = ttk.Frame(dlg); btns.pack(fill="x", padx=12, pady=(0, 10))

        def _do_import():
            _import_from_analysis(instance, ctx)
            _refresh_tree()
            _show_row(None)
            on_change()
            dlg.destroy()

        confirm_btn = ttk.Button(
            btns,
            text=tr("tool.news_desk.chapter.import_confirm"),
            command=_do_import)
        confirm_btn.pack(side="right")
        if not found:
            confirm_btn.config(state="disabled")
        ttk.Button(btns,
                    text=tr("tool.news_desk.chapter.cancel_btn"),
                    command=dlg.destroy
                    ).pack(side="right", padx=(0, 8))

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
    import_btn.config(command=_do_import_analysis)

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
    # No host-rendered import buttons — chapter owns its own [Import]
    # button inline in the toolbar (with explanation dialog).
    import_sources=[],
))
