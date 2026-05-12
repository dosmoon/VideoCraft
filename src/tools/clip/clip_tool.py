"""Clip workbench — consumes hotclips.json + renders selected short clips.

Project-only tool (no standalone mode). Opens when the user clicks a
`clip / <inst>` row in the sidebar. Lets the user pick which subtitle
language's hotclips to read from, prune candidates with checkboxes,
and render them via core/clip_render.

MVP scope: pure video slicing — no subtitle burn, no aspect conversion,
no style preset. Those land in follow-up passes; the AI selection
output is already complete here.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from tools.base import ToolBase
from core.subtitle_analysis import analysis_path
from core.clip_render import (
    build_plan, render_clips,
    load_instance_config, save_instance_config,
)
from i18n import tr
import json


class ClipToolApp(ToolBase):
    """Clip workbench — project-only."""

    def __init__(
        self,
        master: tk.Frame,
        project=None,
        instance_name: Optional[str] = None,
    ) -> None:
        if project is None or instance_name is None:
            raise RuntimeError(
                "ClipToolApp requires project + instance_name (project-only tool)"
            )
        self.master = master
        self.project = project
        self.instance_name = instance_name
        self._tool_title = tr("clip_tool.tab_title", instance=instance_name)

        # State
        self._lang_var = tk.StringVar()
        self._candidate_vars: list[tk.BooleanVar] = []
        self._candidate_meta: list[dict] = []  # parallel to vars
        self._hotclips_data: dict = {}
        self._render_thread: Optional[threading.Thread] = None
        self._cancel_flag = False

        self._build_ui()
        self._reload_languages()
        self._restore_selection_from_config()

    # ── UI build ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = tk.Frame(self.master, bg="white")
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        # Header row: language picker + status
        header = tk.Frame(outer, bg="white")
        header.pack(fill="x", pady=(0, 8))
        tk.Label(header, text=tr("clip_tool.lang_label"),
                 bg="white", font=("Microsoft YaHei UI", 10),
                 ).pack(side="left", padx=(0, 6))
        self._lang_combo = ttk.Combobox(
            header, textvariable=self._lang_var, values=[],
            state="readonly", width=24,
        )
        self._lang_combo.pack(side="left")
        self._lang_combo.bind("<<ComboboxSelected>>",
                              lambda _e: self._reload_candidates())

        self._status_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self._status_var,
                 bg="white", fg="#666", font=("Microsoft YaHei UI", 9),
                 ).pack(side="left", padx=(12, 0))

        # Candidate list (scrollable)
        list_frame = tk.LabelFrame(outer, text=tr("clip_tool.candidates"),
                                    bg="white", padx=4, pady=4)
        list_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_frame, bg="white", highlightthickness=0)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._candidate_box = tk.Frame(canvas, bg="white")
        canvas.create_window((0, 0), window=self._candidate_box, anchor="nw")

        def _on_resize(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self._candidate_box.bind("<Configure>", _on_resize)

        def _on_canvas_resize(e):
            children = canvas.find_all()
            if children:
                canvas.itemconfig(children[0], width=e.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

        # Action row
        action = tk.Frame(outer, bg="white")
        action.pack(fill="x", pady=(8, 0))
        self._select_all_btn = tk.Button(
            action, text=tr("clip_tool.btn_select_all"),
            command=self._select_all, relief="flat", bg="#e8e8e8",
        )
        self._select_all_btn.pack(side="left")
        self._select_none_btn = tk.Button(
            action, text=tr("clip_tool.btn_select_none"),
            command=self._select_none, relief="flat", bg="#e8e8e8",
        )
        self._select_none_btn.pack(side="left", padx=(6, 0))

        self._render_btn = tk.Button(
            action, text=tr("clip_tool.btn_render"),
            command=self._on_render,
            bg="#0078d4", fg="white", relief="flat", padx=12, pady=4,
        )
        self._render_btn.pack(side="right")

        # Progress strip
        self._progress = ttk.Progressbar(outer, length=400, mode="determinate")
        self._progress.pack(fill="x", pady=(8, 0))
        self._progress_var = tk.StringVar(value="")
        tk.Label(outer, textvariable=self._progress_var,
                 bg="white", fg="#666", font=("Microsoft YaHei UI", 9),
                 anchor="w",
                 ).pack(fill="x", pady=(2, 0))

    # ── Data loading ─────────────────────────────────────────────────────────

    def _reload_languages(self) -> None:
        """Scan subtitles/ for hotclips.json files. Empty list = no hotclips
        produced yet; UI shows a hint."""
        subs_dir = self.project.subtitles_dir
        langs: list[str] = []
        try:
            for name in sorted(os.listdir(subs_dir)):
                if name.endswith(".hotclips.json"):
                    langs.append(name[:-len(".hotclips.json")])
        except OSError:
            pass

        self._lang_combo["values"] = langs
        if not langs:
            self._status_var.set(tr("clip_tool.status_no_hotclips"))
            self._lang_combo.configure(state="disabled")
            self._render_btn.configure(state="disabled")
            return
        self._lang_combo.configure(state="readonly")
        self._render_btn.configure(state="normal")
        if self._lang_var.get() not in langs:
            self._lang_var.set(langs[0])
        self._reload_candidates()

    def _reload_candidates(self) -> None:
        """Reload candidate list for the currently selected language."""
        for child in self._candidate_box.winfo_children():
            child.destroy()
        self._candidate_vars = []
        self._candidate_meta = []

        lang = self._lang_var.get()
        if not lang:
            return
        path = analysis_path(self.project.subtitles_dir, lang, "hotclips")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self._status_var.set(tr("clip_tool.status_load_failed", error=str(e)))
            return
        self._hotclips_data = data
        clips = data.get("clips") or []
        self._status_var.set(tr("clip_tool.status_loaded", n=len(clips)))

        for i, c in enumerate(clips):
            if not isinstance(c, dict):
                continue
            var = tk.BooleanVar(value=False)
            self._candidate_vars.append(var)
            self._candidate_meta.append(c)
            self._render_candidate_row(i, c, var)

    def _render_candidate_row(self, idx: int, clip: dict, var: tk.BooleanVar) -> None:
        row = tk.Frame(self._candidate_box, bg="white", bd=1, relief="solid")
        row.pack(fill="x", padx=2, pady=2)

        cb = tk.Checkbutton(row, variable=var, bg="white",
                            font=("Microsoft YaHei UI", 10))
        cb.pack(side="left", padx=(4, 8))

        text_col = tk.Frame(row, bg="white")
        text_col.pack(side="left", fill="x", expand=True, pady=4)

        head = tk.Frame(text_col, bg="white")
        head.pack(fill="x")
        tk.Label(head, text=f"#{idx + 1}", bg="white", fg="#888",
                 font=("Microsoft YaHei UI", 9, "bold"),
                 ).pack(side="left")
        ts = f"  {clip.get('start', '')} → {clip.get('end', '')}"
        tk.Label(head, text=ts, bg="white", fg="#0078d4",
                 font=("Consolas", 9),
                 ).pack(side="left")
        dur = clip.get("duration_sec")
        if isinstance(dur, (int, float)):
            tk.Label(head, text=f"  {int(dur)}s", bg="white", fg="#888",
                     font=("Microsoft YaHei UI", 9),
                     ).pack(side="left")
        score = clip.get("score")
        if score is not None:
            color = ("#c00" if isinstance(score, (int, float)) and score >= 8
                     else "#d97706" if isinstance(score, (int, float)) and score >= 6
                     else "#888")
            tk.Label(head, text=f"⭐ {score}", bg="white", fg=color,
                     font=("Microsoft YaHei UI", 10, "bold"),
                     ).pack(side="right", padx=6)

        hook = clip.get("hook", "").strip()
        if hook:
            tk.Label(text_col, text=hook, bg="white", fg="#222",
                     font=("Microsoft YaHei UI", 10, "bold"),
                     wraplength=520, justify="left", anchor="w",
                     ).pack(fill="x")
        why = clip.get("why_viral", "").strip()
        if why:
            tk.Label(text_col, text=why, bg="white", fg="#666",
                     font=("Microsoft YaHei UI", 9),
                     wraplength=520, justify="left", anchor="w",
                     ).pack(fill="x")

    # ── Persistence ──────────────────────────────────────────────────────────

    def _instance_dir(self) -> str:
        return self.project.derivative_dir("clip", self.instance_name)

    def _restore_selection_from_config(self) -> None:
        cfg = load_instance_config(self._instance_dir())
        if not cfg:
            return
        # Restore language pick if it still exists on disk.
        lang = cfg.get("source_subtitle")
        if lang and lang in self._lang_combo["values"]:
            self._lang_var.set(lang)
            self._reload_candidates()
        # Restore checkmarks by source index.
        sel = cfg.get("selected_clip_indices") or []
        sel_set = set(sel)
        for i, var in enumerate(self._candidate_vars):
            var.set(i in sel_set)

    def _save_selection(self, rendered: list[str] | None = None) -> None:
        sel = [i for i, v in enumerate(self._candidate_vars) if v.get()]
        cfg = {
            "schema_version": 1,
            "source_subtitle": self._lang_var.get(),
            "selected_clip_indices": sel,
        }
        if rendered is not None:
            cfg["rendered"] = rendered
            from datetime import datetime, timezone
            cfg["rendered_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save_instance_config(self._instance_dir(), cfg)

    # ── Selection helpers ────────────────────────────────────────────────────

    def _select_all(self) -> None:
        for v in self._candidate_vars:
            v.set(True)

    def _select_none(self) -> None:
        for v in self._candidate_vars:
            v.set(False)

    # ── Render flow ──────────────────────────────────────────────────────────

    def _on_render(self) -> None:
        selected = [i for i, v in enumerate(self._candidate_vars) if v.get()]
        if not selected:
            messagebox.showinfo(
                "VideoCraft", tr("clip_tool.warn_no_selection"),
                parent=self.master,
            )
            return
        video_path = self.project.source_video_path
        if not os.path.isfile(video_path):
            messagebox.showerror(
                "VideoCraft", tr("clip_tool.err_no_source"),
                parent=self.master,
            )
            return

        instance_dir = self._instance_dir()
        os.makedirs(instance_dir, exist_ok=True)
        plan = build_plan(self._hotclips_data, selected, instance_dir)
        if not plan:
            messagebox.showinfo(
                "VideoCraft", tr("clip_tool.warn_no_valid_plan"),
                parent=self.master,
            )
            return

        self._save_selection()
        self._cancel_flag = False
        self._render_btn.configure(state="disabled")
        self.set_busy(tr("clip_tool.rendering"))

        def worker():
            def cb(done, total, label):
                self.master.after(0,
                    lambda d=done, t=total, l=label: self._on_progress(d, t, l))

            def cancel_check():
                return self._cancel_flag

            result = render_clips(
                video_path, plan,
                progress_cb=cb, cancel_check=cancel_check,
            )
            self.master.after(0, lambda: self._on_render_done(result))

        self._render_thread = threading.Thread(target=worker, daemon=True)
        self._render_thread.start()

    def _on_progress(self, done: int, total: int, label: str) -> None:
        if total <= 0:
            return
        pct = (done / total) * 100
        self._progress["value"] = pct
        self._progress_var.set(
            tr("clip_tool.progress_fmt", done=done, total=total, label=label)
        )

    def _on_render_done(self, result) -> None:
        self._render_btn.configure(state="normal")
        if result.errors:
            self.set_warning(
                f"clip render completed with {len(result.errors)} error(s)"
            )
            err_lines = [
                tr("clip_tool.error_line", index=idx, error=msg)
                for idx, msg in result.errors[:5]
            ]
            messagebox.showwarning(
                "VideoCraft",
                tr("clip_tool.done_with_errors",
                   rendered=len(result.rendered),
                   errors=len(result.errors),
                   detail="\n".join(err_lines)),
                parent=self.master,
            )
        else:
            self.set_done()
            messagebox.showinfo(
                "VideoCraft",
                tr("clip_tool.done_ok", n=len(result.rendered)),
                parent=self.master,
            )
        self._save_selection(rendered=result.rendered)
