"""SRT preview pane.

Read-only viewer for an SRT file rendered in the Hub right pane when
the user clicks a subtitle row in the sidebar. Renders the raw SRT
text in a monospace Text widget with light syntax coloring so cue
indices and timestamps are easy to scan.

Pure UI: takes a parent Frame + srt path, builds itself, exposes no
public API beyond the constructor. Caller destroys the frame to clean up.
"""

from __future__ import annotations

import os
import re
import tkinter as tk
from tkinter import ttk

_TS_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}\s*$"
)
_IDX_RE = re.compile(r"^\d+\s*$")


def build_srt_preview(
    parent: tk.Frame,
    srt_path: str,
    *,
    title: str | None = None,
) -> tk.Frame:
    """Build the preview UI inside parent. Returns the outer Frame so the
    caller can pack it or destroy it later."""
    outer = tk.Frame(parent, bg="white")

    # Header
    header = tk.Frame(outer, bg="white")
    header.pack(fill="x", padx=12, pady=(10, 6))

    name = title or os.path.basename(srt_path)
    tk.Label(header, text=name, bg="white", fg="#222",
             font=("Microsoft YaHei UI", 12, "bold"), anchor="w",
             ).pack(side="left")
    try:
        size = os.path.getsize(srt_path)
        size_str = (f"{size} B" if size < 1024
                    else f"{size/1024:.1f} KB" if size < 1024**2
                    else f"{size/1024**2:.1f} MB")
    except OSError:
        size_str = "—"
    tk.Label(header, text=f"  ·  {size_str}",
             bg="white", fg="#888", font=("Microsoft YaHei UI", 9),
             ).pack(side="left")

    ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=12)

    # Text body
    body = tk.Frame(outer, bg="white")
    body.pack(fill="both", expand=True, padx=12, pady=(8, 10))

    txt = tk.Text(
        body, wrap="word", font=("Consolas", 10),
        bg="white", fg="#222", relief="flat",
        padx=8, pady=6, selectbackground="#cce0f5",
    )
    vsb = ttk.Scrollbar(body, command=txt.yview)
    txt.configure(yscrollcommand=vsb.set)
    txt.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    txt.tag_configure("idx", foreground="#888")
    txt.tag_configure("ts",  foreground="#0070c0")
    txt.tag_configure("err", foreground="#c00")

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        txt.insert("end", f"读取失败: {e}\n", ("err",))
        txt.configure(state="disabled")
        return outer

    for line in raw.splitlines():
        if _IDX_RE.match(line):
            txt.insert("end", line + "\n", ("idx",))
        elif _TS_RE.match(line):
            txt.insert("end", line + "\n", ("ts",))
        else:
            txt.insert("end", line + "\n")

    txt.configure(state="disabled")
    return outer
