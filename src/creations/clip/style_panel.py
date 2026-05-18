"""Style tab for the clip workbench.

Owns:
  - Tab 1's UI (preset header, scrollable form, style-side preview,
    global-crop bar)
  - All form Tk vars (aspect / encode / subtitle / watermark /
    hook-outro) and their write traces
  - The style-side CompositionPreview
  - Preset apply/save-as/overwrite/delete + the hook_outro preset apply
  - Watermark image browse, global crop callback, apply-to-all

The host owns `_current_style` (the dataclass written into config) and
the language/preset StringVars that bridge Tab 1 with the rest of the
workbench. The panel reads style off the host, mutates it via
read_form_into_style, then pokes host._save_all + repush detail
preview when anything changes.

Host contract — methods/attrs the panel touches:

  Attributes:
    master                        Tk widget root for dialogs
    _current_style                CompositionStyle (read/write)
    _project_store                comp_presets project preset store
    _hook_outro_store             comp_presets hook/outro preset store
    _global_crop_rect             Optional[dict]
    _clips_overrides              dict[int, dict]  per-candidate edits
    _candidate_meta               list[dict]
    material_model                NewsVideoModel
    _detail                       Optional[ClipDetailPanel]

  Methods:
    _full_video_duration() -> float
    _full_srt_cues() -> list[dict]
    _build_preview_timeline(start, end, *, hook, outro) -> Timeline
    _preview_aspect_short_edge() -> (str, int)
    _reload_candidates() -> None
    _save_all() -> None
    _refresh_render_tv() -> None
    _refresh_overview() -> None
"""

from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from typing import Optional

from core.composition import (
    CompositionStyle,
)
from core.composition import presets as comp_presets
from core.composition.preview import CompositionPreview
from i18n import tr


# ── StylePanel ─────────────────────────────────────────────────────────────

