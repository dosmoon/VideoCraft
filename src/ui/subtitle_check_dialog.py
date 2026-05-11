"""Subtitle-check detail dialog (P4.4.5 UI).

Shows the issue list from core.subtitle_check.check_srt() for a single
SRT file, plus an [清理可修复项] button that runs apply_auto_fixes
and re-checks. File-level issues (cue_index=0) are grouped at top;
per-cue issues are listed below sorted by cue index.

Returns True if any auto-fix was applied so the caller can refresh
the sidebar.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from core.subtitle_check import (
    CheckResult, SubtitleIssue, check_srt, apply_auto_fixes,
    SEV_ERROR, SEV_WARNING, SEV_INFO,
)


_SEV_ICON = {SEV_ERROR: "✗", SEV_WARNING: "⚠", SEV_INFO: "ⓘ"}
_SEV_COLOR = {SEV_ERROR: "#c00", SEV_WARNING: "#a60", SEV_INFO: "#666"}


def show_check_dialog(
    parent: tk.Misc,
    srt_path: str,
    *,
    expected_lang_iso: str | None = None,
    reference_srt_path: str | None = None,
) -> bool:
    """Show the check detail dialog for srt_path.

    Returns True if the user applied auto-fixes (caller should refresh
    sidebar to reflect the cleaned state).
    """
    return _CheckDialog(
        parent, srt_path,
        expected_lang_iso=expected_lang_iso,
        reference_srt_path=reference_srt_path,
    ).run()


class _CheckDialog:
    def __init__(
        self,
        parent: tk.Misc,
        srt_path: str,
        *,
        expected_lang_iso: str | None,
        reference_srt_path: str | None,
    ) -> None:
        self.srt_path = srt_path
        self.expected_lang_iso = expected_lang_iso
        self.reference_srt_path = reference_srt_path
        self._applied_fix: bool = False

        self.win = tk.Toplevel(parent)
        self.win.title(f"字幕检测: {os.path.basename(srt_path)}")
        self.win.transient(parent.winfo_toplevel())
        self.win.geometry("560x500")
        self.win.minsize(420, 360)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._reload()  # run check + populate list

        # Center over parent
        self.win.update_idletasks()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - self.win.winfo_width()) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - self.win.winfo_height()) // 2
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.win, padding=16)
        outer.pack(fill="both", expand=True)

        # Header (file info)
        self._header_var = tk.StringVar(value="…")
        ttk.Label(outer, textvariable=self._header_var,
                  font=("Microsoft YaHei UI", 11, "bold")
                  ).pack(anchor="w")

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(6, 8))

        # Scrollable issues list
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)

        self._list = tk.Text(
            body, wrap="word", height=16,
            font=("Microsoft YaHei UI", 9), bg="white",
            relief="flat", padx=8, pady=6,
        )
        vsb = ttk.Scrollbar(body, command=self._list.yview)
        self._list.configure(yscrollcommand=vsb.set, state="disabled")
        self._list.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Tag styles for severity coloring
        for sev, color in _SEV_COLOR.items():
            self._list.tag_configure(f"sev_{sev}", foreground=color)
        self._list.tag_configure("head", font=("Microsoft YaHei UI", 10, "bold"))
        self._list.tag_configure("muted", foreground="#999",
                                 font=("Microsoft YaHei UI", 9, "italic"))

        # Buttons
        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(12, 0))
        self._fix_btn = ttk.Button(
            btns, text="清理可修复项", command=self._on_apply_fix,
            state="disabled",
        )
        self._fix_btn.pack(side="left")
        ttk.Button(btns, text="打开文件位置", command=self._on_open_folder
                   ).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="关闭", command=self._on_close
                   ).pack(side="right")

    def _reload(self) -> None:
        """Run check_srt and repopulate the list."""
        result = check_srt(
            self.srt_path,
            expected_lang_iso=self.expected_lang_iso,
            reference_srt_path=self.reference_srt_path,
        )
        self._render(result)

    def _render(self, result: CheckResult) -> None:
        # Header line
        n_err = sum(1 for i in result.issues if i.severity == SEV_ERROR)
        n_warn = sum(1 for i in result.issues if i.severity == SEV_WARNING)
        n_info = sum(1 for i in result.issues if i.severity == SEV_INFO)
        head = f"{os.path.basename(self.srt_path)} — {result.cue_count} cues"
        if result.issues:
            head += f"   ·   {n_err} 错误 · {n_warn} 警告"
            if n_info:
                head += f" · {n_info} 提示"
        else:
            head += "   ·   ✓ 全部正常"
        self._header_var.set(head)

        # Fix button state
        any_fixable = any(i.auto_fixable for i in result.issues)
        n_fixable = sum(1 for i in result.issues if i.auto_fixable)
        self._fix_btn.config(
            state="normal" if any_fixable else "disabled",
            text=(f"清理可修复项 ({n_fixable})" if any_fixable
                  else "清理可修复项"),
        )

        # Render issues list
        self._list.config(state="normal")
        self._list.delete("1.0", "end")

        if not result.issues:
            self._list.insert("end",
                              "\n  ✓ 未发现问题。\n",
                              ("muted",))
            self._list.config(state="disabled")
            return

        file_level = [i for i in result.issues if i.cue_index == 0]
        cue_level = sorted(
            (i for i in result.issues if i.cue_index > 0),
            key=lambda i: (i.cue_index, i.category),
        )

        if file_level:
            self._list.insert("end", "文件级问题\n", ("head",))
            for issue in file_level:
                self._insert_issue(issue, is_file_level=True)
            self._list.insert("end", "\n")

        if cue_level:
            self._list.insert("end", f"Cue 级问题 ({len(cue_level)} 处)\n",
                              ("head",))
            for issue in cue_level:
                self._insert_issue(issue, is_file_level=False)

        self._list.config(state="disabled")

    def _insert_issue(self, issue: SubtitleIssue, *, is_file_level: bool) -> None:
        icon = _SEV_ICON.get(issue.severity, "·")
        tag = f"sev_{issue.severity}"
        prefix = "  " if is_file_level else f"  #{issue.cue_index:<5}"
        line = f"{prefix}  {icon}  {issue.message}"
        if issue.auto_fixable:
            line += "    [可清理]"
        self._list.insert("end", line + "\n", (tag,))

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_apply_fix(self) -> None:
        try:
            res = apply_auto_fixes(self.srt_path)
        except Exception as e:
            messagebox.showerror(
                "清理失败", str(e), parent=self.win)
            return
        self._applied_fix = self._applied_fix or (res["cues_fixed"] > 0)
        messagebox.showinfo(
            "清理完成",
            f"已清理 {res['cues_fixed']} 个 cue。",
            parent=self.win,
        )
        self._reload()

    def _on_open_folder(self) -> None:
        folder = os.path.dirname(self.srt_path)
        try:
            os.startfile(folder)
        except OSError as e:
            messagebox.showerror("无法打开文件夹", str(e), parent=self.win)

    def _on_close(self) -> None:
        self.win.destroy()

    def run(self) -> bool:
        self.win.wait_window()
        return self._applied_fix
