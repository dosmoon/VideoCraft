"""One-time disclaimer shown the first time a user creates a project
from a video link. Persisted to settings.json as
`link_disclaimer_accepted=true` after they click 「我已知晓」.

Wording is platform-neutral (no specific site names) — matches the
permanent small-text disclaimer that lives in the new-project dialog
footer.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core import settings
from i18n import tr

SETTINGS_KEY = "link_disclaimer_accepted"


def has_been_accepted() -> bool:
    return bool(settings.get(SETTINGS_KEY, False))


def mark_accepted() -> None:
    settings.set_(SETTINGS_KEY, True)


def show_if_needed(parent: tk.Misc) -> bool:
    """Show the disclaimer if the user hasn't accepted it yet.

    Returns True if the user accepted (or had already accepted previously),
    False if they cancelled. Caller should treat False as "abort the
    create-project flow."
    """
    if has_been_accepted():
        return True
    return _DisclaimerDialog(parent).run()


class _DisclaimerDialog:
    def __init__(self, parent: tk.Misc) -> None:
        self._accepted = False
        self.win = tk.Toplevel(parent)
        self.win.title(tr("dialog.disclaimer.title"))
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._build_ui()
        from ui.dialog_utils import center_dialog_on_parent
        center_dialog_on_parent(self.win, parent)

    def _build_ui(self) -> None:
        body = ttk.Frame(self.win, padding=24)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=tr("dialog.disclaimer.heading"),
                  font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 12))

        ttk.Label(body, text=tr("dialog.disclaimer.body"), justify="left",
                  font=("Microsoft YaHei UI", 10), wraplength=420
                  ).pack(anchor="w")

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(16, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_cancel"), command=self._on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("dialog.disclaimer.btn_accept"), command=self._on_accept
                   ).pack(side="right")

    def _on_accept(self) -> None:
        mark_accepted()
        self._accepted = True
        self.win.destroy()

    def _on_cancel(self) -> None:
        self._accepted = False
        self.win.destroy()

    def run(self) -> bool:
        self.win.wait_window()
        return self._accepted
