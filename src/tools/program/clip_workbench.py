"""Clip Script workbench — chapter-centered UX (2026-05 redesign).

2 tabs:
  Tab 1 「章节」     : master-detail
                      Left = compact chapter list + global [全自动 AI]
                      Right = chapter detail (header + actions + shared
                              preview/crop + scrollable per-clip cards)
  Tab 2 「汇总导出」 : cross-chapter clip Treeview + focused side panel
                      (preview + package form) + batch buttons + export bar

A chapter is the unit of work: find peaks → preview/crop → write package
text — all in one view. Final export work happens in Tab 2.

Architecture: this is the UI layer. Business logic lives in
core.program.clip (find_peaks / package_clip / export_*). Reusable widgets
live in ui.clip_widgets. Cut JSON schema is unchanged.
"""

from __future__ import annotations

import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from tools.base import ToolBase
from core.ai.cancellation import CancellationToken
from core.ai.errors import AIError, Kind
from core.program import clip as cliplib
from core.program.clip import ClipDraft
from core.segment_model import format_timestamp, parse_timestamp
from ui.ai_error_dialog import show_ai_error
from ui.clip_widgets import (
    ClipSummaryTreeview, PackageForm, PreviewPane,
)


def _tr(key: str) -> str:
    from i18n import tr
    return tr(key)


def _seconds_to_str(s: float) -> str:
    return format_timestamp(s)


# ── Heat-tier colors for chapter cards (kept from prior design) ────────────
def _heat_colors(score: int | None) -> tuple[str, str]:
    """Return (card_bg, badge_bg) for a chapter score."""
    if score is None:
        return "#ffffff", "#9aa0a6"
    if score >= 75:
        return "#fff1d6", "#e07a18"
    if score >= 50:
        return "#fbfbe6", "#9c8a26"
    if score < 30:
        return "#f0f0f0", "#9aa0a6"
    return "#ffffff", "#4a86e8"


