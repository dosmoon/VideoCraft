"""Clip Script workbench — Phase A walking skeleton (manual flow).

4-tab wizard: Chapters → Peaks → Package → Crop & Export. Phase A has
no AI buttons; Phase B (separate commit) will add rank / find / package
buttons. Architecture follows docs/draft/program-script-clip.md.
"""

from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from tools.base import ToolBase
from core.program import clip as cliplib
from core.program.clip import ClipDraft
from core.segment_model import format_timestamp, parse_timestamp
from ui.crop_overlay import CropOverlay
from ui.vlc_player import VlcPlayerFrame, is_vlc_available


def _tr(key: str) -> str:
    """Lazy i18n import (avoid circulars)."""
    from i18n import tr
    return tr(key)


def _seconds_to_str(s: float) -> str:
    return format_timestamp(s)


def _str_to_seconds(text: str) -> float | None:
    return parse_timestamp(text)


class ClipWorkbenchApp(ToolBase):
    """Manual clip-script workbench. Reads subtitle.pack output, lets user
    pick chapters → frame clips → write hook/outro/title → crop → export.
    """

    def __init__(self, master, initial_file: str | None = None):
        self.master = master
        master.title(_tr("tool.clip.title"))
        master.geometry("1100x720")

        # ── State ─────────────────────────────────────────────────────────
        self._pack: dict | None = None
        self._pack_path: str = ""
        self._video_path: str = ""
        self._srt_path: str = ""
        self._video_w: int = 0
        self._video_h: int = 0
        self._video_duration: float = 0.0
        self._chapters: list[dict] = []
        self._cues = []                        # parsed SRT cues for snapping
        self._clips: list[ClipDraft] = []
        self._next_clip_id: int = 1
        self._chapter_check_vars: dict[int, tk.BooleanVar] = {}
        self._export_thread: threading.Thread | None = None
        self._export_cancel_flag: dict = {"v": False}

        # ── Notebook ──────────────────────────────────────────────────────
        self._notebook = ttk.Notebook(master)
        self._notebook.pack(fill="both", expand=True, padx=6, pady=6)

        self._tab_setup = ttk.Frame(self._notebook)
        self._tab_peaks = ttk.Frame(self._notebook)
        self._tab_package = ttk.Frame(self._notebook)
        self._tab_export = ttk.Frame(self._notebook)
        self._notebook.add(self._tab_setup,   text=_tr("tool.clip.tab_chapters"))
        self._notebook.add(self._tab_peaks,   text=_tr("tool.clip.tab_peaks"))
        self._notebook.add(self._tab_package, text=_tr("tool.clip.tab_package"))
        self._notebook.add(self._tab_export,  text=_tr("tool.clip.tab_export"))
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_tab_setup()
        self._build_tab_peaks()
        self._build_tab_package()
        self._build_tab_export()

        # Bottom status bar
        self._status_var = tk.StringVar(value="")
        tk.Label(master, textvariable=self._status_var,
                 fg="blue", anchor="w").pack(fill="x", padx=8, pady=(0, 4))

        if initial_file and os.path.isfile(initial_file):
            self._load_pack_file(initial_file)

    # ── Tab 1: setup + chapters ───────────────────────────────────────────

    def _build_tab_setup(self) -> None:
        f = self._tab_setup
        # Top: file pickers
        top = ttk.LabelFrame(f, text=_tr("tool.clip.section_inputs"))
        top.pack(fill="x", padx=6, pady=6)

        # Postprocess.json
        ttk.Label(top, text=_tr("tool.clip.label_pack")).grid(
            row=0, column=0, sticky="e", padx=4, pady=3)
        self._pack_var = tk.StringVar()
        ttk.Entry(top, textvariable=self._pack_var, width=70).grid(
            row=0, column=1, sticky="we", padx=4)
        ttk.Button(top, text=_tr("tool.clip.btn_browse"),
                   command=self._browse_pack).grid(row=0, column=2, padx=4)

        # Video
        ttk.Label(top, text=_tr("tool.clip.label_video")).grid(
            row=1, column=0, sticky="e", padx=4, pady=3)
        self._video_var = tk.StringVar()
        ttk.Entry(top, textvariable=self._video_var, width=70).grid(
            row=1, column=1, sticky="we", padx=4)
        ttk.Button(top, text=_tr("tool.clip.btn_browse"),
                   command=self._browse_video).grid(row=1, column=2, padx=4)

        # SRT
        ttk.Label(top, text=_tr("tool.clip.label_srt")).grid(
            row=2, column=0, sticky="e", padx=4, pady=3)
        self._srt_var = tk.StringVar()
        ttk.Entry(top, textvariable=self._srt_var, width=70).grid(
            row=2, column=1, sticky="we", padx=4)
        ttk.Button(top, text=_tr("tool.clip.btn_browse"),
                   command=self._browse_srt).grid(row=2, column=2, padx=4)

        ttk.Button(top, text=_tr("tool.clip.btn_load"),
                   command=self._on_load_clicked).grid(
            row=3, column=1, sticky="w", padx=4, pady=6)

        top.columnconfigure(1, weight=1)

        # Chapters table
        mid = ttk.LabelFrame(f, text=_tr("tool.clip.section_chapters"))
        mid.pack(fill="both", expand=True, padx=6, pady=6)

        cols = ("idx", "time", "duration", "title", "refined")
        self._chap_tree = ttk.Treeview(mid, columns=cols, show="headings",
                                       selectmode="browse", height=14)
        self._chap_tree.heading("idx",     text="#")
        self._chap_tree.heading("time",    text=_tr("tool.clip.col_time"))
        self._chap_tree.heading("duration",text=_tr("tool.clip.col_duration"))
        self._chap_tree.heading("title",   text=_tr("tool.clip.col_title"))
        self._chap_tree.heading("refined", text=_tr("tool.clip.col_refined"))
        self._chap_tree.column("idx",     width=40,  anchor="center")
        self._chap_tree.column("time",    width=80,  anchor="center")
        self._chap_tree.column("duration",width=80,  anchor="center")
        self._chap_tree.column("title",   width=220, anchor="w")
        self._chap_tree.column("refined", width=520, anchor="w")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self._chap_tree.yview)
        self._chap_tree.configure(yscrollcommand=sb.set)
        self._chap_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Hint: chapter selection happens implicitly — Tab 2 lets user add
        # peaks under any chapter.
        tk.Label(f, text=_tr("tool.clip.hint_chapters"),
                 fg="gray").pack(padx=8, pady=(0, 6), anchor="w")

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
            filetypes=[("Video", "*.mp4 *.mkv *.mov *.webm"),
                       ("All", "*.*")])
        if path:
            self._video_var.set(path)

    def _browse_srt(self) -> None:
        path = filedialog.askopenfilename(
            title=_tr("tool.clip.dialog_pick_srt"),
            filetypes=[("SRT", "*.srt"), ("All", "*.*")])
        if path:
            self._srt_var.set(path)

    def _on_load_clicked(self) -> None:
        pack_path = self._pack_var.get().strip()
        if not pack_path or not os.path.isfile(pack_path):
            messagebox.showerror(_tr("tool.clip.title"),
                                 _tr("tool.clip.err_pack_required"))
            return
        self._load_pack_file(pack_path)

    def _load_pack_file(self, pack_path: str) -> None:
        try:
            self._pack = cliplib.load_pack(pack_path)
        except Exception as e:
            messagebox.showerror(_tr("tool.clip.title"), str(e))
            return
        self._pack_path = pack_path
        self._pack_var.set(pack_path)

        # Resolve video + SRT from the unit's manifest (authoritative).
        # Layout: <project>/<basename>/output/<basename>-postprocess.json
        # Manifest at: <project>/.videocraft/manifests/<basename>.json
        video_from_manifest, srt_from_manifest = self._resolve_from_manifest(pack_path)

        if not self._video_var.get() and video_from_manifest:
            self._video_var.set(video_from_manifest)
        if not self._srt_var.get() and srt_from_manifest:
            self._srt_var.set(srt_from_manifest)

        # Heuristic fallback (for packs not produced by project workbench)
        if not self._video_var.get():
            self._fallback_find_video(pack_path)
        if not self._srt_var.get():
            self._fallback_find_srt(pack_path)

        # Probe video for duration / resolution
        self._video_path = self._video_var.get().strip()
        self._srt_path = self._srt_var.get().strip()
        if self._video_path and os.path.isfile(self._video_path):
            self._video_duration = cliplib.probe_duration(self._video_path)
            self._video_w, self._video_h = cliplib.probe_resolution(self._video_path)
        # Build chapters
        self._chapters = cliplib.list_chapters(self._pack, self._video_duration)
        # Load cues for snapping
        if self._srt_path and os.path.isfile(self._srt_path):
            try:
                self._cues = cliplib.load_cues(self._srt_path)
            except Exception:
                self._cues = []

        self._refresh_chapter_tree()
        self._refresh_peaks_chapter_combo()
        self._set_status(_tr("tool.clip.status_loaded").format(
            n=len(self._chapters)))

    def _resolve_from_manifest(self, pack_path: str
                                ) -> tuple[str | None, str | None]:
        """Walk up from <project>/<basename>/output/<basename>-postprocess.json
        to <project>/.videocraft/manifests/<basename>.json, then read step
        outputs to find canonical video + best SRT."""
        try:
            output_dir = os.path.dirname(pack_path)         # <project>/<basename>/output
            unit_dir = os.path.dirname(output_dir)          # <project>/<basename>
            project_dir = os.path.dirname(unit_dir)         # <project>
            basename = os.path.basename(unit_dir)
            manifest_path = os.path.join(
                project_dir, ".videocraft", "manifests", f"{basename}.json")
            if not os.path.isfile(manifest_path):
                return (None, None)
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            return (None, None)

        def _abs(p: str) -> str:
            return p if os.path.isabs(p) else os.path.join(project_dir, p)

        video: str | None = None
        srt: str | None = None

        # Video: prefer step2 canonical, fall back to step1 raw
        for sk in ("step2_asr", "step1_download"):
            step = manifest.get(sk) or {}
            for out in (step.get("output") or []):
                cand = _abs(str(out))
                if cand.lower().endswith((".mp4", ".mkv", ".mov", ".webm")) \
                        and os.path.isfile(cand):
                    video = cand
                    break
            if video:
                break

        # SRT: prefer step3 translated, fall back to step2 ASR, then step1 manual
        for sk in ("step3_translate", "step2_asr"):
            step = manifest.get(sk) or {}
            for out in (step.get("output") or []):
                cand = _abs(str(out))
                if cand.lower().endswith(".srt") and os.path.isfile(cand):
                    srt = cand
                    break
            if srt:
                break
        if srt is None:
            step1 = manifest.get("step1_download") or {}
            for sub in (step1.get("subtitles") or []):
                if isinstance(sub, dict) and sub.get("path"):
                    cand = _abs(str(sub["path"]))
                    if os.path.isfile(cand):
                        srt = cand
                        break

        return (video, srt)

    def _fallback_find_video(self, pack_path: str) -> None:
        """Heuristic for non-manifest packs: drop -postprocess.json, try
        common video extensions in same dir or parent dir."""
        base = pack_path
        for suffix in ("-postprocess.json", ".json"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        for ext in (".mp4", ".mkv", ".mov", ".webm"):
            cand = base + ext
            if os.path.exists(cand):
                self._video_var.set(cand)
                return
        parent = os.path.dirname(os.path.dirname(pack_path))
        stem = os.path.basename(parent)
        for ext in (".mp4", ".mkv", ".mov", ".webm"):
            cand = os.path.join(parent, f"{stem}{ext}")
            if os.path.exists(cand):
                self._video_var.set(cand)
                return

    def _fallback_find_srt(self, pack_path: str) -> None:
        """Heuristic for non-manifest packs: any .srt in pack dir or
        parent's subtitles/ subdir."""
        for d in (os.path.dirname(pack_path),
                  os.path.join(os.path.dirname(os.path.dirname(pack_path)),
                                "subtitles")):
            if not os.path.isdir(d):
                continue
            for fname in sorted(os.listdir(d)):
                if fname.lower().endswith(".srt"):
                    self._srt_var.set(os.path.join(d, fname))
                    return

    def _refresh_chapter_tree(self) -> None:
        for iid in self._chap_tree.get_children():
            self._chap_tree.delete(iid)
        for ch in self._chapters:
            dur = max(0, int(ch["end_sec"] - ch["start_sec"]))
            mins, secs = divmod(dur, 60)
            self._chap_tree.insert(
                "", "end",
                values=(ch["idx"] + 1,
                        ch["time_str"],
                        f"{mins:d}:{secs:02d}",
                        ch["title"],
                        (ch["refined"] or "")[:120]))

    # ── Tab 2: peaks ──────────────────────────────────────────────────────

    def _build_tab_peaks(self) -> None:
        f = self._tab_peaks

        left = ttk.Frame(f)
        left.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        right = ttk.Frame(f)
        right.pack(side="right", fill="both", expand=True, padx=6, pady=6)

        # Add-clip controls (top of left)
        add_box = ttk.LabelFrame(left, text=_tr("tool.clip.section_add_clip"))
        add_box.pack(fill="x", pady=(0, 6))

        ttk.Label(add_box, text=_tr("tool.clip.label_chapter")).grid(
            row=0, column=0, sticky="e", padx=4, pady=3)
        self._peaks_chapter_var = tk.StringVar()
        self._peaks_chapter_combo = ttk.Combobox(
            add_box, textvariable=self._peaks_chapter_var,
            state="readonly", width=50)
        self._peaks_chapter_combo.grid(row=0, column=1, columnspan=3,
                                       sticky="we", padx=4)
        self._peaks_chapter_combo.bind(
            "<<ComboboxSelected>>", self._on_peak_chapter_changed)

        # Chapter context label (range + length) — updates as chapter switches
        self._peaks_chapter_info = tk.StringVar(value="")
        tk.Label(add_box, textvariable=self._peaks_chapter_info,
                 fg="gray").grid(row=1, column=0, columnspan=4,
                                  sticky="w", padx=8, pady=(0, 4))

        # Two simple inputs: offset within chapter + clip duration (seconds)
        ttk.Label(add_box, text=_tr("tool.clip.field_offset")).grid(
            row=2, column=0, sticky="e", padx=4)
        self._peaks_offset_var = tk.IntVar(value=0)
        ttk.Spinbox(add_box, from_=0, to=99999, increment=5,
                     textvariable=self._peaks_offset_var, width=8).grid(
            row=2, column=1, sticky="w", padx=4)
        ttk.Label(add_box, text=_tr("tool.clip.field_duration_sec")).grid(
            row=2, column=2, sticky="e", padx=4)
        self._peaks_dur_var = tk.IntVar(value=45)
        ttk.Spinbox(add_box, from_=5, to=600, increment=5,
                     textvariable=self._peaks_dur_var, width=8).grid(
            row=2, column=3, sticky="w", padx=4)

        # Live "computed range" preview line
        self._peaks_preview = tk.StringVar(value="")
        tk.Label(add_box, textvariable=self._peaks_preview,
                 fg="#2563eb").grid(row=3, column=0, columnspan=4,
                                     sticky="w", padx=8, pady=(2, 0))
        for v in (self._peaks_offset_var, self._peaks_dur_var):
            v.trace_add("write", lambda *_a: self._refresh_peak_preview())

        btn_row = ttk.Frame(add_box)
        btn_row.grid(row=4, column=0, columnspan=4, sticky="we", pady=4)
        ttk.Button(btn_row, text=_tr("tool.clip.btn_snap"),
                   command=self._snap_peak_inputs).pack(side="left", padx=4)
        ttk.Button(btn_row, text=_tr("tool.clip.btn_add_clip"),
                   command=self._add_clip_from_inputs).pack(side="left", padx=4)
        ttk.Button(btn_row, text=_tr("tool.clip.btn_remove_clip"),
                   command=self._remove_selected_clip).pack(side="left", padx=4)

        # Clips list
        clips_box = ttk.LabelFrame(left, text=_tr("tool.clip.section_clips"))
        clips_box.pack(fill="both", expand=True)
        cols = ("id", "chapter", "start", "end", "duration")
        self._clips_tree = ttk.Treeview(
            clips_box, columns=cols, show="headings", selectmode="browse")
        self._clips_tree.heading("id",       text="#")
        self._clips_tree.heading("chapter",  text=_tr("tool.clip.col_chapter"))
        self._clips_tree.heading("start",    text=_tr("tool.clip.field_start"))
        self._clips_tree.heading("end",      text=_tr("tool.clip.field_end"))
        self._clips_tree.heading("duration", text=_tr("tool.clip.col_duration"))
        self._clips_tree.column("id",       width=40,  anchor="center")
        self._clips_tree.column("chapter",  width=180, anchor="w")
        self._clips_tree.column("start",    width=80,  anchor="center")
        self._clips_tree.column("end",      width=80,  anchor="center")
        self._clips_tree.column("duration", width=80,  anchor="center")
        self._clips_tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(clips_box, orient="vertical",
                           command=self._clips_tree.yview)
        self._clips_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._clips_tree.bind("<<TreeviewSelect>>", self._on_clip_selected)

        # Right: VLC preview (optional)
        prev_box = ttk.LabelFrame(right, text=_tr("tool.clip.section_preview"))
        prev_box.pack(fill="both", expand=True)
        self._vlc = VlcPlayerFrame(prev_box)
        self._vlc.pack(fill="both", expand=True)
        if not is_vlc_available():
            tk.Label(right, text=_tr("tool.clip.hint_no_vlc"),
                     fg="gray").pack(pady=4)

    def _refresh_peaks_chapter_combo(self) -> None:
        labels = [f"#{ch['idx']+1} [{ch['time_str']}] {ch['title']}"
                  for ch in self._chapters]
        self._peaks_chapter_combo["values"] = labels
        if labels and not self._peaks_chapter_var.get():
            self._peaks_chapter_combo.current(0)
        self._on_peak_chapter_changed()

    def _selected_chapter(self) -> dict | None:
        if not self._peaks_chapter_var.get() or not self._chapters:
            return None
        try:
            idx = self._peaks_chapter_combo.current()
            if 0 <= idx < len(self._chapters):
                return self._chapters[idx]
        except Exception:
            pass
        return None

    def _on_peak_chapter_changed(self, _event=None) -> None:
        ch = self._selected_chapter()
        if ch is None:
            self._peaks_chapter_info.set("")
            self._peaks_preview.set("")
            return
        ch_dur = max(0, int(ch["end_sec"] - ch["start_sec"]))
        m, s = divmod(ch_dur, 60)
        self._peaks_chapter_info.set(_tr("tool.clip.label_chapter_range").format(
            start=_seconds_to_str(ch["start_sec"]),
            end=_seconds_to_str(ch["end_sec"]),
            len=f"{m}:{s:02d}"))
        # Clamp default duration to chapter length
        if self._peaks_dur_var.get() > ch_dur > 5:
            self._peaks_dur_var.set(min(60, ch_dur))
        self._refresh_peak_preview()

    def _peak_absolute_range(self) -> tuple[float, float] | None:
        """Compute (start_sec, end_sec) absolute from chapter + offset + dur."""
        ch = self._selected_chapter()
        if ch is None:
            return None
        try:
            offset = max(0, int(self._peaks_offset_var.get()))
            dur = max(1, int(self._peaks_dur_var.get()))
        except (tk.TclError, ValueError):
            return None
        ch_start = float(ch["start_sec"])
        ch_end = float(ch["end_sec"])
        s = min(ch_start + offset, ch_end - 1)
        e = min(s + dur, ch_end)
        if e <= s:
            return None
        return (s, e)

    def _refresh_peak_preview(self) -> None:
        rng = self._peak_absolute_range()
        if rng is None:
            self._peaks_preview.set("")
            return
        s, e = rng
        self._peaks_preview.set(_tr("tool.clip.preview_range").format(
            start=_seconds_to_str(s), end=_seconds_to_str(e),
            dur=int(e - s)))

    def _snap_peak_inputs(self) -> None:
        if not self._cues:
            self._set_status(_tr("tool.clip.warn_no_srt_for_snap"))
            return
        rng = self._peak_absolute_range()
        if rng is None:
            self._set_status(_tr("tool.clip.warn_bad_range"))
            return
        s, e = rng
        s2, e2 = cliplib.snap_to_cue_boundaries(self._cues, s, e)
        ch = self._selected_chapter()
        if ch is not None:
            self._peaks_offset_var.set(max(0, int(s2 - ch["start_sec"])))
            self._peaks_dur_var.set(max(1, int(e2 - s2)))
        self._refresh_peak_preview()
        self._set_status(_tr("tool.clip.status_snapped"))

    def _add_clip_from_inputs(self) -> None:
        ch = self._selected_chapter()
        if ch is None:
            self._set_status(_tr("tool.clip.warn_pick_chapter"))
            return
        rng = self._peak_absolute_range()
        if rng is None:
            self._set_status(_tr("tool.clip.warn_bad_range"))
            return
        s, e = rng
        # Pull excerpt from cues if available
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
        self._refresh_clips_tree()
        self._refresh_package_cards()
        self._refresh_export_clip_combo()
        self._set_status(_tr("tool.clip.status_clip_added").format(
            id=clip.id))

    def _remove_selected_clip(self) -> None:
        sel = self._clips_tree.selection()
        if not sel:
            return
        iid = sel[0]
        try:
            cid = int(self._clips_tree.set(iid, "id"))
        except Exception:
            return
        self._clips = [c for c in self._clips if c.id != cid]
        self._refresh_clips_tree()
        self._refresh_package_cards()
        self._refresh_export_clip_combo()

    def _refresh_clips_tree(self) -> None:
        for iid in self._clips_tree.get_children():
            self._clips_tree.delete(iid)
        for c in self._clips:
            dur = c.duration
            mins, secs = divmod(int(dur), 60)
            self._clips_tree.insert(
                "", "end",
                values=(c.id,
                        f"#{c.chapter_idx+1} {c.chapter_title}"[:40],
                        _seconds_to_str(c.start_sec),
                        _seconds_to_str(c.end_sec),
                        f"{mins:d}:{secs:02d}"))

    def _on_clip_selected(self, _event=None) -> None:
        sel = self._clips_tree.selection()
        if not sel or not self._video_path:
            return
        try:
            cid = int(self._clips_tree.set(sel[0], "id"))
        except Exception:
            return
        clip = next((c for c in self._clips if c.id == cid), None)
        if clip is None:
            return
        if self._vlc.is_available():
            self._vlc.load(self._video_path)
            # Seek shortly after load — VLC needs a tick to set duration
            self._vlc.master.after(500, lambda: self._vlc.seek(clip.start_sec))

    # ── Tab 3: package ────────────────────────────────────────────────────

    def _build_tab_package(self) -> None:
        f = self._tab_package
        # Scrollable cards
        canvas_holder = tk.Frame(f)
        canvas_holder.pack(fill="both", expand=True, padx=6, pady=6)
        self._pkg_canvas = tk.Canvas(canvas_holder, highlightthickness=0)
        self._pkg_scroll = ttk.Scrollbar(canvas_holder, orient="vertical",
                                         command=self._pkg_canvas.yview)
        self._pkg_inner = ttk.Frame(self._pkg_canvas)
        self._pkg_inner.bind(
            "<Configure>",
            lambda e: self._pkg_canvas.configure(
                scrollregion=self._pkg_canvas.bbox("all")))
        self._pkg_canvas.create_window((0, 0), window=self._pkg_inner,
                                        anchor="nw")
        self._pkg_canvas.configure(yscrollcommand=self._pkg_scroll.set)
        self._pkg_canvas.pack(side="left", fill="both", expand=True)
        self._pkg_scroll.pack(side="right", fill="y")

        tk.Label(f, text=_tr("tool.clip.hint_package"),
                 fg="gray").pack(padx=8, pady=4, anchor="w")

    def _refresh_package_cards(self) -> None:
        for child in self._pkg_inner.winfo_children():
            child.destroy()
        for clip in self._clips:
            self._build_package_card(clip)

    def _build_package_card(self, clip: ClipDraft) -> None:
        title = (f"#{clip.id} · [{_seconds_to_str(clip.start_sec)}–"
                 f"{_seconds_to_str(clip.end_sec)}] {clip.chapter_title}")
        card = ttk.LabelFrame(self._pkg_inner, text=title)
        card.pack(fill="x", padx=4, pady=4)

        # Excerpt (read-only)
        if clip.original_excerpt:
            tk.Label(card, text=clip.original_excerpt[:200],
                     fg="gray", wraplength=900,
                     justify="left").grid(row=0, column=0, columnspan=2,
                                          sticky="w", padx=6, pady=(4, 6))

        # Hook
        ttk.Label(card, text=_tr("tool.clip.field_hook")).grid(
            row=1, column=0, sticky="e", padx=4, pady=2)
        hook_var = tk.StringVar(value=clip.hook)
        hook_entry = ttk.Entry(card, textvariable=hook_var, width=80)
        hook_entry.grid(row=1, column=1, sticky="we", padx=4, pady=2)
        hook_var.trace_add("write",
                           lambda *_a, c=clip, v=hook_var: setattr(c, "hook", v.get()))

        # Outro
        ttk.Label(card, text=_tr("tool.clip.field_outro")).grid(
            row=2, column=0, sticky="e", padx=4, pady=2)
        outro_var = tk.StringVar(value=clip.outro)
        outro_entry = ttk.Entry(card, textvariable=outro_var, width=80)
        outro_entry.grid(row=2, column=1, sticky="we", padx=4, pady=2)
        outro_var.trace_add("write",
                            lambda *_a, c=clip, v=outro_var: setattr(c, "outro", v.get()))

        # Title
        ttk.Label(card, text=_tr("tool.clip.field_clip_title")).grid(
            row=3, column=0, sticky="e", padx=4, pady=2)
        title_var = tk.StringVar(value=clip.title)
        ttk.Entry(card, textvariable=title_var, width=80).grid(
            row=3, column=1, sticky="we", padx=4, pady=2)
        title_var.trace_add("write",
                            lambda *_a, c=clip, v=title_var: setattr(c, "title", v.get()))

        # Hashtags (comma-separated)
        ttk.Label(card, text=_tr("tool.clip.field_hashtags")).grid(
            row=4, column=0, sticky="e", padx=4, pady=2)
        tags_var = tk.StringVar(value=" ".join(clip.hashtags))
        ttk.Entry(card, textvariable=tags_var, width=80).grid(
            row=4, column=1, sticky="we", padx=4, pady=2)

        def _save_tags(*_a, c=clip, v=tags_var):
            c.hashtags = [t.strip() for t in v.get().split() if t.strip()]
        tags_var.trace_add("write", _save_tags)

        card.columnconfigure(1, weight=1)

    # ── Tab 4: crop & export ──────────────────────────────────────────────

    def _build_tab_export(self) -> None:
        f = self._tab_export

        # Top: clip selector + crop mode
        top = ttk.Frame(f)
        top.pack(fill="x", padx=6, pady=6)

        ttk.Label(top, text=_tr("tool.clip.label_clip")).pack(side="left", padx=4)
        self._export_clip_var = tk.StringVar()
        self._export_clip_combo = ttk.Combobox(top, textvariable=self._export_clip_var,
                                               state="readonly", width=50)
        self._export_clip_combo.pack(side="left", padx=4)
        self._export_clip_combo.bind("<<ComboboxSelected>>",
                                      self._on_export_clip_picked)

        self._crop_mode_var = tk.StringVar(value="center")
        ttk.Label(top, text=_tr("tool.clip.crop_mode")).pack(side="left", padx=(20, 4))
        ttk.Radiobutton(top, text=_tr("tool.clip.crop_center"),
                        variable=self._crop_mode_var, value="center",
                        command=self._on_crop_mode_changed).pack(side="left", padx=2)
        ttk.Radiobutton(top, text=_tr("tool.clip.crop_manual"),
                        variable=self._crop_mode_var, value="manual",
                        command=self._on_crop_mode_changed).pack(side="left", padx=2)

        ttk.Button(top, text=_tr("tool.clip.btn_apply_to_all"),
                   command=self._apply_crop_to_all).pack(side="left", padx=12)

        # Center: crop overlay
        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True, padx=6, pady=6)
        self._crop_overlay = CropOverlay(
            mid, on_change=self._on_crop_changed)
        self._crop_overlay.pack(fill="both", expand=True)

        # Bottom: output dir + export
        bot = ttk.Frame(f)
        bot.pack(fill="x", padx=6, pady=6)
        ttk.Label(bot, text=_tr("tool.clip.label_output_dir")).pack(side="left", padx=4)
        self._out_dir_var = tk.StringVar()
        ttk.Entry(bot, textvariable=self._out_dir_var, width=50).pack(side="left", padx=4)
        ttk.Button(bot, text=_tr("tool.clip.btn_browse"),
                   command=self._browse_out_dir).pack(side="left", padx=2)
        self._export_btn = ttk.Button(bot, text=_tr("tool.clip.btn_export_all"),
                                       command=self._on_export_clicked)
        self._export_btn.pack(side="right", padx=4)

        self._export_progress = ttk.Progressbar(f, mode="determinate")
        self._export_progress.pack(fill="x", padx=6, pady=4)

    def _refresh_export_clip_combo(self) -> None:
        labels = [f"#{c.id} [{_seconds_to_str(c.start_sec)}–"
                  f"{_seconds_to_str(c.end_sec)}] {c.title or c.chapter_title}"
                  for c in self._clips]
        self._export_clip_combo["values"] = labels
        if labels:
            self._export_clip_combo.current(0)
            self._on_export_clip_picked()

    def _on_export_clip_picked(self, _event=None) -> None:
        idx = self._export_clip_combo.current()
        if not (0 <= idx < len(self._clips)):
            return
        clip = self._clips[idx]
        if not self._video_path or self._video_w == 0:
            return
        # Extract a representative keyframe (middle of the clip)
        if not _PIL_OK:
            self._set_status(_tr("tool.clip.warn_no_pil"))
            return
        midpoint = (clip.start_sec + clip.end_sec) / 2.0
        try:
            import tempfile
            tmp_jpg = os.path.join(tempfile.gettempdir(),
                                   f"clip-keyframe-{clip.id}.jpg")
            cliplib.extract_keyframe(self._video_path, midpoint, tmp_jpg)
            with Image.open(tmp_jpg) as im:
                im.load()
                self._crop_overlay.set_image(
                    im.copy(), self._video_w, self._video_h)
            os.unlink(tmp_jpg)
        except Exception as e:
            self._set_status(f"keyframe: {e}")
            return
        # Apply existing rect or center
        if clip.crop_rect:
            self._crop_overlay.set_rect(clip.crop_rect)
            self._crop_mode_var.set("manual")
        else:
            self._crop_overlay.reset_to_center()
            self._crop_mode_var.set("center")

    def _on_crop_mode_changed(self) -> None:
        idx = self._export_clip_combo.current()
        if not (0 <= idx < len(self._clips)):
            return
        clip = self._clips[idx]
        if self._crop_mode_var.get() == "center":
            self._crop_overlay.reset_to_center()
            clip.crop_rect = self._crop_overlay.get_rect()
        # manual mode just leaves the rect as-is, user drags it.

    def _on_crop_changed(self, rect: dict) -> None:
        idx = self._export_clip_combo.current()
        if not (0 <= idx < len(self._clips)):
            return
        clip = self._clips[idx]
        clip.crop_rect = rect
        if self._crop_mode_var.get() != "manual":
            self._crop_mode_var.set("manual")

    def _apply_crop_to_all(self) -> None:
        rect = self._crop_overlay.get_rect()
        for c in self._clips:
            c.crop_rect = dict(rect)
        self._set_status(_tr("tool.clip.status_crop_applied").format(
            n=len(self._clips)))

    def _browse_out_dir(self) -> None:
        d = filedialog.askdirectory(title=_tr("tool.clip.dialog_pick_out_dir"))
        if d:
            self._out_dir_var.set(d)

    def _default_out_dir(self) -> str:
        if self._out_dir_var.get().strip():
            return self._out_dir_var.get().strip()
        if self._pack_path:
            return os.path.join(os.path.dirname(self._pack_path), "clips")
        return os.path.join(os.path.dirname(self._video_path) or ".", "clips")

    # ── Export worker ─────────────────────────────────────────────────────

    def _on_export_clicked(self) -> None:
        if not self._clips:
            self._set_status(_tr("tool.clip.warn_no_clips"))
            return
        if not self._video_path or not os.path.isfile(self._video_path):
            self._set_status(_tr("tool.clip.warn_no_video"))
            return
        if self._export_thread and self._export_thread.is_alive():
            # Treat second click as cancel.
            self._export_cancel_flag["v"] = True
            self._export_btn.config(state="disabled",
                                    text=_tr("tool.clip.btn_cancelling"))
            return

        out_dir = self._default_out_dir()
        os.makedirs(out_dir, exist_ok=True)
        self._out_dir_var.set(out_dir)

        # Reset cancel flag
        self._export_cancel_flag = {"v": False}
        self._export_btn.config(text=_tr("tool.clip.btn_cancel"))
        self._export_progress["value"] = 0
        self.set_busy()

        self._export_thread = threading.Thread(
            target=self._export_worker,
            args=(out_dir,), daemon=True)
        self._export_thread.start()

    def _export_worker(self, out_dir: str) -> None:
        from i18n import tr
        total = len([c for c in self._clips if c.status != "skipped"])

        def cancel_check() -> bool:
            return bool(self._export_cancel_flag.get("v"))

        def on_step(i: int, total: int, status: str, pct: int) -> None:
            self.master.after(0, self._set_status,
                              tr("tool.clip.status_exporting").format(
                                  n=i, total=total, pct=pct))
            self.master.after(0, lambda: self._export_progress.configure(
                value=int((i - 1 + pct / 100.0) / max(1, total) * 100)))

        try:
            paths = cliplib.export_all(
                self._video_path, self._clips, out_dir,
                source_srt=self._srt_path or None,
                on_progress=on_step,
                cancel_check=cancel_check,
            )
            # Persist clips.json regardless of cancel
            basename = os.path.splitext(os.path.basename(self._video_path))[0]
            json_path = cliplib.write_clips_json(
                self._clips, self._video_path, basename, out_dir)
            if cancel_check():
                self.master.after(0, self._set_status,
                                  tr("tool.clip.status_cancelled"))
                self.set_warning(tr("tool.clip.status_cancelled"))
            else:
                self.master.after(0, self._set_status,
                                  tr("tool.clip.status_done").format(
                                      n=len(paths), json=json_path))
                self.set_done()
        except Exception as e:
            self.master.after(0, self._set_status, f"✗ {e}")
            self.set_error(str(e))
        finally:
            self.master.after(0, self._export_btn.config,
                              {"state": "normal",
                               "text": tr("tool.clip.btn_export_all")})
            self.master.after(0, lambda: self._export_progress.configure(value=0))

    # ── Helpers ───────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        try:
            self._status_var.set(msg)
        except Exception:
            pass

    def _on_tab_changed(self, _event=None) -> None:
        """Refresh whichever tab the user just switched to so it reflects
        clips added on other tabs."""
        try:
            tab = self._notebook.index(self._notebook.select())
        except Exception:
            return
        if tab == 2:        # package
            self._refresh_package_cards()
        elif tab == 3:      # export
            self._refresh_export_clip_combo()


# ── Standalone run ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = ClipWorkbenchApp(root)
    root.mainloop()
