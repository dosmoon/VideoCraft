"""
tools/preferences/preferences.py - Settings panel as a Hub tab.

Sections:
  1. Interface Language
  2. Environment — Node.js / Slidev  (install deps, view status)
  3. Environment — yt-dlp            (upgrade via pip)
  4. Python SDK Status               (read-only version display)
"""

import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

import i18n
from i18n import tr
from tools.base import ToolBase
from core import env_check


class PreferencesApp(ToolBase):
    """Settings tab."""

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.preferences.title"))
        master.geometry("700x860")
        master.resizable(True, True)

        # Scrollable root
        canvas = tk.Canvas(master, highlightthickness=0)
        scrollbar = ttk.Scrollbar(master, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        root = tk.Frame(canvas, padx=24, pady=20)
        _win = canvas.create_window((0, 0), window=root, anchor="nw")

        def _on_root_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(_win, width=event.width)

        root.bind("<Configure>", _on_root_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel scroll
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)

        # ── Section: Language ────────────────────────────────────────────────
        lang_section = tk.LabelFrame(
            root, text=tr("tool.preferences.section_language"),
            padx=16, pady=12,
        )
        lang_section.pack(fill="x")

        tk.Label(lang_section, text=tr("tool.preferences.language_label")).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=6,
        )

        self._lang_labels = {
            "zh": tr("tool.preferences.language_zh"),
            "en": tr("tool.preferences.language_en"),
        }
        self._current_lang = i18n.get_current_lang()
        self._lang_var = tk.StringVar(
            value=self._lang_labels.get(self._current_lang, self._lang_labels["zh"])
        )
        combo = ttk.Combobox(
            lang_section, textvariable=self._lang_var, state="readonly", width=16,
            values=[self._lang_labels["zh"], self._lang_labels["en"]],
        )
        combo.grid(row=0, column=1, sticky="w", pady=6)

        self._save_btn = tk.Button(
            lang_section, text=tr("tool.preferences.save"),
            command=self._on_save, width=14,
            bg="#0078d4", fg="white", relief="flat",
            activebackground="#1a8ae5", cursor="hand2",
        )
        self._save_btn.grid(row=0, column=2, padx=(12, 0), pady=6)

        self._status_lbl = tk.Label(lang_section, text="", fg="#2e8b57", anchor="w")
        self._status_lbl.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # ── Section: Environment — yt-dlp ────────────────────────────────────
        ytdlp_section = tk.LabelFrame(
            root, text=tr("tool.preferences.section_env_ytdlp"),
            padx=16, pady=12,
        )
        ytdlp_section.pack(fill="x", pady=(16, 0))
        ytdlp_section.columnconfigure(1, weight=1)

        tk.Label(ytdlp_section, text=tr("tool.preferences.env_ytdlp_label"), anchor="w", width=14).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=2,
        )
        self._ytdlp_val = tk.Label(ytdlp_section, text="…", anchor="w", fg="#888")
        self._ytdlp_val.grid(row=0, column=1, sticky="w", pady=2)

        btn_row2 = tk.Frame(ytdlp_section)
        btn_row2.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 4))

        tk.Button(
            btn_row2, text=tr("tool.preferences.btn_refresh"),
            command=self._refresh_ytdlp_status, width=12,
        ).pack(side="left", padx=(0, 8))

        self._upgrade_ytdlp_btn = tk.Button(
            btn_row2, text=tr("tool.preferences.btn_upgrade_ytdlp"),
            command=self._upgrade_ytdlp,
            bg="#0078d4", fg="white", relief="flat",
            activebackground="#1a8ae5", cursor="hand2",
        )
        self._upgrade_ytdlp_btn.pack(side="left")

        self._ytdlp_log = scrolledtext.ScrolledText(
            ytdlp_section, height=4, state="disabled",
            font=("Consolas", 9), wrap="word",
        )
        self._ytdlp_log.grid(
            row=2, column=0, columnspan=2,
            sticky="ew", pady=(4, 0),
        )

        # ── Section: Python SDK Status ───────────────────────────────────────
        sdk_section = tk.LabelFrame(
            root, text=tr("tool.preferences.section_env_sdks"),
            padx=16, pady=12,
        )
        sdk_section.pack(fill="x", pady=(16, 0))

        _sdks = [
            ("fish-audio-sdk", env_check.check_fish_audio_sdk()),
            ("openai",         env_check.check_openai_sdk()),
        ]
        for i, (pkg, ver) in enumerate(_sdks):
            tk.Label(sdk_section, text=pkg, anchor="w", width=18).grid(
                row=i, column=0, sticky="w", padx=(0, 8), pady=2,
            )
            if ver:
                val, color = f"✓  {ver}", "#2e8b57"
            else:
                val, color = f"✗  pip install {pkg}", "#888"
            tk.Label(sdk_section, text=val, fg=color, anchor="w").grid(
                row=i, column=1, sticky="w", pady=2,
            )

        tk.Label(
            sdk_section, text=tr("tool.preferences.sdk_install_hint"),
            fg="#777", justify="left",
        ).grid(row=len(_sdks), column=0, columnspan=2, sticky="w", pady=(10, 0))

        # ── Coverage note ────────────────────────────────────────────────────
        tk.Label(
            root, text=tr("tool.preferences.coverage_note"),
            fg="#777", wraplength=580, justify="left",
        ).pack(fill="x", pady=(20, 0))

        # Initial status refresh (in background to avoid blocking UI)
        threading.Thread(target=self._bg_initial_refresh, daemon=True).start()

    # ── Language ─────────────────────────────────────────────────────────────

    def _on_save(self):
        selected_label = self._lang_var.get()
        code = next(
            (k for k, v in self._lang_labels.items() if v == selected_label),
            i18n.DEFAULT_LANG,
        )
        try:
            i18n.set_current_lang(code)
        except Exception as e:
            self.set_error(f"保存设置失败: {e}")
            self._status_lbl.config(text=f"✗ {e}", fg="#c0392b")
            return

        if code == self._current_lang:
            self._status_lbl.config(
                text=tr("tool.preferences.saved_no_change"), fg="#2e8b57",
            )
        else:
            self._status_lbl.config(
                text=tr("tool.preferences.saved_restart"), fg="#c06000",
            )
        self.set_done()

    # ── yt-dlp ───────────────────────────────────────────────────────────────

    def _bg_initial_refresh(self):
        self.master.after(0, self._refresh_ytdlp_status)


    def _refresh_ytdlp_status(self):
        ver = env_check.check_ytdlp()
        if ver:
            self._ytdlp_val.config(text=f"✓  {ver}", fg="#2e8b57")
        else:
            self._ytdlp_val.config(
                text=tr("tool.preferences.env_status_missing"), fg="#c0392b",
            )

    def _upgrade_ytdlp(self):
        self._upgrade_ytdlp_btn.config(state="disabled")
        self._ytdlp_log.config(state="normal")
        self._ytdlp_log.delete("1.0", "end")
        self._ytdlp_log.config(state="disabled")

        def run():
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                )
                for line in proc.stdout:
                    self.master.after(0, self._append_ytdlp_log, line.rstrip())
                proc.wait()
                success = proc.returncode == 0
                self.master.after(
                    0, self._on_ytdlp_done, success,
                    None if success else f"exit {proc.returncode}",
                )
            except Exception as e:
                self.master.after(0, self._on_ytdlp_done, False, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _append_ytdlp_log(self, line: str):
        self._ytdlp_log.config(state="normal")
        self._ytdlp_log.insert("end", line + "\n")
        self._ytdlp_log.see("end")
        self._ytdlp_log.config(state="disabled")

    def _on_ytdlp_done(self, success: bool, err: str | None):
        msg = (
            tr("tool.preferences.ytdlp_upgrade_done")
            if success
            else f"{tr('tool.preferences.ytdlp_upgrade_failed')}: {err}"
        )
        self._append_ytdlp_log(msg)
        self._upgrade_ytdlp_btn.config(state="normal")
        self._refresh_ytdlp_status()
