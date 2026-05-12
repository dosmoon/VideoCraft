"""Source video preview pane.

Right side of the preview tab. Layout:

  +----------------------------------+--------------------+
  |  WebView2 <video> player         |  metadata sidebar  |
  |  (left, main area)               |  来源 / URL / ... |
  |                                  |  [修改]  [浏览]    |
  +----------------------------------+--------------------+

Uses ui.web_preview.WebPreviewFrame (child-process WebView2 + SetParent)
for the video; an inline metadata column replaces the old details dialog.
"""

from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from core.project_schema import ORIGIN_LINK, ORIGIN_LOCAL
from ui.web_preview import WebPreviewFrame
from i18n import tr


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


def _fmt_size(path: str) -> str:
    try:
        n = os.path.getsize(path)
    except OSError:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_mtime(path: str) -> str:
    try:
        ts = os.path.getmtime(path)
    except OSError:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _fmt_duration(sec: float | None) -> str:
    if sec is None or sec <= 0:
        return "—"
    s = int(sec)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def build_source_preview(
    parent: tk.Frame,
    project,
    on_modify=None,
) -> tk.Frame:
    """Build the source preview UI inside parent. on_modify is invoked when
    the user clicks the [修改] button (Hub re-uses its source-add flow)."""
    outer = tk.Frame(parent, bg="white")

    src = project.meta.source
    video_path = project.source_video_path
    ready = os.path.isfile(video_path) and os.path.getsize(video_path) > 0

    # Two-column body: video left, metadata right.
    body = tk.Frame(outer, bg="white")
    body.pack(fill="both", expand=True, padx=12, pady=10)

    video_col = tk.Frame(body, bg="black")
    video_col.pack(side="left", fill="both", expand=True)

    meta_col = tk.Frame(body, bg="white", width=280)
    meta_col.pack(side="right", fill="y", padx=(12, 0))
    meta_col.pack_propagate(False)

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

    # ── Metadata column ──
    tk.Label(meta_col, text=src.title or "video.mp4",
             bg="white", fg="#222",
             font=("Microsoft YaHei UI", 12, "bold"),
             anchor="w", wraplength=270, justify="left",
             ).pack(fill="x", anchor="w")

    status_txt = (tr("source_preview.status_ready", size=_fmt_size(video_path))
                  if ready else tr("source_preview.missing"))
    tk.Label(meta_col, text=status_txt,
             bg="white", fg="#666", font=("Microsoft YaHei UI", 9),
             anchor="w",
             ).pack(fill="x", anchor="w", pady=(2, 0))

    if ready:
        tk.Label(meta_col, text=tr("source_preview.modified_at", ts=_fmt_mtime(video_path)),
                 bg="white", fg="#888", font=("Microsoft YaHei UI", 9),
                 anchor="w",
                 ).pack(fill="x", anchor="w", pady=(0, 6))

    ttk.Separator(meta_col, orient="horizontal").pack(fill="x", pady=(6, 8))

    # Field rows
    rows: list[tuple[str, str]] = []
    if src.origin == ORIGIN_LINK:
        rows.append((tr("source_preview.field_origin"), tr("source_preview.origin_link")))
        rows.append(("URL", src.url or "—"))
    elif src.origin == ORIGIN_LOCAL:
        rows.append((tr("source_preview.field_origin"), tr("source_preview.origin_local")))
        rows.append((tr("source_preview.field_imported_from"), src.imported_from or "—"))
    else:
        rows.append((tr("source_preview.field_origin"), src.origin or "—"))
    if src.clip_range:
        rows.append((tr("source_preview.field_clip_range"),
                     f"{src.clip_range.start} → {src.clip_range.end}"))
    else:
        rows.append((tr("source_preview.field_clip_range"), tr("source_preview.clip_full")))
    rows.append((tr("source_preview.field_duration"), _fmt_duration(src.duration_sec)))
    if src.width and src.height:
        rows.append((tr("source_preview.field_resolution"), f"{src.width} × {src.height}"))
    else:
        rows.append((tr("source_preview.field_resolution"), "—"))
    rows.append((tr("source_preview.field_local_path"), video_path))

    grid = tk.Frame(meta_col, bg="white")
    grid.pack(fill="x", anchor="w")
    for i, (label, value) in enumerate(rows):
        tk.Label(grid, text=label, bg="white", fg="#666",
                 font=("Microsoft YaHei UI", 9), anchor="nw",
                 ).grid(row=i, column=0, sticky="nw", padx=(0, 10), pady=2)
        tk.Label(grid, text=value, bg="white", fg="#222",
                 font=("Microsoft YaHei UI", 9), anchor="nw",
                 wraplength=170, justify="left",
                 ).grid(row=i, column=1, sticky="nw", pady=2)
    grid.columnconfigure(1, weight=1)

    # Actions
    actions = tk.Frame(meta_col, bg="white")
    actions.pack(fill="x", anchor="w", pady=(12, 0))
    if on_modify is not None:
        tk.Button(actions, text=tr("hub.button.modify"), relief="flat", bg="#e8e8e8",
                  command=on_modify).pack(side="left")

    def _on_open_folder():
        try:
            os.startfile(project.source_dir)
        except OSError as e:
            messagebox.showerror(tr("source_preview.err_open_folder"), str(e), parent=outer)
    tk.Button(actions, text=tr("source_preview.btn_show_in_explorer"), relief="flat", bg="#e8e8e8",
              command=_on_open_folder).pack(side="left", padx=(6, 0))

    return outer
