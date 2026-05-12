"""New Project dialog (P4 simplified).

Asks only for: project name + parent directory. Source video and
subtitles are added later from the Hub sidebar — the project starts
empty.

Returns a NewProjectRequest dataclass on success; caller (launcher)
then just calls Project.new() to mkdir the skeleton. No source
acquisition, no disclaimer, no progress modal.

The source-acquisition pieces that used to live here (link/local
radio, fetch-info button, time range, disclaimer footer) moved to
sidebar Source-row dialogs in P4.3.
"""

from __future__ import annotations

import os
import re
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, ttk
from typing import Optional

from core import settings
from i18n import tr


# Settings keys — also read by sidebar Source-add dialog and Preferences.
SETTINGS_KEY_LAST_PARENT = "last_parent_dir"
SETTINGS_KEY_DEFAULT_PARENT = "default_parent_dir"


@dataclass
class NewProjectRequest:
    """What the dialog returns on success. Source/subtitles come later."""
    parent_dir: str
    name: str


def show_new_project_dialog(parent: tk.Misc) -> Optional[NewProjectRequest]:
    """Show the simplified new-project dialog. None on cancel."""
    return _NewProjectDialog(parent).run()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _default_parent_dir() -> str:
    """Pick a sane default for the parent directory field.

    Priority: explicit Preferences override → last successful create →
    ~/Documents/VideoCraft (Windows) or ~/VideoCraft (Mac/Linux).
    """
    v = settings.get(SETTINGS_KEY_DEFAULT_PARENT)
    if isinstance(v, str) and v:
        return v
    v = settings.get(SETTINGS_KEY_LAST_PARENT)
    if isinstance(v, str) and v and os.path.isdir(v):
        return v
    if os.name == "nt":
        return os.path.join(os.path.expanduser("~"), "Documents", "VideoCraft")
    return os.path.join(os.path.expanduser("~"), "VideoCraft")


_NAME_BAD_RE = re.compile(r'[\\/:\*\?"<>\|]')


def _sanitize_name(s: str) -> str:
    """Strip filesystem-forbidden chars and surrounding whitespace."""
    return _NAME_BAD_RE.sub("", s).strip()


# ── Dialog ───────────────────────────────────────────────────────────────────

class _NewProjectDialog:
    def __init__(self, parent: tk.Misc) -> None:
        self._result: Optional[NewProjectRequest] = None

        self.win = tk.Toplevel(parent)
        self.win.title(tr("dialog.new_project.title"))
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._name_var = tk.StringVar()
        self._parent_var = tk.StringVar(value=_default_parent_dir())
        self._error_var = tk.StringVar()

        self._build_ui()
        self._center_over(parent)

    def _build_ui(self) -> None:
        body = ttk.Frame(self.win, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=tr("dialog.new_project.heading"),
                  font=("Microsoft YaHei UI", 13, "bold")
                  ).pack(anchor="w", pady=(0, 12))

        # Project name
        row1 = ttk.Frame(body)
        row1.pack(fill="x", pady=4)
        ttk.Label(row1, text=tr("dialog.new_project.label_name"), width=8, anchor="e"
                  ).pack(side="left", padx=(0, 6))
        name_entry = ttk.Entry(row1, textvariable=self._name_var, width=40)
        name_entry.pack(side="left", fill="x", expand=True)
        name_entry.focus_set()

        # Parent directory
        row2 = ttk.Frame(body)
        row2.pack(fill="x", pady=4)
        ttk.Label(row2, text=tr("dialog.new_project.label_location"), width=8, anchor="e"
                  ).pack(side="left", padx=(0, 6))
        ttk.Entry(row2, textvariable=self._parent_var
                  ).pack(side="left", fill="x", expand=True)
        ttk.Button(row2, text=tr("dialog.new_project.btn_browse"), command=self._on_pick_parent
                   ).pack(side="left", padx=(6, 0))

        # Hint about empty project
        ttk.Label(
            body,
            text=tr("dialog.new_project.hint"),
            font=("Microsoft YaHei UI", 8), foreground="#888",
        ).pack(anchor="w", pady=(8, 0))

        # Inline error
        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=(12, 6))
        ttk.Label(body, textvariable=self._error_var,
                  foreground="#c00", font=("Microsoft YaHei UI", 9),
                  wraplength=420
                  ).pack(anchor="w")

        # Buttons
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_cancel"), command=self._on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("dialog.new_project.btn_create"), command=self._on_create
                   ).pack(side="right")

        # Enter creates, Escape cancels.
        self.win.bind("<Return>", lambda _e: self._on_create())
        self.win.bind("<Escape>", lambda _e: self._on_cancel())

    def _on_pick_parent(self) -> None:
        cur = self._parent_var.get()
        initial = cur if cur and os.path.isdir(cur) else _default_parent_dir()
        path = filedialog.askdirectory(
            parent=self.win,
            title=tr("dialog.new_project.pick_location_title"),
            initialdir=initial,
        )
        if path:
            self._parent_var.set(path)

    def _on_create(self) -> None:
        # Validate name
        name = self._name_var.get().strip()
        if not name:
            return self._show_error(tr("dialog.new_project.err_empty_name"))
        sanitized = _sanitize_name(name)
        if sanitized != name:
            return self._show_error(tr("dialog.new_project.err_illegal_chars"))
        if len(sanitized) > 64:
            return self._show_error(tr("dialog.new_project.err_name_too_long"))

        # Validate parent dir
        parent_dir = self._parent_var.get().strip()
        if not parent_dir:
            return self._show_error(tr("dialog.new_project.err_select_location"))
        if not os.path.isdir(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except OSError as e:
                return self._show_error(tr("dialog.new_project.err_mkdir_failed", error=str(e)))
        if not os.access(parent_dir, os.W_OK):
            return self._show_error(tr("dialog.new_project.err_parent_not_writable"))

        if os.path.exists(os.path.join(parent_dir, sanitized)):
            return self._show_error(tr("dialog.new_project.err_dir_exists", name=sanitized))

        # Remember the parent for next time.
        settings.set_(SETTINGS_KEY_LAST_PARENT, parent_dir)

        self._result = NewProjectRequest(parent_dir=parent_dir, name=sanitized)
        self.win.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.win.destroy()

    def _show_error(self, msg: str) -> None:
        self._error_var.set(msg)

    def _center_over(self, parent: tk.Misc) -> None:
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - w) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - h) // 2
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def run(self) -> Optional[NewProjectRequest]:
        self.win.wait_window()
        return self._result
