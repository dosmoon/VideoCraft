"""Small dialogs feeding the subtitles pipeline (P4.4).

Three dialogs, all tiny:

  show_asr_dialog(parent) -> dict | None
      Asks: 自动生成 (ASR) vs 导入已有 SRT, plus optional source-language
      hint for ASR ("自动检测" by default). Import path returns a tuple
      describing the imported file.

  show_translate_dialog(parent, source_lang_iso) -> str | None
      Asks: target language ISO code.

  confirm_regenerate(parent) -> bool
      Confirms overwriting all existing subtitles before re-running.

All use the existing lang_names helpers and return ISO codes (not
display names) so callers can hand straight to subtitle_pipeline.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import Optional

from core.lang_names import WHISPER_LANG_CHOICES, WHISPER_DISPLAY_TO_ISO


_AUTO_DETECT_DISPLAY = "自动检测"
_AUTO_DETECT_ISO = None


# ── ASR (first-time subtitles) dialog ─────────────────────────────────────────

def show_asr_dialog(parent: tk.Misc) -> Optional[dict]:
    """Returns {"mode": "asr" | "import", ...} or None on cancel.

    mode="asr"     → {"mode": "asr", "lang_iso": str | None}
    mode="import"  → {"mode": "import", "path": str, "lang_iso": str}
    """
    return _AsrDialog(parent).run()


class _AsrDialog:
    def __init__(self, parent: tk.Misc) -> None:
        self._result: Optional[dict] = None

        self.win = tk.Toplevel(parent)
        self.win.title("生成字幕")
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._mode_var = tk.StringVar(value="asr")
        self._lang_var = tk.StringVar(value=_AUTO_DETECT_DISPLAY)
        self._import_path_var = tk.StringVar()
        self._import_lang_var = tk.StringVar(value=_AUTO_DETECT_DISPLAY)
        self._error_var = tk.StringVar()

        self._build_ui()
        self._update_mode()
        self._center(parent)

    def _build_ui(self) -> None:
        body = ttk.Frame(self.win, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="生成字幕",
                  font=("Microsoft YaHei UI", 12, "bold")
                  ).pack(anchor="w", pady=(0, 10))

        # Mode radios
        ttk.Radiobutton(body, text="自动生成 (ASR)", value="asr",
                        variable=self._mode_var, command=self._update_mode
                        ).pack(anchor="w")
        ttk.Radiobutton(body, text="导入已有 SRT 文件", value="import",
                        variable=self._mode_var, command=self._update_mode
                        ).pack(anchor="w", pady=(2, 8))

        # ASR sub-frame
        self._asr_frame = ttk.Frame(body, padding=(20, 0, 0, 8))
        ttk.Label(self._asr_frame, text="源视频语言:").pack(side="left")
        lang_choices = [_AUTO_DETECT_DISPLAY] + [d for _, d in WHISPER_LANG_CHOICES]
        ttk.Combobox(self._asr_frame, textvariable=self._lang_var,
                     values=lang_choices, state="readonly", width=20
                     ).pack(side="left", padx=(6, 0))

        # Import sub-frame
        self._import_frame = ttk.Frame(body, padding=(20, 0, 0, 8))
        row1 = ttk.Frame(self._import_frame)
        row1.pack(fill="x", pady=(0, 4))
        ttk.Label(row1, text="SRT 文件:", width=10
                  ).pack(side="left")
        ttk.Entry(row1, textvariable=self._import_path_var
                  ).pack(side="left", fill="x", expand=True)
        ttk.Button(row1, text="选择...", command=self._on_pick_srt
                   ).pack(side="left", padx=(6, 0))
        row2 = ttk.Frame(self._import_frame)
        row2.pack(fill="x")
        ttk.Label(row2, text="字幕语言:", width=10
                  ).pack(side="left")
        ttk.Combobox(row2, textvariable=self._import_lang_var,
                     values=[d for _, d in WHISPER_LANG_CHOICES],
                     state="readonly", width=20
                     ).pack(side="left", padx=(0, 0))

        # Buttons
        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=(8, 6))
        btns = ttk.Frame(body)
        btns.pack(fill="x")
        ttk.Button(btns, text="取消", command=self._on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="开始", command=self._on_submit
                   ).pack(side="right")

        ttk.Label(body, textvariable=self._error_var,
                  foreground="#c00", font=("Microsoft YaHei UI", 9),
                  wraplength=420
                  ).pack(anchor="w", pady=(8, 0))

    def _update_mode(self) -> None:
        mode = self._mode_var.get()
        if mode == "asr":
            self._import_frame.pack_forget()
            self._asr_frame.pack(fill="x")
        else:
            self._asr_frame.pack_forget()
            self._import_frame.pack(fill="x")

    def _on_pick_srt(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.win,
            title="选择 SRT 文件",
            filetypes=[("SubRip 字幕", "*.srt"), ("所有文件", "*.*")],
        )
        if path:
            self._import_path_var.set(path)

    def _on_submit(self) -> None:
        mode = self._mode_var.get()
        if mode == "asr":
            disp = self._lang_var.get()
            lang_iso = (None if disp == _AUTO_DETECT_DISPLAY
                        else WHISPER_DISPLAY_TO_ISO.get(disp))
            self._result = {"mode": "asr", "lang_iso": lang_iso}
        else:
            path = self._import_path_var.get().strip()
            if not path:
                self._error_var.set("请选择 SRT 文件")
                return
            import os
            if not os.path.isfile(path):
                self._error_var.set("文件不存在")
                return
            disp = self._import_lang_var.get()
            if disp == _AUTO_DETECT_DISPLAY:
                self._error_var.set("导入需指定字幕语言")
                return
            iso = WHISPER_DISPLAY_TO_ISO.get(disp)
            if not iso:
                self._error_var.set("未知语言")
                return
            self._result = {"mode": "import", "path": path, "lang_iso": iso}
        self.win.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.win.destroy()

    def _center(self, parent: tk.Misc) -> None:
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - w) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - h) // 2
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def run(self) -> Optional[dict]:
        self.win.wait_window()
        return self._result


# ── Translate dialog ──────────────────────────────────────────────────────────

def show_translate_dialog(
    parent: tk.Misc,
    source_lang_iso: str,
    existing_targets: list[str],
) -> Optional[str]:
    """Asks for target language ISO. Returns the ISO or None on cancel.

    existing_targets is shown for context (no enforcement — user may
    intentionally re-translate)."""
    from core import lang_names

    win = tk.Toplevel(parent)
    win.title("添加翻译")
    win.transient(parent.winfo_toplevel())
    win.resizable(False, False)
    win.grab_set()

    result: list[str | None] = [None]

    body = ttk.Frame(win, padding=20)
    body.pack(fill="both", expand=True)

    src_label = lang_names.friendly_name(source_lang_iso, "zh")
    ttk.Label(body,
              text=f"从源语言 {src_label} ({source_lang_iso}.srt) 翻译到:",
              font=("Microsoft YaHei UI", 10)
              ).pack(anchor="w")

    # Build target list: all WHISPER_LANGUAGES minus the source.
    options = [d for iso, d in WHISPER_LANG_CHOICES if iso != source_lang_iso]
    target_var = tk.StringVar(value=options[0] if options else "")
    ttk.Combobox(body, textvariable=target_var,
                 values=options, state="readonly", width=24
                 ).pack(anchor="w", pady=(6, 0))

    if existing_targets:
        existing_str = ", ".join(existing_targets)
        ttk.Label(body,
                  text=f"已有翻译: {existing_str}",
                  font=("Microsoft YaHei UI", 8), foreground="#888"
                  ).pack(anchor="w", pady=(8, 0))

    ttk.Label(body,
              text="若目标语言已存在,旧字幕将被覆盖。",
              font=("Microsoft YaHei UI", 8), foreground="#888"
              ).pack(anchor="w", pady=(4, 0))

    btns = ttk.Frame(body)
    btns.pack(fill="x", pady=(14, 0))

    def on_submit():
        disp = target_var.get()
        iso = WHISPER_DISPLAY_TO_ISO.get(disp)
        if iso:
            result[0] = iso
        win.destroy()

    def on_cancel():
        result[0] = None
        win.destroy()

    ttk.Button(btns, text="取消", command=on_cancel
               ).pack(side="right", padx=(8, 0))
    ttk.Button(btns, text="开始翻译", command=on_submit
               ).pack(side="right")
    win.protocol("WM_DELETE_WINDOW", on_cancel)

    win.update_idletasks()
    pw = parent.winfo_toplevel()
    x = pw.winfo_rootx() + (pw.winfo_width() - win.winfo_width()) // 2
    y = pw.winfo_rooty() + (pw.winfo_height() - win.winfo_height()) // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.wait_window()
    return result[0]


# ── Re-generate confirm ───────────────────────────────────────────────────────

def confirm_regenerate(parent: tk.Misc) -> bool:
    """Hard confirmation before overwriting all existing SRTs.

    Returns True if user confirmed.
    """
    from tkinter import messagebox
    return messagebox.askyesno(
        "重新生成字幕",
        "重新生成将覆盖现有所有字幕文件 (源语言 + 所有翻译)。\n\n确定继续吗?",
        default="no",
        parent=parent,
    )
