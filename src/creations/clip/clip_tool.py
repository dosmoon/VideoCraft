"""Clip workbench — three-tab AI Clip composition workbench.

Tabs:
  Style   — global CompositionStyle design (preset, subtitle, watermark,
            hook/outro card, draggable global crop on source video).
  Clips   — per-clip candidate list + per-clip detail editor (preview with
            own crop, start/end nudge, hook/title/tags override, SRT cues).
  Export  — batch render + status table + per-row actions (play / open /
            rerender / delete) + sidecar JSON.

Data model lives in `derivatives/clip/<inst>/config.json`. See README of
docs/draft/composition-style.md for the schema.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import tkinter as tk
from dataclasses import asdict
from datetime import datetime, timezone
from tkinter import (
    colorchooser, filedialog, messagebox, simpledialog, ttk,
)
from typing import Optional

from materials.news_video import paths as _nv_paths

from tools.base import ToolBase
from core.composition import (
    CompositionRequest, CompositionStyle, render_composition,
    wrap_hook_outro,
)
from core.composition import presets as comp_presets
from core.composition.fonts import hook_outro_font_path
from core.composition.preview import CompositionPreview
from i18n import tr


# ── Timestamp helpers ──────────────────────────────────────────────────────

_TS_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d+))?$")


def _parse_ts(s: str) -> float:
    m = _TS_RE.match((s or "").strip())
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mn = int(m.group(2))
    sec = int(m.group(3))
    frac = m.group(4)
    base = h * 3600 + mn * 60 + sec
    if frac:
        base += int(frac[:3].ljust(3, "0")) / 1000.0
    return base


def _format_ts(seconds: float) -> str:
    """Seconds → HH:MM:SS.mmm string for Entry widgets."""
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _load_instance_config(instance_dir: str) -> dict:
    path = os.path.join(instance_dir, "config.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_instance_config(instance_dir: str, config: dict) -> None:
    os.makedirs(instance_dir, exist_ok=True)
    path = os.path.join(instance_dir, "config.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ── Workbench ──────────────────────────────────────────────────────────────

class ClipToolApp(ToolBase):

    _PREVIEW_DEBOUNCE_MS = 120

    def __init__(self, master: tk.Frame,
                 project=None, instance_name: Optional[str] = None) -> None:
        if project is None or instance_name is None:
            raise RuntimeError(
                "ClipToolApp requires project + instance_name (project-only tool)"
            )
        self.master = master
        self.project = project
        self.instance_name = instance_name
        self._tool_title = tr("clip_tool.tab_title", instance=instance_name)

        # Slice Q (ADR-0005): pick or recall the bound material instance.
        from creations import material_binding
        import os as _os
        config_path = _os.path.join(
            project.creation_instance_dir("clip", instance_name),
            "config.json")
        bound = material_binding.get_or_bind(master, project, config_path)
        if bound is None:
            raise RuntimeError("Clip: material binding cancelled.")
        self.material_type, self.material_instance_id = bound

        # ── Data state ────────────────────────────────────────────────────
        self._lang_var = tk.StringVar()
        self._candidate_vars: list[tk.BooleanVar] = []   # parallel to _candidate_meta
        self._candidate_meta: list[dict] = []
        self._candidate_rows: list[dict] = []            # widget refs per row
        self._hotclips_data: dict = {}

        # ── Composition state ─────────────────────────────────────────────
        self._project_store = comp_presets.load_project_store()
        self._hook_outro_store = comp_presets.load_hook_outro_store()
        last = comp_presets.get_last_used_project(self._project_store)
        self._current_style: CompositionStyle = (
            comp_presets.get_project_preset(self._project_store, last)
            or CompositionStyle()
        )
        self._preset_name_var = tk.StringVar(value=last)
        self._suspend_traces = False
        self._global_crop_rect: Optional[dict] = None    # None = center default
        self._clips_overrides: dict[int, dict] = {}      # idx -> override fields

        # ── UI handles, filled in build phase ─────────────────────────────
        self._style_preview: Optional[CompositionPreview] = None
        self._clip_preview: Optional[CompositionPreview] = None
        self._preview_job: Optional[str] = None
        self._detail_idx: Optional[int] = None
        # tab2 detail var holders
        self._detail_vars: dict = {}    # filled by _build_tab_clips
        self._detail_widgets: dict = {}

        # ── Render state ──────────────────────────────────────────────────
        self._render_thread: Optional[threading.Thread] = None
        self._cancel_flag = False
        self._render_status: dict[int, str] = {}    # candidate idx -> status
        self._current_render_idx: Optional[int] = None
        self._rendered: list[dict] = []

        self._build_ui()
        self._restore_persisted_state()
        self._reload_languages()
        self._populate_form_from_style()

    def destroy_hook(self):
        if self._style_preview is not None:
            self._style_preview.destroy()
            self._style_preview = None
        if self._clip_preview is not None:
            self._clip_preview.destroy()
            self._clip_preview = None

    # ── UI build ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = tk.Frame(self.master, bg="white")
        outer.pack(fill="both", expand=True)
        # Tab labels — bump font size globally; the default ttk style renders
        # them too small to be readable, especially on hi-DPI displays.
        style = ttk.Style(self.master)
        style.configure("TNotebook.Tab",
                        font=("Microsoft YaHei UI", 11),
                        padding=(14, 8))
        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True, padx=4, pady=4)
        self._tab_style = ttk.Frame(nb)
        self._tab_clips = ttk.Frame(nb)
        self._tab_export = ttk.Frame(nb)
        nb.add(self._tab_style, text=tr("clip_tool.tab_style"))
        nb.add(self._tab_clips, text=tr("clip_tool.tab_clips"))
        nb.add(self._tab_export, text=tr("clip_tool.tab_export"))
        self._notebook = nb

        self._build_tab_style()
        self._build_tab_clips()
        self._build_tab_export()

    # ── Tab 1: Style ─────────────────────────────────────────────────────

    def _build_tab_style(self) -> None:
        f = tk.Frame(self._tab_style, bg="white")
        f.pack(fill="both", expand=True)

        # Header: language picker + preset shortcut
        header = tk.Frame(f, bg="white")
        header.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(header, text=tr("clip_tool.lang_label"),
                 bg="white").pack(side="left")
        self._lang_combo = ttk.Combobox(
            header, textvariable=self._lang_var, values=[],
            state="readonly", width=14)
        self._lang_combo.pack(side="left", padx=(4, 12))
        self._lang_combo.bind("<<ComboboxSelected>>",
                              lambda _e: self._reload_candidates())

        tk.Label(header, text=tr("clip_tool.preset_label"),
                 bg="white").pack(side="left")
        self._preset_combo_quick = ttk.Combobox(
            header, textvariable=self._preset_name_var,
            values=comp_presets.list_project_presets(self._project_store),
            state="readonly", width=28)
        self._preset_combo_quick.pack(side="left", padx=(4, 4))
        self._preset_combo_quick.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_preset_applied())

        # Status (lang load status)
        self._status_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self._status_var,
                 bg="white", fg="#666").pack(side="left", padx=(12, 0))

        # Body: form left | preview right
        pw = ttk.PanedWindow(f, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        form_outer = ttk.Frame(pw)
        preview_outer = ttk.Frame(pw)
        pw.add(form_outer, weight=3)
        pw.add(preview_outer, weight=4)

        # ── Scrollable form ──
        canvas = tk.Canvas(form_outer, highlightthickness=0)
        sb = ttk.Scrollbar(form_outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(inner_id, width=e.width))
        self._build_style_form(inner)

        # ── Preview pane with global-crop controls ──
        crop_bar = tk.Frame(preview_outer, bg="white")
        crop_bar.pack(fill="x", padx=4, pady=(4, 2))
        tk.Label(crop_bar, text=tr("clip_tool.tab1_global_crop_label"),
                 bg="white").pack(side="left")
        ttk.Button(crop_bar, text=tr("clip_tool.btn_apply_crop_to_all"),
                   command=self._on_apply_crop_to_all).pack(side="right")

        self._style_preview = CompositionPreview(
            preview_outer,
            on_crop_changed=self._on_style_crop_changed,
            width=420, height=520)
        self._style_preview.widget.pack(fill="both", expand=True,
                                          padx=4, pady=(0, 4))

        # Bottom info note
        note = tk.Label(
            preview_outer, text=tr("clip_tool.tab1_note_per_clip_content"),
            bg="white", fg="#666", anchor="w", justify="left",
            wraplength=420)
        note.pack(fill="x", padx=4, pady=(0, 4))

        self._schedule_style_preview_refresh()

    def _build_style_form(self, parent: ttk.Frame) -> None:
        # Preset row (full controls)
        preset_row = ttk.LabelFrame(parent, text=tr("clip_tool.preset_section"))
        preset_row.pack(fill="x", padx=6, pady=(6, 4))
        self._preset_combo = ttk.Combobox(
            preset_row, textvariable=self._preset_name_var,
            values=comp_presets.list_project_presets(self._project_store),
            state="readonly", width=30)
        self._preset_combo.grid(row=0, column=0, columnspan=4,
                                 padx=4, pady=4, sticky="ew")
        ttk.Button(preset_row, text=tr("clip_tool.btn_apply"),
                   command=self._on_preset_applied).grid(
                       row=1, column=0, padx=2, pady=2)
        ttk.Button(preset_row, text=tr("clip_tool.btn_save_as"),
                   command=self._on_preset_save_as).grid(
                       row=1, column=1, padx=2, pady=2)
        ttk.Button(preset_row, text=tr("clip_tool.btn_overwrite"),
                   command=self._on_preset_overwrite).grid(
                       row=1, column=2, padx=2, pady=2)
        ttk.Button(preset_row, text=tr("clip_tool.btn_delete"),
                   command=self._on_preset_delete).grid(
                       row=1, column=3, padx=2, pady=2)
        for c in range(4):
            preset_row.columnconfigure(c, weight=1)

        # Aspect + encode
        ae = ttk.LabelFrame(parent, text=tr("clip_tool.section_output"))
        ae.pack(fill="x", padx=6, pady=4)
        self._aspect_var = tk.StringVar(value=self._current_style.output.aspect)
        row = ttk.Frame(ae); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.aspect")).pack(side="left")
        for val in ("9:16", "16:9", "1:1", "4:5"):
            ttk.Radiobutton(row, text=val, variable=self._aspect_var,
                            value=val).pack(side="left", padx=(4, 0))
        self._encode_preset_var = tk.StringVar(value=self._current_style.encode_preset)
        row = ttk.Frame(ae); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.encode_preset")).pack(side="left")
        ttk.Combobox(row, textvariable=self._encode_preset_var,
                     values=("ultrafast", "superfast", "veryfast",
                             "faster", "fast", "medium"),
                     state="readonly", width=12).pack(side="left", padx=(4, 0))

        # Subtitle
        sub = ttk.LabelFrame(parent, text=tr("clip_tool.section_subtitle"))
        sub.pack(fill="x", padx=6, pady=4)
        s = self._current_style.subtitle
        self._sub1_enabled = tk.BooleanVar(value=s.sub1.enabled)
        self._sub1_fontsize = tk.IntVar(value=s.sub1.fontsize)
        self._sub1_color = tk.StringVar(value=s.sub1.color)
        self._sub1_bold = tk.BooleanVar(value=s.sub1.bold)
        self._sub1_is_chinese = tk.BooleanVar(value=s.sub1.is_chinese)
        self._sub2_enabled = tk.BooleanVar(value=s.sub2.enabled)
        self._sub2_fontsize = tk.IntVar(value=s.sub2.fontsize)
        self._sub2_color = tk.StringVar(value=s.sub2.color)
        self._sub2_bold = tk.BooleanVar(value=s.sub2.bold)
        self._sub2_is_chinese = tk.BooleanVar(value=s.sub2.is_chinese)
        self._sub_stroke_color = tk.StringVar(value=s.stroke_color)
        self._sub_stroke_width = tk.IntVar(value=s.stroke_width)
        self._sub_position = tk.StringVar(value=s.position)
        # Normalized layout (percent in UI, fraction in schema).
        # Renderer consumes the fraction form via core.composition.layout.
        self._sub_block_margin_pct = tk.DoubleVar(value=s.block_margin_pct * 100.0)
        self._sub_track_gap_pct = tk.DoubleVar(value=s.track_gap_pct * 100.0)

        for tag, en_var, fs_var, c_var, bold_var, cn_var in (
                ("sub1", self._sub1_enabled, self._sub1_fontsize,
                 self._sub1_color, self._sub1_bold, self._sub1_is_chinese),
                ("sub2", self._sub2_enabled, self._sub2_fontsize,
                 self._sub2_color, self._sub2_bold, self._sub2_is_chinese)):
            row = ttk.Frame(sub); row.pack(fill="x", padx=4, pady=2)
            ttk.Checkbutton(row, text=tag, variable=en_var).pack(side="left")
            ttk.Label(row, text=tr("clip_tool.fontsize")).pack(side="left", padx=(8, 2))
            ttk.Spinbox(row, from_=8, to=120, textvariable=fs_var,
                         width=4).pack(side="left")
            self._color_picker(row, c_var)
            ttk.Checkbutton(row, text=tr("clip_tool.bold"),
                            variable=bold_var).pack(side="left", padx=(6, 0))
            ttk.Checkbutton(row, text=tr("clip_tool.is_chinese"),
                            variable=cn_var).pack(side="left", padx=(6, 0))

        row = ttk.Frame(sub); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.stroke")).pack(side="left")
        self._color_picker(row, self._sub_stroke_color)
        ttk.Spinbox(row, from_=0, to=12, textvariable=self._sub_stroke_width,
                     width=3).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("clip_tool.position")).pack(side="left", padx=(8, 2))
        ttk.Combobox(row, textvariable=self._sub_position,
                     values=("top", "middle", "bottom"),
                     state="readonly", width=8).pack(side="left")

        row = ttk.Frame(sub); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.layout_block_margin")
                  ).pack(side="left")
        ttk.Spinbox(row, from_=0, to=30, increment=0.5, width=6,
                    format="%.1f",
                    textvariable=self._sub_block_margin_pct
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text="%").pack(side="left")
        ttk.Label(row, text=tr("clip_tool.layout_track_gap")
                  ).pack(side="left", padx=(16, 0))
        ttk.Spinbox(row, from_=0, to=25, increment=0.5, width=6,
                    format="%.1f",
                    textvariable=self._sub_track_gap_pct
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text="%").pack(side="left")

        # Watermark
        wm = ttk.LabelFrame(parent, text=tr("clip_tool.section_watermark"))
        wm.pack(fill="x", padx=6, pady=4)
        w = self._current_style.watermark
        self._wm_enabled = tk.BooleanVar(value=w.enabled)
        self._wm_type = tk.StringVar(value=w.type)
        self._wm_position = tk.StringVar(value=w.position)
        self._wm_image_path = tk.StringVar(value=w.image_path)
        self._wm_image_scale = tk.DoubleVar(value=w.image_scale)
        self._wm_image_opacity = tk.IntVar(value=w.image_opacity)
        self._wm_text = tk.StringVar(value=w.text)
        self._wm_text_fontsize = tk.IntVar(value=w.text_fontsize)
        self._wm_text_color = tk.StringVar(value=w.text_color)
        self._wm_text_opacity = tk.IntVar(value=w.text_opacity)
        self._wm_margin_x_pct = tk.DoubleVar(value=w.margin_x_pct * 100.0)
        self._wm_margin_y_pct = tk.DoubleVar(value=w.margin_y_pct * 100.0)

        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        ttk.Checkbutton(row, text=tr("clip_tool.enabled"),
                        variable=self._wm_enabled).pack(side="left")
        ttk.Radiobutton(row, text=tr("clip_tool.wm_image"), variable=self._wm_type,
                        value="image").pack(side="left", padx=(8, 0))
        ttk.Radiobutton(row, text=tr("clip_tool.wm_text"), variable=self._wm_type,
                        value="text").pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("clip_tool.position")).pack(side="left", padx=(8, 2))
        ttk.Combobox(row, textvariable=self._wm_position,
                     values=("top-left", "top-right",
                             "bottom-left", "bottom-right"),
                     state="readonly", width=12).pack(side="left")

        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.wm_image_path")).pack(side="left")
        ttk.Entry(row, textvariable=self._wm_image_path,
                  width=24).pack(side="left", padx=(4, 0), fill="x", expand=True)
        ttk.Button(row, text="...",
                   command=self._browse_watermark, width=3).pack(side="left", padx=(2, 0))
        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.wm_image_scale")).pack(side="left")
        ttk.Scale(row, from_=0.05, to=0.5, variable=self._wm_image_scale,
                   orient="horizontal", length=120).pack(side="left", padx=(4, 4))
        ttk.Label(row, text=tr("clip_tool.wm_image_opacity")).pack(side="left", padx=(8, 0))
        ttk.Spinbox(row, from_=0, to=100, textvariable=self._wm_image_opacity,
                     width=4).pack(side="left", padx=(4, 0))

        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.wm_text")).pack(side="left")
        ttk.Entry(row, textvariable=self._wm_text,
                  width=20).pack(side="left", padx=(4, 0))
        ttk.Spinbox(row, from_=8, to=120, textvariable=self._wm_text_fontsize,
                     width=4).pack(side="left", padx=(4, 0))
        self._color_picker(row, self._wm_text_color)
        ttk.Spinbox(row, from_=0, to=100, textvariable=self._wm_text_opacity,
                     width=4).pack(side="left", padx=(4, 0))

        # Normalized margins from anchored corner — same contract as bilingual.
        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.layout_margin_x")
                  ).pack(side="left")
        ttk.Spinbox(row, from_=0, to=10, increment=0.5, width=6,
                    format="%.1f",
                    textvariable=self._wm_margin_x_pct
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text="%").pack(side="left")
        ttk.Label(row, text=tr("clip_tool.layout_margin_y")
                  ).pack(side="left", padx=(16, 0))
        ttk.Spinbox(row, from_=0, to=10, increment=0.5, width=6,
                    format="%.1f",
                    textvariable=self._wm_margin_y_pct
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text="%").pack(side="left")

        # Hook/Outro
        ho = ttk.LabelFrame(parent, text=tr("clip_tool.section_hook_outro"))
        ho.pack(fill="x", padx=6, pady=4)
        h = self._current_style.hook_outro
        self._ho_preset_var = tk.StringVar(
            value=comp_presets.get_last_used_hook_outro(self._hook_outro_store))
        self._ho_font = tk.StringVar(value=h.font)
        self._ho_size = tk.IntVar(value=h.size)
        self._ho_color = tk.StringVar(value=h.color)
        self._ho_bg_color = tk.StringVar(value=h.bg_color)
        self._ho_bg_opacity = tk.IntVar(value=h.bg_opacity)
        self._ho_stroke_color = tk.StringVar(value=h.stroke_color)
        self._ho_stroke_width = tk.IntVar(value=h.stroke_width)
        self._ho_box_padding = tk.IntVar(value=h.box_padding)
        self._ho_hook_position = tk.StringVar(value=h.hook_position)
        self._ho_outro_position = tk.StringVar(value=h.outro_position)
        self._ho_hook_duration = tk.DoubleVar(value=h.hook_duration_sec)
        self._ho_outro_duration = tk.DoubleVar(value=h.outro_duration_sec)

        row = ttk.Frame(ho); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.ho_preset")).pack(side="left")
        self._ho_preset_combo = ttk.Combobox(
            row, textvariable=self._ho_preset_var,
            values=comp_presets.list_hook_outro_presets(self._hook_outro_store),
            state="readonly", width=26)
        self._ho_preset_combo.pack(side="left", padx=(4, 4))
        ttk.Button(row, text=tr("clip_tool.btn_apply"),
                   command=self._on_ho_preset_applied).pack(side="left")

        row = ttk.Frame(ho); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.ho_font")).pack(side="left")
        ttk.Combobox(row, textvariable=self._ho_font,
                     values=("Microsoft YaHei", "SimHei", "SimSun",
                             "KaiTi", "DengXian", "Arial"),
                     state="readonly", width=16).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("clip_tool.fontsize")).pack(side="left", padx=(8, 2))
        ttk.Spinbox(row, from_=12, to=180, textvariable=self._ho_size,
                     width=4).pack(side="left")
        self._color_picker(row, self._ho_color)

        row = ttk.Frame(ho); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.ho_bg")).pack(side="left")
        self._color_picker(row, self._ho_bg_color)
        ttk.Spinbox(row, from_=0, to=100, textvariable=self._ho_bg_opacity,
                     width=4).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("clip_tool.stroke")).pack(side="left", padx=(8, 2))
        self._color_picker(row, self._ho_stroke_color)
        ttk.Spinbox(row, from_=0, to=12, textvariable=self._ho_stroke_width,
                     width=3).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("clip_tool.ho_padding")).pack(side="left", padx=(8, 2))
        ttk.Spinbox(row, from_=0, to=60, textvariable=self._ho_box_padding,
                     width=3).pack(side="left")

        positions = ("top", "upper-third", "center", "lower-third", "bottom")
        row = ttk.Frame(ho); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.ho_hook_pos")).pack(side="left")
        ttk.Combobox(row, textvariable=self._ho_hook_position,
                     values=positions, state="readonly",
                     width=12).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("clip_tool.ho_outro_pos")).pack(side="left", padx=(8, 0))
        ttk.Combobox(row, textvariable=self._ho_outro_position,
                     values=positions, state="readonly",
                     width=12).pack(side="left", padx=(4, 0))
        row = ttk.Frame(ho); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.ho_hook_dur")).pack(side="left")
        ttk.Spinbox(row, from_=0.0, to=30.0, increment=0.5,
                     textvariable=self._ho_hook_duration,
                     width=5).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("clip_tool.ho_outro_dur")).pack(side="left", padx=(8, 0))
        ttk.Spinbox(row, from_=0.0, to=30.0, increment=0.5,
                     textvariable=self._ho_outro_duration,
                     width=5).pack(side="left", padx=(4, 0))

        self._wire_traces()

    def _color_picker(self, parent: tk.Misc, var: tk.StringVar) -> None:
        swatch = tk.Label(parent, text="  ", bg=var.get() or "#FFFFFF",
                          relief="solid", borderwidth=1, width=2)
        swatch.pack(side="left", padx=(4, 0))

        def _pick(_e=None):
            (_, hex_v) = colorchooser.askcolor(
                color=var.get() or "#FFFFFF", parent=parent.winfo_toplevel())
            if hex_v:
                var.set(hex_v)
                swatch.configure(bg=hex_v)
        swatch.bind("<Button-1>", _pick)
        var.trace_add("write",
                       lambda *_a, s=swatch, v=var: s.configure(bg=v.get() or "#FFFFFF"))

    def _wire_traces(self) -> None:
        for var in (
            self._aspect_var, self._encode_preset_var,
            self._sub1_enabled, self._sub1_fontsize, self._sub1_color,
            self._sub1_bold, self._sub1_is_chinese,
            self._sub2_enabled, self._sub2_fontsize, self._sub2_color,
            self._sub2_bold, self._sub2_is_chinese,
            self._sub_stroke_color, self._sub_stroke_width, self._sub_position,
            self._sub_block_margin_pct, self._sub_track_gap_pct,
            self._wm_enabled, self._wm_type, self._wm_position,
            self._wm_image_path, self._wm_image_scale, self._wm_image_opacity,
            self._wm_text, self._wm_text_fontsize, self._wm_text_color,
            self._wm_text_opacity,
            self._wm_margin_x_pct, self._wm_margin_y_pct,
            self._ho_font, self._ho_size, self._ho_color,
            self._ho_bg_color, self._ho_bg_opacity,
            self._ho_stroke_color, self._ho_stroke_width, self._ho_box_padding,
            self._ho_hook_position, self._ho_outro_position,
            self._ho_hook_duration, self._ho_outro_duration,
        ):
            var.trace_add("write", lambda *_a: self._on_form_changed())

    # ── Tab 2: Clips ─────────────────────────────────────────────────────

    def _build_tab_clips(self) -> None:
        f = tk.Frame(self._tab_clips, bg="white")
        f.pack(fill="both", expand=True)

        # Header
        header = tk.Frame(f, bg="white")
        header.pack(fill="x", padx=8, pady=(8, 4))
        self._clips_header_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self._clips_header_var,
                 bg="white").pack(side="left")
        ttk.Button(header, text=tr("clip_tool.btn_select_all"),
                   command=self._select_all).pack(side="right", padx=(4, 0))
        ttk.Button(header, text=tr("clip_tool.btn_select_none"),
                   command=self._select_none).pack(side="right", padx=(4, 0))

        # Body: master list left, detail panel right
        pw = ttk.PanedWindow(f, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        master = ttk.Frame(pw)
        detail = ttk.Frame(pw)
        pw.add(master, weight=3)
        pw.add(detail, weight=5)

        # Master: scrollable list
        canvas = tk.Canvas(master, bg="white", highlightthickness=0)
        sb = ttk.Scrollbar(master, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._candidate_box = tk.Frame(canvas, bg="white")
        canvas.create_window((0, 0), window=self._candidate_box, anchor="nw")
        self._candidate_box.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _on_canvas_resize(e):
            children = canvas.find_all()
            if children:
                canvas.itemconfig(children[0], width=e.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

        # Detail panel
        self._build_clip_detail_panel(detail)

    def _build_clip_detail_panel(self, parent: ttk.Frame) -> None:
        # Empty-state label (visible when no detail loaded)
        self._detail_empty_var = tk.StringVar(
            value=tr("clip_tool.detail_no_selection"))
        self._detail_empty_label = tk.Label(
            parent, textvariable=self._detail_empty_var,
            bg="white", fg="#888", justify="center")
        self._detail_empty_label.pack(fill="both", expand=True)

        # Container (hidden until first detail load)
        self._detail_container = ttk.Frame(parent)

        # Preview
        self._clip_preview = CompositionPreview(
            self._detail_container,
            on_crop_changed=self._on_clip_crop_changed,
            width=420, height=360)
        self._clip_preview.widget.pack(fill="both", expand=True,
                                         padx=4, pady=4)

        # Time row
        time_row = ttk.LabelFrame(self._detail_container,
                                    text=tr("clip_tool.detail_time"))
        time_row.pack(fill="x", padx=6, pady=4)

        self._detail_vars["start"] = tk.StringVar()
        self._detail_vars["end"] = tk.StringVar()
        for label_key, var_key, nudge_fn in (
                ("clip_tool.detail_start", "start", self._on_nudge_start),
                ("clip_tool.detail_end",   "end",   self._on_nudge_end)):
            row = ttk.Frame(time_row); row.pack(fill="x", padx=4, pady=2)
            ttk.Label(row, text=tr(label_key), width=8
                      ).pack(side="left")
            ent = ttk.Entry(row, textvariable=self._detail_vars[var_key],
                            width=14)
            ent.pack(side="left", padx=(4, 4))
            ent.bind("<FocusOut>",
                     lambda _e, k=var_key: self._on_time_entry_blur(k))
            ent.bind("<Return>",
                     lambda _e, k=var_key: self._on_time_entry_blur(k))
            ttk.Button(row, text=tr("clip_tool.nudge_minus"),
                       command=lambda fn=nudge_fn: fn(-0.5),
                       width=6).pack(side="left", padx=(2, 0))
            ttk.Button(row, text=tr("clip_tool.nudge_plus"),
                       command=lambda fn=nudge_fn: fn(0.5),
                       width=6).pack(side="left", padx=(2, 0))

        self._detail_vars["duration_score"] = tk.StringVar()
        tk.Label(time_row, textvariable=self._detail_vars["duration_score"],
                 fg="#666", anchor="w").pack(fill="x", padx=4, pady=(2, 4))

        # Text row
        text_row = ttk.LabelFrame(self._detail_container,
                                    text=tr("clip_tool.detail_text"))
        text_row.pack(fill="x", padx=6, pady=4)

        self._detail_vars["hook"] = tk.StringVar()
        self._detail_vars["outro"] = tk.StringVar()
        self._detail_vars["title"] = tk.StringVar()
        self._detail_vars["tags"] = tk.StringVar()
        for label_key, var_key in (
                ("clip_tool.detail_hook",  "hook"),
                ("clip_tool.detail_outro", "outro"),
                ("clip_tool.detail_title", "title"),
                ("clip_tool.detail_tags",  "tags")):
            row = ttk.Frame(text_row); row.pack(fill="x", padx=4, pady=2)
            ttk.Label(row, text=tr(label_key), width=8
                      ).pack(side="left")
            ent = ttk.Entry(row, textvariable=self._detail_vars[var_key])
            ent.pack(side="left", padx=(4, 0), fill="x", expand=True)
            ent.bind("<FocusOut>",
                     lambda _e, k=var_key: self._on_text_entry_blur(k))
            ent.bind("<Return>",
                     lambda _e, k=var_key: self._on_text_entry_blur(k))

        # SRT cues readonly
        cues_row = ttk.LabelFrame(self._detail_container,
                                    text=tr("clip_tool.detail_srt_cues"))
        cues_row.pack(fill="both", expand=False, padx=6, pady=4)
        self._detail_widgets["cues_text"] = tk.Text(
            cues_row, height=6, state="disabled", wrap="word",
            font=("Consolas", 9), bg="#f6f6f6")
        self._detail_widgets["cues_text"].pack(fill="x", padx=4, pady=4)

        # Buttons
        btn_row = ttk.Frame(self._detail_container)
        btn_row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btn_row, text=tr("clip_tool.btn_reset_clip_crop"),
                   command=self._on_reset_clip_crop).pack(side="left")
        ttk.Button(btn_row, text=tr("clip_tool.btn_restore_ai_text"),
                   command=self._on_restore_ai_text).pack(side="left", padx=(6, 0))

    # ── Tab 3: Export ────────────────────────────────────────────────────

    def _build_tab_export(self) -> None:
        f = tk.Frame(self._tab_export, bg="white")
        f.pack(fill="both", expand=True, padx=10, pady=10)

        # Overview
        ov = ttk.LabelFrame(f, text=tr("clip_tool.section_overview"))
        ov.pack(fill="x", pady=(0, 6))
        self._overview_var = tk.StringVar(value="")
        tk.Label(ov, textvariable=self._overview_var,
                 bg="white", justify="left", anchor="w"
                 ).pack(fill="x", padx=6, pady=6)

        # Action row
        ctrl = tk.Frame(f, bg="white"); ctrl.pack(fill="x", pady=(0, 4))
        self._render_btn = tk.Button(
            ctrl, text=tr("clip_tool.btn_render"),
            command=self._on_render, bg="#0078d4", fg="white",
            relief="flat", padx=14, pady=6)
        self._render_btn.pack(side="left")
        self._cancel_btn = tk.Button(
            ctrl, text=tr("clip_tool.btn_cancel"),
            command=self._on_cancel_render, state="disabled",
            relief="flat", bg="#e8e8e8", padx=10, pady=6)
        self._cancel_btn.pack(side="left", padx=(6, 0))
        tk.Button(ctrl, text=tr("clip_tool.btn_open_folder"),
                  command=self._on_open_folder, relief="flat",
                  bg="#e8e8e8", padx=10, pady=6
                  ).pack(side="left", padx=(6, 0))

        # Progress bars
        prog = tk.Frame(f, bg="white"); prog.pack(fill="x", pady=4)
        self._progress_overall = ttk.Progressbar(prog, length=400,
                                                    mode="determinate")
        self._progress_overall.pack(fill="x")
        self._progress_overall_var = tk.StringVar(value="")
        tk.Label(prog, textvariable=self._progress_overall_var,
                 bg="white", fg="#666", anchor="w").pack(fill="x")
        self._progress_current = ttk.Progressbar(prog, length=400,
                                                   mode="determinate")
        self._progress_current.pack(fill="x", pady=(4, 0))
        self._progress_current_var = tk.StringVar(value="")
        tk.Label(prog, textvariable=self._progress_current_var,
                 bg="white", fg="#666", anchor="w").pack(fill="x")

        # Render table
        cols = ("idx", "source", "duration", "status", "hook")
        self._render_tv = ttk.Treeview(f, columns=cols, show="headings",
                                          height=12)
        for c, w in zip(cols, (40, 70, 70, 90, 280)):
            self._render_tv.heading(c, text=tr(f"clip_tool.col_{c}"))
            self._render_tv.column(c, width=w,
                                    anchor=("e" if c in ("idx", "duration") else "w"))
        self._render_tv.pack(fill="both", expand=True, pady=(8, 4))

        # Context menu
        self._render_menu = tk.Menu(self._render_tv, tearoff=0)
        self._render_menu.add_command(label=tr("clip_tool.act_play"),
                                       command=self._on_act_play)
        self._render_menu.add_command(label=tr("clip_tool.act_open_folder"),
                                       command=self._on_act_open_folder)
        self._render_menu.add_command(label=tr("clip_tool.act_rerender"),
                                       command=self._on_act_rerender)
        self._render_menu.add_command(label=tr("clip_tool.act_delete"),
                                       command=self._on_act_delete)
        self._render_menu.add_separator()
        self._render_menu.add_command(label=tr("clip_tool.act_error_detail"),
                                       command=self._on_act_error_detail)
        self._render_tv.bind("<Button-3>", self._on_render_tv_right_click)
        # Double-click = play (or rerender if not done)
        self._render_tv.bind("<Double-Button-1>", lambda _e: self._on_act_play())

    # ── Data accessors ───────────────────────────────────────────────────

    def _instance_dir(self) -> str:
        return self.project.creation_instance_dir("clip", self.instance_name)

    # ── Clip file naming ─────────────────────────────────────────────────
    #
    # Clip basename is `clip_NNN` plus the hook text (when present),
    # joined with `_`. The hook prefix means the user can scan the
    # output folder by content rather than opening every .md. All file
    # ops resolve via _existing_clip_files() so old `clip_NNN.mp4`
    # outputs and new `clip_NNN_<hook>.mp4` ones coexist on disk.

    @staticmethod
    def _sanitize_filename_part(text: str, max_len: int = 30) -> str:
        """Strip filesystem-invalid chars and trim. Returns "" if the
        result is empty (caller falls back to the bare clip_NNN form)."""
        import re
        if not text:
            return ""
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        text = text.rstrip('. ')
        if len(text) > max_len:
            text = text[:max_len].rstrip('. ')
        return text

    def _clip_basename(self, out_idx: int, src_idx: int) -> str:
        """`clip_001_老黄笑场` (no extension). Falls back to `clip_001`
        when hook is empty / fully stripped by sanitization."""
        suffix = self._sanitize_filename_part(
            self._effective_hook(src_idx) or "")
        if suffix:
            return f"clip_{out_idx:03d}_{suffix}"
        return f"clip_{out_idx:03d}"

    def _existing_clip_files(self, out_idx: int) -> list[str]:
        """All on-disk files belonging to a given output index, across
        legacy `clip_NNN.{mp4,json,md}` and current `clip_NNN_*.{...}`
        naming. Used for conflict checks, deletion, and pre-render
        cleanup when a hook change would otherwise leave stale pairs."""
        inst = self._instance_dir()
        prefix = f"clip_{out_idx:03d}"
        out: list[str] = []
        try:
            for name in os.listdir(inst):
                if not name.startswith(prefix):
                    continue
                # Accept `clip_NNN.<ext>` (exact) or `clip_NNN_<rest>.<ext>`.
                tail = name[len(prefix):]
                if tail and not (tail.startswith(".") or tail.startswith("_")):
                    continue
                if not (name.endswith(".mp4") or name.endswith(".json")
                        or name.endswith(".md")):
                    continue
                out.append(os.path.join(inst, name))
        except OSError:
            pass
        return out

    def _find_clip_mp4(self, out_idx: int) -> Optional[str]:
        """Locate the rendered .mp4 for an output index regardless of
        naming scheme. Returns None if not on disk."""
        for p in self._existing_clip_files(out_idx):
            if p.endswith(".mp4"):
                return p
        return None

    def _candidate_count(self) -> int:
        return len(self._candidate_meta)

    def _override(self, idx: int) -> dict:
        """Return the override dict for `idx`, creating it on demand."""
        return self._clips_overrides.setdefault(idx, {})

    def _effective_start_end(self, idx: int) -> tuple[float, float]:
        if not (0 <= idx < len(self._candidate_meta)):
            return (0.0, 0.0)
        hot = self._candidate_meta[idx]
        ov = self._clips_overrides.get(idx) or {}
        start = ov.get("start_sec")
        if start is None:
            start = _parse_ts(hot.get("start", ""))
        end = ov.get("end_sec")
        if end is None:
            end = _parse_ts(hot.get("end", ""))
        return (float(start), float(end))

    def _effective_hook(self, idx: int) -> str:
        if not (0 <= idx < len(self._candidate_meta)):
            return ""
        hot = self._candidate_meta[idx]
        ov = self._clips_overrides.get(idx) or {}
        if "hook_text" in ov:
            return str(ov["hook_text"])
        # AI hotclips schema: `hook` is the punchy on-screen hook line;
        # `suggested_title` is for off-screen publication metadata.
        return (hot.get("hook") or "").strip()

    def _effective_title(self, idx: int) -> str:
        if not (0 <= idx < len(self._candidate_meta)):
            return ""
        hot = self._candidate_meta[idx]
        ov = self._clips_overrides.get(idx) or {}
        if "title" in ov:
            return str(ov["title"])
        return (hot.get("suggested_title") or "").strip()

    def _wrap_for_overlay(self, text: str) -> list[str]:
        """Pre-wrap hook/outro text using the same algorithm the ffmpeg
        render uses. Both previews consume this to guarantee preview ≡
        rendered output (no JS-side wrap divergence)."""
        if not text:
            return []
        font_path = hook_outro_font_path(self._current_style.hook_outro.font)
        return wrap_hook_outro(
            text, self._current_style.aspect_ratio(),
            font_path, self._current_style.hook_outro.size)

    def _effective_outro(self, idx: int) -> str:
        if not (0 <= idx < len(self._candidate_meta)):
            return ""
        hot = self._candidate_meta[idx]
        ov = self._clips_overrides.get(idx) or {}
        if "outro_text" in ov:
            return str(ov["outro_text"])
        # AI hotclips schema: `outro` is the closing CTA line; falls back
        # to empty for legacy hotclips.json that predate the outro field.
        return (hot.get("outro") or "").strip()

    def _effective_tags(self, idx: int) -> list[str]:
        if not (0 <= idx < len(self._candidate_meta)):
            return []
        hot = self._candidate_meta[idx]
        ov = self._clips_overrides.get(idx) or {}
        if "hashtags" in ov:
            tags = ov["hashtags"]
            if isinstance(tags, list):
                return [str(t) for t in tags]
            if isinstance(tags, str):
                return [t.strip() for t in tags.split() if t.strip()]
            return []
        tags = hot.get("suggested_hashtags") or hot.get("hashtags") or []
        if isinstance(tags, list):
            return [str(t) for t in tags]
        return []

    def _effective_crop(self, idx: int) -> Optional[dict]:
        """Three-level fallback: per-clip override > global > None (= center)."""
        ov = self._clips_overrides.get(idx) or {}
        if "crop_rect" in ov and ov["crop_rect"]:
            return ov["crop_rect"]
        return self._global_crop_rect    # None → center default at render time

    # ── Persistence ──────────────────────────────────────────────────────

    def _restore_persisted_state(self) -> None:
        cfg = _load_instance_config(self._instance_dir())
        if not cfg:
            return
        lang = cfg.get("source_subtitle")
        if lang:
            self._lang_var.set(lang)
        name = cfg.get("preset_name")
        if name:
            style = comp_presets.get_project_preset(self._project_store, name)
            if style is not None:
                self._current_style = style
                self._preset_name_var.set(name)
        raw_style = cfg.get("style")
        if raw_style and isinstance(raw_style, dict):
            try:
                self._current_style = comp_presets.composition_style_from_dict(raw_style)
            except (comp_presets.PresetSchemaError, TypeError, ValueError):
                pass
        crop = cfg.get("global_crop_rect")
        if isinstance(crop, dict):
            self._global_crop_rect = crop
        ovs = cfg.get("clips_overrides") or {}
        if isinstance(ovs, dict):
            self._clips_overrides = {int(k): v for k, v in ovs.items()
                                       if isinstance(v, dict)}
        # Restore rendered list (drop entries whose mp4 no longer exists on disk)
        rendered = cfg.get("rendered") or []
        if isinstance(rendered, list):
            inst = self._instance_dir()
            self._rendered = [
                r for r in rendered
                if isinstance(r, dict) and os.path.isfile(
                    os.path.join(inst, r.get("file", "")))
            ]
        sel = cfg.get("selected_clip_indices") or []
        # Selected indices applied after candidates load (deferred to _reload_candidates)
        self._pending_selection = set(int(i) for i in sel if isinstance(i, int))

    def _save_all(self) -> None:
        """Write full config.json from current in-memory state."""
        sel = [i for i, v in enumerate(self._candidate_vars) if v.get()]
        cfg = {
            "source_subtitle": self._lang_var.get(),
            "selected_clip_indices": sel,
            "preset_name": self._preset_name_var.get(),
            "style": asdict(self._current_style),
            "global_crop_rect": self._global_crop_rect,
            "clips_overrides": {str(k): v for k, v in self._clips_overrides.items()},
            "rendered": self._rendered,
        }
        _save_instance_config(self._instance_dir(), cfg)

    # ── Hotclips snapshot (per-instance immutable source) ────────────────

    # When the user picks a language and the instance doesn't yet have its
    # own copy of <lang>.hotclips.json, we snapshot upstream into the
    # instance dir. From that point on the workbench reads ONLY from the
    # snapshot — upstream regeneration cannot corrupt per-clip overrides
    # or already-rendered outputs. Stage 1: hotclips only; SRT and source
    # video remain shared upstream (regeneration of those is rare and
    # currently produces near-identical output).

    _SNAPSHOT_RE = re.compile(r"^source-hotclips\.([^.]+)\.json$")

    def _hotclips_snapshot_path(self, lang: str) -> str:
        return os.path.join(self._instance_dir(),
                              f"source-hotclips.{lang}.json")

    def _srt_snapshot_path(self, lang: str) -> str:
        return os.path.join(self._instance_dir(),
                              f"source-subtitles.{lang}.srt")

    def _ensure_snapshot(self, lang: str) -> Optional[str]:
        """Snapshot upstream hotclips + SRT into the instance dir if not yet
        present. Returns the hotclips snapshot path (the only one callers
        currently switch on), or None if hotclips upstream is missing AND
        no prior snapshot exists. SRT snapshot is best-effort: missing
        upstream SRT is fine (subtitles are optional for burn)."""
        os.makedirs(self._instance_dir(), exist_ok=True)
        # Hotclips — required
        hot_snap = self._hotclips_snapshot_path(lang)
        if not os.path.isfile(hot_snap):
            upstream = os.path.join(_nv_paths.subtitles_dir(self.project, self.material_instance_id),
                                      f"{lang}.hotclips.json")
            if not os.path.isfile(upstream):
                return None
            try:
                shutil.copy2(upstream, hot_snap)
            except OSError:
                return None
        # SRT — optional; copy on best-effort basis. Once snapshotted,
        # _resolve_source_srt() returns this path so upstream regeneration
        # cannot affect this instance's renders.
        srt_snap = self._srt_snapshot_path(lang)
        if not os.path.isfile(srt_snap):
            upstream_srt = os.path.join(_nv_paths.subtitles_dir(self.project, self.material_instance_id),
                                          f"{lang}.srt")
            if os.path.isfile(upstream_srt):
                try:
                    shutil.copy2(upstream_srt, srt_snap)
                except OSError:
                    pass
        return hot_snap

    def _list_available_langs(self) -> list[str]:
        """Languages with hotclips available — union of instance snapshots
        and upstream subtitles. Snapshotted langs are always listed even if
        upstream was deleted; not-yet-snapshotted langs from upstream are
        listed and will be snapshotted on first selection."""
        langs: set[str] = set()
        inst_dir = self._instance_dir()
        try:
            for name in os.listdir(inst_dir):
                m = self._SNAPSHOT_RE.match(name)
                if m:
                    langs.add(m.group(1))
        except OSError:
            pass
        try:
            for name in os.listdir(_nv_paths.subtitles_dir(self.project, self.material_instance_id)):
                if name.endswith(".hotclips.json"):
                    langs.add(name[:-len(".hotclips.json")])
        except OSError:
            pass
        return sorted(langs)

    # ── Language / candidate loading ─────────────────────────────────────

    def _reload_languages(self) -> None:
        langs = self._list_available_langs()
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
        for child in self._candidate_box.winfo_children():
            child.destroy()
        self._candidate_vars = []
        self._candidate_meta = []
        self._candidate_rows = []
        self._render_status = {}

        lang = self._lang_var.get()
        if not lang:
            return
        path = self._ensure_snapshot(lang)
        if path is None:
            self._status_var.set(tr("clip_tool.status_load_failed",
                                     error="hotclips source not found"))
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self._status_var.set(tr("clip_tool.status_load_failed", error=str(e)))
            return
        self._hotclips_data = data
        clips = data.get("clips") or []
        self._status_var.set(tr("clip_tool.status_loaded", n=len(clips)))

        # Apply restored selection
        restore = getattr(self, "_pending_selection", None) or set()
        for i, c in enumerate(clips):
            if not isinstance(c, dict):
                continue
            checked = i in restore
            var = tk.BooleanVar(value=checked)
            var.trace_add("write", lambda *_a: self._on_selection_changed())
            self._candidate_vars.append(var)
            self._candidate_meta.append(c)
            self._render_candidate_row(i, c, var)
            self._render_status[i] = "queued" if checked else ""
        self._pending_selection = None

        self._refresh_clips_header()
        self._refresh_overview()
        self._refresh_render_tv()
        # Auto-load first selected (or first) into detail
        first_sel = next((i for i, v in enumerate(self._candidate_vars) if v.get()),
                          None)
        if first_sel is None and self._candidate_vars:
            first_sel = 0
        if first_sel is not None:
            self._show_detail(first_sel)

    def _render_candidate_row(self, idx: int, clip: dict,
                                var: tk.BooleanVar) -> None:
        row = tk.Frame(self._candidate_box, bg="white",
                       bd=1, relief="solid")
        row.pack(fill="x", padx=2, pady=2)
        cb = tk.Checkbutton(row, variable=var, bg="white")
        cb.pack(side="left", padx=(4, 8))

        col = tk.Frame(row, bg="white")
        col.pack(side="left", fill="x", expand=True, pady=4)
        head = tk.Frame(col, bg="white"); head.pack(fill="x")
        tk.Label(head, text=f"#{idx + 1}", bg="white", fg="#888",
                 font=("Microsoft YaHei UI", 9, "bold")
                 ).pack(side="left")
        ts = f"  {clip.get('start', '')} → {clip.get('end', '')}"
        tk.Label(head, text=ts, bg="white", fg="#0078d4",
                 font=("Consolas", 9)).pack(side="left")
        dur = clip.get("duration_sec")
        if isinstance(dur, (int, float)):
            tk.Label(head, text=f"  {int(dur)}s", bg="white", fg="#888"
                     ).pack(side="left")
        score = clip.get("score")
        if score is not None:
            color = ("#c00" if isinstance(score, (int, float)) and score >= 8
                     else "#d97706" if isinstance(score, (int, float)) and score >= 6
                     else "#888")
            tk.Label(head, text=f"⭐ {score}", bg="white", fg=color,
                     font=("Microsoft YaHei UI", 10, "bold")
                     ).pack(side="right", padx=6)
        hook = (clip.get("hook") or clip.get("suggested_title") or "").strip()
        if hook:
            tk.Label(col, text=hook, bg="white", fg="#222",
                     font=("Microsoft YaHei UI", 10, "bold"),
                     wraplength=420, justify="left", anchor="w"
                     ).pack(fill="x")
        # Mode B: clicking the text area (not the checkbox) switches detail.
        for w in (col, head):
            w.bind("<Button-1>", lambda _e, i=idx: self._show_detail(i))
            for child in w.winfo_children():
                if isinstance(child, tk.Label):
                    child.bind("<Button-1>",
                               lambda _e, i=idx: self._show_detail(i))
        self._candidate_rows.append({"row": row})

    # ── Selection / header ───────────────────────────────────────────────

    def _select_all(self) -> None:
        for v in self._candidate_vars:
            v.set(True)

    def _select_none(self) -> None:
        for v in self._candidate_vars:
            v.set(False)

    def _on_selection_changed(self) -> None:
        # Keep render_status synced for queue display
        for i, v in enumerate(self._candidate_vars):
            cur = self._render_status.get(i, "")
            if cur in ("", "queued"):
                self._render_status[i] = "queued" if v.get() else ""
        self._refresh_clips_header()
        self._refresh_overview()
        self._refresh_render_tv()
        self._save_all()

    def _refresh_clips_header(self) -> None:
        total = len(self._candidate_vars)
        sel = sum(1 for v in self._candidate_vars if v.get())
        self._clips_header_var.set(
            tr("clip_tool.clips_header_fmt", selected=sel, total=total))

    # ── Detail panel ─────────────────────────────────────────────────────

    def _show_detail(self, idx: int) -> None:
        if not (0 <= idx < len(self._candidate_meta)):
            return
        self._detail_idx = idx
        # Swap empty placeholder for the real container on first load
        self._detail_empty_label.pack_forget()
        self._detail_container.pack(fill="both", expand=True)
        # Push preview source
        if self._clip_preview is not None:
            start, end = self._effective_start_end(idx)
            video_path = _nv_paths.source_video_path(self.project, self.material_instance_id)
            if os.path.isfile(video_path):
                self._clip_preview.set_source(video_path, start, end)
                hook = self._effective_hook(idx)
                outro = self._effective_outro(idx)
                self._clip_preview.set_clip_meta(
                    hook=hook, outro=outro,
                    hook_lines=self._wrap_for_overlay(hook),
                    outro_lines=self._wrap_for_overlay(outro))
                self._clip_preview.set_cues(
                    self._cues_for_window(start, end))
                self._clip_preview.set_crop(self._effective_crop(idx))
                self._clip_preview.enable_crop_drag(True)
                self._clip_preview.set_style(self._current_style)
        # Populate fields
        start, end = self._effective_start_end(idx)
        self._detail_vars["start"].set(_format_ts(start))
        self._detail_vars["end"].set(_format_ts(end))
        self._detail_vars["duration_score"].set(
            tr("clip_tool.detail_duration_score_fmt",
               duration=f"{end - start:.1f}",
               score=str(self._candidate_meta[idx].get("score", "-"))))
        self._detail_vars["hook"].set(self._effective_hook(idx))
        self._detail_vars["outro"].set(self._effective_outro(idx))
        self._detail_vars["title"].set(self._effective_title(idx))
        self._detail_vars["tags"].set(" ".join(self._effective_tags(idx)))
        # SRT cues
        cues = self._cues_for_window(start, end)
        cues_widget = self._detail_widgets["cues_text"]
        cues_widget.configure(state="normal")
        cues_widget.delete("1.0", "end")
        for c in cues:
            cues_widget.insert("end",
                                 f"[{_format_ts(c['start'])}]  {c['text']}\n")
        cues_widget.configure(state="disabled")

    def _cues_for_window(self, start_sec: float,
                          end_sec: float) -> list[dict]:
        """Return SRT cues overlapping [start_sec, end_sec] in *source-video*
        timeline (no rebase — the clip preview seeks within the source).
        Wrap/split is performed by core.composition.prepare_subtitle_cues,
        the same helper the burn path uses, so preview ≡ render."""
        full = self._full_srt_cues()
        return [c for c in full
                if c["end"] > start_sec and c["start"] < end_sec]

    def _full_srt_cues(self) -> list[dict]:
        """Whole SRT, pre-split per current sub1 config via the shared core
        helper. Source-video timeline, no slicing."""
        srt_path = self._resolve_source_srt()
        if not srt_path or not os.path.isfile(srt_path):
            return []
        from core.composition import prepare_subtitle_cues
        sub1 = self._current_style.subtitle.sub1
        return prepare_subtitle_cues(
            srt_path, sub1,
            aspect=self._current_style.output.aspect,
            short_edge=self._current_style.output.short_edge)

    def _resolve_source_srt(self) -> Optional[str]:
        """Return the instance's SRT snapshot. Falls back to upstream only
        when the snapshot hasn't been taken (e.g. very old instances from
        before the snapshot principle was introduced) — that case should
        be rare, since _ensure_snapshot is called on every language load."""
        lang = self._lang_var.get()
        if not lang:
            return None
        snap = self._srt_snapshot_path(lang)
        if os.path.isfile(snap):
            return snap
        upstream = os.path.join(_nv_paths.subtitles_dir(self.project, self.material_instance_id), f"{lang}.srt")
        return upstream if os.path.isfile(upstream) else None

    # ── Detail field handlers ────────────────────────────────────────────

    def _on_time_entry_blur(self, key: str) -> None:
        if self._detail_idx is None:
            return
        raw = self._detail_vars[key].get()
        secs = _parse_ts(raw)
        ov = self._override(self._detail_idx)
        ov[f"{key}_sec"] = secs
        # Reformat in case user typed "1:23"
        self._detail_vars[key].set(_format_ts(secs))
        self._refresh_detail_dependents()
        self._refresh_render_tv()
        self._save_all()

    def _on_text_entry_blur(self, key: str) -> None:
        if self._detail_idx is None:
            return
        raw = self._detail_vars[key].get()
        ov = self._override(self._detail_idx)
        if key == "tags":
            tags = [t.strip() for t in raw.split() if t.strip()]
            if tags:
                ov["hashtags"] = tags
            else:
                ov.pop("hashtags", None)
        else:
            field = {
                "hook":  "hook_text",
                "outro": "outro_text",
                "title": "title",
            }[key]
            if raw.strip():
                ov[field] = raw
            else:
                ov.pop(field, None)
        self._refresh_render_tv()
        self._save_all()
        # Push to preview (hook/outro overlay updates) with canonical lines
        if self._clip_preview is not None and self._detail_idx is not None:
            hook = self._effective_hook(self._detail_idx)
            outro = self._effective_outro(self._detail_idx)
            self._clip_preview.set_clip_meta(
                hook=hook, outro=outro,
                hook_lines=self._wrap_for_overlay(hook),
                outro_lines=self._wrap_for_overlay(outro))

    def _on_nudge_start(self, delta: float) -> None:
        if self._detail_idx is None:
            return
        start, end = self._effective_start_end(self._detail_idx)
        new_start = max(0.0, min(end - 0.1, start + delta))
        ov = self._override(self._detail_idx)
        ov["start_sec"] = new_start
        self._detail_vars["start"].set(_format_ts(new_start))
        self._refresh_detail_dependents()
        self._refresh_render_tv()
        self._save_all()
        # Re-push preview window
        if self._clip_preview is not None:
            self._clip_preview.set_clip_range(new_start, end)

    def _on_nudge_end(self, delta: float) -> None:
        if self._detail_idx is None:
            return
        start, end = self._effective_start_end(self._detail_idx)
        new_end = max(start + 0.1, end + delta)
        ov = self._override(self._detail_idx)
        ov["end_sec"] = new_end
        self._detail_vars["end"].set(_format_ts(new_end))
        self._refresh_detail_dependents()
        self._refresh_render_tv()
        self._save_all()
        if self._clip_preview is not None:
            self._clip_preview.set_clip_range(start, new_end)

    def _refresh_detail_dependents(self) -> None:
        if self._detail_idx is None:
            return
        start, end = self._effective_start_end(self._detail_idx)
        self._detail_vars["duration_score"].set(
            tr("clip_tool.detail_duration_score_fmt",
               duration=f"{end - start:.1f}",
               score=str(self._candidate_meta[self._detail_idx]
                          .get("score", "-"))))
        # Refresh SRT cues for new window
        cues = self._cues_for_window(start, end)
        cues_widget = self._detail_widgets["cues_text"]
        cues_widget.configure(state="normal")
        cues_widget.delete("1.0", "end")
        for c in cues:
            cues_widget.insert("end",
                                 f"[{_format_ts(c['start'])}]  {c['text']}\n")
        cues_widget.configure(state="disabled")
        if self._clip_preview is not None:
            self._clip_preview.set_cues(cues)

    def _on_clip_crop_changed(self, rect: dict) -> None:
        """Called from JS when user drags the crop rect in the clip preview."""
        if self._detail_idx is None:
            return
        if not rect or "x" not in rect:
            return
        self._override(self._detail_idx)["crop_rect"] = rect
        self._save_all()

    def _on_reset_clip_crop(self) -> None:
        if self._detail_idx is None:
            return
        ov = self._clips_overrides.get(self._detail_idx)
        if ov and "crop_rect" in ov:
            ov.pop("crop_rect", None)
        # Apply effective (= global or default center) to preview
        if self._clip_preview is not None:
            self._clip_preview.set_crop(self._effective_crop(self._detail_idx))
        self._save_all()

    def _on_restore_ai_text(self) -> None:
        if self._detail_idx is None:
            return
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_restore_ai_text"),
                parent=self.master):
            return
        ov = self._clips_overrides.get(self._detail_idx)
        if ov:
            for k in ("hook_text", "outro_text", "title", "hashtags"):
                ov.pop(k, None)
        self._show_detail(self._detail_idx)
        self._refresh_render_tv()
        self._save_all()

    # ── Tab 1: global crop handler + apply-to-all ────────────────────────

    def _on_style_crop_changed(self, rect: dict) -> None:
        if not rect or "x" not in rect:
            return
        self._global_crop_rect = rect
        self._save_all()

    def _on_apply_crop_to_all(self) -> None:
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_apply_crop_to_all"),
                parent=self.master):
            return
        # Drop per-clip crop_rect entries; keep other override fields
        for idx, ov in list(self._clips_overrides.items()):
            ov.pop("crop_rect", None)
            if not ov:
                self._clips_overrides.pop(idx, None)
        # Refresh clip detail preview if showing
        if self._detail_idx is not None and self._clip_preview is not None:
            self._clip_preview.set_crop(self._effective_crop(self._detail_idx))
        self._save_all()

    # ── Style preview refresh ────────────────────────────────────────────

    def _schedule_style_preview_refresh(self) -> None:
        if self._style_preview is None:
            return
        if self._preview_job is not None:
            try:
                self.master.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.master.after(
            self._PREVIEW_DEBOUNCE_MS, self._do_style_preview_refresh)

    def _do_style_preview_refresh(self) -> None:
        self._preview_job = None
        if self._style_preview is None:
            return
        self._style_preview.set_style(self._current_style)
        self._style_preview.enable_crop_drag(True)
        if self._global_crop_rect is not None:
            self._style_preview.set_crop(self._global_crop_rect)
        # Load source video (whole file) as preview backdrop
        video_path = _nv_paths.source_video_path(self.project, self.material_instance_id)
        if os.path.isfile(video_path):
            self._style_preview.set_source(video_path, 0.0, 0.0)
            # Push the full SRT so the subtitle layer shows real text as
            # playback advances, not a static placeholder.
            self._style_preview.set_cues(self._full_srt_cues())
            # Sample hook from first candidate so the user sees what real
            # hooks look like with their style.
            if self._candidate_meta:
                first = self._candidate_meta[0]
                sample_hook = (first.get("hook")
                                or first.get("suggested_title")
                                or tr("clip_tool.sample_hook_placeholder"))
                sample_outro = first.get("outro") or ""
            else:
                sample_hook = tr("clip_tool.sample_hook_placeholder")
                sample_outro = ""
            self._style_preview.set_clip_meta(
                hook=sample_hook, outro=sample_outro,
                hook_lines=self._wrap_for_overlay(sample_hook),
                outro_lines=self._wrap_for_overlay(sample_outro))

    def _push_clip_preview_style(self) -> None:
        """Re-push style + re-split cues to the clip detail preview. Called
        whenever the user changes anything that affects subtitle layout."""
        if self._clip_preview is None or self._detail_idx is None:
            return
        self._clip_preview.set_style(self._current_style)
        start, end = self._effective_start_end(self._detail_idx)
        self._clip_preview.set_cues(self._cues_for_window(start, end))

    # ── Form → style sync ────────────────────────────────────────────────

    def _populate_form_from_style(self) -> None:
        if not hasattr(self, "_aspect_var"):
            return
        self._suspend_traces = True
        try:
            s = self._current_style
            self._aspect_var.set(s.output.aspect)
            self._encode_preset_var.set(s.encode_preset)
            sub = s.subtitle
            self._sub1_enabled.set(sub.sub1.enabled)
            self._sub1_fontsize.set(sub.sub1.fontsize)
            self._sub1_color.set(sub.sub1.color)
            self._sub1_bold.set(sub.sub1.bold)
            self._sub1_is_chinese.set(sub.sub1.is_chinese)
            self._sub2_enabled.set(sub.sub2.enabled)
            self._sub2_fontsize.set(sub.sub2.fontsize)
            self._sub2_color.set(sub.sub2.color)
            self._sub2_bold.set(sub.sub2.bold)
            self._sub2_is_chinese.set(sub.sub2.is_chinese)
            self._sub_stroke_color.set(sub.stroke_color)
            self._sub_stroke_width.set(sub.stroke_width)
            self._sub_position.set(sub.position)
            self._sub_block_margin_pct.set(round(sub.block_margin_pct * 100.0, 1))
            self._sub_track_gap_pct.set(round(sub.track_gap_pct * 100.0, 1))
            w = s.watermark
            self._wm_enabled.set(w.enabled)
            self._wm_type.set(w.type)
            self._wm_position.set(w.position)
            self._wm_image_path.set(w.image_path)
            self._wm_image_scale.set(w.image_scale)
            self._wm_image_opacity.set(w.image_opacity)
            self._wm_text.set(w.text)
            self._wm_text_fontsize.set(w.text_fontsize)
            self._wm_text_color.set(w.text_color)
            self._wm_text_opacity.set(w.text_opacity)
            self._wm_margin_x_pct.set(round(w.margin_x_pct * 100.0, 1))
            self._wm_margin_y_pct.set(round(w.margin_y_pct * 100.0, 1))
            h = s.hook_outro
            self._ho_font.set(h.font)
            self._ho_size.set(h.size)
            self._ho_color.set(h.color)
            self._ho_bg_color.set(h.bg_color)
            self._ho_bg_opacity.set(h.bg_opacity)
            self._ho_stroke_color.set(h.stroke_color)
            self._ho_stroke_width.set(h.stroke_width)
            self._ho_box_padding.set(h.box_padding)
            self._ho_hook_position.set(h.hook_position)
            self._ho_outro_position.set(h.outro_position)
            self._ho_hook_duration.set(h.hook_duration_sec)
            self._ho_outro_duration.set(h.outro_duration_sec)
        finally:
            self._suspend_traces = False
        self._schedule_style_preview_refresh()
        self._push_clip_preview_style()

    def _read_form_into_style(self) -> None:
        from core.composition import (
            SubtitleStyle, SubtitleLineStyle, WatermarkStyle,
            HookOutroStyle,
        )
        from core.composition.style import OutputGeometry
        self._current_style = CompositionStyle(
            output=OutputGeometry(
                mode=self._current_style.output.mode,
                aspect=self._aspect_var.get(),
                short_edge=self._current_style.output.short_edge,
            ),
            encode_preset=self._encode_preset_var.get(),
            subtitle=SubtitleStyle(
                sub1=SubtitleLineStyle(
                    enabled=self._sub1_enabled.get(),
                    fontsize=int(self._sub1_fontsize.get()),
                    color=self._sub1_color.get(),
                    bold=self._sub1_bold.get(),
                    is_chinese=self._sub1_is_chinese.get(),
                ),
                sub2=SubtitleLineStyle(
                    enabled=self._sub2_enabled.get(),
                    fontsize=int(self._sub2_fontsize.get()),
                    color=self._sub2_color.get(),
                    bold=self._sub2_bold.get(),
                    is_chinese=self._sub2_is_chinese.get(),
                ),
                stroke_color=self._sub_stroke_color.get(),
                stroke_width=int(self._sub_stroke_width.get()),
                position=self._sub_position.get(),
                block_margin_pct=float(self._sub_block_margin_pct.get()) / 100.0,
                track_gap_pct=float(self._sub_track_gap_pct.get()) / 100.0,
            ),
            watermark=WatermarkStyle(
                enabled=self._wm_enabled.get(),
                type=self._wm_type.get(),
                position=self._wm_position.get(),
                margin_x_pct=float(self._wm_margin_x_pct.get()) / 100.0,
                margin_y_pct=float(self._wm_margin_y_pct.get()) / 100.0,
                image_path=self._wm_image_path.get(),
                image_scale=float(self._wm_image_scale.get()),
                image_opacity=int(self._wm_image_opacity.get()),
                text=self._wm_text.get(),
                text_fontsize=int(self._wm_text_fontsize.get()),
                text_color=self._wm_text_color.get(),
                text_opacity=int(self._wm_text_opacity.get()),
            ),
            hook_outro=HookOutroStyle(
                font=self._ho_font.get(),
                size=int(self._ho_size.get()),
                color=self._ho_color.get(),
                bg_color=self._ho_bg_color.get(),
                bg_opacity=int(self._ho_bg_opacity.get()),
                stroke_color=self._ho_stroke_color.get(),
                stroke_width=int(self._ho_stroke_width.get()),
                box_padding=int(self._ho_box_padding.get()),
                hook_position=self._ho_hook_position.get(),
                outro_position=self._ho_outro_position.get(),
                hook_duration_sec=float(self._ho_hook_duration.get()),
                outro_duration_sec=float(self._ho_outro_duration.get()),
            ),
            overlay_styles=dict(self._current_style.overlay_styles),
        )

    def _on_form_changed(self) -> None:
        if self._suspend_traces:
            return
        try:
            self._read_form_into_style()
        except (tk.TclError, ValueError):
            return
        self._schedule_style_preview_refresh()
        self._push_clip_preview_style()
        self._save_all()

    # ── Preset handlers ──────────────────────────────────────────────────

    def _on_preset_applied(self) -> None:
        name = self._preset_name_var.get()
        if not name:
            return
        style = comp_presets.get_project_preset(self._project_store, name)
        if style is None:
            return
        self._current_style = style
        self._populate_form_from_style()
        comp_presets.set_last_used_project(self._project_store, name)
        comp_presets.save_project_store(self._project_store)
        self._refresh_preset_combos()
        self._save_all()

    def _on_preset_save_as(self) -> None:
        name = simpledialog.askstring(
            tr("clip_tool.dlg_preset_save_title"),
            tr("clip_tool.dlg_preset_save_prompt"),
            parent=self.master)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self._project_store.get("presets", {}):
            messagebox.showwarning(
                "VideoCraft",
                tr("clip_tool.warn_preset_taken", name=name),
                parent=self.master)
            return
        self._read_form_into_style()
        comp_presets.upsert_project_preset(
            self._project_store, name, self._current_style)
        comp_presets.set_last_used_project(self._project_store, name)
        comp_presets.save_project_store(self._project_store)
        self._preset_name_var.set(name)
        self._refresh_preset_combos()
        self._save_all()

    def _on_preset_overwrite(self) -> None:
        name = self._preset_name_var.get()
        if not name or comp_presets.is_builtin_project(name):
            messagebox.showinfo(
                "VideoCraft",
                tr("clip_tool.info_builtin_protected"),
                parent=self.master)
            return
        self._read_form_into_style()
        comp_presets.upsert_project_preset(
            self._project_store, name, self._current_style)
        comp_presets.save_project_store(self._project_store)
        self._save_all()

    def _on_preset_delete(self) -> None:
        name = self._preset_name_var.get()
        if not name or comp_presets.is_builtin_project(name):
            messagebox.showinfo(
                "VideoCraft",
                tr("clip_tool.info_builtin_protected"),
                parent=self.master)
            return
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_delete", name=name),
                parent=self.master):
            return
        if comp_presets.delete_project_preset(self._project_store, name):
            comp_presets.save_project_store(self._project_store)
            self._preset_name_var.set(comp_presets.BUILTIN_DEFAULT_PROJECT)
            self._on_preset_applied()
            self._refresh_preset_combos()

    def _on_ho_preset_applied(self) -> None:
        name = self._ho_preset_var.get()
        if not name:
            return
        h = comp_presets.get_hook_outro_preset(self._hook_outro_store, name)
        if h is None:
            return
        self._suspend_traces = True
        try:
            self._ho_font.set(h.font)
            self._ho_size.set(h.size)
            self._ho_color.set(h.color)
            self._ho_bg_color.set(h.bg_color)
            self._ho_bg_opacity.set(h.bg_opacity)
            self._ho_stroke_color.set(h.stroke_color)
            self._ho_stroke_width.set(h.stroke_width)
            self._ho_box_padding.set(h.box_padding)
            self._ho_hook_position.set(h.hook_position)
            self._ho_outro_position.set(h.outro_position)
            self._ho_hook_duration.set(h.hook_duration_sec)
            self._ho_outro_duration.set(h.outro_duration_sec)
        finally:
            self._suspend_traces = False
        self._read_form_into_style()
        comp_presets.set_last_used_hook_outro(self._hook_outro_store, name)
        comp_presets.save_hook_outro_store(self._hook_outro_store)
        self._schedule_style_preview_refresh()
        self._push_clip_preview_style()
        self._save_all()

    def _refresh_preset_combos(self) -> None:
        names = comp_presets.list_project_presets(self._project_store)
        if hasattr(self, "_preset_combo"):
            self._preset_combo["values"] = names
        if hasattr(self, "_preset_combo_quick"):
            self._preset_combo_quick["values"] = names
        if hasattr(self, "_ho_preset_combo"):
            self._ho_preset_combo["values"] = (
                comp_presets.list_hook_outro_presets(self._hook_outro_store))

    def _browse_watermark(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.master,
            filetypes=[("Image", "*.png *.jpg *.jpeg *.bmp")])
        if path:
            self._wm_image_path.set(path)

    # ── Tab 3: Render queue ──────────────────────────────────────────────

    def _refresh_overview(self) -> None:
        if not hasattr(self, "_overview_var"):
            return
        sel = sum(1 for v in self._candidate_vars if v.get())
        total = len(self._candidate_vars)
        self._overview_var.set(tr(
            "clip_tool.overview_fmt",
            preset=self._preset_name_var.get() or "(none)",
            lang=self._lang_var.get() or "(none)",
            selected=sel, total=total))

    def _refresh_render_tv(self) -> None:
        if not hasattr(self, "_render_tv"):
            return
        self._render_tv.delete(*self._render_tv.get_children())
        # Show only selected candidates, in selection order with re-numbered idx
        selected = [i for i, v in enumerate(self._candidate_vars) if v.get()]
        for out_idx, src_idx in enumerate(selected, 1):
            start, end = self._effective_start_end(src_idx)
            duration = end - start
            status = self._render_status.get(src_idx, "queued")
            status_label = tr(f"clip_tool.status_{status}") if status else ""
            hook = self._effective_hook(src_idx)
            self._render_tv.insert(
                "", "end", iid=f"src_{src_idx}",
                values=(out_idx,
                         f"#{src_idx + 1}",
                         f"{duration:.1f}s",
                         status_label,
                         hook[:60]))

    def _on_render(self) -> None:
        selected = [i for i, v in enumerate(self._candidate_vars) if v.get()]
        if not selected:
            messagebox.showinfo(
                "VideoCraft", tr("clip_tool.warn_no_selection"),
                parent=self.master)
            return
        video_path = _nv_paths.source_video_path(self.project, self.material_instance_id)
        if not os.path.isfile(video_path):
            messagebox.showerror(
                "VideoCraft", tr("clip_tool.err_no_source"),
                parent=self.master)
            return

        # Conflict check
        inst = self._instance_dir()
        os.makedirs(inst, exist_ok=True)
        existing: list[tuple[int, str]] = []   # (output_idx, file)
        for out_idx, _src_idx in enumerate(selected, 1):
            mp4 = self._find_clip_mp4(out_idx)
            if mp4:
                existing.append((out_idx, os.path.basename(mp4)))
        skip_indices: set[int] = set()
        if existing:
            action = self._prompt_conflict(existing)
            if action == "cancel":
                return
            if action == "skip":
                skip_indices = {oi for oi, _ in existing}

        self._read_form_into_style()
        self._save_all()

        # Build requests
        srt_path = self._resolve_source_srt()
        requests: list[tuple[int, int, CompositionRequest]] = []  # (out_idx, src_idx, req)
        for out_idx, src_idx in enumerate(selected, 1):
            if out_idx in skip_indices:
                continue
            start, end = self._effective_start_end(src_idx)
            if end <= start:
                continue
            base = self._clip_basename(out_idx, src_idx)
            out_path = os.path.join(inst, base + ".mp4")
            requests.append((out_idx, src_idx, CompositionRequest(
                source_video=video_path,
                start_sec=start, end_sec=end,
                output_path=out_path,
                style=self._current_style,
                source_srt=srt_path,
                hook_text=self._effective_hook(src_idx),
                outro_text=self._effective_outro(src_idx),
                crop_rect=self._effective_crop(src_idx),
            )))

        if not requests:
            messagebox.showinfo(
                "VideoCraft", tr("clip_tool.warn_no_valid_plan"),
                parent=self.master)
            return

        self._cancel_flag = False
        self._render_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        for _o, src_idx, _r in requests:
            self._render_status[src_idx] = "queued"
        self._refresh_render_tv()
        self.set_busy(tr("clip_tool.rendering"))
        self._render_thread = threading.Thread(
            target=self._render_worker, args=(requests,), daemon=True)
        self._render_thread.start()

    def _prompt_conflict(self, existing: list[tuple[int, str]]) -> str:
        n = len(existing)
        files = "\n".join(f"  · {f}" for _o, f in existing[:5])
        if n > 5:
            files += "\n  ..."
        dlg = tk.Toplevel(self.master)
        dlg.title(tr("clip_tool.conflict_title"))
        dlg.transient(self.master)
        dlg.grab_set()
        result = {"action": "cancel"}
        tk.Label(dlg, text=tr("clip_tool.conflict_body_fmt", n=n),
                 justify="left", anchor="w").pack(padx=12, pady=(12, 4),
                                                    anchor="w")
        tk.Label(dlg, text=files, justify="left", anchor="w",
                 font=("Consolas", 9), fg="#666"
                 ).pack(padx=12, anchor="w")
        btns = tk.Frame(dlg); btns.pack(padx=12, pady=12)

        def _close(action):
            result["action"] = action
            dlg.destroy()
        tk.Button(btns, text=tr("clip_tool.conflict_btn_overwrite"),
                  command=lambda: _close("overwrite"),
                  width=12).pack(side="left", padx=4)
        tk.Button(btns, text=tr("clip_tool.conflict_btn_skip"),
                  command=lambda: _close("skip"),
                  width=12).pack(side="left", padx=4)
        tk.Button(btns, text=tr("clip_tool.conflict_btn_cancel"),
                  command=lambda: _close("cancel"),
                  width=12).pack(side="left", padx=4)
        dlg.wait_window()
        return result["action"]

    def _render_worker(self, requests):
        total = len(requests)
        last_error: Optional[str] = None
        for done, (out_idx, src_idx, req) in enumerate(requests, 1):
            if self._cancel_flag:
                break
            self._current_render_idx = src_idx
            self._render_status[src_idx] = "in_progress"
            self.master.after(
                0, lambda d=done, t=total, oi=out_idx:
                    self._on_render_progress(d - 1, t, oi, 0))

            def _on_pct(_stage, pct, oi=out_idx, d=done, t=total):
                self.master.after(0,
                    lambda: self._on_render_progress(d - 1, t, oi, pct))

            try:
                # If a previous render for this out_idx left files
                # under a different hook (and thus a different
                # basename), wipe them so we never end up with two
                # paired sets for one logical clip.
                new_base = os.path.basename(
                    os.path.splitext(req.output_path)[0])
                for stale in self._existing_clip_files(out_idx):
                    if os.path.splitext(os.path.basename(stale))[0] == new_base:
                        continue
                    try:
                        os.unlink(stale)
                    except OSError:
                        pass

                result = render_composition(
                    req, on_progress=_on_pct,
                    cancel_check=lambda: self._cancel_flag)
                # Sidecar JSON + publish markdown
                self._write_sidecar(req, result, out_idx, src_idx)
                self._write_publish_sidecar(req.output_path)
                self._render_status[src_idx] = "done"
                fname = os.path.basename(req.output_path)
                self._rendered = [
                    r for r in self._rendered
                    if int(r.get("output_index") or -1) != out_idx
                ]
                self._rendered.insert(0, {
                    "file": fname,
                    "source_clip_idx": src_idx,
                    "output_index": out_idx,
                    "duration_sec": result.duration_sec,
                    "rendered_at": datetime.now(timezone.utc)
                                    .isoformat(timespec="seconds"),
                })
            except InterruptedError:
                self._render_status[src_idx] = "queued"
                break
            except Exception as e:
                last_error = f"#{out_idx}: {e}"
                self._render_status[src_idx] = "failed"
                self._set_failure_reason(src_idx, str(e))
            self.master.after(0, self._refresh_render_tv)

        self.master.after(0, lambda err=last_error:
                            self._on_render_done(err))

    def _on_render_progress(self, done: int, total: int,
                              current_out_idx: int, pct: int) -> None:
        if total <= 0:
            return
        overall_pct = ((done + pct / 100.0) / total) * 100
        self._progress_overall["value"] = overall_pct
        self._progress_overall_var.set(tr(
            "clip_tool.progress_overall_fmt",
            done=done, total=total))
        self._progress_current["value"] = pct
        self._progress_current_var.set(tr(
            "clip_tool.progress_current_fmt",
            file=f"clip_{current_out_idx:03d}.mp4",
            pct=pct))
        self._refresh_render_tv()

    def _on_render_done(self, last_error: Optional[str]) -> None:
        self._render_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        self._progress_overall["value"] = 0
        self._progress_current["value"] = 0
        self._progress_overall_var.set("")
        self._progress_current_var.set("")
        self._current_render_idx = None
        self._save_all()
        self._refresh_render_tv()
        if self._cancel_flag:
            self.set_warning(tr("clip_tool.cancelled_msg"))
        elif last_error:
            self.set_warning(tr("clip_tool.done_with_warning"))
        else:
            self.set_done()

    def _on_cancel_render(self) -> None:
        if not self._render_thread or not self._render_thread.is_alive():
            return
        self._cancel_flag = True

    def _write_sidecar(self, req: CompositionRequest, result,
                         out_idx: int, src_idx: int) -> None:
        sidecar_path = os.path.splitext(req.output_path)[0] + ".json"
        meta = self._candidate_meta[src_idx]
        sidecar = {
            "source_clip_idx": src_idx,
            "output_index":   out_idx,
            "filename":       os.path.basename(req.output_path),
            "title":          self._effective_title(src_idx),
            "hashtags":       self._effective_tags(src_idx),
            "hook":           self._effective_hook(src_idx),
            "outro":          self._effective_outro(src_idx),
            "transcript":     meta.get("transcript") or "",
            "why_viral":      meta.get("why_viral") or "",
            "duration_sec":   result.duration_sec,
            "start_sec":      req.start_sec,
            "end_sec":        req.end_sec,
            "score":          meta.get("score"),
            "rendered_at":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(sidecar, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _write_publish_sidecar(self, output_path: str) -> None:
        """Render clip_NNN.md (publish copy for one clip) + rewrite the
        instance's index.md. Best-effort — the video and JSON are
        already on disk; .md files are nice-to-have.
        """
        try:
            from creations.clip.publish import (
                render_clip_publish,
                render_clip_index,
                collect_clip_sidecars,
            )
            inst_dir = os.path.dirname(output_path)
            json_path = os.path.splitext(output_path)[0] + ".json"
            if not os.path.isfile(json_path):
                return
            with open(json_path, "r", encoding="utf-8") as f:
                sidecar = json.load(f)

            lang_iso = (self.project.meta.language.source or "zh")
            project_title = self.project.meta.source.title

            # Per-clip publish.md
            md_path = os.path.splitext(output_path)[0] + ".md"
            md = render_clip_publish(
                project_title=project_title,
                sidecar=sidecar,
                lang_iso=lang_iso,
            )
            with open(md_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)

            # Instance index.md — rescan all clip_*.json so deleted/
            # re-rendered clips stay in sync without bespoke state.
            sidecars = collect_clip_sidecars(inst_dir)
            index_md = render_clip_index(
                project_title=project_title,
                instance_name=self.instance_name,
                sidecars=sidecars,
                rendered_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                lang_iso=lang_iso,
            )
            with open(os.path.join(inst_dir, "index.md"),
                      "w", encoding="utf-8", newline="\n") as f:
                f.write(index_md)
        except Exception as e:
            logger.warning(f"clip publish.md write skipped: {e}")

    def _set_failure_reason(self, src_idx: int, reason: str) -> None:
        # Store last failure text alongside status so the context menu can show it
        ov = self._override(src_idx)
        ov["_last_failure"] = reason

    # ── Render table actions ─────────────────────────────────────────────

    def _on_render_tv_right_click(self, event) -> None:
        row = self._render_tv.identify_row(event.y)
        if not row:
            return
        self._render_tv.selection_set(row)
        self._render_menu.tk_popup(event.x_root, event.y_root)

    def _selected_render_row(self) -> Optional[tuple[int, int]]:
        """Return (out_idx, src_idx) of the selected render-table row."""
        sel = self._render_tv.selection()
        if not sel:
            return None
        iid = sel[0]
        if not iid.startswith("src_"):
            return None
        src_idx = int(iid.split("_", 1)[1])
        selected = [i for i, v in enumerate(self._candidate_vars) if v.get()]
        try:
            out_idx = selected.index(src_idx) + 1
        except ValueError:
            return None
        return (out_idx, src_idx)

    def _on_act_play(self) -> None:
        row = self._selected_render_row()
        if not row:
            return
        out_idx, _ = row
        path = self._find_clip_mp4(out_idx)
        if path and os.path.isfile(path):
            os.startfile(path)

    def _on_act_open_folder(self) -> None:
        path = self._instance_dir()
        if os.path.isdir(path):
            os.startfile(path)

    def _on_act_rerender(self) -> None:
        row = self._selected_render_row()
        if not row:
            return
        out_idx, src_idx = row
        # Single-clip render: build one request, run worker on it
        video_path = _nv_paths.source_video_path(self.project, self.material_instance_id)
        if not os.path.isfile(video_path):
            return
        start, end = self._effective_start_end(src_idx)
        if end <= start:
            return
        base = self._clip_basename(out_idx, src_idx)
        out_path = os.path.join(self._instance_dir(), base + ".mp4")
        # Wipe any prior paired files for this out_idx — hook may have
        # changed, so basename may differ from the existing files. Same
        # cleanup as the bulk-render path runs inside _render_worker;
        # do it eagerly here too so a mid-render cancel can't leave us
        # with both old and new naming side-by-side.
        for stale in self._existing_clip_files(out_idx):
            try:
                os.unlink(stale)
            except OSError:
                pass
        self._read_form_into_style()
        req = CompositionRequest(
            source_video=video_path,
            start_sec=start, end_sec=end,
            output_path=out_path,
            style=self._current_style,
            source_srt=self._resolve_source_srt(),
            hook_text=self._effective_hook(src_idx),
            outro_text="",
            crop_rect=self._effective_crop(src_idx),
        )
        self._cancel_flag = False
        self._render_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self.set_busy(tr("clip_tool.rendering"))
        self._render_thread = threading.Thread(
            target=self._render_worker, args=([(out_idx, src_idx, req)],),
            daemon=True)
        self._render_thread.start()

    def _on_act_delete(self) -> None:
        row = self._selected_render_row()
        if not row:
            return
        out_idx, _ = row
        mp4 = self._find_clip_mp4(out_idx)
        display = os.path.basename(mp4) if mp4 else f"clip_{out_idx:03d}.mp4"
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_delete_output", file=display),
                parent=self.master):
            return
        for p in self._existing_clip_files(out_idx):
            try:
                os.unlink(p)
            except OSError:
                pass
        self._rendered = [r for r in self._rendered
                            if int(r.get("output_index") or -1) != out_idx]
        self._save_all()
        self._refresh_render_tv()

    def _on_act_error_detail(self) -> None:
        row = self._selected_render_row()
        if not row:
            return
        _out_idx, src_idx = row
        ov = self._clips_overrides.get(src_idx) or {}
        reason = ov.get("_last_failure", "")
        if not reason:
            return
        dlg = tk.Toplevel(self.master)
        dlg.title(tr("clip_tool.error_detail_title"))
        dlg.transient(self.master)
        txt = tk.Text(dlg, wrap="word", font=("Consolas", 9), width=80, height=20)
        txt.insert("1.0", reason)
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        tk.Button(dlg, text=tr("clip_tool.btn_close"),
                  command=dlg.destroy).pack(pady=(0, 8))

    def _on_open_folder(self) -> None:
        path = self._instance_dir()
        if os.path.isdir(path):
            os.startfile(path)
