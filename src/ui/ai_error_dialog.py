"""AI error dialog — Kind-driven recovery actions.

Replaces "messagebox.showerror(str(e))" for AIError exceptions. Each
Kind drives a different set of action buttons (open AI console, retry,
wait + retry with countdown, etc.) so users can recover without
remembering which provider config / prompt is to blame.

Usage:
    from ui.ai_error_dialog import show_ai_error
    try:
        ai.complete(...)
    except AIError as e:
        show_ai_error(self.master, e, retry_callback=lambda: do_again())

The Hub registers an "open AI console" handler at startup via
set_open_console_handler() so the dialog can navigate without each
caller plumbing it manually.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from i18n import tr
from core.ai.errors import AIError, Kind


# Module-level handler — set by Hub at startup. None when running a tool
# standalone (the "Open AI Console" button is then hidden).
_open_console_handler: Optional[Callable[[], None]] = None


def set_open_console_handler(fn: Optional[Callable[[], None]]) -> None:
    """Register a callable that opens the AI Console tab. Hub sets this on
    init. Tools running standalone (without a Hub) leave it None."""
    global _open_console_handler
    _open_console_handler = fn


# Per-Kind config: title key + a list of action keys that should appear.
# Action keys are looked up against the action handler table below; missing
# actions degrade gracefully (the row simply disappears).
_KIND_TITLE_KEYS: dict[Kind, str] = {
    Kind.NETWORK:    "ui.ai_error.title.network",
    Kind.AUTH:       "ui.ai_error.title.auth",
    Kind.QUOTA:      "ui.ai_error.title.quota",
    Kind.RATE_LIMIT: "ui.ai_error.title.rate_limit",
    Kind.REFUSED:    "ui.ai_error.title.refused",
    Kind.MALFORMED:  "ui.ai_error.title.malformed",
    Kind.OVERFLOW:   "ui.ai_error.title.overflow",
    Kind.CANCELLED:  "ui.ai_error.title.cancelled",
    Kind.UNKNOWN:    "ui.ai_error.title.unknown",
}

# Per-Kind hint text shown under the message — explains what to do next.
_KIND_HINT_KEYS: dict[Kind, str] = {
    Kind.NETWORK:    "ui.ai_error.hint.network",
    Kind.AUTH:       "ui.ai_error.hint.auth",
    Kind.QUOTA:      "ui.ai_error.hint.quota",
    Kind.RATE_LIMIT: "ui.ai_error.hint.rate_limit",
    Kind.REFUSED:    "ui.ai_error.hint.refused",
    Kind.MALFORMED:  "ui.ai_error.hint.malformed",
    Kind.OVERFLOW:   "ui.ai_error.hint.overflow",
    Kind.CANCELLED:  "ui.ai_error.hint.cancelled",
    Kind.UNKNOWN:    "ui.ai_error.hint.unknown",
}


def show_ai_error(parent, error: AIError, *,
                   retry_callback: Optional[Callable[[], None]] = None) -> None:
    """Open a modal AI error dialog. parent should be a Tk widget."""
    dlg = AIErrorDialog(parent, error, retry_callback=retry_callback)
    parent.wait_window(dlg)


class AIErrorDialog(tk.Toplevel):
    def __init__(self, parent, error: AIError, *,
                  retry_callback: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self._error = error
        self._retry_callback = retry_callback
        self._countdown_id: Optional[str] = None
        self._countdown_remaining: float = 0.0

        self.title(tr(_KIND_TITLE_KEYS.get(error.kind,
                                            "ui.ai_error.title.unknown")))
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.geometry("520x320")

        # Header — provider + Kind label
        head = tk.Frame(self, padx=14, pady=10, bg="#fef2f2")
        head.pack(fill=tk.X)
        tk.Label(head, text=tr(_KIND_TITLE_KEYS.get(error.kind,
                                                     "ui.ai_error.title.unknown")),
                 bg="#fef2f2", fg="#991b1b",
                 font=("Arial", 11, "bold"), anchor="w").pack(
            side=tk.LEFT)
        tk.Label(head, text=f"({error.provider})", bg="#fef2f2",
                 fg="#7f1d1d", font=("Arial", 9), anchor="e").pack(
            side=tk.RIGHT)

        # Message body
        body = tk.Frame(self, padx=14, pady=12)
        body.pack(fill=tk.BOTH, expand=True)
        tk.Label(body, text=error.message, anchor="w", justify="left",
                 wraplength=480, font=("Arial", 10)).pack(
            fill=tk.X, anchor="w")
        hint_key = _KIND_HINT_KEYS.get(error.kind, "ui.ai_error.hint.unknown")
        tk.Label(body, text=tr(hint_key), anchor="w", justify="left",
                 wraplength=480, font=("Arial", 9), fg="#525252").pack(
            fill=tk.X, anchor="w", pady=(8, 0))

        # Optional Retry-After hint
        if error.retry_after:
            tk.Label(body, text=tr("ui.ai_error.retry_after_hint",
                                    seconds=int(error.retry_after)),
                     anchor="w", font=("Arial", 9), fg="#92400e").pack(
                fill=tk.X, anchor="w", pady=(4, 0))

        # Action buttons row — picked per Kind
        actions = tk.Frame(self, padx=14, pady=10)
        actions.pack(fill=tk.X, side=tk.BOTTOM)
        self._build_actions(actions)

        from ui.dialog_utils import center_dialog_on_parent
        try:
            center_dialog_on_parent(self, parent)
        except Exception:
            pass

        self.bind("<Escape>", lambda *_: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_actions(self, parent: tk.Frame) -> None:
        e = self._error
        # Right-aligned cluster.
        cluster = tk.Frame(parent)
        cluster.pack(side=tk.RIGHT)

        # Always-present: dismiss
        tk.Button(cluster, text=tr("ui.ai_error.btn_close"),
                  command=self._close, width=10).pack(
            side=tk.RIGHT, padx=(4, 0))

        # AUTH / QUOTA / OVERFLOW → AI Console (key/provider/model fixes)
        if e.kind in (Kind.AUTH, Kind.QUOTA, Kind.OVERFLOW) and \
                _open_console_handler is not None:
            tk.Button(cluster, text=tr("ui.ai_error.btn_open_console"),
                      command=self._open_console, width=18).pack(
                side=tk.RIGHT, padx=(4, 0))

        # REFUSED → also direct to AI Console (Prompts tab inside it)
        if e.kind == Kind.REFUSED and _open_console_handler is not None:
            tk.Button(cluster, text=tr("ui.ai_error.btn_open_prompts"),
                      command=self._open_console, width=18).pack(
                side=tk.RIGHT, padx=(4, 0))

        # NETWORK / RATE_LIMIT / MALFORMED → optional retry
        if self._retry_callback is not None and e.kind in (
                Kind.NETWORK, Kind.RATE_LIMIT, Kind.MALFORMED):
            if e.kind == Kind.RATE_LIMIT and e.retry_after:
                self._countdown_remaining = float(e.retry_after)
                self._retry_btn = tk.Button(
                    cluster, text="", command=self._do_retry, width=18,
                    state="disabled")
                self._retry_btn.pack(side=tk.RIGHT, padx=(4, 0))
                self._tick_countdown()
            else:
                tk.Button(cluster, text=tr("ui.ai_error.btn_retry"),
                          command=self._do_retry, width=10).pack(
                    side=tk.RIGHT, padx=(4, 0))

    def _tick_countdown(self) -> None:
        remaining = max(0, int(self._countdown_remaining))
        if remaining <= 0:
            self._retry_btn.config(
                text=tr("ui.ai_error.btn_retry"), state="normal")
            return
        self._retry_btn.config(
            text=tr("ui.ai_error.btn_retry_in", seconds=remaining))
        self._countdown_remaining -= 1
        self._countdown_id = self.after(1000, self._tick_countdown)

    def _open_console(self) -> None:
        if _open_console_handler is not None:
            try:
                _open_console_handler()
            except Exception:
                pass
        self._close()

    def _do_retry(self) -> None:
        cb = self._retry_callback
        self._close()
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _close(self) -> None:
        if self._countdown_id is not None:
            try:
                self.after_cancel(self._countdown_id)
            except Exception:
                pass
        self.destroy()
