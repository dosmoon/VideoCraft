"""SRT preview pane with inline issue panel.

Two-column layout:
  Left  — full SRT text (monospace, lightly colored).
  Right — file metadata + 3-section issue list (hard / fixable / advisory).
          Each issue row is clickable: jumps the left text to the cue and
          highlights its line for a moment.

The preview is mounted inside the permanent preview tab and replaces the
old subtitle_check_dialog (which used to live as a popup). on_fixed is
invoked after [🔧 一键修复] so the Hub can refresh its sidebar.
"""

from __future__ import annotations

import os
import re
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Callable

from core.subtitle_check import (
    CheckResult, SubtitleIssue, check_srt, apply_auto_fixes,
    SEV_ERROR, SEV_WARNING, SEV_INFO,
    CLASS_HARD, CLASS_FIXABLE, CLASS_ADVISORY,
)
from i18n import tr


_TS_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}\s*$"
)
_TS_PARSE_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*$"
)
_IDX_RE = re.compile(r"^\d+\s*$")

_SEV_ICON = {SEV_ERROR: "✗", SEV_WARNING: "⚠", SEV_INFO: "ⓘ"}
_SEV_COLOR = {SEV_ERROR: "#c00", SEV_WARNING: "#a60", SEV_INFO: "#666"}

_CLASS_KEY = {
    CLASS_HARD:     ("subtitle.preview.cls_hard",     "#c00"),
    CLASS_FIXABLE:  ("subtitle.preview.cls_fixable",  "#a60"),
    CLASS_ADVISORY: ("subtitle.preview.cls_advisory", "#666"),
}


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


def build_srt_preview(
    parent: tk.Frame,
    srt_path: str,
    *,
    lang_iso: str | None = None,
    reference_srt_path: str | None = None,
    on_fixed: Callable[[], None] | None = None,
    jump_to_sec: float | None = None,
) -> tk.Frame:
    """Build the preview UI inside parent. Returns the outer Frame.

    The returned frame carries `_srt_pane` (the underlying pane object)
    so callers that need to re-jump without rebuilding can call
    `pane.jump_to_time(sec)` on it.
    """
    pane = _SrtPreviewPane(parent, srt_path,
                            lang_iso=lang_iso,
                            reference_srt_path=reference_srt_path,
                            on_fixed=on_fixed)
    if jump_to_sec is not None:
        pane.jump_to_time(jump_to_sec)
    pane.frame._srt_pane = pane  # type: ignore[attr-defined]
    return pane.frame


