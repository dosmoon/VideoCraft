"""
Project Workbench — manifest editor + scheduler.

Acts as a visual editor over `<project>/.videocraft/manifests/<basename>.json`:
left panel lists manifests (with New / Delete), right panel renders one
StepCard per pipeline step with editable fields. Unknown fields are preserved
verbatim and shown read-only in each card's "raw" section so the workbench
never silently destroys hand-written data.

A3 decision: only the workbench writes to manifests. Tools opened from the
regular menu remain manifest-unaware.

M2 scope: Step 1 (download), Step 1.5 (segment select — single start/end),
Step 2 (ASR) are runnable end-to-end. Other steps are editor-only.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from tools.base import ToolBase
from i18n import tr
from project import Project
from core.asr import transcribe_audio
from core.translate import SUPPORTED_LANGUAGES, translate_srt_file
from core.video_ops import extract_clip


# Lemonfox upload limit (and a generally safe ASR upload size).
_ASR_MAX_BYTES = 100 * 1024 * 1024
# Bitrate ladder used when the prepared mp3 is still over the size limit.
_AUDIO_BITRATE_LADDER = ["128k", "64k", "32k", "16k"]


def _ffmpeg_to_mp3(src: str, dst: str, bitrate: str) -> None:
    """Re-encode any audio/video to a mp3 at the given bitrate (mono, 22kHz).
    Mono + 22k is more than enough for ASR and roughly halves the bitrate
    again on top of the nominal value."""
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-vn",
        "-ac", "1",
        "-ar", "22050",
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        dst,
    ]
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-500:]}")


def _prep_audio_for_asr(src: str, dst: str, on_status) -> str:
    """Produce an mp3 ≤ _ASR_MAX_BYTES suitable for ASR upload.

    Always re-encodes through ffmpeg (even mp3 input) — that way the size
    is predictable and we don't depend on whatever bitrate the source
    came at. Walks the bitrate ladder until the file fits."""
    last_err = None
    for br in _AUDIO_BITRATE_LADDER:
        on_status(f"prep audio @ {br}")
        try:
            _ffmpeg_to_mp3(src, dst, br)
        except Exception as e:
            last_err = e
            continue
        size = os.path.getsize(dst)
        on_status(f"audio @ {br} = {size // (1024*1024)} MB")
        if size <= _ASR_MAX_BYTES:
            return dst
    if last_err:
        raise last_err
    raise RuntimeError(
        f"Audio still over {_ASR_MAX_BYTES // (1024*1024)}MB at lowest "
        f"bitrate ({_AUDIO_BITRATE_LADDER[-1]}); split the source first")


# ── Styling ──────────────────────────────────────────────────────────────────
# All colors / fonts go through this dict so they can be tweaked centrally
# without hunting down literals scattered through widget builders.

S = {
    "canvas_bg":   "#f3f4f6",
    "card_bg":     "#ffffff",
    "card_border": "#e5e7eb",
    "label_fg":    "#6b7280",
    "value_fg":    "#111827",
    "raw_bg":      "#f9fafb",
    "raw_fg":      "#374151",
    "section_fg":  "#9ca3af",
    "dirty_fg":    "#d97706",
    "title_font":   ("Segoe UI", 11, "bold"),
    "label_font":   ("Segoe UI", 9),
    "value_font":   ("Segoe UI", 10),
    "section_font": ("Segoe UI", 8, "italic"),
    "mono_font":    ("Consolas", 9),
}


# ── Step config ──────────────────────────────────────────────────────────────

_STEPS: list[tuple[str, str]] = [
    ("step1_download",  "tool.project_workbench.step.download"),
    ("step1_5_select",  "tool.project_workbench.step.select"),
    ("step2_asr",       "tool.project_workbench.step.asr"),
    ("step3_translate", "tool.project_workbench.step.translate"),
    ("step4_burn",      "tool.project_workbench.step.burn"),
    ("step5_pack",      "tool.project_workbench.step.pack"),
    ("step6_split",     "tool.project_workbench.step.split"),
]

# Known fields (rendered with widgets). Anything else lands in raw section.
_KNOWN_FIELDS: dict[str, list[str]] = {
    "step1_download":  ["enabled", "status", "url", "range_enabled",
                        "start", "end", "output"],
    "step1_5_select":  ["enabled", "status", "source", "start", "end", "output"],
    "step2_asr":       ["enabled", "status", "language", "source", "output"],
    "step3_translate": ["enabled", "status", "source_lang", "targets",
                        "source_srt", "output"],
    "step4_burn":      ["enabled", "status"],
    "step5_pack":      ["enabled", "status"],
    "step6_split":     ["enabled", "status"],
}

# Field type per (step, field). Drives widget choice in _add_field.
_FIELD_TYPE: dict[tuple[str, str], str] = {
    ("step1_download", "url"):           "string",
    ("step1_download", "range_enabled"): "bool",
    ("step1_download", "start"):         "time",
    ("step1_download", "end"):           "time",
    ("step1_download", "output"):        "readonly_list",
    ("step1_5_select", "source"):        "filepath",
    ("step1_5_select", "start"):         "time",
    ("step1_5_select", "end"):           "time",
    ("step1_5_select", "output"):        "readonly_list",
    ("step2_asr", "language"):           "lang",
    ("step2_asr", "source"):             "filepath",
    ("step2_asr", "output"):             "readonly_list",
    ("step3_translate", "source_lang"):  "lang",
    ("step3_translate", "targets"):      "lang_one_list",
    ("step3_translate", "source_srt"):   "filepath",
    ("step3_translate", "output"):       "readonly_list",
}

_STATUS_VALUES = ["pending", "running", "done", "failed"]

# Steps that can be run from the workbench in M2.
_RUNNABLE_STEPS = {"step1_download", "step1_5_select", "step2_asr", "step3_translate"}

def _parse_hms(s: str) -> tuple[int, int, int]:
    """Parse 'HH:MM:SS' (or sloppy variants) → (h, m, s). Returns (0,0,0) on
    junk input — Spinbox callers will overwrite with the clamped value."""
    parts = (s or "").strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]), int(parts[1]), int(float(parts[2]))
        if len(parts) == 2:
            return 0, int(parts[0]), int(float(parts[1]))
        if len(parts) == 1 and parts[0]:
            sec = int(float(parts[0]))
            return sec // 3600, (sec % 3600) // 60, sec % 60
    except ValueError:
        pass
    return 0, 0, 0


_LANG_CHOICES: list[tuple[str, str]] = [
    (iso, f"{iso} — {names[0]}") for iso, names in SUPPORTED_LANGUAGES.items()
]
_LANG_DISPLAY_TO_ISO = {disp: iso for iso, disp in _LANG_CHOICES}
_LANG_ISO_TO_DISPLAY = {iso: disp for iso, disp in _LANG_CHOICES}


class ProjectWorkbenchApp(ToolBase):
    def __init__(self, master, initial_file: str | None = None):
        self.master = master
        master.title(tr("tool.project_workbench.title"))
        master.geometry("1100x720")

        self.project: Project | None = None
        self._buffer: dict | None = None
        self._current_basename: str | None = None
        self._dirty: bool = False
        self._busy: bool = False

        self._field_vars: list = []
        self._suppress_dirty: bool = False
        # Per-step Run buttons populated by _build_step_card.
        self._run_buttons: dict[str, tk.Button] = {}
        # Run-all chain queue. Non-empty means we're running multiple steps;
        # _finish_step pops the next one on success and aborts on failure.
        self._chain: list[str] = []

        self._build_ui()

        if initial_file and os.path.isdir(initial_file):
            self._load_project(initial_file)

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        m = self.master
        m.columnconfigure(0, weight=1)
        m.rowconfigure(1, weight=1)

        top = tk.Frame(m)
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        top.columnconfigure(1, weight=1)
        tk.Label(top, text=tr("tool.project_workbench.label_project")).grid(
            row=0, column=0, sticky="w")
        self._project_var = tk.StringVar(value=tr("tool.project_workbench.no_project"))
        tk.Label(top, textvariable=self._project_var, fg="#555", anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(6, 0))

        pane = tk.PanedWindow(m, orient="horizontal", sashrelief="raised")
        pane.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

        self._build_left_panel(pane)
        self._build_right_panel(pane)

        self._status_var = tk.StringVar(value="")
        # Mirror status into the prominent banner.
        self._status_var.trace_add(
            "write", lambda *_: self._banner_var.set(self._status_var.get()))
        tk.Label(m, textvariable=self._status_var, fg="#666", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=8, pady=(0, 4))

    def _build_left_panel(self, parent) -> None:
        left = tk.Frame(parent)
        parent.add(left, minsize=240)

        btn_bar = tk.Frame(left)
        btn_bar.pack(fill="x", padx=4, pady=(2, 4))
        tk.Button(btn_bar, text=tr("tool.project_workbench.new_manifest"),
                  command=self._on_new_manifest).pack(side="left")
        tk.Button(btn_bar, text=tr("tool.project_workbench.delete"),
                  command=self._on_delete_manifest).pack(side="left", padx=(4, 0))
        tk.Button(btn_bar, text=tr("tool.project_workbench.refresh"),
                  command=self._reload_manifest_list).pack(side="right")

        tree_frame = tk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        self._tree = ttk.Treeview(tree_frame, show="tree",
                                  yscrollcommand=vsb.set, selectmode="browse")
        vsb.config(command=self._tree.yview)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select_manifest)

    def _build_right_panel(self, parent) -> None:
        right = tk.Frame(parent)
        parent.add(right, minsize=620)

        tb = tk.Frame(right)
        tb.pack(fill="x", padx=8, pady=(4, 4))
        self._title_var = tk.StringVar(value=tr("tool.project_workbench.select_hint"))
        tk.Label(tb, textvariable=self._title_var, font=("Segoe UI", 12, "bold"),
                 anchor="w").pack(side="left", fill="x", expand=True)
        self._dirty_lbl = tk.Label(tb, text="", fg=S["dirty_fg"],
                                   font=("Segoe UI", 9, "bold"))
        self._dirty_lbl.pack(side="left", padx=(8, 0))
        self._save_btn = tk.Button(tb, text=tr("tool.project_workbench.save"),
                                   command=self._on_save, state="disabled")
        self._save_btn.pack(side="right", padx=(4, 0))
        self._reload_btn = tk.Button(tb, text=tr("tool.project_workbench.reload"),
                                     command=self._on_reload, state="disabled")
        self._reload_btn.pack(side="right")
        self._run_all_btn = tk.Button(tb, text=tr("tool.project_workbench.run_all"),
                                      command=self._on_run_all, state="disabled",
                                      bg="#2563eb", fg="white", activebackground="#1d4ed8",
                                      activeforeground="white", relief="flat", padx=10)
        self._run_all_btn.pack(side="right", padx=(0, 8))

        # Prominent status banner (above the scrollable cards).
        banner = tk.Frame(right, bg="#eff6ff", height=36)
        banner.pack(fill="x", padx=8, pady=(2, 4))
        banner.pack_propagate(False)
        self._banner_var = tk.StringVar(value="")
        self._banner_lbl = tk.Label(banner, textvariable=self._banner_var,
                                    bg="#eff6ff", fg="#1d4ed8",
                                    font=("Segoe UI", 10, "bold"),
                                    anchor="w", padx=10)
        self._banner_lbl.pack(fill="both", expand=True)

        scroll_wrap = tk.Frame(right, bd=1, relief="sunken")
        scroll_wrap.pack(fill="both", expand=True, padx=8, pady=4)
        canvas = tk.Canvas(scroll_wrap, highlightthickness=0, bg=S["canvas_bg"])
        vsb = ttk.Scrollbar(scroll_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._cards_canvas = canvas
        self._cards_frame = tk.Frame(canvas, bg=S["canvas_bg"])
        self._cards_window = canvas.create_window((0, 0), window=self._cards_frame,
                                                   anchor="nw")
        self._cards_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(self._cards_window, width=e.width)
        )
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

    # ── Project / manifest loading ───────────────────────────────────────────

    def _load_project(self, folder: str) -> None:
        try:
            self.project = Project.open(folder)
            self._project_var.set(self.project.folder)
            self._reload_manifest_list()
        except Exception as e:
            self.set_error(f"Open project failed: {e}")

    def _reload_manifest_list(self) -> None:
        if self.project is None:
            return
        prev = self._current_basename
        self._tree.delete(*self._tree.get_children())
        for basename in self.project.list_manifests():
            self._tree.insert("", "end", iid=basename, text=f"  {basename}")
        if prev and self._tree.exists(prev):
            self._tree.selection_set(prev)
        else:
            self._clear_right_panel()

    def _on_select_manifest(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        new_basename = sel[0]
        if new_basename == self._current_basename:
            return
        if self._dirty and self._current_basename is not None:
            choice = self._ask_save_discard_cancel()
            if choice is None:
                self._tree.selection_set(self._current_basename)
                return
            if choice is True and not self._save_buffer():
                self._tree.selection_set(self._current_basename)
                return
        self._load_manifest_into_buffer(new_basename)

    def _load_manifest_into_buffer(self, basename: str) -> None:
        assert self.project is not None
        data = self.project.load_manifest(basename)
        if data is None:
            self.set_error(f"Failed to load manifest: {basename}")
            return
        self._current_basename = basename
        self._buffer = data
        self._dirty = False
        self._update_dirty_indicator()
        self._title_var.set(f"basename: {basename}")
        self._render_step_cards()
        self._save_btn.config(state="normal")
        self._reload_btn.config(state="normal")

    def _clear_right_panel(self) -> None:
        self._current_basename = None
        self._buffer = None
        self._dirty = False
        self._update_dirty_indicator()
        self._title_var.set(tr("tool.project_workbench.select_hint"))
        self._clear_step_cards()
        self._save_btn.config(state="disabled")
        self._reload_btn.config(state="disabled")

    # ── Step card rendering ──────────────────────────────────────────────────

    def _clear_step_cards(self) -> None:
        for child in self._cards_frame.winfo_children():
            child.destroy()
        self._field_vars = []
        self._run_buttons = {}

    def _render_step_cards(self) -> None:
        self._clear_step_cards()
        if self._buffer is None:
            return
        self._suppress_dirty = True
        try:
            self._build_source_card()
            for step_key, label_key in _STEPS:
                self._build_step_card(step_key, label_key)
        finally:
            self._suppress_dirty = False
        # Refresh all run buttons after populating
        for sk in _RUNNABLE_STEPS:
            self._refresh_run_state(sk)
        self._refresh_run_all_state()
        self._cards_canvas.yview_moveto(0)

    def _build_source_card(self) -> None:
        """Top-level 'source' field: a local file path used as the chain
        starting input when step1_download is disabled. Steps fall back to
        the chain (most recent enabled+done step's output[0]) and finally to
        this top-level source when their own source field is empty."""
        assert self._buffer is not None
        card = tk.Frame(self._cards_frame, bg=S["card_bg"],
                        highlightbackground=S["card_border"],
                        highlightthickness=1)
        card.pack(fill="x", padx=10, pady=6)
        header = tk.Frame(card, bg=S["card_bg"])
        header.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(header, text=tr("tool.project_workbench.section.source"),
                 bg=S["card_bg"], fg=S["value_fg"], font=S["title_font"],
                 anchor="w").pack(side="left")
        tk.Frame(card, bg=S["card_border"], height=1).pack(fill="x", padx=10)
        body = tk.Frame(card, bg=S["card_bg"])
        body.pack(fill="x", padx=10, pady=(6, 8))
        body.columnconfigure(1, weight=1)

        # Top-level "source" — like _add_filepath_field but writes to buffer["source"]
        cur = str(self._buffer.get("source", ""))
        var = tk.StringVar(value=cur)
        self._label_cell(body, 0, tr("tool.project_workbench.field.source") + ":")
        wrap = tk.Frame(body, bg=S["card_bg"])
        wrap.grid(row=0, column=1, sticky="ew", pady=2)
        wrap.columnconfigure(0, weight=1)
        ent = tk.Entry(wrap, textvariable=var, font=S["value_font"])
        ent.grid(row=0, column=0, sticky="ew")
        def browse():
            initial = var.get() or (self.project.folder if self.project else "")
            if os.path.isfile(initial):
                initial = os.path.dirname(initial)
            path = filedialog.askopenfilename(initialdir=initial)
            if path:
                var.set(path)
        tk.Button(wrap, text=tr("tool.project_workbench.browse"),
                  command=browse).grid(row=0, column=1, padx=(4, 0))
        def on_write(*_):
            if self._suppress_dirty or self._buffer is None:
                return
            v = var.get()
            if v:
                self._buffer["source"] = v
            else:
                self._buffer.pop("source", None)
            self._mark_dirty()
            for sk in _RUNNABLE_STEPS:
                self._refresh_run_state(sk)
            self._refresh_run_all_state()
        var.trace_add("write", on_write)
        self._field_vars.append(var)

        tk.Label(body, text=tr("tool.project_workbench.source_hint"),
                 bg=S["card_bg"], fg=S["section_fg"],
                 font=S["section_font"], anchor="w", justify="left",
                 wraplength=700).grid(row=1, column=0, columnspan=2,
                                       sticky="w", pady=(4, 0))

    def _build_step_card(self, step_key: str, label_key: str) -> None:
        assert self._buffer is not None
        step = self._buffer.setdefault(step_key, {"enabled": False, "status": "pending"})

        # Outer card frame; running step gets a blue border for at-a-glance
        # progress visibility, done gets a subtle green tint.
        status = step.get("status", "pending")
        if status == "running":
            border, thickness = "#2563eb", 2
        elif status == "done":
            border, thickness = "#86efac", 1
        elif status == "failed":
            border, thickness = "#ef4444", 1
        else:
            border, thickness = S["card_border"], 1
        card = tk.Frame(self._cards_frame, bg=S["card_bg"],
                        highlightbackground=border,
                        highlightthickness=thickness)
        card.pack(fill="x", padx=10, pady=6)

        # Header bar: title + Run button
        header = tk.Frame(card, bg=S["card_bg"])
        header.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(header, text=tr(label_key), bg=S["card_bg"], fg=S["value_fg"],
                 font=S["title_font"], anchor="w").pack(side="left")
        if step_key in _RUNNABLE_STEPS:
            run_label_key = {
                "step1_download":  "tool.project_workbench.run_download",
                "step1_5_select":  "tool.project_workbench.run_select",
                "step2_asr":       "tool.project_workbench.run_asr",
                "step3_translate": "tool.project_workbench.run_translate",
            }[step_key]
            btn = tk.Button(header, text=tr(run_label_key),
                            command=lambda sk=step_key: self._on_run_step(sk))
            btn.pack(side="right")
            self._run_buttons[step_key] = btn

        # Subtle divider
        tk.Frame(card, bg=S["card_border"], height=1).pack(fill="x", padx=10)

        # Body
        body = tk.Frame(card, bg=S["card_bg"])
        body.pack(fill="x", padx=10, pady=(6, 8))
        body.columnconfigure(1, weight=1)

        row = [0]
        def next_row() -> int:
            r = row[0]; row[0] += 1; return r

        # Common fields
        self._add_bool_field(body, next_row(), step_key, "enabled",
                             tr("tool.project_workbench.field.enabled"))
        self._add_enum_field(body, next_row(), step_key, "status",
                             tr("tool.project_workbench.field.status"),
                             _STATUS_VALUES)

        # Per-step known fields
        known = _KNOWN_FIELDS.get(step_key, ["enabled", "status"])
        for fname in known:
            if fname in ("enabled", "status"):
                continue
            label = tr(f"tool.project_workbench.field.{fname}")
            self._add_field(body, next_row(), step_key, fname, label)

        # Raw section: any unknown keys
        leftover = {k: v for k, v in step.items() if k not in known}
        if leftover:
            self._add_raw_section(body, next_row(), leftover)

    # ── Field widgets ────────────────────────────────────────────────────────

    def _label_cell(self, parent, r: int, label: str) -> None:
        tk.Label(parent, text=label, bg=S["card_bg"], fg=S["label_fg"],
                 font=S["label_font"], anchor="e").grid(
            row=r, column=0, sticky="e", padx=(0, 8), pady=2)

    def _add_field(self, parent, r: int, step_key: str, fname: str,
                   label: str) -> None:
        ftype = _FIELD_TYPE.get((step_key, fname), "string")
        if ftype == "lang":
            self._add_lang_field(parent, r, step_key, fname, label)
        elif ftype == "filepath":
            self._add_filepath_field(parent, r, step_key, fname, label)
        elif ftype == "readonly_list":
            self._add_readonly_list_field(parent, r, step_key, fname, label)
        elif ftype == "bool":
            self._add_bool_field(parent, r, step_key, fname, label)
        elif ftype == "time":
            self._add_time_field(parent, r, step_key, fname, label)
        elif ftype == "csv_iso":
            self._add_csv_iso_field(parent, r, step_key, fname, label)
        elif ftype == "lang_one_list":
            self._add_lang_one_list_field(parent, r, step_key, fname, label)
        else:
            self._add_string_field(parent, r, step_key, fname, label)

    def _add_bool_field(self, parent, r: int, step_key: str, field: str,
                        label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        var = tk.BooleanVar(value=bool(step.get(field, False)))
        cb = tk.Checkbutton(parent, text=label, variable=var,
                            bg=S["card_bg"], fg=S["value_fg"],
                            activebackground=S["card_bg"],
                            font=S["value_font"], anchor="w")
        cb.grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_enum_field(self, parent, r: int, step_key: str, field: str,
                        label: str, choices: list[str]) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        cur = str(step.get(field, choices[0]))
        if cur not in choices:
            choices = [cur] + choices
        var = tk.StringVar(value=cur)
        self._label_cell(parent, r, f"{label}:")
        cb = ttk.Combobox(parent, textvariable=var, values=choices,
                          state="readonly", width=14, font=S["value_font"])
        cb.grid(row=r, column=1, sticky="w", pady=2)
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_lang_field(self, parent, r: int, step_key: str, field: str,
                        label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        cur_iso = step.get(field) or "auto"
        display = _LANG_ISO_TO_DISPLAY.get(cur_iso, cur_iso)
        var = tk.StringVar(value=display)
        self._label_cell(parent, r, f"{label}:")
        cb = ttk.Combobox(parent, textvariable=var,
                          values=[d for _, d in _LANG_CHOICES],
                          state="readonly", width=24, font=S["value_font"])
        cb.grid(row=r, column=1, sticky="w", pady=2)
        def on_write(*_):
            iso = _LANG_DISPLAY_TO_ISO.get(var.get(), var.get())
            self._on_field_change(step_key, field, iso)
        var.trace_add("write", on_write)
        self._field_vars.append(var)

    def _add_filepath_field(self, parent, r: int, step_key: str, field: str,
                            label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        var = tk.StringVar(value=str(step.get(field, "")))
        self._label_cell(parent, r, f"{label}:")
        wrap = tk.Frame(parent, bg=S["card_bg"])
        wrap.grid(row=r, column=1, sticky="ew", pady=2)
        wrap.columnconfigure(0, weight=1)
        ent = tk.Entry(wrap, textvariable=var, font=S["value_font"])
        ent.grid(row=0, column=0, sticky="ew")
        def browse():
            initial = var.get() or (self.project.folder if self.project else "")
            if os.path.isfile(initial):
                initial = os.path.dirname(initial)
            path = filedialog.askopenfilename(initialdir=initial)
            if path:
                var.set(path)
        tk.Button(wrap, text=tr("tool.project_workbench.browse"),
                  command=browse).grid(row=0, column=1, padx=(4, 0))
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_time_field(self, parent, r: int, step_key: str, field: str,
                        label: str) -> None:
        """Three Spinboxes (HH MM SS) → "HH:MM:SS" string in the buffer.
        tkinter has no time picker; spinboxes make valid input the only
        possibility, so the user never has to wonder about the format."""
        assert self._buffer is not None
        step = self._buffer[step_key]
        h, m, s = _parse_hms(str(step.get(field, "00:00:00")))
        h_var = tk.StringVar(value=f"{h:02d}")
        m_var = tk.StringVar(value=f"{m:02d}")
        s_var = tk.StringVar(value=f"{s:02d}")
        self._label_cell(parent, r, f"{label}:")
        wrap = tk.Frame(parent, bg=S["card_bg"])
        wrap.grid(row=r, column=1, sticky="w", pady=2)
        sb_kw = dict(width=3, font=S["mono_font"], justify="center", format="%02.0f")
        sh = tk.Spinbox(wrap, from_=0, to=23, textvariable=h_var, **sb_kw)
        sh.pack(side="left")
        tk.Label(wrap, text=":", bg=S["card_bg"], fg=S["value_fg"],
                 font=S["mono_font"]).pack(side="left")
        sm = tk.Spinbox(wrap, from_=0, to=59, textvariable=m_var, **sb_kw)
        sm.pack(side="left")
        tk.Label(wrap, text=":", bg=S["card_bg"], fg=S["value_fg"],
                 font=S["mono_font"]).pack(side="left")
        ss = tk.Spinbox(wrap, from_=0, to=59, textvariable=s_var, **sb_kw)
        ss.pack(side="left")
        tk.Label(wrap, text="  HH:MM:SS", bg=S["card_bg"], fg=S["section_fg"],
                 font=S["section_font"]).pack(side="left", padx=(6, 0))

        def update(*_):
            try:
                hv = max(0, min(23, int(h_var.get() or 0)))
                mv = max(0, min(59, int(m_var.get() or 0)))
                sv = max(0, min(59, int(s_var.get() or 0)))
            except ValueError:
                return
            value = f"{hv:02d}:{mv:02d}:{sv:02d}"
            self._on_field_change(step_key, field, value)
            if step_key in _RUNNABLE_STEPS:
                self._refresh_run_state(step_key)
        h_var.trace_add("write", update)
        m_var.trace_add("write", update)
        s_var.trace_add("write", update)
        self._field_vars.extend([h_var, m_var, s_var])

    def _add_lang_one_list_field(self, parent, r: int, step_key: str,
                                 field: str, label: str) -> None:
        """Single-language picker that stores the value as a list[str] of one
        ISO code (so the schema field stays list-shaped for forward compat
        with future multi-target support)."""
        assert self._buffer is not None
        step = self._buffer[step_key]
        cur = step.get(field, [])
        cur_iso = (cur[0] if isinstance(cur, list) and cur else
                   (cur if isinstance(cur, str) else "auto"))
        display = _LANG_ISO_TO_DISPLAY.get(cur_iso, cur_iso)
        var = tk.StringVar(value=display)
        self._label_cell(parent, r, f"{label}:")
        cb = ttk.Combobox(parent, textvariable=var,
                          values=[d for _, d in _LANG_CHOICES],
                          state="readonly", width=24, font=S["value_font"])
        cb.grid(row=r, column=1, sticky="w", pady=2)
        def on_write(*_):
            iso = _LANG_DISPLAY_TO_ISO.get(var.get(), var.get())
            self._on_field_change(step_key, field, [iso] if iso else [])
            if step_key in _RUNNABLE_STEPS:
                self._refresh_run_state(step_key)
        var.trace_add("write", on_write)
        self._field_vars.append(var)

    def _add_csv_iso_field(self, parent, r: int, step_key: str, field: str,
                           label: str) -> None:
        """List of ISO language codes shown as CSV in an Entry. Stored as a
        list[str] in the buffer. Empty entries are dropped."""
        assert self._buffer is not None
        step = self._buffer[step_key]
        cur = step.get(field, [])
        if isinstance(cur, str):
            cur_str = cur
        else:
            cur_str = ", ".join(str(x) for x in (cur or []))
        var = tk.StringVar(value=cur_str)
        self._label_cell(parent, r, f"{label}:")
        wrap = tk.Frame(parent, bg=S["card_bg"])
        wrap.grid(row=r, column=1, sticky="ew", pady=2)
        wrap.columnconfigure(0, weight=1)
        ent = tk.Entry(wrap, textvariable=var, font=S["value_font"])
        ent.grid(row=0, column=0, sticky="ew")
        tk.Label(wrap, text="  e.g.  zh, ja, fr",
                 bg=S["card_bg"], fg=S["section_fg"],
                 font=S["section_font"]).grid(row=0, column=1, padx=(6, 0))
        def on_write(*_):
            items = [tok.strip() for tok in var.get().split(",") if tok.strip()]
            self._on_field_change(step_key, field, items)
            if step_key in _RUNNABLE_STEPS:
                self._refresh_run_state(step_key)
        var.trace_add("write", on_write)
        self._field_vars.append(var)

    def _add_string_field(self, parent, r: int, step_key: str, field: str,
                          label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        var = tk.StringVar(value=str(step.get(field, "")))
        self._label_cell(parent, r, f"{label}:")
        ent = tk.Entry(parent, textvariable=var, font=S["value_font"])
        ent.grid(row=r, column=1, sticky="ew", pady=2)
        var.trace_add("write", lambda *_: self._on_field_change(step_key, field, var.get()))
        if step_key in _RUNNABLE_STEPS:
            var.trace_add("write", lambda *_: self._refresh_run_state(step_key))
        self._field_vars.append(var)

    def _add_readonly_list_field(self, parent, r: int, step_key: str, field: str,
                                 label: str) -> None:
        assert self._buffer is not None
        step = self._buffer[step_key]
        items = step.get(field, []) or []
        if not isinstance(items, list):
            items = [str(items)]
        self._label_cell(parent, r, f"{label}:")
        if not items:
            tk.Label(parent, text="—", bg=S["card_bg"], fg="#9ca3af",
                     font=S["value_font"], anchor="w").grid(
                row=r, column=1, sticky="w", pady=2)
            return
        text = tk.Text(parent, height=min(len(items), 4), bg=S["raw_bg"],
                       fg=S["raw_fg"], relief="flat", wrap="none",
                       font=S["mono_font"], borderwidth=0)
        for it in items:
            text.insert("end", f"{it}\n")
        text.configure(state="disabled")
        text.grid(row=r, column=1, sticky="ew", pady=2)

    def _add_raw_section(self, parent, r: int, leftover: dict) -> None:
        sep = tk.Frame(parent, bg=S["card_border"], height=1)
        sep.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        tk.Label(parent, text=tr("tool.project_workbench.raw_fields"),
                 bg=S["card_bg"], fg=S["section_fg"],
                 font=S["section_font"], anchor="w").grid(
            row=r + 1, column=0, columnspan=2, sticky="w")
        text_widget = tk.Text(parent, height=min(8, max(2, len(leftover) + 1)),
                              bg=S["raw_bg"], fg=S["raw_fg"],
                              relief="flat", wrap="none",
                              font=S["mono_font"], borderwidth=0)
        text_widget.insert("1.0", json.dumps(leftover, ensure_ascii=False, indent=2))
        text_widget.configure(state="disabled")
        text_widget.grid(row=r + 2, column=0, columnspan=2, sticky="ew", pady=(2, 0))

    # ── Buffer / dirty ───────────────────────────────────────────────────────

    def _on_field_change(self, step_key: str, field: str, value) -> None:
        if self._suppress_dirty or self._buffer is None:
            return
        step = self._buffer.setdefault(step_key, {})
        step[field] = value
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_dirty_indicator()

    def _update_dirty_indicator(self) -> None:
        self._dirty_lbl.config(text=(tr("tool.project_workbench.dirty") if self._dirty else ""))

    def _ask_save_discard_cancel(self) -> bool | None:
        return messagebox.askyesnocancel(
            tr("tool.project_workbench.confirm_unsaved_title"),
            tr("tool.project_workbench.confirm_unsaved_msg").format(
                name=self._current_basename or "?"),
        )

    # ── Save / Reload ────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        self._save_buffer()

    def _save_buffer(self) -> bool:
        if self.project is None or self._buffer is None or self._current_basename is None:
            return False
        try:
            self.project.save_manifest(self._current_basename, self._buffer)
            self._dirty = False
            self._update_dirty_indicator()
            self._status_var.set(tr("tool.project_workbench.saved").format(
                name=self._current_basename))
            return True
        except Exception as e:
            self.set_error(f"Save failed: {e}")
            return False

    def _on_reload(self) -> None:
        if self._current_basename is None:
            return
        if self._dirty:
            if not messagebox.askyesno(
                tr("tool.project_workbench.confirm_reload_title"),
                tr("tool.project_workbench.confirm_reload_msg"),
            ):
                return
        self._load_manifest_into_buffer(self._current_basename)

    # ── New / Delete ─────────────────────────────────────────────────────────

    def _on_new_manifest(self) -> None:
        if self.project is None:
            messagebox.showinfo("VideoCraft", tr("tool.project_workbench.no_project"))
            return
        if self._dirty:
            choice = self._ask_save_discard_cancel()
            if choice is None:
                return
            if choice is True and not self._save_buffer():
                return
        basename = simpledialog.askstring(
            tr("tool.project_workbench.new_manifest"),
            tr("tool.project_workbench.new_manifest_prompt"),
            parent=self.master,
        )
        if not basename:
            return
        basename = basename.strip()
        if not basename or any(c in basename for c in r'\/:*?"<>|'):
            messagebox.showerror("VideoCraft",
                                 tr("tool.project_workbench.invalid_basename"))
            return
        if self.project.manifest_exists(basename):
            messagebox.showerror("VideoCraft",
                                 tr("tool.project_workbench.basename_exists").format(
                                     name=basename))
            return
        try:
            self.project.save_manifest(basename, Project.default_manifest(basename))
        except Exception as e:
            self.set_error(f"Create failed: {e}")
            return
        self._reload_manifest_list()
        if self._tree.exists(basename):
            self._tree.selection_set(basename)

    def _on_delete_manifest(self) -> None:
        if self.project is None or self._current_basename is None:
            return
        basename = self._current_basename
        if not messagebox.askyesno(
            tr("tool.project_workbench.confirm_delete_title"),
            tr("tool.project_workbench.confirm_delete_msg").format(name=basename),
            default="no",
        ):
            return
        if not self.project.delete_manifest(basename):
            self.set_error(f"Delete failed: {basename}")
            return
        self._dirty = False
        self._current_basename = None
        self._buffer = None
        self._reload_manifest_list()
        self._clear_right_panel()
        self._status_var.set(tr("tool.project_workbench.deleted").format(name=basename))

    # ── Input resolution (auto-chain) ────────────────────────────────────────

    # Order of steps that produce media that downstream steps consume.
    _MEDIA_CHAIN = ["step1_download", "step1_5_select"]

    def _resolve_input(self, step_key: str) -> str | None:
        """Resolve the input file path for a runnable step.

        Resolution order:
          1. Explicit non-empty `source` on this step (manual override)
          2. Most recent prior step in _MEDIA_CHAIN that is enabled+done with
             output[0] populated
          3. Top-level manifest `source` (local file input)
          4. None — caller must surface an error
        """
        if self._buffer is None:
            return None
        # 1) self override
        own = str(self._buffer.get(step_key, {}).get("source", "")).strip()
        if own:
            return self._abspath(own)
        # 2) walk back through media chain (only steps strictly before this one)
        for sk in reversed(self._MEDIA_CHAIN):
            if sk == step_key:
                continue
            # Skip steps that come after step_key in the official _STEPS order.
            if self._step_index(sk) >= self._step_index(step_key):
                continue
            step = self._buffer.get(sk, {}) or {}
            if step.get("enabled") and step.get("status") == "done":
                outs = step.get("output", []) or []
                if outs:
                    return self._abspath(str(outs[0]))
        # 3) top-level source
        top = str(self._buffer.get("source", "")).strip()
        if top:
            return self._abspath(top)
        return None

    def _resolve_srt_input(self, step_key: str) -> str | None:
        """Find the SRT this step should consume.

        1. Explicit `source_srt` on this step (override)
        2. The .srt path inside step2_asr.output (when enabled+done)
        3. Top-level `source` if it points at a .srt file (lets users feed
           an existing SRT straight into translate without running ASR)
        4. None
        """
        if self._buffer is None:
            return None
        own = str(self._buffer.get(step_key, {}).get("source_srt", "")).strip()
        if own:
            return self._abspath(own)
        asr = self._buffer.get("step2_asr", {}) or {}
        if asr.get("enabled") and asr.get("status") == "done":
            for path in (asr.get("output", []) or []):
                if str(path).lower().endswith(".srt"):
                    return self._abspath(str(path))
        top = str(self._buffer.get("source", "")).strip()
        if top.lower().endswith(".srt"):
            return self._abspath(top)
        return None

    @staticmethod
    def _step_index(step_key: str) -> int:
        for i, (sk, _) in enumerate(_STEPS):
            if sk == step_key:
                return i
        return 999

    def _abspath(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        if self.project is None:
            return path
        return os.path.join(self.project.folder, path)

    # ── Step run dispatch ────────────────────────────────────────────────────

    def _refresh_run_all_state(self) -> None:
        if self._buffer is None or self._busy:
            self._run_all_btn.config(state="disabled")
            return
        # Enable if at least one runnable enabled step is pending or failed.
        pending = [sk for sk in _RUNNABLE_STEPS
                   if (self._buffer.get(sk, {}) or {}).get("enabled")
                   and (self._buffer.get(sk, {}) or {}).get("status") in ("pending", "failed")]
        self._run_all_btn.config(state=("normal" if pending else "disabled"))

    def _on_run_all(self) -> None:
        if (self.project is None or self._buffer is None
                or self._current_basename is None or self._busy):
            return
        if self._dirty:
            if not messagebox.askyesno(
                tr("tool.project_workbench.confirm_save_before_run_title"),
                tr("tool.project_workbench.confirm_save_before_run_msg"),
            ):
                return
            if not self._save_buffer():
                return
        # Build queue in step order
        queue: list[str] = []
        for sk, _ in _STEPS:
            if sk not in _RUNNABLE_STEPS:
                continue
            step = self._buffer.get(sk, {}) or {}
            if step.get("enabled") and step.get("status") in ("pending", "failed"):
                queue.append(sk)
        if not queue:
            return
        self._chain = queue
        self._run_chain_next()

    def _run_chain_next(self) -> None:
        """Pop the next step off the chain and run it."""
        if not self._chain:
            return
        step_key = self._chain.pop(0)
        self._on_run_step(step_key)

    def _refresh_run_state(self, step_key: str) -> None:
        btn = self._run_buttons.get(step_key)
        if btn is None:
            return
        if self._buffer is None or self._busy:
            btn.config(state="disabled")
            return
        step = self._buffer.get(step_key, {}) or {}
        if not bool(step.get("enabled")) or step.get("status") not in ("pending", "failed"):
            btn.config(state="disabled")
            return
        # Per-step prerequisite check
        ok = True
        if step_key == "step1_download":
            ok = bool(str(step.get("url", "")).strip())
            if step.get("range_enabled"):
                start = str(step.get("start", "00:00:00"))
                end = str(step.get("end", "00:00:00"))
                ok = ok and (start != end)
        elif step_key == "step1_5_select":
            # Source is auto-resolved via chain; only start/end and a
            # resolvable input are required.
            start = str(step.get("start", "00:00:00"))
            end = str(step.get("end", "00:00:00"))
            ok = (start != end) and (self._resolve_input(step_key) is not None)
        elif step_key == "step2_asr":
            ok = self._resolve_input(step_key) is not None
        elif step_key == "step3_translate":
            targets = step.get("targets", []) or []
            ok = (bool(targets)
                  and self._resolve_srt_input(step_key) is not None)
        btn.config(state=("normal" if ok else "disabled"))

    def _on_run_step(self, step_key: str) -> None:
        if (self.project is None or self._buffer is None
                or self._current_basename is None or self._busy):
            return
        if self._dirty:
            if not messagebox.askyesno(
                tr("tool.project_workbench.confirm_save_before_run_title"),
                tr("tool.project_workbench.confirm_save_before_run_msg"),
            ):
                return
            if not self._save_buffer():
                return

        basename = self._current_basename
        if step_key == "step1_download":
            self._run_download(basename)
        elif step_key == "step1_5_select":
            self._run_select(basename)
        elif step_key == "step2_asr":
            self._run_asr(basename)
        elif step_key == "step3_translate":
            self._run_translate(basename)

    def _begin_busy(self, step_key: str, basename: str, status_msg: str) -> dict:
        """Mark step running on disk, refresh UI, and return the manifest."""
        assert self.project is not None
        manifest = self.project.load_manifest(basename) or {}
        step = manifest.setdefault(step_key, {})
        step["status"] = "running"
        manifest[step_key] = step
        self.project.save_manifest(basename, manifest)
        self._buffer = manifest
        self._busy = True
        self.set_busy()
        self._status_var.set(status_msg)
        self._render_step_cards()
        return manifest

    def _finish_step(self, step_key: str, basename: str, status: str,
                     updates: dict, msg: str) -> None:
        self._busy = False
        if self.project is None:
            return
        manifest = self.project.load_manifest(basename) or {}
        step = manifest.setdefault(step_key, {})
        step["status"] = status
        for k, v in updates.items():
            if v is None:
                step.pop(k, None)
            else:
                step[k] = v
        manifest[step_key] = step
        self.project.save_manifest(basename, manifest)
        self._status_var.set(msg)
        if status == "done":
            self.set_done()
        elif status == "failed":
            self.set_error(msg)
            self._abort_chain()
        if self._current_basename == basename:
            self._buffer = manifest
            self._dirty = False
            self._update_dirty_indicator()
            self._render_step_cards()
        # Advance chain on success
        if status == "done" and self._chain:
            self.master.after(50, self._run_chain_next)

    def _abort_chain(self) -> None:
        if self._chain:
            self._chain = []
            self._status_var.set(tr("tool.project_workbench.chain_aborted"))

    # ── Step 1: Download ─────────────────────────────────────────────────────

    def _run_download(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        step = self._buffer["step1_download"]
        url = str(step.get("url", "")).strip()
        if not url:
            messagebox.showerror("Error", "step1_download.url is empty")
            return
        # When range_enabled, download to <basename>_raw.mp4 then ffmpeg-trim
        # to <basename>.mp4. The trimmed file is the canonical "source"
        # downstream steps reference. The raw is kept for re-trimming.
        range_enabled = bool(step.get("range_enabled"))
        start = str(step.get("start", "00:00:00")) if range_enabled else None
        end = str(step.get("end", "00:00:00")) if range_enabled else None
        if range_enabled and start == end:
            messagebox.showerror("Error", "start and end are equal — nothing to clip")
            return
        raw_basename = f"{basename}_raw" if range_enabled else basename
        out_template = os.path.join(self.project.folder, f"{raw_basename}.%(ext)s")
        self._begin_busy("step1_download", basename, f"Download running: {basename}")
        threading.Thread(
            target=self._download_worker,
            args=(basename, url, out_template, range_enabled, start, end),
            daemon=True,
        ).start()

    def _download_worker(self, basename: str, url: str, out_template: str,
                         range_enabled: bool, start: str | None,
                         end: str | None) -> None:
        try:
            import yt_dlp

            # progress_hook fires from yt-dlp's worker; marshal back to UI.
            def hook(d):
                if d.get("status") == "downloading":
                    pct = (d.get("_percent_str") or "?").strip()
                    speed = (d.get("_speed_str") or "").strip()
                    eta = (d.get("_eta_str") or "").strip()
                    msg = f"Download {pct} {speed} ETA {eta} — {basename}"
                    self.master.after(0, self._status_var.set, msg)
                elif d.get("status") == "finished":
                    self.master.after(0, self._status_var.set,
                                      f"Download merging… {basename}")

            opts = {
                "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "outtmpl": out_template,
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "retries": 5,
                "fragment_retries": 5,
                "progress_hooks": [hook],
            }
            self.master.after(0, self._status_var.set,
                              f"Download starting — {basename}")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                fpath = ydl.prepare_filename(info)
            mp4 = os.path.splitext(fpath)[0] + ".mp4"
            raw_path = mp4 if os.path.exists(mp4) else fpath

            if not range_enabled:
                outputs = [self._project_relpath(raw_path)]
            else:
                # Trim full download into the canonical <basename>.mp4
                assert self.project is not None
                trimmed = os.path.join(self.project.folder, f"{basename}.mp4")
                self.master.after(0, self._status_var.set,
                                  f"Download [trim] {basename}")
                extract_clip(raw_path, start, end, output_path=trimmed)
                outputs = [self._project_relpath(trimmed),
                           self._project_relpath(raw_path)]

            self.master.after(0, self._finish_step, "step1_download", basename,
                              "done", {"output": outputs, "title": info.get("title")},
                              f"Download done: {basename}")
        except Exception as e:
            self.master.after(0, self._finish_step, "step1_download", basename,
                              "failed", {"error": str(e)},
                              f"Download failed: {basename}: {e}")

    # ── Step 1.5: Select segment (single start/end clip) ─────────────────────

    def _run_select(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        step = self._buffer["step1_5_select"]
        start = str(step.get("start", "")).strip()
        end = str(step.get("end", "")).strip()
        if not (start and end) or start == end:
            messagebox.showerror("Error", "step1_5_select needs valid start / end")
            return
        source = self._resolve_input("step1_5_select")
        if not source:
            messagebox.showerror("Error",
                "Cannot resolve input — set step1_download or top-level source")
            self._abort_chain()
            return
        if not os.path.exists(source):
            messagebox.showerror("Error", f"Source not found:\n{source}")
            self._abort_chain()
            return
        units_dir = os.path.join(self.project.folder, "units")
        os.makedirs(units_dir, exist_ok=True)
        ext = os.path.splitext(source)[1] or ".mp4"
        output = os.path.join(units_dir, f"{basename}{ext}")
        self._begin_busy("step1_5_select", basename, f"Clip running: {basename}")
        threading.Thread(
            target=self._select_worker,
            args=(basename, source, start, end, output),
            daemon=True,
        ).start()

    def _select_worker(self, basename: str, source: str, start: str, end: str,
                       output: str) -> None:
        try:
            extract_clip(source, start, end, output_path=output,
                         progress_callback=lambda m: self.master.after(
                             0, self._status_var.set, f"Clip [{m}] {basename}"))
            rel = self._project_relpath(output)
            self.master.after(0, self._finish_step, "step1_5_select", basename,
                              "done", {"output": [rel]},
                              f"Clip done: {basename}")
        except Exception as e:
            self.master.after(0, self._finish_step, "step1_5_select", basename,
                              "failed", {"error": str(e)},
                              f"Clip failed: {basename}: {e}")

    # ── Step 2: ASR ──────────────────────────────────────────────────────────

    def _run_asr(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        asr = self._buffer["step2_asr"]
        source = self._resolve_input("step2_asr")
        if not source:
            messagebox.showerror("Error",
                "Cannot resolve input for ASR — set step1_download, step1_5_select, or top-level source")
            self._abort_chain()
            return
        if not os.path.exists(source):
            messagebox.showerror("Error", f"Source not found:\n{source}")
            self._abort_chain()
            return
        lang_iso = asr.get("language") or None
        out_dir = os.path.join(self.project.folder, "subtitles")
        os.makedirs(out_dir, exist_ok=True)
        suffix = lang_iso or "auto"
        output_srt = os.path.join(out_dir, f"{basename}_{suffix}.srt")

        language_hint: str | None = None
        if lang_iso and lang_iso in SUPPORTED_LANGUAGES and lang_iso != "auto":
            language_hint = SUPPORTED_LANGUAGES[lang_iso][0]
        expected_iso = lang_iso if lang_iso != "auto" else None

        self._begin_busy("step2_asr", basename, f"ASR running: {basename}")
        threading.Thread(
            target=self._asr_worker,
            args=(basename, source, output_srt, expected_iso, language_hint),
            daemon=True,
        ).start()

    def _asr_worker(self, basename: str, source: str, output_srt: str,
                    expected_iso: str | None, language_hint: str | None) -> None:
        try:
            assert self.project is not None
            # Always normalize through ffmpeg → mp3 ≤100MB. Lemonfox's upload
            # cap is 100MB; even when the source is already an mp3, we don't
            # know its bitrate, so we re-encode for predictability.
            prep_path = os.path.join(self.project.folder, f"{basename}.mp3")
            on_status = lambda msg: self.master.after(
                0, self._status_var.set, f"ASR [{msg}] {basename}")
            audio_path = _prep_audio_for_asr(source, prep_path, on_status)

            result = transcribe_audio(
                audio_path, output_srt,
                expected_lang_iso=expected_iso, language=language_hint,
                on_event=lambda evt, **kw: self.master.after(
                    0, self._status_var.set, f"ASR [{evt}] {basename}"),
            )
            outputs = []
            for path in (result.get("srt_path"), result.get("json_path")):
                if path:
                    outputs.append(self._project_relpath(path))
            # Also record the prepped audio so user can see / reuse it.
            outputs.append(self._project_relpath(audio_path))
            updates = {"output": outputs, "error": None}
            detected = result.get("detected_lang_iso")
            if detected:
                updates["detected_language"] = detected
            self.master.after(0, self._finish_step, "step2_asr", basename,
                              "done", updates, f"ASR done: {basename}")
        except Exception as e:
            self.master.after(0, self._finish_step, "step2_asr", basename,
                              "failed", {"error": str(e)},
                              f"ASR failed: {basename}: {e}")

    # ── Step 3: Translate ────────────────────────────────────────────────────

    def _run_translate(self, basename: str) -> None:
        assert self.project is not None and self._buffer is not None
        step = self._buffer["step3_translate"]
        targets = step.get("targets", []) or []
        if not targets:
            messagebox.showerror("Error", "step3_translate.targets is empty")
            return
        srt_in = self._resolve_srt_input("step3_translate")
        if not srt_in:
            messagebox.showerror("Error",
                "Cannot resolve SRT — set step2_asr or step3_translate.source_srt")
            self._abort_chain()
            return
        if not os.path.exists(srt_in):
            messagebox.showerror("Error", f"SRT not found:\n{srt_in}")
            self._abort_chain()
            return
        # Source language: explicit > step2's detected/configured > "auto"
        source_lang = str(step.get("source_lang") or "").strip()
        if not source_lang:
            asr = self._buffer.get("step2_asr", {}) or {}
            source_lang = (asr.get("detected_language")
                           or asr.get("language")
                           or "auto")
        self._begin_busy("step3_translate", basename,
                         f"Translate running: {basename}")
        threading.Thread(
            target=self._translate_worker,
            args=(basename, srt_in, source_lang, list(targets)),
            daemon=True,
        ).start()

    def _translate_worker(self, basename: str, srt_in: str,
                          source_lang: str, targets: list[str]) -> None:
        try:
            outputs: list[str] = []
            for tgt in targets:
                self.master.after(
                    0, self._status_var.set,
                    f"Translate [{source_lang}→{tgt}] {basename}")
                progress_cb = lambda done, total, msg, t=tgt: self.master.after(
                    0, self._status_var.set,
                    f"Translate [{t}] {msg}")
                out = translate_srt_file(
                    srt_in,
                    source_lang=source_lang,
                    target_lang=tgt,
                    progress_cb=progress_cb,
                )
                # translate_srt_file names by language English name (e.g.
                # "Chinese.srt"); rename to match ASR convention
                # "<basename>_<iso>.srt" so the project's SRT files all
                # follow the same scheme.
                desired = os.path.join(os.path.dirname(out),
                                       f"{basename}_{tgt}.srt")
                if os.path.normpath(desired) != os.path.normpath(out):
                    if os.path.exists(desired):
                        os.remove(desired)
                    os.replace(out, desired)
                    out = desired
                outputs.append(self._project_relpath(out))
            self.master.after(0, self._finish_step, "step3_translate", basename,
                              "done", {"output": outputs, "error": None,
                                       "source_lang_used": source_lang},
                              f"Translate done: {basename}")
        except Exception as e:
            self.master.after(0, self._finish_step, "step3_translate", basename,
                              "failed", {"error": str(e)},
                              f"Translate failed: {basename}: {e}")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _project_relpath(self, path: str) -> str:
        if self.project is None:
            return path
        try:
            return os.path.relpath(path, self.project.folder).replace("\\", "/")
        except ValueError:
            return path
