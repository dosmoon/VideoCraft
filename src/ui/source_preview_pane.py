"""Source video preview pane.

Embeds a WebView2 surface (via ui.web_preview.WebPreviewFrame) showing
the project's source/video.mp4 with an HTML5 `<video>` element. Reuses
the same child-process + SetParent infrastructure as clip_workbench.

A thin HTML file is written into the project's .videocraft/cache/
directory and loaded by URL — this lets the video src use absolute
file:// references (load_html's about:blank base would block them).
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from ui.web_preview import WebPreviewFrame


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


def build_source_preview(
    parent: tk.Frame,
    project,
) -> tk.Frame:
    """Build the source preview UI inside parent. Returns the outer Frame."""
    outer = tk.Frame(parent, bg="white")

    src = project.meta.source
    video_path = project.source_video_path

    # Header
    header = tk.Frame(outer, bg="white")
    header.pack(fill="x", padx=12, pady=(10, 6))
    title = src.title or "video.mp4"
    tk.Label(header, text=title, bg="white", fg="#222",
             font=("Microsoft YaHei UI", 12, "bold"), anchor="w",
             ).pack(side="left")
    bits = []
    if src.duration_sec:
        sec = int(src.duration_sec)
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        bits.append(f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}")
    if src.width and src.height:
        bits.append(f"{src.width}×{src.height}")
    if bits:
        tk.Label(header, text="  ·  " + "  ·  ".join(bits),
                 bg="white", fg="#888", font=("Microsoft YaHei UI", 9),
                 ).pack(side="left")

    ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=12)

    # Body: WebView holding the <video> element.
    body = tk.Frame(outer, bg="black")
    body.pack(fill="both", expand=True, padx=12, pady=(8, 10))

    if not os.path.isfile(video_path):
        tk.Label(body, text="✗ 源视频缺失", bg="black", fg="#aaa",
                 font=("Microsoft YaHei UI", 11),
                 ).pack(expand=True)
        return outer

    # Write a tiny HTML file into the project's cache dir so the WebView
    # can load it via a file:// URL (about:blank can't reference file://
    # media). The cache file is overwritten each call — single-use is fine.
    cache_dir = os.path.join(project.videocraft_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    html_path = os.path.join(cache_dir, "source_preview.html")
    video_url = "file:///" + os.path.abspath(video_path).replace("\\", "/")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_HTML_TEMPLATE.format(video_url=video_url))
    initial_url = "file:///" + html_path.replace("\\", "/")

    web = WebPreviewFrame(body, initial_url=initial_url)
    web.pack(fill="both", expand=True)

    # Stash for clean shutdown when the pane is destroyed.
    outer._web = web  # type: ignore[attr-defined]

    def _on_destroy(_e=None):
        try:
            web.destroy()
        except Exception:
            pass
    outer.bind("<Destroy>", _on_destroy)

    return outer
