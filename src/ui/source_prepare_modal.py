"""Modal dialog driving core.source_acquire.acquire() with a progress bar.

The acquisition runs in a worker thread; progress callbacks are
marshalled to the Tk main thread via root.after. User can cancel via
the button; cancellation cleanly rolls back the partial download/copy.

On success the dialog closes and run() returns the AcquireResult.
On failure or cancel run() raises the underlying AcquireError so the
caller (new-project dialog) can decide what to do (retry / cleanup
project skeleton / etc).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Optional

from core.project_schema import Source
from core.source_acquire import (
    acquire, AcquireError, CancelToken, ProgressInfo, AcquireResult,
    ERR_CANCELLED,
)
from i18n import tr


class SourcePrepareModal:
    """One-shot blocking modal. Construct with the Source + dest paths,
    call run() to block until done. run() returns AcquireResult on
    success or raises AcquireError."""

    def __init__(
        self,
        parent: tk.Misc,
        source: Source,
        dest_video_path: str,
        dest_meta_path: str | None = None,
        title: str | None = None,
    ) -> None:
        self.parent = parent
        self.source = source
        self.dest_video_path = dest_video_path
        self.dest_meta_path = dest_meta_path

        self._result: Optional[AcquireResult] = None
        self._error: Optional[AcquireError] = None
        self._cancel_token = CancelToken()

        self.win = tk.Toplevel(parent)
        self.win.title(title or tr("dialog.source_prepare.title"))
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        # X button = cancel
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._build_ui()

        # Center over parent.
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - w) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - h) // 2
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _build_ui(self) -> None:
        body = ttk.Frame(self.win, padding=24)
        body.pack(fill="both", expand=True)

        self._phase_label = ttk.Label(
            body, text=tr("dialog.source_prepare.preparing"), font=("Microsoft YaHei UI", 11, "bold")
        )
        self._phase_label.pack(anchor="w")

        # Width fixed so the layout doesn't bounce as the status text grows.
        self._title_label = ttk.Label(body, text="", font=("Microsoft YaHei UI", 9),
                                      foreground="#555", wraplength=480)
        self._title_label.pack(anchor="w", pady=(2, 12))

        self._progress = ttk.Progressbar(body, length=480, mode="determinate")
        self._progress.pack(fill="x")

        self._status_label = ttk.Label(body, text="", font=("Microsoft YaHei UI", 9),
                                       foreground="#666")
        self._status_label.pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(18, 0))
        self._cancel_btn = ttk.Button(
            btns, text=tr("dialog.source_prepare.btn_cancel"), command=self._on_cancel,
        )
        self._cancel_btn.pack(side="right")

        # Show source title if known
        if self.source.title:
            self._title_label.config(text=self.source.title)
        elif self.source.url:
            self._title_label.config(text=self.source.url)
        elif self.source.imported_from:
            self._title_label.config(text=self.source.imported_from)

    # ── Worker thread → UI marshalling ────────────────────────────────────────

    def _on_progress(self, info: ProgressInfo) -> None:
        """Called from worker thread; marshal to UI thread."""
        # Snapshot dataclass into immutable tuple before crossing thread bound.
        self.win.after(0, lambda i=info: self._apply_progress(i))

    def _apply_progress(self, info: ProgressInfo) -> None:
        # Phase label
        phase_key_map = {
            "fetching info": "dialog.source_prepare.phase.fetching_info",
            "downloading":   "dialog.source_prepare.phase.downloading",
            "copying":       "dialog.source_prepare.phase.copying",
            "cutting":       "dialog.source_prepare.phase.cutting",
            "probing":       "dialog.source_prepare.phase.probing",
        }
        phase_key = phase_key_map.get(info.phase)
        self._phase_label.config(text=tr(phase_key) if phase_key else info.phase)

        # Progress bar
        if info.percent is None:
            # Switch to indeterminate if not already
            if self._progress["mode"] != "indeterminate":
                self._progress.config(mode="indeterminate")
                self._progress.start(80)
        else:
            if self._progress["mode"] != "determinate":
                self._progress.stop()
                self._progress.config(mode="determinate")
            self._progress["value"] = max(0.0, min(100.0, info.percent))

        # Status line: bytes / speed / ETA, or custom override
        if info.status_text:
            self._status_label.config(text=info.status_text)
        else:
            parts = []
            if info.downloaded_bytes is not None and info.total_bytes:
                parts.append(f"{_fmt_bytes(info.downloaded_bytes)} / "
                             f"{_fmt_bytes(info.total_bytes)}")
            elif info.downloaded_bytes is not None:
                parts.append(f"{_fmt_bytes(info.downloaded_bytes)}")
            if info.speed_bps:
                parts.append(f"{_fmt_bytes(info.speed_bps)}/s")
            if info.eta_sec is not None:
                parts.append(tr("dialog.source_prepare.remaining", eta=_fmt_eta(info.eta_sec)))
            self._status_label.config(text=" · ".join(parts))

    def _on_cancel(self) -> None:
        """User asked to cancel — signal worker and disable button."""
        if self._cancel_token.cancelled:
            return  # already cancelling
        self._cancel_token.cancel()
        self._cancel_btn.config(state="disabled", text=tr("dialog.source_prepare.cancelling"))

    # ── Run the worker ────────────────────────────────────────────────────────

    def _worker(self) -> None:
        try:
            self._result = acquire(
                self.source,
                self.dest_video_path,
                dest_meta_path=self.dest_meta_path,
                progress_cb=self._on_progress,
                cancel_token=self._cancel_token,
            )
        except AcquireError as e:
            self._error = e
        except Exception as e:  # last-ditch safety net
            self._error = AcquireError("other", tr("dialog.source_prepare.unexpected_error"), repr(e))
        finally:
            # Close the modal from the UI thread.
            self.win.after(0, self.win.destroy)

    def run(self) -> AcquireResult:
        """Show the modal and block until the worker finishes. Returns
        the AcquireResult on success, raises AcquireError on failure
        (including user cancel → category=ERR_CANCELLED)."""
        threading.Thread(target=self._worker, daemon=True).start()
        self.win.wait_window()
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


# ── Display helpers ───────────────────────────────────────────────────────────

def _fmt_bytes(b: float) -> str:
    """Human-readable bytes. Works for ints or floats."""
    if b < 1024:
        return f"{b:.0f} B"
    for unit in ("KB", "MB", "GB", "TB"):
        b /= 1024
        if b < 1024:
            return f"{b:.1f} {unit}"
    return f"{b:.1f} PB"


def _fmt_eta(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"
