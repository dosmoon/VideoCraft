"""Generic video preview pane.

Renders any local video file inside a WebView2 surface, using the same
child-process + SetParent infrastructure as the source preview. Used
by the Hub to preview derivative outputs (e.g. derivatives/<type>/
<inst>/output.mp4) when the user clicks the corresponding sidebar row.

Lighter than source_preview_pane.py — no metadata column, just video
+ a thin header. The metadata for derivative outputs is essentially
just the burn config which the workbench already shows.
"""

from __future__ import annotations

import os
import tkinter as tk

from ui.web_preview import WebPreviewFrame
from i18n import tr


_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>video preview</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #000; height: 100%; }}
  body {{ display: flex; align-items: center; justify-content: center; }}
  video {{ width: 100%; height: 100%; object-fit: contain; }}
</style>
</head><body>
  <video id="v" controls preload="metadata" src="{video_url}"></video>
</body></html>
"""


def build_video_preview(
    parent: tk.Frame,
    video_path: str,
    cache_dir: str,
    *,
    title: str | None = None,
) -> tk.Frame:
    """Build the player UI inside parent. Returns the outer Frame."""
    outer = tk.Frame(parent, bg="white")

    # Header
    header = tk.Frame(outer, bg="white")
    header.pack(fill="x", padx=12, pady=(10, 6))
    tk.Label(header, text=title or os.path.basename(video_path),
             bg="white", fg="#222",
             font=("Microsoft YaHei UI", 12, "bold"),
             anchor="w",
             ).pack(side="left")
    try:
        size = os.path.getsize(video_path)
        if size < 1024**2:
            size_str = f"{size/1024:.1f} KB"
        elif size < 1024**3:
            size_str = f"{size/1024**2:.1f} MB"
        else:
            size_str = f"{size/1024**3:.2f} GB"
    except OSError:
        size_str = "—"
    tk.Label(header, text=f"  ·  {size_str}",
             bg="white", fg="#888", font=("Microsoft YaHei UI", 9),
             ).pack(side="left")

    body = tk.Frame(outer, bg="black")
    body.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    if not os.path.isfile(video_path):
        tk.Label(body, text=tr("video_preview.missing"), bg="black", fg="#aaa",
                 font=("Microsoft YaHei UI", 11),
                 ).pack(expand=True)
        return outer

    # Stable HTML stub per video path so the WebView can load via file://.
    os.makedirs(cache_dir, exist_ok=True)
    stub_name = "video_preview.html"
    html_path = os.path.join(cache_dir, stub_name)
    video_url = "file:///" + os.path.abspath(video_path).replace("\\", "/")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_HTML_TEMPLATE.format(video_url=video_url))
    initial_url = "file:///" + html_path.replace("\\", "/")

    web = WebPreviewFrame(body, initial_url=initial_url)
    web.pack(fill="both", expand=True)
    outer._web = web  # type: ignore[attr-defined]

    def _on_destroy(_e=None):
        try:
            web.destroy()
        except Exception:
            pass
    outer.bind("<Destroy>", _on_destroy)

    return outer
