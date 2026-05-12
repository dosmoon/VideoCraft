"""Subtitle details + check dialog.

Three sections grouped by severity class:

  必须处理 (HARD)     — parse / empty / timing / count_mismatch / lang_purity
                       Needs manual SRT editing or re-generation.
  自动修复 (FIXABLE)  — format residue (`【N】`, `<|im_*|>`, role labels)
                       One-click [🔧 一键修复 N].
  建议 (ADVISORY)     — length_ratio / duplicate / overlap.
                       Quality hints, no blocking action.

Header shows file metadata (cue count, size, mtime). Sections with zero
issues are hidden. Returns True when the user applied auto-fixes so the
caller can refresh sidebar.
"""

from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from core.subtitle_check import (
    CheckResult, SubtitleIssue, check_srt, apply_auto_fixes,
    SEV_ERROR, SEV_WARNING, SEV_INFO,
    CLASS_HARD, CLASS_FIXABLE, CLASS_ADVISORY,
)


_SEV_ICON = {SEV_ERROR: "✗", SEV_WARNING: "⚠", SEV_INFO: "ⓘ"}
_SEV_COLOR = {SEV_ERROR: "#c00", SEV_WARNING: "#a60", SEV_INFO: "#666"}

_CLASS_HEAD = {
    CLASS_HARD:     ("必须处理", "#c00",
                     "下列问题需要手动编辑 SRT 或重新生成字幕。"),
    CLASS_FIXABLE:  ("自动修复", "#a60",
                     "下列残留可一键清理。"),
    CLASS_ADVISORY: ("建议",     "#666",
                     "下列项不影响烧录，仅供参考。"),
}


def show_check_dialog(
    parent: tk.Misc,
    srt_path: str,
    *,
    expected_lang_iso: str | None = None,
    reference_srt_path: str | None = None,
) -> bool:
    """Show the details dialog for srt_path. Returns True if auto-fixes
    were applied (caller should refresh sidebar)."""
    return _DetailsDialog(
        parent, srt_path,
        expected_lang_iso=expected_lang_iso,
        reference_srt_path=reference_srt_path,
    ).run()


