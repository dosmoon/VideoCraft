"""Source video preview pane.

Layout (resizable horizontal split):

  +------------------+--------------------------------+
  |                  |  Title + status                |
  |  WebView2 player |  ──                             |
  |  (left)          |  Source fields (origin / URL / |
  |                  |  duration / resolution / path) |
  |                  |  ──                             |
  |                  |  [Modify source] [Open folder] |
  +------------------+--------------------------------+

Scope: pure file/URL metadata. AI-generated event context lives in the
sibling "新闻背景" pane (ui/news_context_pane.py) so the source card
stays manually-controlled and does not get rewritten by AI workflows.
"""

from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from core.project_schema import ORIGIN_LINK, ORIGIN_LOCAL
from materials.news_video.schema import read_basic_info
from ui.web_preview import WebPreviewFrame
from i18n import tr
from materials.news_video import paths as _nv_paths


_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>source preview</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #000; height: 100%; }}
  body {{ display: flex; align-items: center; justify-content: center; }}
  video {{ width: 100%; height: 100%; object-fit: contain; }}
</style>
</head><body>
  <video id="v" controls preload="metadata" src="{video_url}"></video>
</body></html>
"""

_EMPTY = "—"


def _fmt_size(path: str) -> str:
    try:
        n = os.path.getsize(path)
    except OSError:
        return _EMPTY
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_mtime(path: str) -> str:
    try:
        ts = os.path.getmtime(path)
    except OSError:
        return _EMPTY
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _fmt_duration(sec: float | None) -> str:
    if sec is None or sec <= 0:
        return _EMPTY
    s = int(sec)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def build_source_preview(
    parent: tk.Frame,
    model_or_project,
    on_modify=None,
) -> tk.Frame:
    """Build the source preview UI inside parent. Accepts either a
    NewsVideoModel or (legacy) a Project — extracts paths via the
    model when given, else falls back to first-instance via paths.py.
    on_modify is invoked when the user clicks [Modify]."""
    outer = tk.Frame(parent, bg="white")

    # Duck-type: model has instance_id; project doesn't.
    if hasattr(model_or_project, "instance_id"):
        project = model_or_project.project
        video_path = model_or_project.source_video_path
    else:
        project = model_or_project
        video_path = _nv_paths.source_video_path(project)
    src = project.meta.source
    ready = os.path.isfile(video_path) and os.path.getsize(video_path) > 0

    # Resizable horizontal split.
    paned = tk.PanedWindow(outer, orient="horizontal", sashwidth=6,
                            sashrelief="flat", bg="#ddd", bd=0)
    paned.pack(fill="both", expand=True, padx=8, pady=8)

    video_col = tk.Frame(paned, bg="black")
    meta_outer = tk.Frame(paned, bg="white")
    paned.add(video_col, minsize=240, stretch="always")
    paned.add(meta_outer, minsize=360, stretch="always")

    # Default the sash so the meta column gets a real share (~45%).
    def _set_initial_sash(_e=None):
        try:
            total = paned.winfo_width()
            if total > 100:
                paned.sash_place(0, int(total * 0.55), 1)
                paned.unbind("<Configure>")
        except tk.TclError:
            pass
    paned.bind("<Configure>", _set_initial_sash)

    # ── Video column ──
    if not ready:
        tk.Label(video_col, text=tr("source_preview.missing"), bg="black", fg="#aaa",
                 font=("Microsoft YaHei UI", 11),
                 ).pack(expand=True)
    else:
        cache_dir = os.path.join(project.videocraft_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        html_path = os.path.join(cache_dir, "source_preview.html")
        video_url = "file:///" + os.path.abspath(video_path).replace("\\", "/")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(_HTML_TEMPLATE.format(video_url=video_url))
        initial_url = "file:///" + html_path.replace("\\", "/")

        web = WebPreviewFrame(video_col, initial_url=initial_url)
        web.pack(fill="both", expand=True)
        outer._web = web  # type: ignore[attr-defined]

        def _on_destroy(_e=None):
            try:
                web.destroy()
            except Exception:
                pass
        outer.bind("<Destroy>", _on_destroy)

    # ── Meta column: scrollable so long fields don't push the bottom buttons out ──
    canvas = tk.Canvas(meta_outer, bg="white", highlightthickness=0, bd=0)
    vsb = ttk.Scrollbar(meta_outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    meta_col = tk.Frame(canvas, bg="white")
    meta_window = canvas.create_window((0, 0), window=meta_col, anchor="nw")

    def _on_meta_configure(_e=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
    meta_col.bind("<Configure>", _on_meta_configure)

    def _on_canvas_configure(e):
        canvas.itemconfigure(meta_window, width=e.width)
    canvas.bind("<Configure>", _on_canvas_configure)

    # Mouse wheel scrolling while hovering the meta column.
    def _on_wheel(e):
        canvas.yview_scroll(-1 * (e.delta // 120), "units")
    meta_col.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_wheel))
    meta_col.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

    inner = tk.Frame(meta_col, bg="white", padx=14, pady=10)
    inner.pack(fill="both", expand=True)

    # Title.
    tk.Label(inner, text=src.title or "video.mp4",
             bg="white", fg="#222",
             font=("Microsoft YaHei UI", 13, "bold"),
             anchor="w", wraplength=420, justify="left",
             ).pack(fill="x", anchor="w")

    status_txt = (tr("source_preview.status_ready", size=_fmt_size(video_path))
                  if ready else tr("source_preview.missing"))
    tk.Label(inner, text=status_txt,
             bg="white", fg="#666", font=("Microsoft YaHei UI", 9),
             anchor="w",
             ).pack(fill="x", anchor="w", pady=(2, 0))

    if ready:
        tk.Label(inner, text=tr("source_preview.modified_at", ts=_fmt_mtime(video_path)),
                 bg="white", fg="#888", font=("Microsoft YaHei UI", 9),
                 anchor="w",
                 ).pack(fill="x", anchor="w", pady=(0, 4))

    ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=(8, 8))

    # ── Source field rows ──
    rows: list[tuple[str, str]] = []
    if src.origin == ORIGIN_LINK:
        rows.append((tr("source_preview.field_origin"), tr("source_preview.origin_link")))
        rows.append(("URL", src.url or _EMPTY))
    elif src.origin == ORIGIN_LOCAL:
        rows.append((tr("source_preview.field_origin"), tr("source_preview.origin_local")))
        rows.append((tr("source_preview.field_imported_from"), src.imported_from or _EMPTY))
    else:
        rows.append((tr("source_preview.field_origin"), src.origin or _EMPTY))
    if src.clip_range:
        rows.append((tr("source_preview.field_clip_range"),
                     f"{src.clip_range.start} → {src.clip_range.end}"))
    else:
        rows.append((tr("source_preview.field_clip_range"), tr("source_preview.clip_full")))
    rows.append((tr("source_preview.field_duration"), _fmt_duration(src.duration_sec)))
    if src.width and src.height:
        rows.append((tr("source_preview.field_resolution"), f"{src.width} × {src.height}"))
    else:
        rows.append((tr("source_preview.field_resolution"), _EMPTY))
    rows.append((tr("source_preview.field_local_path"), video_path))

    _render_kv_grid(inner, rows, label_width=10, value_wrap=300)

    ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=(10, 6))

    # ── Manual anchor fields ──
    # Hand-filled ground-truth that the AI extractor sees as `existing` and
    # MUST preserve. Edit here BEFORE clicking AI Fill in the news pane to
    # constrain the model's guesses (e.g. correct host name, exact date).
    header = tk.Frame(inner, bg="white")
    header.pack(fill="x", anchor="w")
    tk.Label(header, text=tr("source_preview.manual_section"),
             bg="white", fg="#333",
             font=("Microsoft YaHei UI", 10, "bold"),
             anchor="w").pack(side="left")

    def _on_edit_context():
        from materials.news_video.ui.source_basic_info_dialog import show_source_basic_info_dialog
        if show_source_basic_info_dialog(outer, _nv_paths.source_dir(project)):
            _refresh_manual()
    tk.Button(header, text=tr("source_preview.btn_edit_context"), relief="flat",
              bg="#e8e8e8", command=_on_edit_context, padx=8,
              ).pack(side="right")

    tk.Label(inner, text=tr("source_preview.manual_hint"),
             bg="white", fg="#888", font=("Microsoft YaHei UI", 8),
             anchor="w", justify="left", wraplength=400,
             ).pack(fill="x", anchor="w", pady=(2, 4))

    manual_block = tk.Frame(inner, bg="white")
    manual_block.pack(fill="x", anchor="w")

    def _refresh_manual():
        for child in manual_block.winfo_children():
            child.destroy()
        _render_anchor_fields(manual_block, _nv_paths.source_dir(project))
    _refresh_manual()

    ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=(12, 8))

    # ── Bottom action row ──
    actions = tk.Frame(inner, bg="white")
    actions.pack(fill="x", anchor="w")

    if on_modify is not None:
        tk.Button(actions, text=tr("hub.button.modify"), relief="flat", bg="#e8e8e8",
                  command=on_modify, padx=10,
                  ).pack(side="left")

    def _on_open_folder():
        try:
            os.startfile(_nv_paths.source_dir(project))
        except OSError as e:
            messagebox.showerror(tr("source_preview.err_open_folder"), str(e), parent=outer)
    tk.Button(actions, text=tr("source_preview.btn_show_in_explorer"), relief="flat",
              bg="#e8e8e8", command=_on_open_folder, padx=10,
              ).pack(side="left", padx=(6, 0))

    return outer


_ANCHOR_FIELDS = (
    # (field, label_i18n_key) — curated set of "facts a human knows by
    # watching the video for 5 seconds". Used as authoritative seed for AI
    # extraction. Other 10 fields (summary / background / key_points / ...)
    # are AI-derived and live in the news_context pane.
    ("host",           "dialog.source_context.host"),
    ("host_bio",       "dialog.source_context.host_bio"),
    ("event_date",     "dialog.source_context.event_date"),
    ("event_location", "dialog.source_context.event_location"),
    ("episode_topic",  "dialog.source_context.episode_topic"),
)


def _render_anchor_fields(parent: tk.Frame, source_dir: str) -> None:
    """Render the 5 manual-anchor fields read-only (edit via dialog)."""
    info = read_basic_info(source_dir)
    rows: list[tuple[str, str]] = []
    for fname, key in _ANCHOR_FIELDS:
        label = tr(key).rstrip(":：")
        value = (getattr(info, fname, "") or "").strip()
        rows.append((label, value or _EMPTY))
    _render_kv_grid(parent, rows, label_width=10, value_wrap=300)


def _render_kv_grid(parent: tk.Frame,
                     rows: list[tuple[str, str]],
                     *,
                     label_width: int = 10,
                     value_wrap: int = 300) -> None:
    """Render a key/value table with grey labels and wrapping values."""
    grid = tk.Frame(parent, bg="white")
    grid.pack(fill="x", anchor="w")
    for i, (label, value) in enumerate(rows):
        tk.Label(grid, text=label, bg="white", fg="#666",
                 font=("Microsoft YaHei UI", 9), anchor="nw",
                 width=label_width,
                 ).grid(row=i, column=0, sticky="nw", padx=(0, 10), pady=2)
        tk.Label(grid, text=value or _EMPTY, bg="white", fg="#222",
                 font=("Microsoft YaHei UI", 9), anchor="nw",
                 wraplength=value_wrap, justify="left",
                 ).grid(row=i, column=1, sticky="nw", pady=2)
    grid.columnconfigure(1, weight=1)