class ClipWorkbenchApp(ToolBase):
    def __init__(self, master, initial_file: str | None = None):
        self.master = master
        master.title(_tr("tool.clip.title"))
        master.geometry("1480x900")

        try:
            style = ttk.Style(master)
            style.configure("Clip.Treeview", rowheight=30, font=("", 10))
            style.configure("Clip.Treeview.Heading",
                             font=("", 10, "bold"))
        except tk.TclError:
            pass

        # ── State ─────────────────────────────────────────────────────────
        self._project_root: str | None = (
            initial_file if initial_file and os.path.isdir(initial_file)
            else None
        )
        self._cut_path: str | None = None
        self._cut_name: str = ""
        self._pack: dict | None = None
        self._pack_path: str = ""
        self._video_path: str = ""
        self._srt_path: str = ""
        self._video_w: int = 0
        self._video_h: int = 0
        self._video_duration: float = 0.0
        self._chapters: list[dict] = []
        self._cues = []
        self._clips: list[ClipDraft] = []
        self._next_clip_id: int = 1
        self._ranks: dict[int, dict] = {}
        self._suspend_autosave: bool = False
        # Focus state
        self._selected_chapter_idx: int | None = None
        self._focused_clip_id: int | None = None
        # Whether the chapter-detail "💡 hint" group is expanded
        self._chapter_hint_open: bool = False
        # Export
        self._export_thread: threading.Thread | None = None
        self._export_cancel_flag: dict = {"v": False}
        # Global auto-run state
        self._global_auto_token: CancellationToken | None = None

        # ── Notebook (project / chapters / export) ────────────────────────
        self._notebook = ttk.Notebook(master)
        self._notebook.pack(fill="both", expand=True, padx=6, pady=6)
        self._tab_project  = ttk.Frame(self._notebook)
        self._tab_chapters = ttk.Frame(self._notebook)
        self._tab_export   = ttk.Frame(self._notebook)
        self._notebook.add(self._tab_project,  text=_tr("tool.clip.tab_project"))
        self._notebook.add(self._tab_chapters, text=_tr("tool.clip.tab_chapters"))
        self._notebook.add(self._tab_export,   text=_tr("tool.clip.tab_export"))
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_tab_project()
        self._build_tab_chapters()
        self._build_tab_export()

        # Bottom status bar
        self._status_var = tk.StringVar(value="")
        tk.Label(master, textvariable=self._status_var, fg="blue",
                 anchor="w").pack(fill="x", padx=8, pady=(0, 4))

        self._refresh_cut_state()

    # ── Tab 0: project (cut + sources) ────────────────────────────────────

    def _build_tab_project(self) -> None:
        f = self._tab_project

        # Cut row
        cut_box = ttk.LabelFrame(f, text=_tr("tool.clip.section_cut"))
        cut_box.pack(fill="x", padx=6, pady=(8, 4))
        row = ttk.Frame(cut_box)
        row.pack(fill="x", padx=4, pady=4)
        ttk.Button(row, text=_tr("tool.clip.btn_new_cut"),
                   command=self._on_new_cut).pack(side="left", padx=2)
        ttk.Button(row, text=_tr("tool.clip.btn_open_cut"),
                   command=self._on_open_cut).pack(side="left", padx=2)
        ttk.Button(row, text=_tr("tool.clip.btn_save_as_cut"),
                   command=self._on_save_as_cut).pack(side="left", padx=2)
        self._cut_status_var = tk.StringVar(value=_tr("tool.clip.cut_none"))
        tk.Label(row, textvariable=self._cut_status_var, fg="#2563eb",
                 anchor="w").pack(side="left", padx=(20, 0))

        # Sources row (Pack / Video / SRT)
        src = ttk.LabelFrame(f, text=_tr("tool.clip.section_inputs"))
        src.pack(fill="x", padx=6, pady=(0, 4))
        self._pack_var  = tk.StringVar()
        self._video_var = tk.StringVar()
        self._srt_var   = tk.StringVar()
        for var in (self._pack_var, self._video_var, self._srt_var):
            var.trace_add("write", self._on_source_path_changed)
        for row_idx, (label, var, browse) in enumerate((
                (_tr("tool.clip.label_pack"),  self._pack_var,  self._browse_pack),
                (_tr("tool.clip.label_video"), self._video_var, self._browse_video),
                (_tr("tool.clip.label_srt"),   self._srt_var,   self._browse_srt))):
            ttk.Label(src, text=label).grid(row=row_idx, column=0,
                                             sticky="e", padx=4, pady=2)
            ttk.Entry(src, textvariable=var).grid(
                row=row_idx, column=1, sticky="we", padx=4)
            ttk.Button(src, text=_tr("tool.clip.btn_browse"),
                       command=browse).grid(row=row_idx, column=2, padx=4)
        ttk.Button(src, text=_tr("tool.clip.btn_load"),
                   command=self._on_load_clicked).grid(
            row=3, column=1, sticky="w", padx=4, pady=4)
        src.columnconfigure(1, weight=1)

    # ── Tab 1: master-detail ──────────────────────────────────────────────

    def _build_tab_chapters(self) -> None:
        f = self._tab_chapters
        pw = ttk.PanedWindow(f, orient="horizontal")
        pw.pack(fill="both", expand=True)

        left = ttk.Frame(pw, width=380)
        right = ttk.Frame(pw, width=900)
        pw.add(left, weight=0)
        pw.add(right, weight=1)

        # ── Left pane: global actions + chapter tree ──
        tk.Label(left, text=_tr("tool.clip.section_chapters"),
                 font=("", 10, "bold"), anchor="w").pack(
            fill="x", padx=8, pady=(6, 4))

        action_bar = ttk.Frame(left)
        action_bar.pack(fill="x", padx=8, pady=(0, 4))
        self._global_auto_btn = self._make_ai_button(
            action_bar,
            idle_text=_tr("tool.clip.btn_global_auto"),
            worker=self._worker_global_full_auto,
            on_success=self._on_global_auto_done,
        )
        self._global_auto_btn.pack(side="left")
        self._ai_rank_btn = self._make_ai_button(
            action_bar,
            idle_text=_tr("tool.clip.btn_ai_rank"),
            worker=self._worker_rank_chapters,
            on_success=self._on_rank_done,
        )
        self._ai_rank_btn.pack(side="left", padx=(6, 0))

        # Tree: top-level rows = chapters, children = clips. Accordion: only
        # one chapter expanded at a time (handled in _on_chapter_expanded).
        tree_holder = ttk.Frame(left)
        tree_holder.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        self._chap_tree = ttk.Treeview(
            tree_holder, columns=("count", "score"),
            show="tree headings", selectmode="browse")
        self._chap_tree.heading("#0", text=_tr("tool.clip.tree_col_title"))
        self._chap_tree.heading("count", text=_tr("tool.clip.tree_col_count"))
        self._chap_tree.heading("score", text=_tr("tool.clip.tree_col_score"))
        self._chap_tree.column("#0", width=240, anchor="w", stretch=True)
        self._chap_tree.column("count", width=44, anchor="center",
                                stretch=False)
        self._chap_tree.column("score", width=50, anchor="center",
                                stretch=False)
        sb = ttk.Scrollbar(tree_holder, orient="vertical",
                            command=self._chap_tree.yview)
        self._chap_tree.configure(yscrollcommand=sb.set)
        self._chap_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Heat tags (background tint = AI score bucket)
        for tag, color in (("heat95", "#fde68a"), ("heat85", "#fef3c7"),
                            ("heat75", "#fefce8"), ("heat0",  "#f4f4f6")):
            self._chap_tree.tag_configure(tag, background=color)
        self._chap_tree.tag_configure("clip_row", foreground="#444",
                                       font=("", 9))
        self._chap_tree.tag_configure("clip_skipped", foreground="#999",
                                       font=("", 9, "overstrike"))

        self._chap_tree.bind("<<TreeviewSelect>>", self._on_tree_selection)
        self._chap_tree.bind("<<TreeviewOpen>>", self._on_chapter_expanded)

        # ── Right pane: detail (chapter-mode or clip-mode, rebuilt on select) ──
        self._detail_pane = ttk.Frame(right)
        self._detail_pane.pack(fill="both", expand=True, padx=4, pady=4)
        self._build_detail_placeholder()

    def _build_detail_placeholder(self) -> None:
        for w in self._detail_pane.winfo_children():
            w.destroy()
        tk.Label(self._detail_pane,
                 text=_tr("tool.clip.hint_pick_chapter"),
                 fg="gray", font=("", 11)).pack(pady=40)

    def _clip_count_for_chapter(self, chapter_idx: int) -> int:
        return sum(1 for c in self._clips if c.chapter_idx == chapter_idx)

    def _chapter_status_glyph(self, chapter_idx: int) -> str:
        clips = [c for c in self._clips if c.chapter_idx == chapter_idx]
        if not clips:
            return "○"
        if all(c.status in ("reviewed", "exported") for c in clips):
            return "●"
        return "◐"

    @staticmethod
    def _heat_tag_for_score(score: int | None) -> str:
        s = score or 0
        if s >= 95: return "heat95"
        if s >= 85: return "heat85"
        if s >= 75: return "heat75"
        return "heat0"

    def _refresh_chapter_list(self) -> None:
        """Rebuild the whole tree. Preserves expansion + selection."""
        if not hasattr(self, "_chap_tree"):
            return
        open_iids = {iid for iid in self._chap_tree.get_children()
                     if self._chap_tree.item(iid, "open")}
        sel = self._chap_tree.selection()
        sel_iid = sel[0] if sel else None

        self._chap_tree.delete(*self._chap_tree.get_children())

        ordered = (sorted(self._chapters,
                           key=lambda c: -self._ranks.get(c["idx"], {})
                                          .get("score", -1))
                    if self._ranks else list(self._chapters))
        for ch in ordered:
            self._insert_chapter_row(ch, expanded=(f"ch:{ch['idx']}" in open_iids))

        if sel_iid and self._chap_tree.exists(sel_iid):
            self._chap_tree.selection_set(sel_iid)
            self._chap_tree.focus(sel_iid)

    def _insert_chapter_row(self, ch: dict, *, expanded: bool = False) -> None:
        idx = ch["idx"]
        rank = self._ranks.get(idx) or {}
        score = rank.get("score") if isinstance(rank.get("score"), int) else None
        clip_count = self._clip_count_for_chapter(idx)
        glyph = self._chapter_status_glyph(idx)
        title_one_line = (ch["title"] or "").strip().splitlines()[0]

        ch_iid = f"ch:{idx}"
        self._chap_tree.insert(
            "", "end", iid=ch_iid,
            text=f"{glyph} #{idx+1}  {title_one_line}",
            values=(str(clip_count) if clip_count else "",
                    str(score) if score is not None else ""),
            tags=(self._heat_tag_for_score(score),),
            open=expanded,
        )
        for c in [c for c in self._clips if c.chapter_idx == idx]:
            self._insert_clip_row(ch_iid, c)

    def _insert_clip_row(self, parent_iid: str, c: ClipDraft) -> None:
        check = ("✓" if c.status in ("reviewed", "exported")
                 else "✗" if c.status == "skipped"
                 else "·")
        duration = int(c.end_sec - c.start_sec)
        excerpt = (c.excerpt or "").strip().replace("\n", " ")
        tag = "clip_skipped" if c.status == "skipped" else "clip_row"
        self._chap_tree.insert(
            parent_iid, "end", iid=f"clip:{c.id}",
            text=f"  └ {check}  {duration}s  {excerpt[:80]}",
            tags=(tag,),
        )

    def _refresh_clip_cards_for_chapter(self, chapter_idx: int) -> None:
        """Refresh the clip child rows of a single chapter."""
        if not hasattr(self, "_chap_tree"):
            return
        ch_iid = f"ch:{chapter_idx}"
        if not self._chap_tree.exists(ch_iid):
            return
        for child in self._chap_tree.get_children(ch_iid):
            self._chap_tree.delete(child)
        for c in [c for c in self._clips if c.chapter_idx == chapter_idx]:
            self._insert_clip_row(ch_iid, c)
        # Update count column on the chapter row itself
        score = self._ranks.get(chapter_idx, {}).get("score")
        score_txt = str(score) if isinstance(score, int) else ""
        clip_count = self._clip_count_for_chapter(chapter_idx)
        self._chap_tree.item(
            ch_iid,
            text=f"{self._chapter_status_glyph(chapter_idx)} #{chapter_idx+1}  "
                 f"{(self._chapters[chapter_idx]['title'] or '').strip().splitlines()[0]}",
            values=(str(clip_count) if clip_count else "", score_txt),
        )

    def _on_chapter_selected(self, chapter_idx: int) -> None:
        """Programmatic chapter select (used by [跳到该章节] from Tab 2)."""
        if not hasattr(self, "_chap_tree"):
            return
        ch_iid = f"ch:{chapter_idx}"
        if not self._chap_tree.exists(ch_iid):
            return
        # Expand the chapter so its clips are visible, then select it
        self._chap_tree.item(ch_iid, open=True)
        self._enforce_accordion(ch_iid)
        target_iid = ch_iid
        if self._focused_clip_id is not None:
            clip_iid = f"clip:{self._focused_clip_id}"
            if self._chap_tree.exists(clip_iid):
                target_iid = clip_iid
        self._chap_tree.selection_set(target_iid)
        self._chap_tree.focus(target_iid)
        self._chap_tree.see(target_iid)

    def _on_tree_selection(self, _event=None) -> None:
        sel = self._chap_tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid.startswith("ch:"):
            idx = int(iid.split(":", 1)[1])
            # Idempotent: same chapter, no clip → don't rebuild detail.
            if (idx == self._selected_chapter_idx
                    and self._focused_clip_id is None):
                return
            self._selected_chapter_idx = idx
            self._focused_clip_id = None
            self._build_detail_chapter(idx)
        elif iid.startswith("clip:"):
            cid = int(iid.split(":", 1)[1])
            if cid == self._focused_clip_id:
                return
            clip = next((c for c in self._clips if c.id == cid), None)
            if clip is None:
                return
            self._selected_chapter_idx = clip.chapter_idx
            self._focused_clip_id = cid
            self._build_detail_clip(cid)

    def _on_chapter_expanded(self, _event=None) -> None:
        """Accordion: opening a chapter collapses any other open chapter."""
        opened = self._chap_tree.focus()
        if not opened.startswith("ch:"):
            return
        self._enforce_accordion(opened)

    def _enforce_accordion(self, keep_open_iid: str) -> None:
        for iid in self._chap_tree.get_children():
            if iid != keep_open_iid and self._chap_tree.item(iid, "open"):
                self._chap_tree.item(iid, open=False)

    def _expand_chapter_in_tree(self, chapter_idx: int) -> None:
        """Open the chapter row + apply accordion + scroll into view."""
        if not hasattr(self, "_chap_tree"):
            return
        ch_iid = f"ch:{chapter_idx}"
        if not self._chap_tree.exists(ch_iid):
            return
        self._chap_tree.item(ch_iid, open=True)
        self._enforce_accordion(ch_iid)
        self._chap_tree.see(ch_iid)

    def _select_clip_in_tree(self, clip_id: int) -> None:
        """Select the clip row + scroll into view (parent must already exist)."""
        if not hasattr(self, "_chap_tree"):
            return
        clip_iid = f"clip:{clip_id}"
        if not self._chap_tree.exists(clip_iid):
            return
        self._chap_tree.selection_set(clip_iid)
        self._chap_tree.focus(clip_iid)
        self._chap_tree.see(clip_iid)

    def _build_detail_chapter(self, chapter_idx: int) -> None:
        for w in self._detail_pane.winfo_children():
            w.destroy()
        if not (0 <= chapter_idx < len(self._chapters)):
            self._build_detail_placeholder()
            return
        ch = self._chapters[chapter_idx]
        rank = self._ranks.get(chapter_idx) or {}
        score = rank.get("score") if isinstance(rank.get("score"), int) else None

        # Header: title + score badge + time range
        header = ttk.Frame(self._detail_pane)
        header.pack(fill="x", padx=4, pady=(0, 4))
        title_text = (
            f"#{chapter_idx+1}  {ch['title']}    "
            f"⏱ {_seconds_to_str(ch['start_sec'])} – "
            f"{_seconds_to_str(ch['end_sec'])}")
        tk.Label(header, text=title_text, font=("", 12, "bold"),
                 anchor="w", justify="left", wraplength=900).pack(
            side="left", fill="x", expand=True)
        if score is not None:
            _bg, badge_bg = _heat_colors(score)
            tk.Label(header, text=f" {score} ",
                     background=badge_bg, foreground="white",
                     font=("", 11, "bold"), padx=8).pack(side="right")

        # Action bar (chapter-level AI)
        action_bar = ttk.Frame(self._detail_pane)
        action_bar.pack(fill="x", padx=4, pady=(0, 6))
        chap_auto_btn = self._make_ai_button(
            action_bar,
            idle_text=_tr("tool.clip.btn_chapter_auto"),
            worker=lambda token, idx=chapter_idx:
                self._worker_chapter_full_auto(token, idx),
            on_success=lambda result, idx=chapter_idx:
                self._on_chapter_auto_done(result, idx),
        )
        chap_auto_btn.pack(side="left")
        find_peaks_btn = self._make_ai_button(
            action_bar,
            idle_text=_tr("tool.clip.btn_ai_peaks"),
            worker=lambda token, idx=chapter_idx:
                self._worker_find_peaks(token, idx),
            on_success=lambda peaks, idx=chapter_idx:
                self._on_peaks_done(peaks, idx),
        )
        find_peaks_btn.pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text=_tr("tool.clip.btn_add_manual"),
                   command=lambda idx=chapter_idx:
                       self._add_manual_clip(idx)).pack(side="left", padx=(6, 0))

        # Collapsible 💡 hint (rank reason + refined excerpt)
        if rank.get("reason") or ch.get("refined"):
            self._build_chapter_hint(rank, ch)

        # Chapter status summary
        clips_in_ch = [c for c in self._clips if c.chapter_idx == chapter_idx]
        status_frame = ttk.Frame(self._detail_pane)
        status_frame.pack(fill="x", padx=4, pady=(2, 0))
        if clips_in_ch:
            n_reviewed = sum(1 for c in clips_in_ch
                              if c.status in ("reviewed", "exported"))
            n_skipped = sum(1 for c in clips_in_ch if c.status == "skipped")
            tk.Label(
                status_frame, fg="#555", anchor="w",
                text=_tr("tool.clip.chapter_status_summary").format(
                    total=len(clips_in_ch),
                    reviewed=n_reviewed, skipped=n_skipped),
            ).pack(fill="x")
        else:
            tk.Label(status_frame,
                     text=_tr("tool.clip.hint_no_clips_in_chapter"),
                     fg="gray").pack(fill="x")

    def _build_chapter_hint(self, rank: dict, ch: dict) -> None:
        bits = []
        if rank.get("reason"):
            bits.append(f"💡 {rank['reason']}")
        if ch.get("refined"):
            bits.append(ch["refined"])
        if not bits:
            return
        text = "   ·   ".join(bits)

        wrap = ttk.Frame(self._detail_pane)
        wrap.pack(fill="x", padx=4, pady=(0, 4))

        # Toggle button + collapsed summary on a single row.
        head_row = ttk.Frame(wrap)
        head_row.pack(fill="x")
        toggle_var = tk.StringVar(
            value=("▾" if self._chapter_hint_open else "▸"))
        body_holder = tk.Frame(wrap)

        def render() -> None:
            if self._chapter_hint_open:
                body_holder.pack(fill="x", pady=(2, 0))
            else:
                body_holder.pack_forget()
            toggle_var.set("▾" if self._chapter_hint_open else "▸")

        def toggle() -> None:
            self._chapter_hint_open = not self._chapter_hint_open
            render()

        ttk.Button(head_row, textvariable=toggle_var, width=2,
                   command=toggle).pack(side="left")
        # When collapsed, show first ~60 chars after the button as a teaser.
        teaser = text if len(text) <= 80 else text[:80] + "…"
        tk.Label(head_row, text=teaser, fg="#666", anchor="w",
                 font=("", 9), justify="left",
                 wraplength=900).pack(side="left", fill="x", expand=True,
                                        padx=(4, 0))
        # Body (full text, only visible when expanded).
        tk.Label(body_holder, text=text, fg="#444", anchor="w",
                 justify="left", wraplength=900, font=("", 9)).pack(
            fill="x", padx=(20, 0))
        render()

    def _build_detail_clip(self, clip_id: int) -> None:
        for w in self._detail_pane.winfo_children():
            w.destroy()
        clip = next((c for c in self._clips if c.id == clip_id), None)
        if clip is None:
            self._build_detail_placeholder()
            return

        # Header
        header = ttk.Frame(self._detail_pane)
        header.pack(fill="x", padx=4, pady=(0, 4))
        duration = int(clip.end_sec - clip.start_sec)
        title_text = (
            f"#{clip.chapter_idx+1} / clip   "
            f"⏱ {_seconds_to_str(clip.start_sec)} – "
            f"{_seconds_to_str(clip.end_sec)} · {duration}s")
        tk.Label(header, text=title_text, font=("", 12, "bold"),
                 anchor="w").pack(side="left", fill="x", expand=True)
        if clip.status == "skipped":
            tk.Label(header, text=" SKIPPED ",
                     background="#9ca3af", foreground="white",
                     font=("", 9, "bold"), padx=6).pack(side="right")
        elif clip.status in ("reviewed", "exported"):
            tk.Label(header, text=" READY ",
                     background="#16a34a", foreground="white",
                     font=("", 9, "bold"), padx=6).pack(side="right")

        # Time-range editor row (start / end seconds + snap)
        time_row = ttk.Frame(self._detail_pane)
        time_row.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Label(time_row, text=_tr("tool.clip.field_start")).pack(
            side="left", padx=(0, 2))
        start_var = tk.IntVar(value=int(clip.start_sec))
        ttk.Spinbox(time_row, from_=0, to=99999, increment=1,
                     textvariable=start_var, width=8,
                     command=lambda c=clip, v=start_var:
                         self._set_clip_start(c, v.get())).pack(
            side="left", padx=(0, 8))
        ttk.Label(time_row, text=_tr("tool.clip.field_end")).pack(
            side="left", padx=(0, 2))
        end_var = tk.IntVar(value=int(clip.end_sec))
        ttk.Spinbox(time_row, from_=0, to=99999, increment=1,
                     textvariable=end_var, width=8,
                     command=lambda c=clip, v=end_var:
                         self._set_clip_end(c, v.get())).pack(
            side="left", padx=(0, 8))
        ttk.Button(time_row, text=_tr("tool.clip.btn_snap"),
                   command=lambda c=clip: self._snap_clip_to_cues(c)).pack(
            side="left", padx=(0, 2))

        # Action bar
        actions = ttk.Frame(self._detail_pane)
        actions.pack(fill="x", padx=4, pady=(0, 6))
        skip_label = (_tr("tool.clip.btn_unskip") if clip.status == "skipped"
                      else _tr("tool.clip.btn_skip"))
        ttk.Button(actions, text=skip_label,
                   command=lambda c=clip: self._toggle_clip_skip(c)).pack(
            side="left", padx=2)
        ttk.Button(actions, text=_tr("tool.clip.btn_reset_crop"),
                   command=lambda c=clip: self._reset_focused_crop(c)).pack(
            side="left", padx=2)
        ttk.Button(actions, text=_tr("tool.clip.btn_delete_clip"),
                   command=lambda c=clip: self._delete_focused_clip(c)).pack(
            side="left", padx=(20, 2))

        # Body: preview (top) + package form (bottom)
        body_pw = ttk.PanedWindow(self._detail_pane, orient="vertical")
        body_pw.pack(fill="both", expand=True, padx=4, pady=2)
        prev_holder = ttk.Frame(body_pw)
        form_holder = ttk.Frame(body_pw)
        body_pw.add(prev_holder, weight=2)
        body_pw.add(form_holder, weight=3)

        self._preview = PreviewPane(
            prev_holder, on_change=self._on_preview_crop_changed)
        self._preview.set_apply_all_callback(self._apply_crop_to_all_in_chapter)
        self._preview.bind_clip(clip,
                                  video_path=self._video_path,
                                  video_w=self._video_w,
                                  video_h=self._video_h)
        self._preview.pack(fill="both", expand=True, padx=2, pady=2)

        self._clip_form = PackageForm(
            form_holder, on_change=self._on_clip_changed,
            ai_button_factory=self._make_ai_button,
            ai_worker_for_clip=self._make_pkg_worker)
        self._clip_form.bind_clip(clip)
        self._clip_form.pack(fill="both", expand=True, padx=2, pady=2)

    def _refresh_focused_preview(self) -> None:
        """Rebind the active PreviewPane (only present in clip-detail mode)."""
        if not hasattr(self, "_preview") or not self._preview.winfo_exists():
            return
        clip = next((c for c in self._clips if c.id == self._focused_clip_id),
                     None)
        self._preview.bind_clip(clip,
                                  video_path=self._video_path,
                                  video_w=self._video_w,
                                  video_h=self._video_h)

    def _set_clip_start(self, clip: ClipDraft, new_start: int) -> None:
        new_start = max(0, int(new_start))
        if new_start >= int(clip.end_sec):
            return
        clip.start_sec = float(new_start)
        self._refresh_focused_preview()
        self._refresh_clip_cards_for_chapter(clip.chapter_idx)
        self._autosave()

    def _set_clip_end(self, clip: ClipDraft, new_end: int) -> None:
        new_end = max(int(clip.start_sec) + 1, int(new_end))
        clip.end_sec = float(new_end)
        self._refresh_focused_preview()
        self._refresh_clip_cards_for_chapter(clip.chapter_idx)
        self._autosave()

    def _snap_clip_to_cues(self, clip: ClipDraft) -> None:
        if not self._cues:
            self._set_status(_tr("tool.clip.warn_no_srt_for_snap"))
            return
        s, e = cliplib.snap_to_cue_boundaries(
            self._cues, clip.start_sec, clip.end_sec)
        clip.start_sec = float(s)
        clip.end_sec = float(e)
        self._autosave()
        self._refresh_clip_cards_for_chapter(clip.chapter_idx)
        # Rebuild detail to refresh Spinbox values + preview
        self._build_detail_clip(clip.id)
        self._set_status(_tr("tool.clip.status_snapped"))

    def _toggle_clip_skip(self, clip: ClipDraft) -> None:
        clip.status = "draft" if clip.status == "skipped" else "skipped"
        self._refresh_clip_cards_for_chapter(clip.chapter_idx)
        self._refresh_export_summary()
        self._autosave()
        self._build_detail_clip(clip.id)

    def _reset_focused_crop(self, clip: ClipDraft) -> None:
        clip.crop_rect = None
        self._autosave()
        self._refresh_focused_preview()
        self._set_status(_tr("tool.clip.status_crop_reset").format(n=1))

    def _delete_focused_clip(self, clip: ClipDraft) -> None:
        if not messagebox.askyesno(
                _tr("tool.clip.title"),
                _tr("tool.clip.confirm_delete_clip")):
            return
        self._on_clip_removed(clip)
        # Right side: fall back to the chapter-level detail
        self._build_detail_chapter(clip.chapter_idx)

    def _on_clip_removed(self, clip: ClipDraft) -> None:
        self._clips = [c for c in self._clips if c.id != clip.id]
        if self._focused_clip_id == clip.id:
            self._focused_clip_id = None
        if self._selected_chapter_idx is not None:
            self._refresh_clip_cards_for_chapter(self._selected_chapter_idx)
        self._refresh_chapter_list()    # clip count badge
        self._refresh_export_summary()
        self._refresh_focused_preview()
        self._autosave()

    def _on_clip_changed(self, clip: ClipDraft) -> None:
        # Keep export summary fresh; tree row text refresh is deferred to
        # avoid widget churn on every keystroke. Status changes (skip) flow
        # through _toggle_clip_skip which already refreshes the affected row.
        self._refresh_export_summary()
        self._autosave()

    def _on_preview_crop_changed(self, clip: ClipDraft, _rect: dict) -> None:
        self._autosave()

    def _apply_crop_to_all_in_chapter(self, rect: dict) -> None:
        if self._selected_chapter_idx is None:
            return
        n = 0
        for c in self._clips:
            if c.chapter_idx == self._selected_chapter_idx:
                c.crop_rect = dict(rect)
                n += 1
        self._autosave()
        self._set_status(_tr("tool.clip.status_crop_applied").format(n=n))

    def _add_manual_clip(self, chapter_idx: int) -> None:
        """Drop a default-range clip into the chapter (no dialog).

        Range: first ~30 s of the chapter, snapped to cue boundaries when SRT
        is loaded, capped by chapter end. After insertion the detail pane is
        rebuilt directly to the new clip — we do not rely on the tree's
        <<TreeviewSelect>> event, which has been observed to occasionally
        no-op on programmatic selection changes.
        """
        try:
            if not (0 <= chapter_idx < len(self._chapters)):
                messagebox.showerror(
                    _tr("tool.clip.title"),
                    f"chapter_idx out of range: {chapter_idx}")
                return
            ch = self._chapters[chapter_idx]
            chap_dur = float(ch["end_sec"]) - float(ch["start_sec"])
            if chap_dur < 1.0:
                messagebox.showerror(_tr("tool.clip.title"),
                                     _tr("tool.clip.err_chapter_too_short"))
                return
            default_dur = min(30.0, max(5.0, chap_dur))
            s = float(ch["start_sec"])
            e = float(min(ch["start_sec"] + default_dur, ch["end_sec"]))
            if self._cues:
                s, e = cliplib.snap_to_cue_boundaries(self._cues, s, e)
            clip = self._append_new_clip(ch, s, e)
            # Reveal in tree
            self._expand_chapter_in_tree(chapter_idx)
            self._select_clip_in_tree(clip.id)
            # Force-rebuild the detail pane straight to the new clip (the
            # tree selection event is best-effort; this is the contract).
            self._selected_chapter_idx = chapter_idx
            self._focused_clip_id = clip.id
            self._build_detail_clip(clip.id)
            self._set_status(_tr("tool.clip.status_manual_added").format(
                s=_seconds_to_str(s), e=_seconds_to_str(e)))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            messagebox.showerror(
                _tr("tool.clip.title"),
                f"手工切片失败：{type(exc).__name__}: {exc}")

    def _append_new_clip(self, ch: dict, s: float, e: float) -> ClipDraft:
        """Create + register a clip; refresh dependent panes."""
        excerpt = ""
        if self._cues:
            buf = []
            for cue in self._cues:
                cs = cue.start.total_seconds()
                ce = cue.end.total_seconds()
                if ce <= s or cs >= e:
                    continue
                buf.append(cue.content.replace("\n", " "))
            excerpt = " ".join(buf)[:500]
        clip = ClipDraft(
            id=self._next_clip_id,
            chapter_idx=ch["idx"],
            chapter_title=ch["title"],
            start_sec=float(s),
            end_sec=float(e),
            original_excerpt=excerpt,
        )
        self._next_clip_id += 1
        self._clips.append(clip)
        self._refresh_clip_cards_for_chapter(ch["idx"])
        self._refresh_export_summary()
        self._autosave()
        return clip

    # ── Tab 2: export summary ─────────────────────────────────────────────

    def _build_tab_export(self) -> None:
        f = self._tab_export

        tk.Label(f, text=_tr("tool.clip.section_summary"),
                 font=("", 10, "bold"), anchor="w").pack(
            fill="x", padx=8, pady=(6, 4))

        self._summary_tree = ClipSummaryTreeview(
            f, on_select=self._on_summary_clip_selected)
        self._summary_tree.pack(fill="both", expand=True, padx=4, pady=4)

        batch = ttk.Frame(f)
        batch.pack(fill="x", padx=4, pady=(2, 4))
        ttk.Button(batch, text=_tr("tool.clip.btn_skip"),
                   command=lambda: self._batch_status("skipped")).pack(
            side="left", padx=2)
        ttk.Button(batch, text=_tr("tool.clip.btn_unskip"),
                   command=lambda: self._batch_status("draft")).pack(
            side="left", padx=2)
        ttk.Button(batch, text=_tr("tool.clip.btn_reset_crop"),
                   command=self._batch_reset_crop).pack(
            side="left", padx=2)
        ttk.Button(batch, text=_tr("tool.clip.btn_jump_to_chapter"),
                   command=self._jump_to_chapter).pack(side="left", padx=(20, 2))

        # ── Bottom export bar ──
        bot = ttk.Frame(f)
        bot.pack(fill="x", padx=6, pady=6)
        ttk.Label(bot, text=_tr("tool.clip.label_output_dir")).pack(
            side="left", padx=4)
        self._out_dir_var = tk.StringVar()
        self._out_dir_var.trace_add("write", lambda *_a: self._autosave())

        self._export_btn = ttk.Button(
            bot, text=_tr("tool.clip.btn_export_all"),
            command=self._on_export_clicked)
        self._export_btn.pack(side="right", padx=(2, 4))
        self._export_one_btn = ttk.Button(
            bot, text=_tr("tool.clip.btn_export_selected"),
            command=self._on_export_selected_clicked)
        self._export_one_btn.pack(side="right", padx=2)
        ttk.Button(bot, text=_tr("tool.clip.btn_browse"),
                   command=self._browse_out_dir).pack(side="right", padx=2)
        ttk.Entry(bot, textvariable=self._out_dir_var).pack(
            side="left", fill="x", expand=True, padx=4)

        self._export_progress = ttk.Progressbar(f, mode="determinate")
        self._export_progress.pack(fill="x", padx=6, pady=(0, 6))

    def _refresh_export_summary(self) -> None:
        if not hasattr(self, "_summary_tree"):
            return
        self._summary_tree.bind(self._clips)

    def _on_summary_clip_selected(self, clip: ClipDraft | None) -> None:
        # Tab 2 no longer hosts a focused-clip editor. Selection just records
        # the focused id so batch buttons know which row is current; actual
        # editing happens after [跳到该章节] navigates back to Tab 1.
        self._focused_clip_id = clip.id if clip is not None else None

    def _batch_status(self, new_status: str) -> None:
        clips = self._summary_tree.get_selected_clips()
        if not clips:
            self._set_status(_tr("tool.clip.warn_pick_rows"))
            return
        for c in clips:
            c.status = new_status
        self._refresh_export_summary()
        self._refresh_chapter_list()
        # Refresh open chapter detail too
        if self._selected_chapter_idx is not None:
            self._refresh_clip_cards_for_chapter(self._selected_chapter_idx)
        self._autosave()
        self._set_status(_tr("tool.clip.status_batch_status").format(
            n=len(clips), status=new_status))

    def _batch_reset_crop(self) -> None:
        clips = self._summary_tree.get_selected_clips()
        if not clips:
            self._set_status(_tr("tool.clip.warn_pick_rows"))
            return
        for c in clips:
            c.crop_rect = None
        self._autosave()
        # If any reset clip is the one currently focused on the chapter tab,
        # rebind its preview so the user sees the reset reflected.
        if self._focused_clip_id is not None and any(
                c.id == self._focused_clip_id for c in clips):
            self._refresh_focused_preview()
        self._set_status(_tr("tool.clip.status_crop_reset").format(
            n=len(clips)))

    def _jump_to_chapter(self) -> None:
        clip = self._summary_tree.get_focused_clip()
        if clip is None:
            self._set_status(_tr("tool.clip.warn_pick_rows"))
            return
        self._notebook.select(self._tab_chapters)
        self._focused_clip_id = clip.id
        self._on_chapter_selected(clip.chapter_idx)

    # ── Header / source handlers ──────────────────────────────────────────

    def _browse_pack(self) -> None:
        path = filedialog.askopenfilename(
            title=_tr("tool.clip.dialog_pick_pack"),
            filetypes=[("postprocess.json", "*postprocess.json"),
                       ("JSON", "*.json")])
        if path:
            self._pack_var.set(path)

    def _browse_video(self) -> None:
        path = filedialog.askopenfilename(
            title=_tr("tool.clip.dialog_pick_video"),
            filetypes=[("Video", "*.mp4 *.mkv *.mov *.webm"), ("All", "*.*")])
        if path:
            self._video_var.set(path)

    def _browse_srt(self) -> None:
        path = filedialog.askopenfilename(
            title=_tr("tool.clip.dialog_pick_srt"),
            filetypes=[("SRT", "*.srt"), ("All", "*.*")])
        if path:
            self._srt_var.set(path)

    def _browse_out_dir(self) -> None:
        d = filedialog.askdirectory(title=_tr("tool.clip.dialog_pick_out_dir"))
        if d:
            self._out_dir_var.set(d)

    def _on_load_clicked(self) -> None:
        pack_path = self._pack_var.get().strip()
        if not pack_path or not os.path.isfile(pack_path):
            messagebox.showerror(_tr("tool.clip.title"),
                                 _tr("tool.clip.err_pack_required"))
            return
        self._load_pack_file(pack_path)

    def _on_source_path_changed(self, *_a) -> None:
        self._autosave()

    def _load_pack_file(self, pack_path: str) -> None:
        try:
            self._pack = cliplib.load_pack(pack_path)
        except Exception as e:
            messagebox.showerror(_tr("tool.clip.title"), str(e))
            return
        self._pack_path = pack_path
        if self._pack_var.get() != pack_path:
            self._pack_var.set(pack_path)

        self._video_path = self._video_var.get().strip()
        self._srt_path = self._srt_var.get().strip()
        if self._video_path and os.path.isfile(self._video_path):
            self._video_duration = cliplib.probe_duration(self._video_path)
            self._video_w, self._video_h = \
                cliplib.probe_resolution(self._video_path)
        self._chapters = cliplib.list_chapters(self._pack, self._video_duration)
        if self._srt_path and os.path.isfile(self._srt_path):
            try:
                self._cues = cliplib.load_cues(self._srt_path)
            except Exception:
                self._cues = []

        self._refresh_chapter_list()
        self._refresh_export_summary()
        self._set_status(_tr("tool.clip.status_loaded").format(
            n=len(self._chapters)))
        self._autosave()
        # Pack just loaded — pop user over to the chapters tab to start work.
        try:
            self._notebook.select(self._tab_chapters)
        except tk.TclError:
            pass

    # ── Cut file management ───────────────────────────────────────────────

    def _has_cut(self) -> bool:
        return self._cut_path is not None

    def _refresh_cut_state(self) -> None:
        has = self._has_cut()
        if has:
            self._cut_status_var.set(
                _tr("tool.clip.cut_open").format(
                    name=self._cut_name, path=self._cut_path))
        else:
            self._cut_status_var.set(_tr("tool.clip.cut_none"))
        # Tab 0 (project) always enabled. Tab 1 (chapters) and Tab 2 (export)
        # require a loaded cut.
        state = "normal" if has else "disabled"
        try:
            self._notebook.tab(1, state=state)
            self._notebook.tab(2, state=state)
        except tk.TclError:
            pass
        # When no cut is open, force the user back to the project tab so the
        # disabled tabs don't leave them staring at an empty pane.
        if not has:
            try:
                self._notebook.select(self._tab_project)
            except tk.TclError:
                pass

    def _default_cut_dir(self) -> str | None:
        if not self._project_root:
            return None
        return os.path.join(self._project_root, ".videocraft", "clips")

    def _suggested_cut_filename(self) -> str:
        v = self._video_var.get().strip()
        if v:
            return f"{os.path.splitext(os.path.basename(v))[0]}.json"
        if self._project_root:
            return f"{os.path.basename(self._project_root)}.json"
        return "cut.json"

    _INVALID_FNAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    def _sanitize_cut_name(self, raw: str) -> str:
        return self._INVALID_FNAME_CHARS.sub("", raw or "").strip()

    def _on_new_cut(self) -> None:
        cut_dir = self._default_cut_dir()
        if cut_dir is None:
            messagebox.showerror(_tr("tool.clip.title"),
                                  _tr("tool.clip.warn_no_project"))
            return
        default_name = os.path.splitext(self._suggested_cut_filename())[0]
        name = simpledialog.askstring(
            _tr("tool.clip.title"),
            _tr("tool.clip.dialog_new_cut_name"),
            initialvalue=default_name, parent=self.master)
        if name is None:
            return
        name = self._sanitize_cut_name(name)
        if not name:
            messagebox.showerror(_tr("tool.clip.title"),
                                  _tr("tool.clip.warn_empty_name"))
            return
        os.makedirs(cut_dir, exist_ok=True)
        path = os.path.join(cut_dir, f"{name}.json")
        if os.path.exists(path):
            if not messagebox.askyesno(
                _tr("tool.clip.title"),
                _tr("tool.clip.confirm_overwrite").format(name=name)):
                return
        self._cut_path = path
        self._cut_name = os.path.splitext(os.path.basename(path))[0]
        self._suspend_autosave = True
        try:
            self._pack = None
            self._pack_path = ""
            self._pack_var.set("")
            self._video_var.set("")
            self._srt_var.set("")
            self._video_path = ""
            self._srt_path = ""
            self._chapters = []
            self._cues = []
            self._clips = []
            self._next_clip_id = 1
            self._ranks = {}
            self._selected_chapter_idx = None
            self._focused_clip_id = None
            self._refresh_chapter_list()
            self._build_detail_placeholder()
            self._refresh_export_summary()
            self._out_dir_var.set("")
        finally:
            self._suspend_autosave = False
        self._refresh_out_dir()
        self._refresh_cut_state()
        self._autosave()
        self._set_status(_tr("tool.clip.status_cut_new").format(
            name=self._cut_name))

    def _on_open_cut(self) -> None:
        cut_dir = self._default_cut_dir()
        if cut_dir is None:
            messagebox.showerror(_tr("tool.clip.title"),
                                  _tr("tool.clip.warn_no_project"))
            return
        if not os.path.isdir(cut_dir):
            messagebox.showinfo(_tr("tool.clip.title"),
                                 _tr("tool.clip.info_no_cuts_yet"))
            return
        names = sorted(f for f in os.listdir(cut_dir)
                        if f.lower().endswith(".json"))
        if not names:
            messagebox.showinfo(_tr("tool.clip.title"),
                                 _tr("tool.clip.info_no_cuts_yet"))
            return
        items = [(os.path.splitext(n)[0], os.path.join(cut_dir, n))
                  for n in names]
        picked = self._show_cut_picker(items)
        if not picked:
            return
        self._open_cut_path(picked)

    def _show_cut_picker(self, items: list[tuple[str, str]]) -> str | None:
        dlg = tk.Toplevel(self.master)
        dlg.title(_tr("tool.clip.dialog_pick_cut"))
        dlg.transient(self.master)
        dlg.geometry("500x360")
        dlg.grab_set()

        tk.Label(dlg, text=_tr("tool.clip.dialog_pick_cut_hint"),
                  anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        list_frame = tk.Frame(dlg)
        list_frame.pack(fill="both", expand=True, padx=10, pady=4)
        listbox = tk.Listbox(list_frame, activestyle="dotbox")
        listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(list_frame, orient="vertical",
                            command=listbox.yview)
        listbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        for label, _path in items:
            listbox.insert("end", label)
        listbox.selection_set(0)
        listbox.activate(0)
        listbox.focus_set()

        result: dict = {"v": None}

        def on_ok():
            sel = listbox.curselection()
            if sel:
                result["v"] = items[sel[0]][1]
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        listbox.bind("<Double-Button-1>", lambda _e: on_ok())
        listbox.bind("<Return>", lambda _e: on_ok())
        dlg.bind("<Escape>", lambda _e: on_cancel())
        btn_row = tk.Frame(dlg)
        btn_row.pack(fill="x", pady=(4, 8), padx=10)
        ttk.Button(btn_row, text=_tr("tool.clip.btn_open"),
                    command=on_ok).pack(side="right", padx=4)
        ttk.Button(btn_row, text=_tr("tool.clip.btn_cancel_dialog"),
                    command=on_cancel).pack(side="right", padx=4)
        self.master.wait_window(dlg)
        return result["v"]

    def _open_cut_path(self, path: str) -> None:
        try:
            cut = cliplib.load_cut_file(path)
        except Exception as e:
            messagebox.showerror(_tr("tool.clip.title"), str(e))
            return
        self._cut_path = path
        self._cut_name = cut["name"] or os.path.splitext(
            os.path.basename(path))[0]

        sources = cut["sources"] or {}
        self._suspend_autosave = True
        try:
            self._pack_var.set(sources.get("pack_path", ""))
            self._video_var.set(sources.get("video_path", ""))
            self._srt_var.set(sources.get("srt_path", ""))
            self._out_dir_var.set(cut.get("output_dir", "") or "")
            self._clips = cut["clips"]
            self._next_clip_id = max((c.id for c in self._clips), default=0) + 1
            self._ranks = cut.get("ranks") or {}
            self._selected_chapter_idx = None
            self._focused_clip_id = None
            pack_path = sources.get("pack_path") or ""
            if pack_path and os.path.isfile(pack_path):
                self._load_pack_file(pack_path)
            else:
                self._video_path = self._video_var.get().strip()
                self._srt_path = self._srt_var.get().strip()
                if self._video_path and os.path.isfile(self._video_path):
                    self._video_duration = cliplib.probe_duration(self._video_path)
                    self._video_w, self._video_h = \
                        cliplib.probe_resolution(self._video_path)
                if self._srt_path and os.path.isfile(self._srt_path):
                    try:
                        self._cues = cliplib.load_cues(self._srt_path)
                    except Exception:
                        self._cues = []
            self._refresh_export_summary()
        finally:
            self._suspend_autosave = False
        self._refresh_out_dir()
        self._refresh_cut_state()
        self._set_status(_tr("tool.clip.status_cut_opened").format(
            name=self._cut_name, n=len(self._clips)))

    def _on_save_as_cut(self) -> None:
        if not self._has_cut():
            self._on_new_cut()
            return
        default_dir = self._default_cut_dir() or os.path.dirname(
            self._cut_path or "")
        if default_dir:
            os.makedirs(default_dir, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title=_tr("tool.clip.dialog_save_as_cut"),
            defaultextension=".json",
            initialdir=default_dir or None,
            initialfile=f"{self._cut_name}.json",
            filetypes=[("Clip cut JSON", "*.json")])
        if not path:
            return
        self._cut_path = path
        self._cut_name = os.path.splitext(os.path.basename(path))[0]
        self._refresh_cut_state()
        self._autosave()
        self._set_status(_tr("tool.clip.status_cut_saved_as").format(
            name=self._cut_name))

    def _autosave(self) -> None:
        if self._suspend_autosave or not self._has_cut():
            return
        try:
            cliplib.write_cut_file(
                self._cut_path,
                name=self._cut_name,
                sources={
                    "pack_path":  self._pack_var.get().strip(),
                    "video_path": self._video_var.get().strip(),
                    "srt_path":   self._srt_var.get().strip(),
                },
                clips=self._clips,
                output_dir=self._out_dir_var.get().strip(),
                ranks=self._ranks,
            )
        except Exception as e:
            self._set_status(f"autosave failed: {e}")

    def _default_out_dir(self) -> str:
        if self._out_dir_var.get().strip():
            return self._out_dir_var.get().strip()
        if self._project_root and self._cut_name:
            return os.path.join(self._project_root,
                                f"clip_{self._cut_name}", "output")
        if self._cut_path and self._cut_name:
            return os.path.join(os.path.dirname(self._cut_path),
                                 f"clip_{self._cut_name}", "output")
        return os.path.join(os.path.dirname(self._video_path) or ".", "clips")

    def _refresh_out_dir(self) -> None:
        if self._project_root and self._cut_name:
            target = os.path.join(self._project_root,
                                   f"clip_{self._cut_name}", "output")
        elif self._cut_path and self._cut_name:
            target = os.path.join(os.path.dirname(self._cut_path),
                                   f"clip_{self._cut_name}", "output")
        else:
            return
        self._suspend_autosave = True
        try:
            self._out_dir_var.set(target)
        finally:
            self._suspend_autosave = False

    # ── AI helpers ─────────────────────────────────────────────────────────

    def _make_ai_button(self, parent, *, idle_text: str,
                         worker: Callable, on_success: Callable):
        """Tri-state AI button. worker(token) → result; on_success(result)
        runs on main thread; cancelling routes through token.cancel()."""
        btn = ttk.Button(parent, text=idle_text)
        btn._token = None    # type: ignore[attr-defined]

        def _reset():
            btn._token = None    # type: ignore[attr-defined]
            try:
                btn.config(state="normal", text=idle_text)
            except tk.TclError:
                pass

        def _click():
            if btn._token is None:
                token = CancellationToken()
                btn._token = token    # type: ignore[attr-defined]
                btn.config(text=_tr("tool.clip.btn_cancel"))
                threading.Thread(target=_run, args=(token,), daemon=True).start()
            else:
                btn._token.cancel()
                try:
                    btn.config(state="disabled",
                                text=_tr("tool.clip.btn_cancelling"))
                except tk.TclError:
                    pass

        def _run(token):
            try:
                result = worker(token)
                self.master.after(0, lambda r=result: on_success(r))
                self.master.after(0, _reset)
            except AIError as e:
                if e.kind == Kind.CANCELLED:
                    self.master.after(0, lambda: self._set_status(
                        _tr("tool.clip.status_cancelled")))
                else:
                    self.master.after(0,
                                       lambda err=e: show_ai_error(self.master, err))
                self.master.after(0, _reset)
            except Exception as e:
                self.master.after(0, lambda err=e: messagebox.showerror(
                    _tr("tool.clip.title"), str(err)))
                self.master.after(0, _reset)

        btn.config(command=_click)
        return btn

    def _make_pkg_worker(self, clip: ClipDraft):
        def worker(token, c=clip):
            return cliplib.package_clip(c, self._pack or {},
                                          cancel_token=token)
        return worker

    # ── AI workers ─────────────────────────────────────────────────────────

    def _worker_rank_chapters(self, token):
        if not self._pack:
            raise RuntimeError(_tr("tool.clip.warn_no_pack_loaded"))
        paragraphs_path = ""
        if self._pack_path:
            paragraphs_path = self._pack_path.replace("-postprocess.json",
                                                       "-paragraphs.txt")
            if not os.path.isfile(paragraphs_path):
                paragraphs_path = ""
        return cliplib.rank_chapters(self._pack, paragraphs_path,
                                      video_duration=self._video_duration,
                                      cancel_token=token)

    def _on_rank_done(self, ranked: list[dict]) -> None:
        self._ranks = {int(r["idx"]): r for r in ranked}
        self._refresh_chapter_list()
        self._autosave()
        self._set_status(_tr("tool.clip.status_rank_done").format(
            n=len(ranked)))

    def _worker_find_peaks(self, token, chapter_idx: int):
        if not self._pack:
            raise RuntimeError(_tr("tool.clip.warn_no_pack_loaded"))
        if not self._cues:
            raise RuntimeError(_tr("tool.clip.warn_no_paragraphs").format(
                path=self._srt_path or "<SRT 未加载>"))
        return cliplib.find_peaks(
            self._pack, chapter_idx, self._cues,
            video_duration=self._video_duration,
            cancel_token=token)

    def _on_peaks_done(self, peaks: list[dict], chapter_idx: int) -> None:
        if not (0 <= chapter_idx < len(self._chapters)):
            return
        ch = self._chapters[chapter_idx]
        added = 0
        first_clip_id = None
        for p in peaks:
            s, e = p["start_sec"], p["end_sec"]
            if self._cues:
                s, e = cliplib.snap_to_cue_boundaries(self._cues, s, e)
            new_clip = self._append_new_clip(ch, s, e)
            if first_clip_id is None:
                first_clip_id = new_clip.id
            added += 1
        # Reveal the result + land on the first new clip's editor
        self._expand_chapter_in_tree(chapter_idx)
        if first_clip_id is not None:
            self._select_clip_in_tree(first_clip_id)
            self._selected_chapter_idx = chapter_idx
            self._focused_clip_id = first_clip_id
            self._build_detail_clip(first_clip_id)
        self._set_status(_tr("tool.clip.status_peaks_done").format(
            n=added, ch=ch["title"]))

    def _worker_chapter_full_auto(self, token: CancellationToken,
                                    chapter_idx: int):
        """find peaks → for each new clip, package → return summary dict."""
        if not self._pack:
            raise RuntimeError(_tr("tool.clip.warn_no_pack_loaded"))
        if not self._cues:
            raise RuntimeError(_tr("tool.clip.warn_no_paragraphs").format(
                path=self._srt_path or "<SRT 未加载>"))
        peaks = cliplib.find_peaks(
            self._pack, chapter_idx, self._cues,
            video_duration=self._video_duration,
            cancel_token=token)
        # We need real ClipDrafts. Build them in-thread (no UI ops),
        # main-thread later wires them in. Snap + excerpt prep here.
        new_clips: list[ClipDraft] = []
        ch = self._chapters[chapter_idx]
        next_id = self._next_clip_id
        for p in peaks:
            if token.cancelled:
                break
            s, e = p["start_sec"], p["end_sec"]
            if self._cues:
                s, e = cliplib.snap_to_cue_boundaries(self._cues, s, e)
            excerpt = ""
            if self._cues:
                buf = []
                for cue in self._cues:
                    cs = cue.start.total_seconds()
                    ce = cue.end.total_seconds()
                    if ce <= s or cs >= e:
                        continue
                    buf.append(cue.content.replace("\n", " "))
                excerpt = " ".join(buf)[:500]
            clip = ClipDraft(
                id=next_id, chapter_idx=chapter_idx,
                chapter_title=ch["title"],
                start_sec=float(s), end_sec=float(e),
                original_excerpt=excerpt)
            next_id += 1
            new_clips.append(clip)

        # Run package_clip per new clip, serially, honoring cancel
        for c in new_clips:
            if token.cancelled:
                break
            try:
                pkg = cliplib.package_clip(c, self._pack,
                                            cancel_token=token)
                c.hook  = pkg.get("hook",  "") or ""
                c.outro = pkg.get("outro", "") or ""
                c.title = pkg.get("title", "") or ""
                c.hashtags = list(pkg.get("hashtags") or [])
                # Center crop default
                if self._video_w and self._video_h:
                    c.crop_rect = cliplib.center_crop_rect(
                        self._video_w, self._video_h)
                c.status = "reviewed"
            except AIError as ae:
                if ae.kind == Kind.CANCELLED:
                    raise
                # Single clip package failure: leave it draft, continue
                c.status = "draft"
            except Exception:
                c.status = "draft"

        return {"chapter_idx": chapter_idx, "clips": new_clips}

    def _on_chapter_auto_done(self, result: dict, chapter_idx: int) -> None:
        clips = result.get("clips") or []
        for c in clips:
            c.id = self._next_clip_id
            self._next_clip_id += 1
            self._clips.append(c)
        self._refresh_clip_cards_for_chapter(chapter_idx)
        self._refresh_export_summary()
        self._autosave()
        # Reveal the result and land on the first new clip's editor
        self._expand_chapter_in_tree(chapter_idx)
        if clips:
            self._select_clip_in_tree(clips[0].id)
            self._selected_chapter_idx = chapter_idx
            self._focused_clip_id = clips[0].id
            self._build_detail_clip(clips[0].id)
        self._set_status(_tr("tool.clip.status_chapter_auto_done").format(
            n=len(clips), ch=self._chapters[chapter_idx]["title"]))

    def _worker_global_full_auto(self, token: CancellationToken):
        """Iterate all chapters by score (desc), skip those that already
        have clips. Returns total clips created.
        """
        if not self._pack:
            raise RuntimeError(_tr("tool.clip.warn_no_pack_loaded"))
        if not self._cues:
            raise RuntimeError(_tr("tool.clip.warn_no_paragraphs").format(
                path=self._srt_path or "<SRT 未加载>"))
        # Order by score desc; chapters without rank go last
        order = sorted(range(len(self._chapters)),
                        key=lambda i: -self._ranks.get(i, {}).get("score", -1))
        produced: list[tuple[int, list[ClipDraft]]] = []
        for ch_idx in order:
            if token.cancelled:
                break
            if any(c.chapter_idx == ch_idx for c in self._clips):
                continue    # skip chapters already populated
            self.master.after(
                0, self._set_status,
                _tr("tool.clip.status_global_progress").format(
                    ch=self._chapters[ch_idx]["title"]))
            try:
                result = self._worker_chapter_full_auto(token, ch_idx)
                produced.append((ch_idx, result["clips"]))
            except AIError as ae:
                if ae.kind == Kind.CANCELLED:
                    break
                # Chapter failure → log + continue
                self.master.after(
                    0, self._set_status,
                    _tr("tool.clip.status_global_chapter_fail").format(
                        ch=self._chapters[ch_idx]["title"], err=str(ae)[:60]))
            except Exception as e:
                self.master.after(
                    0, self._set_status,
                    _tr("tool.clip.status_global_chapter_fail").format(
                        ch=self._chapters[ch_idx]["title"], err=str(e)[:60]))
        return produced

    def _on_global_auto_done(self, produced: list) -> None:
        total = 0
        for ch_idx, clips in produced:
            for c in clips:
                c.id = self._next_clip_id
                self._next_clip_id += 1
                self._clips.append(c)
                total += 1
        self._refresh_chapter_list()
        if self._selected_chapter_idx is not None:
            self._refresh_clip_cards_for_chapter(self._selected_chapter_idx)
        self._refresh_export_summary()
        self._autosave()
        self._set_status(_tr("tool.clip.status_global_auto_done").format(
            n=total, c=len(produced)))

    # ── Export workers (preserved from prior design) ──────────────────────

    def _on_export_clicked(self) -> None:
        if not self._clips:
            self._set_status(_tr("tool.clip.warn_no_clips"))
            return
        if not self._video_path or not os.path.isfile(self._video_path):
            self._set_status(_tr("tool.clip.warn_no_video"))
            return
        if self._export_thread and self._export_thread.is_alive():
            self._export_cancel_flag["v"] = True
            self._export_btn.config(state="disabled",
                                    text=_tr("tool.clip.btn_cancelling"))
            return
        out_dir = self._default_out_dir()
        os.makedirs(out_dir, exist_ok=True)
        self._out_dir_var.set(out_dir)
        self._export_cancel_flag = {"v": False}
        self._export_btn.config(text=_tr("tool.clip.btn_cancel"))
        self._export_progress["value"] = 0
        self.set_busy()
        self._export_thread = threading.Thread(
            target=self._export_worker,
            args=(out_dir, list(self._clips)), daemon=True)
        self._export_thread.start()

    def _on_export_selected_clicked(self) -> None:
        clips = self._summary_tree.get_selected_clips()
        if not clips:
            self._set_status(_tr("tool.clip.warn_pick_rows"))
            return
        if not self._video_path:
            self._set_status(_tr("tool.clip.warn_no_video"))
            return
        if self._export_thread and self._export_thread.is_alive():
            return
        out_dir = self._default_out_dir()
        os.makedirs(out_dir, exist_ok=True)
        self._out_dir_var.set(out_dir)
        self._export_cancel_flag = {"v": False}
        self._export_one_btn.config(state="disabled")
        self._export_progress["value"] = 0
        self.set_busy()
        self._export_thread = threading.Thread(
            target=self._export_worker,
            args=(out_dir, list(clips)), daemon=True)
        self._export_thread.start()

    def _export_worker(self, out_dir: str, clips: list[ClipDraft]) -> None:
        from i18n import tr
        eligible = [c for c in clips if c.status != "skipped"]
        total = len(eligible)

        def cancel_check() -> bool:
            return bool(self._export_cancel_flag.get("v"))

        def on_step(i: int, total: int, _status: str, pct: int) -> None:
            self.master.after(0, self._set_status,
                              tr("tool.clip.status_exporting").format(
                                  n=i, total=total, pct=pct))
            self.master.after(0, lambda: self._export_progress.configure(
                value=int((i - 1 + pct / 100.0) / max(1, total) * 100)))

        try:
            paths = cliplib.export_all(
                self._video_path, eligible, out_dir,
                source_srt=self._srt_path or None,
                on_progress=on_step,
                cancel_check=cancel_check)
            self.master.after(0, self._autosave)
            if cancel_check():
                self.master.after(0, self._set_status,
                                  tr("tool.clip.status_cancelled"))
                self.set_warning(tr("tool.clip.status_cancelled"))
            else:
                self.master.after(0, self._set_status,
                                  tr("tool.clip.status_done").format(
                                      n=len(paths), out_dir=out_dir))
                self.set_done()
        except Exception as e:
            self.master.after(0, self._set_status, f"✗ {e}")
            self.set_error(str(e))
        finally:
            self.master.after(0, self._export_btn.config,
                              {"state": "normal",
                               "text": tr("tool.clip.btn_export_all")})
            self.master.after(0, self._export_one_btn.config,
                              {"state": "normal"})
            self.master.after(0, lambda: self._export_progress.configure(value=0))
            self.master.after(0, self._refresh_export_summary)

    # ── Misc ───────────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        try:
            self._status_var.set(msg)
        except Exception:
            pass

    def _on_tab_changed(self, _event=None) -> None:
        try:
            tab = self._notebook.index(self._notebook.select())
        except Exception:
            return
        if tab == 1:    # export
            self._refresh_export_summary()


# ── Standalone run ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = ClipWorkbenchApp(root)
    root.mainloop()