class _SrtPreviewPane:
    def __init__(
        self,
        parent: tk.Frame,
        srt_path: str,
        *,
        lang_iso: str | None,
        reference_srt_path: str | None,
        on_fixed: Callable[[], None] | None,
    ) -> None:
        self.srt_path = srt_path
        self.lang_iso = lang_iso
        self.reference_srt_path = reference_srt_path
        self.on_fixed = on_fixed
        # Maps 1-based cue index → 1-based Text line number where the cue's
        # number line lives, populated when SRT body is rendered.
        self._cue_line: dict[int, int] = {}
        # Maps 1-based cue index → (start_sec, end_sec), populated alongside.
        # Used by jump_to_time() so external callers (e.g. hotclip card click)
        # can locate the cue containing a wall-clock timestamp.
        self._cue_time: dict[int, tuple[float, float]] = {}

        self.frame = tk.Frame(parent, bg="white")
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        body = tk.Frame(self.frame, bg="white")
        body.pack(fill="both", expand=True, padx=12, pady=10)

        # ── Left: SRT text ──
        text_col = tk.Frame(body, bg="white")
        text_col.pack(side="left", fill="both", expand=True)

        self._header_var = tk.StringVar(value=os.path.basename(self.srt_path))
        tk.Label(text_col, textvariable=self._header_var,
                 bg="white", fg="#222",
                 font=("Microsoft YaHei UI", 12, "bold"),
                 anchor="w").pack(fill="x")
        self._meta_var = tk.StringVar(value="")
        tk.Label(text_col, textvariable=self._meta_var,
                 bg="white", fg="#888",
                 font=("Microsoft YaHei UI", 9),
                 anchor="w").pack(fill="x", pady=(2, 6))
        ttk.Separator(text_col, orient="horizontal").pack(fill="x")

        text_frame = tk.Frame(text_col, bg="white")
        text_frame.pack(fill="both", expand=True, pady=(8, 0))
        self._text = tk.Text(
            text_frame, wrap="word", font=("Consolas", 10),
            bg="white", fg="#222", relief="flat",
            padx=8, pady=6, selectbackground="#cce0f5",
        )
        vsb = ttk.Scrollbar(text_frame, command=self._text.yview)
        self._text.configure(yscrollcommand=vsb.set)
        self._text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._text.tag_configure("idx", foreground="#888")
        self._text.tag_configure("ts",  foreground="#0070c0")
        self._text.tag_configure("err", foreground="#c00")
        self._text.tag_configure("highlight", background="#fff3a8")

        # ── Right: metadata + issue panel ──
        side = tk.Frame(body, bg="white", width=280)
        side.pack(side="right", fill="y", padx=(12, 0))
        side.pack_propagate(False)

        self._summary_var = tk.StringVar(value="")
        tk.Label(side, textvariable=self._summary_var,
                 bg="white", fg="#222",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 anchor="w").pack(fill="x", pady=(0, 6))

        # Fix button (visibility toggled per check)
        self._fix_btn = tk.Button(
            side, text=tr("subtitle.preview.fix_btn"),
            relief="flat", bg="#fff3cd", fg="#856404",
            font=("Microsoft YaHei UI", 9), cursor="hand2",
            command=self._on_apply_fix,
        )
        # Packed dynamically only when fixable_count > 0.

        self._side_sep = ttk.Separator(side, orient="horizontal")
        self._side_sep.pack(fill="x", pady=(4, 6))

        # Scrollable issue list area (each row is a clickable Label)
        list_wrap = tk.Frame(side, bg="white")
        list_wrap.pack(fill="both", expand=True)
        self._list_canvas = tk.Canvas(
            list_wrap, bg="white", highlightthickness=0, borderwidth=0,
        )
        list_vsb = ttk.Scrollbar(list_wrap, command=self._list_canvas.yview)
        self._list_canvas.configure(yscrollcommand=list_vsb.set)
        self._list_canvas.pack(side="left", fill="both", expand=True)
        list_vsb.pack(side="right", fill="y")
        self._list_inner = tk.Frame(self._list_canvas, bg="white")
        self._list_canvas.create_window((0, 0), window=self._list_inner,
                                         anchor="nw", tags="inner")
        self._list_inner.bind(
            "<Configure>",
            lambda _e: self._list_canvas.configure(
                scrollregion=self._list_canvas.bbox("all")
            ),
        )
        self._list_canvas.bind(
            "<Configure>",
            lambda e: self._list_canvas.itemconfigure("inner", width=e.width),
        )

    # ── Render passes ──

    def _reload(self) -> None:
        """Re-read SRT, re-run check, repaint both columns."""
        self._render_text()
        result = check_srt(
            self.srt_path,
            expected_lang_iso=self.lang_iso,
            reference_srt_path=self.reference_srt_path,
        )
        self._render_meta(result)
        self._render_issues(result)

    def _render_text(self) -> None:
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._cue_line.clear()
        self._cue_time.clear()
        try:
            with open(self.srt_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError as e:
            self._text.insert("end",
                              tr("subtitle.preview.read_failed", error=str(e))
                              + "\n",
                              ("err",))
            self._text.config(state="disabled")
            return

        next_is_cue_index = True
        current_cue_idx: int | None = None
        line_no = 1
        for line in raw.splitlines():
            if _IDX_RE.match(line):
                if next_is_cue_index:
                    try:
                        current_cue_idx = int(line.strip())
                        self._cue_line[current_cue_idx] = line_no
                    except ValueError:
                        current_cue_idx = None
                    next_is_cue_index = False
                self._text.insert("end", line + "\n", ("idx",))
            elif _TS_RE.match(line):
                if current_cue_idx is not None:
                    m = _TS_PARSE_RE.match(line)
                    if m:
                        h1, mn1, s1, ms1, h2, mn2, s2, ms2 = (int(g) for g in m.groups())
                        start = h1 * 3600 + mn1 * 60 + s1 + ms1 / 1000.0
                        end   = h2 * 3600 + mn2 * 60 + s2 + ms2 / 1000.0
                        self._cue_time[current_cue_idx] = (start, end)
                self._text.insert("end", line + "\n", ("ts",))
            elif line == "":
                self._text.insert("end", "\n")
                next_is_cue_index = True
                current_cue_idx = None
            else:
                self._text.insert("end", line + "\n")
            line_no += 1
        self._text.config(state="disabled")

    def _render_meta(self, result: CheckResult) -> None:
        bits = [
            tr("subtitle.preview.meta_cues", n=result.cue_count),
            _fmt_size(self.srt_path),
            tr("subtitle.preview.meta_mtime", ts=_fmt_mtime(self.srt_path)),
        ]
        if self.lang_iso:
            bits.insert(0, tr("subtitle.preview.meta_lang", iso=self.lang_iso))
        self._meta_var.set("  ·  ".join(bits))

        if not result.issues:
            self._summary_var.set(tr("subtitle.preview.all_ok"))
        else:
            chunks = []
            if result.hard_count:
                chunks.append(tr("subtitle.preview.summary_hard",
                                  n=result.hard_count))
            if result.fixable_count:
                chunks.append(tr("subtitle.preview.summary_fixable",
                                  n=result.fixable_count))
            if result.advisory_count:
                chunks.append(tr("subtitle.preview.summary_advisory",
                                  n=result.advisory_count))
            self._summary_var.set("  ·  ".join(chunks))

        n_fix = result.fixable_count
        if n_fix > 0:
            self._fix_btn.config(text=tr("subtitle.preview.fix_btn_n", n=n_fix))
            self._fix_btn.pack(fill="x", pady=(0, 6), before=self._side_sep)
        else:
            self._fix_btn.pack_forget()

    def _render_issues(self, result: CheckResult) -> None:
        for child in self._list_inner.winfo_children():
            child.destroy()

        if not result.issues:
            tk.Label(self._list_inner,
                     text=tr("subtitle.preview.no_issues"),
                     bg="white", fg="#999",
                     font=("Microsoft YaHei UI", 9, "italic"),
                     anchor="w",
                     ).pack(fill="x", pady=4)
            return

        for cls in (CLASS_HARD, CLASS_FIXABLE, CLASS_ADVISORY):
            items = result.by_class(cls)
            if not items:
                continue
            title_key, color = _CLASS_KEY[cls]
            header = tr("subtitle.preview.section_header",
                        title=tr(title_key), n=len(items))
            tk.Label(self._list_inner, text=header,
                     bg="white", fg=color,
                     font=("Microsoft YaHei UI", 9, "bold"),
                     anchor="w",
                     ).pack(fill="x", pady=(6, 2))
            for issue in sorted(items, key=lambda i: (i.cue_index, i.category)):
                self._add_issue_row(issue)

    def _add_issue_row(self, issue: SubtitleIssue) -> None:
        icon = _SEV_ICON.get(issue.severity, "·")
        color = _SEV_COLOR.get(issue.severity, "#222")
        if issue.cue_index == 0:
            text = f"  {icon}  {tr('subtitle.preview.file_level')} — {issue.message}"
        else:
            text = f"  {icon}  #{issue.cue_index}  {issue.message}"
        lbl = tk.Label(self._list_inner, text=text,
                       bg="white", fg=color,
                       font=("Microsoft YaHei UI", 9),
                       anchor="w", justify="left",
                       wraplength=240, cursor="hand2")
        lbl.pack(fill="x", pady=1)
        lbl.bind("<Button-1>",
                  lambda _e, idx=issue.cue_index: self._jump_to_cue(idx))
        # Hover style
        lbl.bind("<Enter>", lambda _e, w=lbl: w.configure(bg="#f0f6ff"))
        lbl.bind("<Leave>", lambda _e, w=lbl: w.configure(bg="white"))

    # ── Interaction ──

    def jump_to_time(self, sec: float) -> None:
        """Find the cue containing `sec` (or the first cue starting at/after
        it) and scroll to its line. No-op if the SRT had no parseable cues."""
        if not self._cue_time:
            return
        target: int | None = None
        for idx in sorted(self._cue_time.keys()):
            start, end = self._cue_time[idx]
            if start <= sec < end:
                target = idx
                break
            if start >= sec:
                target = idx
                break
        if target is None:
            target = max(self._cue_time.keys())
        self._jump_to_cue(target)

    def _jump_to_cue(self, cue_index: int) -> None:
        if cue_index <= 0:
            # File-level: scroll to top.
            self._text.see("1.0")
            return
        line = self._cue_line.get(cue_index)
        if line is None:
            return
        # Highlight 4 lines (number + timestamp + ~2 text lines).
        self._text.tag_remove("highlight", "1.0", "end")
        self._text.tag_add("highlight",
                            f"{line}.0", f"{line + 4}.0")
        self._text.see(f"{line}.0")

    def _on_apply_fix(self) -> None:
        try:
            res = apply_auto_fixes(self.srt_path)
        except Exception as e:
            messagebox.showerror(tr("subtitle.preview.fix_failed_title"),
                                 str(e), parent=self.frame)
            return
        if res["cues_fixed"] > 0 and self.on_fixed is not None:
            self.on_fixed()
        self._reload()
