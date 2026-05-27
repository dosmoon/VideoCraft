"""GPU runtime install dialog for the Model Manager.

Single entry point: GpuRuntimeDialog(parent).open() opens a modal that
shows current CUDA status and lets the user install / uninstall the
nvidia-*-cu12 wheels.  Runs pip on a worker thread; streams output into
a Text widget.  Disables action buttons while a job is running.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from i18n import tr
from ui.dialog_utils import center_dialog_on_parent

from core import gpu as _gpu
from core import gpu_install


class GpuRuntimeDialog:
    def __init__(self, parent: tk.Misc, on_changed=None):
        self._parent = parent
        self._on_changed = on_changed
        self._dlg: tk.Toplevel | None = None
        self._busy = False

    def open(self):
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        dlg.title(tr("tool.models.gpu.title"))
        dlg.transient(self._parent.winfo_toplevel())
        dlg.grab_set()
        dlg.minsize(560, 380)

        # Action row pinned to the bottom — see ui.dialog_utils convention.
        btns = ttk.Frame(dlg)
        btns.pack(side="bottom", fill="x", padx=12, pady=10)

        body = ttk.Frame(dlg)
        body.pack(fill="both", expand=True, padx=12, pady=10)

        # ── Status block ────────────────────────────────────────────────
        status = _gpu.cuda_status()
        installed = gpu_install.is_installed()

        self._var_state = tk.StringVar()
        self._var_device = tk.StringVar()
        self._var_size = tk.StringVar(value=tr("tool.models.gpu.size_hint"))

        ttk.Label(body, textvariable=self._var_state,
                  font=("", 11, "bold")).pack(anchor="w")
        ttk.Label(body, textvariable=self._var_device,
                  foreground="#555").pack(anchor="w", pady=(2, 0))
        ttk.Label(body, textvariable=self._var_size,
                  foreground="#888").pack(anchor="w", pady=(2, 8))

        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=(0, 8))

        # ── Log area ────────────────────────────────────────────────────
        ttk.Label(body, text=tr("tool.models.gpu.log_label"),
                  foreground="#555").pack(anchor="w")

        log_frame = ttk.Frame(body)
        log_frame.pack(fill="both", expand=True, pady=(2, 0))

        self._log = tk.Text(log_frame, height=10, wrap="none",
                            font=("Consolas", 9), state="disabled",
                            background="#f4f4f4")
        sb_y = ttk.Scrollbar(log_frame, orient="vertical",
                             command=self._log.yview)
        self._log.configure(yscrollcommand=sb_y.set)
        self._log.pack(side="left", fill="both", expand=True)
        sb_y.pack(side="right", fill="y")

        # ── Buttons ─────────────────────────────────────────────────────
        self._btn_install = ttk.Button(
            btns, text=tr("tool.models.gpu.btn_install"),
            command=self._on_install)
        self._btn_uninstall = ttk.Button(
            btns, text=tr("tool.models.gpu.btn_uninstall"),
            command=self._on_uninstall)
        self._btn_close = ttk.Button(
            btns, text=tr("tool.models.gpu.btn_close"),
            command=self._close)

        self._btn_install.pack(side="left", padx=4)
        self._btn_uninstall.pack(side="left", padx=4)
        self._btn_close.pack(side="right", padx=4)

        self._refresh_status(status, installed)
        center_dialog_on_parent(dlg, self._parent)

    # ── Status / button gating ─────────────────────────────────────────

    def _refresh_status(self, status: dict | None = None,
                        installed: bool | None = None):
        if status is None:
            status = _gpu.cuda_status()
        if installed is None:
            installed = gpu_install.is_installed()

        if installed and status.get("available"):
            self._var_state.set(tr("tool.models.gpu.state_enabled"))
        elif installed:
            # Wheels installed but no driver / nvidia-smi failure.
            self._var_state.set(tr("tool.models.gpu.state_installed_no_driver"))
        else:
            self._var_state.set(tr("tool.models.gpu.state_disabled"))

        device = status.get("device_name") or ""
        driver = status.get("driver") or ""
        vram = status.get("vram_mb") or 0
        if device:
            self._var_device.set(tr("tool.models.gpu.device_info").format(
                device=device, vram=vram, driver=driver))
        else:
            self._var_device.set(tr("tool.models.gpu.no_device_info"))

        self._btn_install.configure(
            state="disabled" if (self._busy or installed) else "normal")
        self._btn_uninstall.configure(
            state="disabled" if (self._busy or not installed) else "normal")

    # ── Actions ────────────────────────────────────────────────────────

    def _on_install(self):
        if not messagebox.askyesno(
            tr("tool.models.gpu.title"),
            tr("tool.models.gpu.confirm_install"),
            parent=self._dlg,
        ):
            return
        self._start("install")

    def _on_uninstall(self):
        if not messagebox.askyesno(
            tr("tool.models.gpu.title"),
            tr("tool.models.gpu.confirm_uninstall"),
            parent=self._dlg,
        ):
            return
        self._start("uninstall")

    def _start(self, action: str):
        self._busy = True
        self._refresh_status()
        self._log_clear()
        self._log_line(tr("tool.models.gpu.starting").format(action=action))

        def on_line(line: str):
            # Worker thread → marshal to Tk.
            try:
                self._dlg.after(0, lambda: self._log_line(line))
            except Exception:
                pass

        def on_done(rc: int):
            try:
                self._dlg.after(0, lambda: self._finish(action, rc))
            except Exception:
                pass

        gpu_install.run_in_background(action, on_line, on_done)

    def _finish(self, action: str, rc: int):
        self._busy = False
        # `cuda_available()` caches its probe result.  Reset so the next
        # status refresh re-evaluates after install/uninstall.
        _gpu._CUDA_PROBE_RESULT = None
        self._refresh_status()
        if rc == 0:
            self._log_line(tr("tool.models.gpu.done_ok").format(action=action))
        else:
            self._log_line(tr("tool.models.gpu.done_fail").format(
                action=action, rc=rc))
        if self._on_changed is not None:
            try:
                self._on_changed()
            except Exception:
                pass

    # ── Log helpers ────────────────────────────────────────────────────

    def _log_clear(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _log_line(self, line: str):
        self._log.configure(state="normal")
        self._log.insert("end", line + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _close(self):
        if self._busy:
            if not messagebox.askyesno(
                tr("tool.models.gpu.title"),
                tr("tool.models.gpu.confirm_close_busy"),
                parent=self._dlg,
            ):
                return
        try:
            self._dlg.grab_release()
        except Exception:
            pass
        self._dlg.destroy()