class StylePanel:
    """Style tab body — preset / aspect / subtitle / watermark /
    hook-outro form + the style-side preview."""

    _PREVIEW_DEBOUNCE_MS = 120

    def __init__(self, parent: ttk.Frame, host, *,
                  lang_var: tk.StringVar,
                  preset_name_var: tk.StringVar) -> None:
        self._host = host
        self._lang_var = lang_var
        self._preset_name_var = preset_name_var
        self._suspend_traces = False
        self._preview: Optional[CompositionPreview] = None
        self._preview_job: Optional[str] = None
        self._build_tab(parent)

    # ── public surface ────────────────────────────────────────────────────

    @property
    def preview(self) -> Optional[CompositionPreview]:
        return self._preview

    @property
    def lang_combo(self) -> ttk.Combobox:
        return self._lang_combo

    @property
    def status_var(self) -> tk.StringVar:
        return self._status_var

    def destroy_preview(self) -> None:
        if self._preview is not None:
            self._preview.destroy()
            self._preview = None

    def populate_form_from_style(self) -> None:
        if not hasattr(self, "_aspect_var"):
            return
        self._suspend_traces = True
        try:
            s = self._host._current_style
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
        self.schedule_preview_refresh()
        self._repush_clip_preview()

    def read_form_into_style(self) -> None:
        from core.composition import (
            SubtitleStyle, SubtitleLineStyle, WatermarkStyle,
            HookOutroStyle,
        )
        from core.composition.style import OutputGeometry
        cur = self._host._current_style
        self._host._current_style = CompositionStyle(
            output=OutputGeometry(
                mode=cur.output.mode,
                aspect=self._aspect_var.get(),
                short_edge=cur.output.short_edge,
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
            overlay_styles=dict(cur.overlay_styles),
        )

    def schedule_preview_refresh(self) -> None:
        if self._preview is None:
            return
        if self._preview_job is not None:
            try:
                self._host.master.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self._host.master.after(
            self._PREVIEW_DEBOUNCE_MS, self._do_preview_refresh)

    def refresh_preset_combos(self) -> None:
        names = comp_presets.list_project_presets(self._host._project_store)
        if hasattr(self, "_preset_combo"):
            self._preset_combo["values"] = names
        if hasattr(self, "_preset_combo_quick"):
            self._preset_combo_quick["values"] = names
        if hasattr(self, "_ho_preset_combo"):
            self._ho_preset_combo["values"] = (
                comp_presets.list_hook_outro_presets(
                    self._host._hook_outro_store))

    # ── UI build ──────────────────────────────────────────────────────────

    def _build_tab(self, parent) -> None:
        f = tk.Frame(parent, bg="white")
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
                              lambda _e: self._host._reload_candidates())

        tk.Label(header, text=tr("clip_tool.preset_label"),
                 bg="white").pack(side="left")
        self._preset_combo_quick = ttk.Combobox(
            header, textvariable=self._preset_name_var,
            values=comp_presets.list_project_presets(
                self._host._project_store),
            state="readonly", width=28)
        self._preset_combo_quick.pack(side="left", padx=(4, 4))
        self._preset_combo_quick.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_preset_applied())

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

        # Scrollable form
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
        self._build_form(inner)

        # Preview pane with global-crop controls
        crop_bar = tk.Frame(preview_outer, bg="white")
        crop_bar.pack(fill="x", padx=4, pady=(4, 2))
        tk.Label(crop_bar, text=tr("clip_tool.tab1_global_crop_label"),
                 bg="white").pack(side="left")
        ttk.Button(crop_bar, text=tr("clip_tool.btn_apply_crop_to_all"),
                   command=self._on_apply_crop_to_all).pack(side="right")

        self._preview = CompositionPreview(
            preview_outer,
            on_crop_changed=self._on_crop_changed,
            width=420, height=520)
        self._preview.widget.pack(fill="both", expand=True,
                                    padx=4, pady=(0, 4))

        # Bottom info note
        note = tk.Label(
            preview_outer, text=tr("clip_tool.tab1_note_per_clip_content"),
            bg="white", fg="#666", anchor="w", justify="left",
            wraplength=420)
        note.pack(fill="x", padx=4, pady=(0, 4))

        self.schedule_preview_refresh()

    def _build_form(self, parent: ttk.Frame) -> None:
        # Preset row (full controls)
        preset_row = ttk.LabelFrame(parent, text=tr("clip_tool.preset_section"))
        preset_row.pack(fill="x", padx=6, pady=(6, 4))
        self._preset_combo = ttk.Combobox(
            preset_row, textvariable=self._preset_name_var,
            values=comp_presets.list_project_presets(
                self._host._project_store),
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

        s = self._host._current_style

        # Aspect + encode
        ae = ttk.LabelFrame(parent, text=tr("clip_tool.section_output"))
        ae.pack(fill="x", padx=6, pady=4)
        self._aspect_var = tk.StringVar(value=s.output.aspect)
        row = ttk.Frame(ae); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.aspect")).pack(side="left")
        for val in ("9:16", "16:9", "1:1", "4:5"):
            ttk.Radiobutton(row, text=val, variable=self._aspect_var,
                            value=val).pack(side="left", padx=(4, 0))
        self._encode_preset_var = tk.StringVar(value=s.encode_preset)
        row = ttk.Frame(ae); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("clip_tool.encode_preset")).pack(side="left")
        ttk.Combobox(row, textvariable=self._encode_preset_var,
                     values=("ultrafast", "superfast", "veryfast",
                             "faster", "fast", "medium"),
                     state="readonly", width=12).pack(side="left", padx=(4, 0))

        # Subtitle
        sub = ttk.LabelFrame(parent, text=tr("clip_tool.section_subtitle"))
        sub.pack(fill="x", padx=6, pady=4)
        ss = s.subtitle
        self._sub1_enabled = tk.BooleanVar(value=ss.sub1.enabled)
        self._sub1_fontsize = tk.IntVar(value=ss.sub1.fontsize)
        self._sub1_color = tk.StringVar(value=ss.sub1.color)
        self._sub1_bold = tk.BooleanVar(value=ss.sub1.bold)
        self._sub1_is_chinese = tk.BooleanVar(value=ss.sub1.is_chinese)
        self._sub2_enabled = tk.BooleanVar(value=ss.sub2.enabled)
        self._sub2_fontsize = tk.IntVar(value=ss.sub2.fontsize)
        self._sub2_color = tk.StringVar(value=ss.sub2.color)
        self._sub2_bold = tk.BooleanVar(value=ss.sub2.bold)
        self._sub2_is_chinese = tk.BooleanVar(value=ss.sub2.is_chinese)
        self._sub_stroke_color = tk.StringVar(value=ss.stroke_color)
        self._sub_stroke_width = tk.IntVar(value=ss.stroke_width)
        self._sub_position = tk.StringVar(value=ss.position)
        self._sub_block_margin_pct = tk.DoubleVar(value=ss.block_margin_pct * 100.0)
        self._sub_track_gap_pct = tk.DoubleVar(value=ss.track_gap_pct * 100.0)

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
        w = s.watermark
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
        h = s.hook_outro
        self._ho_preset_var = tk.StringVar(
            value=comp_presets.get_last_used_hook_outro(
                self._host._hook_outro_store))
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
            values=comp_presets.list_hook_outro_presets(
                self._host._hook_outro_store),
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

    # ── form/style sync ───────────────────────────────────────────────────

    def _on_form_changed(self) -> None:
        if self._suspend_traces:
            return
        try:
            self.read_form_into_style()
        except (tk.TclError, ValueError):
            return
        self.schedule_preview_refresh()
        self._repush_clip_preview()
        self._host._save_all()

    def _do_preview_refresh(self) -> None:
        self._preview_job = None
        self._push_preview()

    def _push_preview(self) -> None:
        """Push unified state to the Style-tab preview using sample hook /
        outro from candidate 0 and the full SRT range."""
        if self._preview is None:
            return
        video_path = self._host.material_model.source_video_path
        import os
        if not os.path.isfile(video_path):
            return
        duration = self._host._full_video_duration()
        if duration <= 0:
            cues = self._host._full_srt_cues()
            duration = (cues[-1]["end"] + 60.0) if cues else 600.0
        if self._host._candidate_meta:
            first = self._host._candidate_meta[0]
            sample_hook = (first.get("hook")
                            or first.get("suggested_title")
                            or tr("clip_tool.sample_hook_placeholder"))
            sample_outro = first.get("outro") or ""
        else:
            sample_hook = tr("clip_tool.sample_hook_placeholder")
            sample_outro = ""
        self._preview.set_source(video_path, 0.0, 0.0)
        self._preview.set_geometry(self._host._current_style.output)
        if self._host._global_crop_rect is not None:
            self._preview.set_crop(self._host._global_crop_rect)
        self._preview.enable_crop_drag(True)
        aspect, short = self._host._preview_aspect_short_edge()
        tl = self._host._build_preview_timeline(
            0.0, duration, hook=sample_hook, outro=sample_outro)
        self._preview.set_timeline(
            tl, aspect=aspect, short_edge=short)

    def _repush_clip_preview(self) -> None:
        """Tell the host's clip-detail preview to re-render with the new
        style. Safe when the detail panel hasn't been built yet."""
        if getattr(self._host, "_detail", None) is not None:
            self._host._detail.push_preview()

    # ── preset handlers ───────────────────────────────────────────────────

    def _on_preset_applied(self) -> None:
        name = self._preset_name_var.get()
        if not name:
            return
        style = comp_presets.get_project_preset(
            self._host._project_store, name)
        if style is None:
            return
        self._host._current_style = style
        self.populate_form_from_style()
        comp_presets.set_last_used_project(self._host._project_store, name)
        comp_presets.save_project_store(self._host._project_store)
        self.refresh_preset_combos()
        self._host._save_all()

    def _on_preset_save_as(self) -> None:
        name = simpledialog.askstring(
            tr("clip_tool.dlg_preset_save_title"),
            tr("clip_tool.dlg_preset_save_prompt"),
            parent=self._host.master)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self._host._project_store.get("presets", {}):
            messagebox.showwarning(
                "VideoCraft",
                tr("clip_tool.warn_preset_taken", name=name),
                parent=self._host.master)
            return
        self.read_form_into_style()
        comp_presets.upsert_project_preset(
            self._host._project_store, name, self._host._current_style)
        comp_presets.set_last_used_project(self._host._project_store, name)
        comp_presets.save_project_store(self._host._project_store)
        self._preset_name_var.set(name)
        self.refresh_preset_combos()
        self._host._save_all()

    def _on_preset_overwrite(self) -> None:
        name = self._preset_name_var.get()
        if not name or comp_presets.is_builtin_project(name):
            messagebox.showinfo(
                "VideoCraft",
                tr("clip_tool.info_builtin_protected"),
                parent=self._host.master)
            return
        self.read_form_into_style()
        comp_presets.upsert_project_preset(
            self._host._project_store, name, self._host._current_style)
        comp_presets.save_project_store(self._host._project_store)
        self._host._save_all()

    def _on_preset_delete(self) -> None:
        name = self._preset_name_var.get()
        if not name or comp_presets.is_builtin_project(name):
            messagebox.showinfo(
                "VideoCraft",
                tr("clip_tool.info_builtin_protected"),
                parent=self._host.master)
            return
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_delete", name=name),
                parent=self._host.master):
            return
        if comp_presets.delete_project_preset(
                self._host._project_store, name):
            comp_presets.save_project_store(self._host._project_store)
            self._preset_name_var.set(comp_presets.BUILTIN_DEFAULT_PROJECT)
            self._on_preset_applied()
            self.refresh_preset_combos()

    def _on_ho_preset_applied(self) -> None:
        name = self._ho_preset_var.get()
        if not name:
            return
        h = comp_presets.get_hook_outro_preset(
            self._host._hook_outro_store, name)
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
        self.read_form_into_style()
        comp_presets.set_last_used_hook_outro(
            self._host._hook_outro_store, name)
        comp_presets.save_hook_outro_store(self._host._hook_outro_store)
        self.schedule_preview_refresh()
        self._repush_clip_preview()
        self._host._save_all()

    # ── crop / browse ─────────────────────────────────────────────────────

    def _browse_watermark(self) -> None:
        path = filedialog.askopenfilename(
            parent=self._host.master,
            filetypes=[("Image", "*.png *.jpg *.jpeg *.bmp")])
        if path:
            self._wm_image_path.set(path)

    def _on_crop_changed(self, rect: dict) -> None:
        if not rect or "x" not in rect:
            return
        self._host._global_crop_rect = rect
        self._host._save_all()

    def _on_apply_crop_to_all(self) -> None:
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_apply_crop_to_all"),
                parent=self._host.master):
            return
        # Drop per-clip crop_rect entries; keep other override fields
        for idx, ov in list(self._host._clips_overrides.items()):
            ov.pop("crop_rect", None)
            if not ov:
                self._host._clips_overrides.pop(idx, None)
        if getattr(self._host, "_detail", None) is not None:
            self._host._detail.refresh_crop()
        self._host._save_all()
