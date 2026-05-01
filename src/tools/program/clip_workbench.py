"""Clip Script workbench — Phase A walking skeleton (manual flow).

4-tab wizard: Chapters → Peaks → Package → Crop & Export. Phase A has
no AI buttons; Phase B (separate commit) will add rank / find / package
buttons. Architecture follows docs/draft/program-script-clip.md.
"""

from __future__ import annotations

import json
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from tools.base import ToolBase
from core.ai.cancellation import CancellationToken
from core.ai.errors import AIError, Kind
from core.program import clip as cliplib
from core.program.clip import ClipDraft
from core.segment_model import format_timestamp, parse_timestamp
from ui.ai_error_dialog import show_ai_error
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
        # Project folder is the anchor: cuts live under
        # <project>/.videocraft/clips/<name>.json. Hub passes the folder of
        # the currently-opened project as initial_file (or None if none open).
        self._project_root: str | None = (
            initial_file if initial_file and os.path.isdir(initial_file)
            else None
        )
        self._cut_path: str | None = None       # path to current .json cut file
        self._cut_name: str = ""                # display name (== file stem)
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
        self._export_thread: threading.Thread | None = None
        self._export_cancel_flag: dict = {"v": False}
        self._suspend_autosave: bool = False    # set during bulk hydration
        # AI rank results: chapter_idx → {score, reason}; populated by Tab 1
        # AI button, consumed by _refresh_chapter_tree to fill score columns.
        self._ranks: dict[int, dict] = {}

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

        # Start in "no cut" mode — Tab 2/3/4 disabled until New / Open.
        self._refresh_cut_state()

    # ── Tab 1: setup + chapters ───────────────────────────────────────────

    def _build_tab_setup(self) -> None:
        f = self._tab_setup

        # ── Cut file management (top) ────────────────────────────────────
        cut_box = ttk.LabelFrame(f, text=_tr("tool.clip.section_cut"))
        cut_box.pack(fill="x", padx=6, pady=6)
        btn_row = ttk.Frame(cut_box)
        btn_row.pack(fill="x", padx=4, pady=4)
        ttk.Button(btn_row, text=_tr("tool.clip.btn_new_cut"),
                   command=self._on_new_cut).pack(side="left", padx=2)
        ttk.Button(btn_row, text=_tr("tool.clip.btn_open_cut"),
                   command=self._on_open_cut).pack(side="left", padx=2)
        ttk.Button(btn_row, text=_tr("tool.clip.btn_save_as_cut"),
                   command=self._on_save_as_cut).pack(side="left", padx=2)
        self._cut_status_var = tk.StringVar(value=_tr("tool.clip.cut_none"))
        tk.Label(cut_box, textvariable=self._cut_status_var,
                 fg="#2563eb", anchor="w").pack(fill="x", padx=8, pady=(0, 4))

        # ── Sources (manual) ─────────────────────────────────────────────
        top = ttk.LabelFrame(f, text=_tr("tool.clip.section_inputs"))
        top.pack(fill="x", padx=6, pady=6)

        # Pack JSON (optional in spirit, but Phase A still requires it)
        ttk.Label(top, text=_tr("tool.clip.label_pack")).grid(
            row=0, column=0, sticky="e", padx=4, pady=3)
        self._pack_var = tk.StringVar()
        self._pack_var.trace_add("write", self._on_source_path_changed)
        ttk.Entry(top, textvariable=self._pack_var, width=70).grid(
            row=0, column=1, sticky="we", padx=4)
        ttk.Button(top, text=_tr("tool.clip.btn_browse"),
                   command=self._browse_pack).grid(row=0, column=2, padx=4)

        # Video
        ttk.Label(top, text=_tr("tool.clip.label_video")).grid(
            row=1, column=0, sticky="e", padx=4, pady=3)
        self._video_var = tk.StringVar()
        self._video_var.trace_add("write", self._on_source_path_changed)
        ttk.Entry(top, textvariable=self._video_var, width=70).grid(
            row=1, column=1, sticky="we", padx=4)
        ttk.Button(top, text=_tr("tool.clip.btn_browse"),
                   command=self._browse_video).grid(row=1, column=2, padx=4)

        # SRT
        ttk.Label(top, text=_tr("tool.clip.label_srt")).grid(
            row=2, column=0, sticky="e", padx=4, pady=3)
        self._srt_var = tk.StringVar()
        self._srt_var.trace_add("write", self._on_source_path_changed)
        ttk.Entry(top, textvariable=self._srt_var, width=70).grid(
            row=2, column=1, sticky="we", padx=4)
        ttk.Button(top, text=_tr("tool.clip.btn_browse"),
                   command=self._browse_srt).grid(row=2, column=2, padx=4)

        ttk.Button(top, text=_tr("tool.clip.btn_load"),
                   command=self._on_load_clicked).grid(
            row=3, column=1, sticky="w", padx=4, pady=6)

        top.columnconfigure(1, weight=1)

        # Chapters table + AI rank button on top
        mid = ttk.LabelFrame(f, text=_tr("tool.clip.section_chapters"))
        mid.pack(fill="both", expand=True, padx=6, pady=6)

        rank_bar = ttk.Frame(mid)
        rank_bar.pack(fill="x", padx=4, pady=(2, 4))
        self._ai_rank_btn = self._make_ai_button(
            rank_bar,
            idle_text=_tr("tool.clip.btn_ai_rank"),
            worker=self._worker_rank_chapters,
            on_success=self._on_rank_done,
        )
        self._ai_rank_btn.pack(side="left")

        tree_holder = ttk.Frame(mid)
        tree_holder.pack(fill="both", expand=True)

        cols = ("idx", "time", "duration", "title", "refined", "score", "reason")
        self._chap_tree = ttk.Treeview(tree_holder, columns=cols, show="headings",
                                       selectmode="browse", height=14)
        self._chap_tree.heading("idx",     text="#")
        self._chap_tree.heading("time",    text=_tr("tool.clip.col_time"))
        self._chap_tree.heading("duration",text=_tr("tool.clip.col_duration"))
        self._chap_tree.heading("title",   text=_tr("tool.clip.col_title"))
        self._chap_tree.heading("refined", text=_tr("tool.clip.col_refined"))
        self._chap_tree.heading("score",   text=_tr("tool.clip.col_ai_score"))
        self._chap_tree.heading("reason",  text=_tr("tool.clip.col_ai_reason"))
        self._chap_tree.column("idx",     width=40,  anchor="center")
        self._chap_tree.column("time",    width=80,  anchor="center")
        self._chap_tree.column("duration",width=70,  anchor="center")
        self._chap_tree.column("title",   width=180, anchor="w")
        self._chap_tree.column("refined", width=320, anchor="w")
        self._chap_tree.column("score",   width=60,  anchor="center")
        self._chap_tree.column("reason",  width=260, anchor="w")
        sb = ttk.Scrollbar(tree_holder, orient="vertical", command=self._chap_tree.yview)
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
        """Load chapters from the user-picked pack file. Sources (video/SRT)
        are NOT auto-filled — user fills them manually. No manifest sniffing,
        no restore prompts; restore lives entirely in the cut-file model."""
        try:
            self._pack = cliplib.load_pack(pack_path)
        except Exception as e:
            messagebox.showerror(_tr("tool.clip.title"), str(e))
            return
        self._pack_path = pack_path
        if self._pack_var.get() != pack_path:
            self._pack_var.set(pack_path)

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
        self._autosave()

    # ── Cut file management ─────────────────────────────────────────────────

    def _has_cut(self) -> bool:
        return self._cut_path is not None

    def _refresh_cut_state(self) -> None:
        """Update title-bar status + enable/disable Tab 2/3/4 based on whether
        a cut is currently open."""
        has = self._has_cut()
        if has:
            self._cut_status_var.set(
                _tr("tool.clip.cut_open").format(
                    name=self._cut_name, path=self._cut_path))
        else:
            self._cut_status_var.set(_tr("tool.clip.cut_none"))
        # Disable tabs 2/3/4 (peaks / package / export) when no cut is loaded.
        for idx in (1, 2, 3):
            try:
                self._notebook.tab(idx, state=("normal" if has else "disabled"))
            except tk.TclError:
                pass

    def _default_cut_dir(self) -> str | None:
        """Canonical home: <project>/.videocraft/clips/.
        Returns None if no project is open in the Hub."""
        if not self._project_root:
            return None
        return os.path.join(self._project_root, ".videocraft", "clips")

    def _suggested_cut_filename(self) -> str:
        """Default filename for new cuts. Uses video basename if available,
        else falls back to project folder name."""
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
            initialvalue=default_name,
            parent=self.master,
        )
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
        # Reset state to empty — user fills sources next
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
            self._refresh_chapter_tree()
            self._refresh_peaks_chapter_combo()
            self._refresh_clips_tree()
            self._refresh_package_cards()
            self._refresh_export_clip_combo()
            # Force-clear out_dir so _refresh_out_dir picks up the new default
            self._out_dir_var.set("")
        finally:
            self._suspend_autosave = False
        self._refresh_out_dir()
        self._refresh_cut_state()
        self._autosave()    # write the empty cut so the file exists
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
        """Modal listbox of cuts. items = [(display_label, full_path)].
        Returns the chosen full_path, or None on cancel."""
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
        self._cut_name = cut["name"] or os.path.splitext(os.path.basename(path))[0]

        sources = cut["sources"] or {}
        self._suspend_autosave = True
        try:
            self._pack_var.set(sources.get("pack_path", ""))
            self._video_var.set(sources.get("video_path", ""))
            self._srt_var.set(sources.get("srt_path", ""))
            self._out_dir_var.set(cut.get("output_dir", "") or "")
            self._clips = cut["clips"]
            self._next_clip_id = max((c.id for c in self._clips), default=0) + 1
            # Eagerly load pack chapters + cues so chapters appear immediately.
            pack_path = sources.get("pack_path") or ""
            if pack_path and os.path.isfile(pack_path):
                self._load_pack_file(pack_path)
            else:
                # No pack — still need video probe for export.
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
            self._refresh_clips_tree()
            self._refresh_package_cards()
            self._refresh_export_clip_combo()
            # If the cut didn't carry an output_dir (legacy / blank), recompute
            if not self._out_dir_var.get().strip():
                self._out_dir_var.set("")    # ensure trace fires below
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
        default_dir = self._default_cut_dir() or os.path.dirname(self._cut_path or "")
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
        """Write the current state to the active cut file. No-op if no cut
        loaded or autosave is suspended (during bulk hydration)."""
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
            )
        except Exception as e:
            self._set_status(f"autosave failed: {e}")

    def _on_source_path_changed(self, *_a) -> None:
        """Trace callback for the three source path entries — persist."""
        self._autosave()

    def _refresh_chapter_tree(self) -> None:
        for iid in self._chap_tree.get_children():
            self._chap_tree.delete(iid)
        # Sort by AI score desc when ranks are available; otherwise time order.
        ordered = sorted(
            self._chapters,
            key=lambda c: -self._ranks.get(c["idx"], {}).get("score", -1),
        ) if self._ranks else list(self._chapters)
        for ch in ordered:
            dur = max(0, int(ch["end_sec"] - ch["start_sec"]))
            mins, secs = divmod(dur, 60)
            rank = self._ranks.get(ch["idx"]) or {}
            self._chap_tree.insert(
                "", "end",
                values=(ch["idx"] + 1,
                        ch["time_str"],
                        f"{mins:d}:{secs:02d}",
                        ch["title"],
                        (ch["refined"] or "")[:120],
                        rank.get("score", "") if rank else "",
                        rank.get("reason", "")[:60] if rank else ""))

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
        self._make_ai_button(
            btn_row,
            idle_text=_tr("tool.clip.btn_ai_peaks"),
            worker=self._worker_find_peaks,
            on_success=self._on_peaks_done,
        ).pack(side="left", padx=12)

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
        self._autosave()
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
        self._autosave()

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

    # ── AI helpers (Phase B) ──────────────────────────────────────────────

    def _make_ai_button(self, parent, *, idle_text: str,
                         worker: Callable, on_success: Callable):
        """Tri-state AI button. `worker(token)` runs in a daemon thread and
        returns a result; `on_success(result)` is invoked on the main thread.

        State machine:
          idle → click → start worker, swap to "Cancel" label
          running → click → token.cancel(), swap to "Cancelling…" disabled
          done/cancelled/failed → reset to idle
        """
        btn = ttk.Button(parent, text=idle_text)
        btn._token = None       # type: ignore[attr-defined]

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

    # ── Tab 1: rank chapters worker ──
    def _worker_rank_chapters(self, token):
        if not self._pack:
            raise RuntimeError(_tr("tool.clip.warn_no_pack_loaded"))
        return cliplib.rank_chapters(self._pack, cancel_token=token)

    def _on_rank_done(self, ranked: list[dict]) -> None:
        self._ranks = {int(r["idx"]): r for r in ranked}
        self._refresh_chapter_tree()
        self._set_status(_tr("tool.clip.status_rank_done").format(
            n=len(ranked)))

    # ── Tab 2: find peaks worker ──
    def _worker_find_peaks(self, token):
        ch = self._selected_chapter()
        if ch is None:
            raise RuntimeError(_tr("tool.clip.warn_pick_chapter"))
        if not self._pack:
            raise RuntimeError(_tr("tool.clip.warn_no_pack_loaded"))
        # paragraphs.txt path is sibling of pack file (subtitle.pack convention)
        paragraphs_path = self._pack_path.replace("-postprocess.json",
                                                    "-paragraphs.txt")
        if not os.path.isfile(paragraphs_path):
            raise RuntimeError(_tr("tool.clip.warn_no_paragraphs").format(
                path=paragraphs_path))
        return cliplib.find_peaks(
            self._pack, ch["idx"], paragraphs_path,
            video_duration=self._video_duration,
            cancel_token=token)

    def _on_peaks_done(self, peaks: list[dict]) -> None:
        ch = self._selected_chapter()
        if ch is None:
            return
        added = 0
        for p in peaks:
            s, e = p["start_sec"], p["end_sec"]
            # Snap to cue boundaries if cues are loaded
            if self._cues:
                s, e = cliplib.snap_to_cue_boundaries(self._cues, s, e)
            # Build excerpt from cues
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
            added += 1
        if added:
            self._refresh_clips_tree()
            self._refresh_package_cards()
            self._refresh_export_clip_combo()
            self._autosave()
        self._set_status(_tr("tool.clip.status_peaks_done").format(
            n=added, ch=ch["title"]))

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
        def _save_hook(*_a, c=clip, v=hook_var):
            setattr(c, "hook", v.get())
            self._autosave()
        hook_var.trace_add("write", _save_hook)

        # Outro
        ttk.Label(card, text=_tr("tool.clip.field_outro")).grid(
            row=2, column=0, sticky="e", padx=4, pady=2)
        outro_var = tk.StringVar(value=clip.outro)
        outro_entry = ttk.Entry(card, textvariable=outro_var, width=80)
        outro_entry.grid(row=2, column=1, sticky="we", padx=4, pady=2)
        def _save_outro(*_a, c=clip, v=outro_var):
            setattr(c, "outro", v.get())
            self._autosave()
        outro_var.trace_add("write", _save_outro)

        # Title
        ttk.Label(card, text=_tr("tool.clip.field_clip_title")).grid(
            row=3, column=0, sticky="e", padx=4, pady=2)
        title_var = tk.StringVar(value=clip.title)
        ttk.Entry(card, textvariable=title_var, width=80).grid(
            row=3, column=1, sticky="we", padx=4, pady=2)
        def _save_title(*_a, c=clip, v=title_var):
            setattr(c, "title", v.get())
            self._autosave()
        title_var.trace_add("write", _save_title)

        # Hashtags (comma-separated)
        ttk.Label(card, text=_tr("tool.clip.field_hashtags")).grid(
            row=4, column=0, sticky="e", padx=4, pady=2)
        tags_var = tk.StringVar(value=" ".join(clip.hashtags))
        ttk.Entry(card, textvariable=tags_var, width=80).grid(
            row=4, column=1, sticky="we", padx=4, pady=2)

        def _save_tags(*_a, c=clip, v=tags_var):
            c.hashtags = [t.strip() for t in v.get().split() if t.strip()]
            self._autosave()
        tags_var.trace_add("write", _save_tags)

        # Per-card AI [生成文案] button
        ai_btn_holder = ttk.Frame(card)
        ai_btn_holder.grid(row=5, column=1, sticky="w", padx=4, pady=(2, 6))

        # Closure capturing this clip + the four StringVars so we can write
        # back to the UI after AI returns
        def _on_pkg_done(result, hv=hook_var, ov=outro_var,
                          tv=title_var, gv=tags_var):
            hv.set(result.get("hook", ""))
            ov.set(result.get("outro", ""))
            tv.set(result.get("title", ""))
            gv.set(" ".join(result.get("hashtags", [])))
            self._set_status(_tr("tool.clip.status_pkg_done").format(id=clip.id))

        def _worker_pkg(token, c=clip):
            return cliplib.package_clip(c, self._pack or {},
                                          cancel_token=token)

        self._make_ai_button(
            ai_btn_holder,
            idle_text=_tr("tool.clip.btn_ai_package"),
            worker=_worker_pkg,
            on_success=_on_pkg_done,
        ).pack(side="left")

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

        ttk.Button(top, text=_tr("tool.clip.btn_reset_center"),
                   command=self._reset_crop_to_center).pack(side="left", padx=(20, 4))
        ttk.Button(top, text=_tr("tool.clip.btn_apply_to_all"),
                   command=self._apply_crop_to_all).pack(side="left", padx=4)

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
        self._out_dir_var.trace_add("write", lambda *_a: self._autosave())
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
        # Apply existing rect or center default. set_rect / reset_to_center
        # both fire _on_crop_changed via the overlay's _notify; that's fine
        # — it just persists the rect onto the clip again, no mode mucking.
        if clip.crop_rect:
            self._crop_overlay.set_rect(clip.crop_rect)
        else:
            self._crop_overlay.reset_to_center()

    def _reset_crop_to_center(self) -> None:
        """Snap the current clip's crop back to a centered 9:16 rect."""
        idx = self._export_clip_combo.current()
        if not (0 <= idx < len(self._clips)):
            return
        self._crop_overlay.reset_to_center()
        # _on_crop_changed will fire via _notify and persist the new rect.

    def _on_crop_changed(self, rect: dict) -> None:
        """Persist whatever rect the overlay currently shows (whether the
        user dragged or we set it programmatically)."""
        idx = self._export_clip_combo.current()
        if not (0 <= idx < len(self._clips)):
            return
        self._clips[idx].crop_rect = dict(rect)
        self._autosave()

    def _apply_crop_to_all(self) -> None:
        rect = self._crop_overlay.get_rect()
        for c in self._clips:
            c.crop_rect = dict(rect)
        self._autosave()
        self._set_status(_tr("tool.clip.status_crop_applied").format(
            n=len(self._clips)))

    def _browse_out_dir(self) -> None:
        d = filedialog.askdirectory(title=_tr("tool.clip.dialog_pick_out_dir"))
        if d:
            self._out_dir_var.set(d)

    def _default_out_dir(self) -> str:
        """Authoritative output dir: <project>/<cut_name>/output/.

        User-set value (if any) wins. Otherwise we always auto-compute from
        the project root + cut name so the user never needs to fiddle with
        Tab 4 paths."""
        if self._out_dir_var.get().strip():
            return self._out_dir_var.get().strip()
        if self._project_root and self._cut_name:
            return os.path.join(self._project_root,
                                f"clip_{self._cut_name}", "output")
        # Fallback for the (rare) case of no project — write next to cut file.
        if self._cut_path and self._cut_name:
            return os.path.join(os.path.dirname(self._cut_path),
                                 f"clip_{self._cut_name}", "output")
        return os.path.join(os.path.dirname(self._video_path) or ".", "clips")

    def _refresh_out_dir(self) -> None:
        """Auto-fill the Tab 4 output dir entry from the current default.
        Called after New / Open so the field reflects where files will land.
        Computes the default fresh (ignoring any existing user value)."""
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
            # The cut file is the source of truth and was already autosaved
            # during edits. Just refresh it once after export so output_path /
            # status fields stick.
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