def _fmt_size(path: str) -> str:
    try:
        n = os.path.getsize(path)
    except OSError:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_mtime(path: str) -> str:
    try:
        ts = os.path.getmtime(path)
    except OSError:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class _DetailsDialog:
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
        self.win.title(f"字幕详情: {os.path.basename(srt_path)}")
        self.win.transient(parent.winfo_toplevel())
        self.win.geometry("600x560")
        self.win.minsize(460, 380)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._reload()

        # Center
        self.win.update_idletasks()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - self.win.winfo_width()) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - self.win.winfo_height()) // 2
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.win, padding=16)
        outer.pack(fill="both", expand=True)

        # ── File metadata header ──
        self._title_var = tk.StringVar(value=os.path.basename(self.srt_path))
        ttk.Label(outer, textvariable=self._title_var,
                  font=("Microsoft YaHei UI", 12, "bold"),
                  ).pack(anchor="w")

        self._meta_var = tk.StringVar(value="…")
        ttk.Label(outer, textvariable=self._meta_var,
                  foreground="#666",
                  font=("Microsoft YaHei UI", 9),
                  ).pack(anchor="w", pady=(2, 0))

        ttk.Separator(outer, orient="horizontal"
                      ).pack(fill="x", pady=(10, 8))

        # ── Summary line ──
        self._summary_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self._summary_var,
                  font=("Microsoft YaHei UI", 10, "bold"),
                  ).pack(anchor="w", pady=(0, 6))

        # ── Issue body (scrollable Text with section tags) ──
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)

        self._list = tk.Text(
            body, wrap="word", height=18,
            font=("Microsoft YaHei UI", 9), bg="white",
            relief="flat", padx=8, pady=6,
        )
        vsb = ttk.Scrollbar(body, command=self._list.yview)
        self._list.configure(yscrollcommand=vsb.set, state="disabled")
        self._list.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for sev, color in _SEV_COLOR.items():
            self._list.tag_configure(f"sev_{sev}", foreground=color)
        for cls, (_, color, _desc) in _CLASS_HEAD.items():
            self._list.tag_configure(f"head_{cls}", foreground=color,
                                     font=("Microsoft YaHei UI", 10, "bold"),
                                     spacing1=4, spacing3=2)
        self._list.tag_configure("desc", foreground="#888",
                                 font=("Microsoft YaHei UI", 9, "italic"),
                                 spacing3=4)
        self._list.tag_configure("muted", foreground="#999",
                                 font=("Microsoft YaHei UI", 9, "italic"))

        # ── Buttons ──
        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(12, 0))
        self._fix_btn = ttk.Button(
            btns, text="🔧 一键修复", command=self._on_apply_fix,
            state="disabled",
        )
        self._fix_btn.pack(side="left")
        ttk.Button(btns, text="在资源管理器中显示",
                   command=self._on_open_folder
                   ).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="关闭", command=self._on_close
                   ).pack(side="right")

    def _reload(self) -> None:
        result = check_srt(
            self.srt_path,
            expected_lang_iso=self.expected_lang_iso,
            reference_srt_path=self.reference_srt_path,
        )
        self._render(result)

    def _render(self, result: CheckResult) -> None:
        # ── Metadata header ──
        bits = [
            f"{result.cue_count} cues",
            _fmt_size(self.srt_path),
            f"修改于 {_fmt_mtime(self.srt_path)}",
        ]
        if self.expected_lang_iso:
            bits.insert(0, f"语言 {self.expected_lang_iso}")
        self._meta_var.set("  ·  ".join(bits))

        # ── Summary ──
        if not result.issues:
            self._summary_var.set("✓ 全部正常")
        else:
            chunks = []
            if result.hard_count:
                chunks.append(f"{result.hard_count} 处必须处理")
            if result.fixable_count:
                chunks.append(f"{result.fixable_count} 处可自动修复")
            if result.advisory_count:
                chunks.append(f"{result.advisory_count} 条建议")
            self._summary_var.set("  ·  ".join(chunks))

        # ── Fix button ──
        n_fix = result.fixable_count
        self._fix_btn.config(
            state="normal" if n_fix else "disabled",
            text=(f"🔧 一键修复 ({n_fix})" if n_fix else "🔧 一键修复"),
        )

        # ── Body sections ──
        self._list.config(state="normal")
        self._list.delete("1.0", "end")

        if not result.issues:
            self._list.insert("end", "\n  ✓ 未发现任何问题。\n", ("muted",))
            self._list.config(state="disabled")
            return

        # Render in fixed order: hard → fixable → advisory.
        for cls in (CLASS_HARD, CLASS_FIXABLE, CLASS_ADVISORY):
            items = result.by_class(cls)
            if not items:
                continue
            title, _color, desc = _CLASS_HEAD[cls]
            self._list.insert("end",
                              f"{title} ({len(items)})\n",
                              (f"head_{cls}",))
            self._list.insert("end", f"  {desc}\n", ("desc",))
            for issue in sorted(items, key=lambda i: (i.cue_index, i.category)):
                self._insert_issue(issue)
            self._list.insert("end", "\n")

        self._list.config(state="disabled")

    def _insert_issue(self, issue: SubtitleIssue) -> None:
        icon = _SEV_ICON.get(issue.severity, "·")
        tag = f"sev_{issue.severity}"
        prefix = "    文件级" if issue.cue_index == 0 else f"    #{issue.cue_index:<5}"
        line = f"{prefix}  {icon}  {issue.message}\n"
        self._list.insert("end", line, (tag,))

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_apply_fix(self) -> None:
        try:
            res = apply_auto_fixes(self.srt_path)
        except Exception as e:
            messagebox.showerror("清理失败", str(e), parent=self.win)
            return
        if res["cues_fixed"] > 0:
            self._applied_fix = True
        messagebox.showinfo(
            "清理完成",
            f"已清理 {res['cues_fixed']} 个 cue。",
            parent=self.win,
        )
        self._reload()

    def _on_open_folder(self) -> None:
        # Highlight the SRT file in Explorer
        try:
            os.startfile(os.path.dirname(self.srt_path))
        except OSError as e:
            messagebox.showerror("无法打开文件夹", str(e), parent=self.win)

    def _on_close(self) -> None:
        self.win.destroy()

    def run(self) -> bool:
        self.win.wait_window()
        return self._applied_fix
