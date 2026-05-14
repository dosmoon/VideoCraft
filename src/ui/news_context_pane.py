"""News-context preview pane.

Renders the project's source/context.json — a 15-field 5W+ event
archive — as a read-only inline display, with two action buttons:

  [✨ AI 填充]    one-click search-grounded extraction (xAI Grok or
                  whichever provider is routed to task=news.realtime)
  [✎ 手工编辑]   open the existing modal dialog for fine-grained edits

Lives in the preview tab; activated by the sidebar "新闻背景" entry.
Separated from source_preview_pane.py per the principle: source card
stays manually-controlled (file/URL metadata only); AI-generated
content has its own dedicated surface.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from core.source_context import (
    SourceContext, read_context, read_platform_metadata,
)
from i18n import tr


_EMPTY = "—"


# Field groups — only the 10 AI-owned fields. Anchor fields (host,
# host_bio, event_date, event_location, episode_topic) live in
# basic_info.json and render in source_preview_pane.
_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("dialog.source_context.sec_people", (
        ("host_affiliation", "dialog.source_context.host_affiliation"),
        ("guests",           "dialog.source_context.guests"),
    )),
    ("dialog.source_context.sec_when_where", (
        ("event_time",     "dialog.source_context.event_time"),
    )),
    ("dialog.source_context.sec_event", (
        ("show_type",     "dialog.source_context.show_type"),
        ("event_summary", "dialog.source_context.event_summary"),
        ("key_points",    "dialog.source_context.key_points"),
    )),
    ("dialog.source_context.sec_why", (
        ("background", "dialog.source_context.background"),
    )),
    ("dialog.source_context.sec_production", (
        ("audience",      "dialog.source_context.audience"),
        ("platform_tone", "dialog.source_context.platform_tone"),
        ("notes",         "dialog.source_context.notes"),
    )),
)


def build_news_context_preview(parent: tk.Frame, project) -> tk.Frame:
    """Build the news-context preview UI inside `parent`."""
    outer = tk.Frame(parent, bg="white")

    # Header: title + action buttons + status.
    header = tk.Frame(outer, bg="white", padx=20, pady=14)
    header.pack(fill="x")

    tk.Label(header, text=tr("news_context.heading"),
             bg="white", fg="#222",
             font=("Microsoft YaHei UI", 14, "bold"),
             ).pack(side="left")

    btn_box = tk.Frame(header, bg="white")
    btn_box.pack(side="right")
    status_lbl = tk.Label(btn_box, text="", bg="white", fg="#666",
                          font=("Microsoft YaHei UI", 8))
    status_lbl.pack(side="right", padx=(8, 0))

    ai_btn = tk.Button(btn_box, text=tr("news_context.btn_ai_fill"),
                       relief="flat", bg="#e8e8e8", padx=10)
    ai_btn.pack(side="right", padx=(8, 0))

    edit_btn = tk.Button(btn_box, text=tr("news_context.btn_edit"),
                         relief="flat", bg="#e8e8e8", padx=10)
    edit_btn.pack(side="right")

    # Subtitle hint under heading.
    tk.Label(outer, text=tr("news_context.hint"),
             bg="white", fg="#888", font=("Microsoft YaHei UI", 9),
             anchor="w", justify="left", wraplength=900,
             padx=20,
             ).pack(fill="x", pady=(0, 6))

    ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=20)

    # Scrollable body for the field groups.
    body_wrap = tk.Frame(outer, bg="white")
    body_wrap.pack(fill="both", expand=True, padx=12, pady=(8, 12))

    canvas = tk.Canvas(body_wrap, bg="white", highlightthickness=0, bd=0)
    vsb = ttk.Scrollbar(body_wrap, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    body = tk.Frame(canvas, bg="white")
    body_win = canvas.create_window((0, 0), window=body, anchor="nw")
    body.bind("<Configure>",
              lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfigure(body_win, width=e.width))

    def _on_wheel(e):
        canvas.yview_scroll(-1 * (e.delta // 120), "units")
    body.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_wheel))
    body.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

    def _refresh():
        for child in body.winfo_children():
            child.destroy()
        _render_groups(body, project.source_dir)
    _refresh()

    # Handlers — defined after _refresh so they can call it.
    def _on_edit():
        from ui.source_context_dialog import show_source_context_dialog
        if show_source_context_dialog(outer, project.source_dir):
            _refresh()
    edit_btn.configure(command=_on_edit)

    def _on_ai_fill():
        ai_btn.configure(state="disabled")
        edit_btn.configure(state="disabled")
        status_lbl.configure(text=tr("news_context.ai_running"),
                              fg="#666")

        def _worker():
            err: Exception | None = None
            ctx: SourceContext | None = None
            try:
                from core.source_context_ai import extract
                ctx = extract(project.source_dir, project.subtitles_dir)
            except Exception as e:
                err = e

            def _apply():
                ai_btn.configure(state="normal")
                edit_btn.configure(state="normal")
                if err is not None or ctx is None:
                    status_lbl.configure(text=tr("news_context.ai_error"),
                                          fg="#c44")
                    messagebox.showerror(
                        tr("news_context.ai_error_title"),
                        str(err) if err else "(unknown error)",
                        parent=outer,
                    )
                    return
                # Persist merged context then re-render.
                from core.source_context import write_context
                write_context(project.source_dir, ctx)
                status_lbl.configure(text=tr("news_context.ai_done"),
                                      fg="#2a7")
                _refresh()
            outer.after(0, _apply)

        threading.Thread(target=_worker, daemon=True).start()
    ai_btn.configure(command=_on_ai_fill)

    return outer


def _render_groups(parent: tk.Frame, source_dir: str) -> None:
    """Render platform metadata + 5 grouped sections of context fields."""
    ctx = read_context(source_dir)
    platform = read_platform_metadata(source_dir)

    # Platform metadata block (condensed, read-only).
    pf_rows: list[tuple[str, str]] = []
    up = (platform.get("uploader") or "").strip()
    if up:
        pf_rows.append((tr("dialog.source_context.pf_uploader"), up))
    desc = (platform.get("description") or "").strip()
    if desc:
        if len(desc) > 240:
            desc = desc[:240] + "…"
        pf_rows.append((tr("dialog.source_context.pf_description"), desc))
    tags = platform.get("tags")
    if isinstance(tags, list) and tags:
        pf_rows.append((tr("dialog.source_context.pf_tags"),
                        ", ".join(str(t) for t in tags[:12])))
    if pf_rows:
        _render_section(parent,
                        tr("dialog.source_context.platform_section"),
                        pf_rows, value_color="#666")
        tk.Frame(parent, bg="white", height=4).pack()

    # 5 grouped sections.
    for section_key, fields in _GROUPS:
        rows = [(tr(label_key).rstrip(":："),
                 (getattr(ctx, fname, "") or "").strip() or _EMPTY)
                for fname, label_key in fields]
        _render_section(parent, tr(section_key), rows)


def _render_section(parent: tk.Frame, title: str,
                     rows: list[tuple[str, str]],
                     *, value_color: str = "#222") -> None:
    """Render a labeled section with a kv grid."""
    sec = tk.LabelFrame(parent, text=title, bg="white", fg="#444",
                        font=("Microsoft YaHei UI", 10, "bold"),
                        padx=10, pady=8, bd=1, relief="solid")
    sec.pack(fill="x", anchor="w", padx=4, pady=(0, 8))

    grid = tk.Frame(sec, bg="white")
    grid.pack(fill="x", anchor="w")
    for i, (label, value) in enumerate(rows):
        tk.Label(grid, text=label, bg="white", fg="#666",
                 font=("Microsoft YaHei UI", 9), anchor="nw",
                 width=12,
                 ).grid(row=i, column=0, sticky="nw", padx=(0, 10), pady=2)
        tk.Label(grid, text=value, bg="white", fg=value_color,
                 font=("Microsoft YaHei UI", 9), anchor="nw",
                 wraplength=720, justify="left",
                 ).grid(row=i, column=1, sticky="nw", pady=2)
    grid.columnconfigure(1, weight=1)
