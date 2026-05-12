"""Source video details dialog.

Read-only modal showing full Source metadata + on-disk file info. Entry
point: Hub sidebar Source row → [详情] button. Acts as the place where
users see *everything* about the source video without re-opening the
Add/Modify dialog.

Buttons:
  [修改]                     → close, caller invokes the Add/Modify flow
  [在资源管理器中显示]       → opens source/ folder in Explorer
  [关闭]                     → close
"""

from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from core.project_schema import ORIGIN_LINK, ORIGIN_LOCAL, Source


def show_source_details(parent: tk.Misc, project) -> str | None:
    """Show details. Returns "modify" when the user clicked 修改, else None."""
    return _SourceDetailsDialog(parent, project).run()


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


class _SourceDetailsDialog:
    def __init__(self, parent: tk.Misc, project) -> None:
        self.project = project
        self._result: str | None = None

        self.win = tk.Toplevel(parent)
        self.win.title("源视频详情")
        self.win.transient(parent.winfo_toplevel())
        self.win.geometry("560x440")
        self.win.minsize(440, 320)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._populate()

        # Center
        self.win.update_idletasks()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - self.win.winfo_width()) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - self.win.winfo_height()) // 2
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.win, padding=16)
        outer.pack(fill="both", expand=True)

        self._title_var = tk.StringVar(value="…")
        ttk.Label(outer, textvariable=self._title_var,
                  font=("Microsoft YaHei UI", 12, "bold"),
                  ).pack(anchor="w")

        self._status_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self._status_var,
                  foreground="#666", font=("Microsoft YaHei UI", 9),
                  ).pack(anchor="w", pady=(2, 0))

        ttk.Separator(outer, orient="horizontal"
                      ).pack(fill="x", pady=(10, 8))

        # Field grid
        self._grid = ttk.Frame(outer)
        self._grid.pack(fill="both", expand=True)

        # Buttons
        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="修改", command=self._on_modify
                   ).pack(side="left")
        ttk.Button(btns, text="在资源管理器中显示",
                   command=self._on_open_folder
                   ).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="关闭", command=self._on_close
                   ).pack(side="right")

    def _populate(self) -> None:
        src: Source = self.project.meta.source
        video_path = self.project.source_video_path
        ready = self.project.source_status() == "ready"

        self._title_var.set(src.title or "video.mp4")
        if ready:
            self._status_var.set(
                f"✓ 已就绪  ·  {_fmt_size(video_path)}  "
                f"·  修改于 {_fmt_mtime(video_path)}"
            )
        else:
            self._status_var.set("✗ 源视频缺失")

        # Clear and rebuild grid rows
        for child in self._grid.winfo_children():
            child.destroy()

        rows: list[tuple[str, str]] = []

        # Origin
        if src.origin == ORIGIN_LINK:
            rows.append(("来源", "链接"))
            rows.append(("URL", src.url or "—"))
        elif src.origin == ORIGIN_LOCAL:
            rows.append(("来源", "本地文件"))
            rows.append(("原始路径", src.imported_from or "—"))
        else:
            rows.append(("来源", src.origin or "—"))

        # Clip range
        if src.clip_range:
            rows.append(("截取范围",
                         f"{src.clip_range.start} → {src.clip_range.end}"))
        else:
            rows.append(("截取范围", "全片"))

        # Media properties
        rows.append(("时长", _fmt_duration(src.duration_sec)))
        if src.width and src.height:
            rows.append(("分辨率", f"{src.width} × {src.height}"))
        else:
            rows.append(("分辨率", "—"))

        # On-disk
        rows.append(("本地路径", video_path))

        for i, (label, value) in enumerate(rows):
            ttk.Label(self._grid, text=label + ":",
                      foreground="#666",
                      font=("Microsoft YaHei UI", 9),
                      ).grid(row=i, column=0, sticky="nw", padx=(0, 12), pady=2)
            ttk.Label(self._grid, text=value,
                      font=("Microsoft YaHei UI", 9),
                      wraplength=380, justify="left",
                      ).grid(row=i, column=1, sticky="nw", pady=2)
        self._grid.columnconfigure(1, weight=1)

    def _on_modify(self) -> None:
        self._result = "modify"
        self.win.destroy()

    def _on_open_folder(self) -> None:
        folder = self.project.source_dir
        try:
            os.startfile(folder)
        except OSError as e:
            messagebox.showerror("无法打开文件夹", str(e), parent=self.win)

    def _on_close(self) -> None:
        self.win.destroy()

    def run(self) -> str | None:
        self.win.wait_window()
        return self._result
