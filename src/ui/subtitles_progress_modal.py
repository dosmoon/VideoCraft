"""Modal dialog driving core.subtitle_pipeline.{run_asr,run_translate}.

Same pattern as ui/source_prepare_modal: worker thread runs the
operation, progress marshalled to UI thread via root.after. Cancel
button signals the CancellationToken; provider tear-down latency is
provider-dependent but always cooperative.

run() returns the pipeline operation's result dict on success or
raises the underlying exception (AIError / FileNotFoundError /
ValueError) so caller can decide on user-facing recovery.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from core.ai.cancellation import CancellationToken
from core.ai.errors import AIError, Kind
from core.subtitle_pipeline import ProgressInfo


# A worker function takes (progress_cb, cancel_token) and returns a dict.
Worker = Callable[[Callable[[ProgressInfo], None], CancellationToken], dict]


class SubtitlesProgressModal:
    """One-shot blocking modal for ASR or translate operations.

    Construct with the worker function + title, call run() to block
    until done. Returns the worker's result dict on success or raises
    the worker's exception (AIError, etc).
    """

    def __init__(
        self,
        parent: tk.Misc,
        worker: Worker,
        title: str = "生成字幕",
        cancel_label: str = "取消",
    ) -> None:
        self.parent = parent
        self.worker = worker
        self._cancel_label = cancel_label

        self._result: dict | None = None
        self._error: Exception | None = None
        self._cancel_token = CancellationToken()

        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._build_ui()

        # Center over parent
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
            body, text="准备中...", font=("Microsoft YaHei UI", 11, "bold")
        )
        self._phase_label.pack(anchor="w")

        self._progress = ttk.Progressbar(body, length=460, mode="determinate")
        self._progress.pack(fill="x", pady=(10, 0))

        self._status_label = ttk.Label(
            body, text="", font=("Microsoft YaHei UI", 9),
            foreground="#666", wraplength=460, justify="left",
        )
        self._status_label.pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(18, 0))
        self._cancel_btn = ttk.Button(
            btns, text=self._cancel_label, command=self._on_cancel,
        )
        self._cancel_btn.pack(side="right")

    # ── Progress marshalling ──────────────────────────────────────────────────

    def _on_progress(self, info: ProgressInfo) -> None:
        self.win.after(0, lambda i=info: self._apply_progress(i))

    def _apply_progress(self, info: ProgressInfo) -> None:
        phase_zh = {
            "preparing":    "准备中",
            "transcribing": "正在转写",
            "translating":  "正在翻译",
        }.get(info.phase, info.phase)
        self._phase_label.config(text=phase_zh)

        if info.percent is None:
            if self._progress["mode"] != "indeterminate":
                self._progress.config(mode="indeterminate")
                self._progress.start(80)
        else:
            if self._progress["mode"] != "determinate":
                self._progress.stop()
                self._progress.config(mode="determinate")
            self._progress["value"] = max(0.0, min(100.0, info.percent))

        if info.status_text:
            self._status_label.config(text=info.status_text)

    def _on_cancel(self) -> None:
        if self._cancel_token.cancelled:
            return
        self._cancel_token.cancel()
        self._cancel_btn.config(state="disabled", text="正在取消...")

    # ── Worker ────────────────────────────────────────────────────────────────

    def _worker_thread(self) -> None:
        try:
            self._result = self.worker(self._on_progress, self._cancel_token)
        except Exception as e:
            self._error = e
        finally:
            self.win.after(0, self.win.destroy)

    def run(self) -> dict:
        threading.Thread(target=self._worker_thread, daemon=True).start()
        self.win.wait_window()
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result
