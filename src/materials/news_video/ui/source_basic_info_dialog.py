"""Modal dialog for editing source/basic_info.json (5 anchor fields).

The 5 fields are hand-filled ground truth a human knows after seeing
5 seconds of the source video. They seed the news.realtime AI
extraction (preserved verbatim in the merge).

This dialog is intentionally minimal — no AI fill button, no platform
metadata block, no scrolling. The rich 10-field news context lives in
news_context_pane.py's dialog.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from materials.news_video.schema import (
    SourceBasicInfo, read_basic_info, write_basic_info,
)
from i18n import tr


_FIELDS = (
    ("host",           "dialog.source_context.host"),
    ("host_bio",       "dialog.source_context.host_bio"),
    ("event_date",     "dialog.source_context.event_date"),
    ("event_location", "dialog.source_context.event_location"),
    ("episode_topic",  "dialog.source_context.episode_topic"),
)


def show_source_basic_info_dialog(parent: tk.Misc, source_dir: str) -> bool:
    """Show the modal. Returns True if user saved, False if cancelled."""
    return _BasicInfoDialog(parent, source_dir).run()


class _BasicInfoDialog:
    def __init__(self, parent: tk.Misc, source_dir: str) -> None:
        self.source_dir = source_dir
        self._saved = False

        self.win = tk.Toplevel(parent)
        self.win.title(tr("dialog.basic_info.title"))
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        info = read_basic_info(source_dir)
        self._vars: dict[str, tk.StringVar] = {
            f: tk.StringVar(value=getattr(info, f, ""))
            for f, _ in _FIELDS
        }

        self._build_ui()
        self._center_over(parent)

    def _build_ui(self) -> None:
        body = ttk.Frame(self.win, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=tr("dialog.basic_info.heading"),
                  font=("Microsoft YaHei UI", 13, "bold"),
                  ).pack(anchor="w", pady=(0, 6))

        ttk.Label(body, text=tr("dialog.basic_info.hint"),
                  foreground="#666", font=("Microsoft YaHei UI", 8),
                  wraplength=440, justify="left",
                  ).pack(anchor="w", pady=(0, 10))

        form = ttk.Frame(body)
        form.pack(fill="x")
        for i, (field, key) in enumerate(_FIELDS):
            ttk.Label(form, text=tr(key), anchor="ne", width=12,
                      ).grid(row=i, column=0, sticky="ne", padx=(0, 8), pady=4)
            entry = ttk.Entry(form, textvariable=self._vars[field], width=44)
            entry.grid(row=i, column=1, sticky="ew", pady=4)
            if field == "event_date":
                ttk.Label(form, text="YYYY-MM-DD",
                          foreground="#888",
                          font=("Microsoft YaHei UI", 8),
                          ).grid(row=i, column=2, sticky="w", padx=(6, 0))
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(16, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_cancel"),
                   command=self._on_cancel,
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("dialog.source_context.btn_save"),
                   command=self._on_save,
                   ).pack(side="right")

        self.win.bind("<Escape>", lambda _e: self._on_cancel())

    def _on_save(self) -> None:
        info = SourceBasicInfo(
            **{f: self._vars[f].get().strip() for f, _ in _FIELDS}
        )
        write_basic_info(self.source_dir, info)
        self._saved = True
        self.win.destroy()

    def _on_cancel(self) -> None:
        self._saved = False
        self.win.destroy()

    def _center_over(self, parent: tk.Misc) -> None:
        from ui.dialog_utils import center_dialog_on_parent
        center_dialog_on_parent(self.win, parent)

    def run(self) -> bool:
        self.win.wait_window()
        return self._saved
