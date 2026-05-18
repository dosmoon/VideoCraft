"""Style tab for the clip workbench — three-pane component-driven UI.

Layout (mirrors news_desk):
  ┌─────────────────────────────────────────────────────────────┐
  │ [toolbar] lang | aspect | encode | preset combo + buttons   │
  ├──────────────────────────────────┬──────────────────────────┤
  │ [preview]                        │                          │
  │   WebView + crop bar +           │  [property panel]        │
  │   apply-crop-to-all              │  (selected component)    │
  ├──────────────────────────────────┤                          │
  │ [component list] + [+ add] menu  │                          │
  │ ☑ subtitle (primary)             │                          │
  │ ☑ hook card                      │                          │
  │ ☑ outro card                     │                          │
  │ ...                              │                          │
  └──────────────────────────────────┴──────────────────────────┘

Authoritative model: `host.config.components` (list of instance dicts).
Each row in the list maps 1:1 to a component dict. Selection drives
the property panel via the spec's `build_property_panel` callback.

All authoritative state is on host.config (a ClipInstanceConfig).
Output settings (aspect / short_edge / mode / encode_preset) are flat
fields on the config dataclass; preset apply/save uses a thin
CompositionStyle wrapper (presets carry output only, since component
templates are project-level not preset-level).

Host contract — methods/attrs the panel touches:
    Attributes:
      master                 Tk widget root for dialogs
      _project_store         comp_presets project preset store
      _global_crop_rect      Optional[dict]
      _candidate_meta        list[dict]
      config                 ClipInstanceConfig (everything lives here)
      material_model         NewsVideoModel
      _detail                Optional[ClipDetailPanel]
    Methods:
      _full_video_duration() -> float
      _full_srt_cues() -> list[dict]
      _build_preview_timeline(start, end, *, hook, outro) -> Timeline
      _preview_aspect_short_edge() -> (str, int)
      _output_geometry() -> OutputGeometry
      _reload_candidates() -> None
      _save_all() -> None
      _refresh_render_tv() -> None
"""

from __future__ import annotations

import os
import tkinter as tk
from dataclasses import asdict
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional

from core.composition import presets as comp_presets
from core.composition.preview import CompositionPreview
from i18n import tr

from creations.clip import components as cc
from creations.news_desk.components import ProjectContext


_ENCODE_PRESETS = ["ultrafast", "superfast", "veryfast", "faster",
                    "fast", "medium", "slow", "slower"]
_ASPECTS = ["9:16", "1:1", "16:9", "4:5"]


class StylePanel:
    """Style tab body — component-list editor + preview + property pane."""

    _PREVIEW_DEBOUNCE_MS = 120

    def __init__(self, parent: ttk.Frame, host, *,
                  lang_var: tk.StringVar,
                  preset_name_var: tk.StringVar) -> None:
        self._host = host
        self._lang_var = lang_var
        self._preset_name_var = preset_name_var
        self._preview: Optional[CompositionPreview] = None
        self._preview_job: Optional[str] = None
        self._selected_idx: Optional[int] = None
        self._property_frame: Optional[ttk.Frame] = None
        self._comp_tree: Optional[ttk.Treeview] = None
        self._status_var = tk.StringVar(value="")
        self._build_ui(parent)

    # ── public API ────────────────────────────────────────────────────────

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
        """Pull toolbar values out of host.config and refresh the
        component list. Called once at workbench startup and again after
        preset-apply."""
        cfg = self._host.config
        self._aspect_var.set(cfg.output_aspect)
        self._encode_var.set(cfg.encode_preset)
        self.refresh_preset_combos()
        self._reload_component_list()
        self.schedule_preview_refresh()

    def read_form_into_style(self) -> None:
        """Push toolbar values back into host.config. Component edits go
        directly into config.components via the property-panel commits."""
        cfg = self._host.config
        cfg.output_aspect = self._aspect_var.get() or "9:16"
        cfg.encode_preset = self._encode_var.get() or "medium"

    def schedule_preview_refresh(self) -> None:
        if self._preview_job is not None:
            try:
                self._host.master.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self._host.master.after(
            self._PREVIEW_DEBOUNCE_MS, self._do_preview_refresh)

    def refresh_preset_combos(self) -> None:
        names = comp_presets.list_project_presets(self._host._project_store)
        if self._preset_combo is not None:
            self._preset_combo["values"] = names

    # ── UI build ──────────────────────────────────────────────────────────

    def _build_ui(self, parent: ttk.Frame) -> None:
        # Tab notebook tabs are styled at workbench level; we just fill.
        outer = tk.Frame(parent, bg="white")
        outer.pack(fill="both", expand=True)

        self._build_toolbar(outer)

        body = ttk.PanedWindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=3)
        body.add(right, weight=2)

        # Left: preview top, component list bottom (resizable)
        left_split = ttk.PanedWindow(left, orient="vertical")
        left_split.pack(fill="both", expand=True)
        preview_pane = ttk.Frame(left_split)
        list_pane = ttk.Frame(left_split)
        left_split.add(preview_pane, weight=3)
        left_split.add(list_pane, weight=2)

        self._build_preview(preview_pane)
        self._build_component_list(list_pane)

        # Right: scrollable property panel
        self._build_property_pane(right)

        # Without this, clicking any Entry/Spinbox after the WebView2
        # preview has had focus leaves keystrokes stranded in the
        # WebView's input thread.
        from ui.web_preview import attach_focus_grab_fix
        attach_focus_grab_fix(parent)

    def _build_toolbar(self, parent) -> None:
        bar = tk.Frame(parent, bg="white")
        bar.pack(fill="x", padx=6, pady=(6, 4))

        # Language picker (combobox state populated by host._reload_languages)
        tk.Label(bar, text=tr("clip_tool.lang_label"), bg="white"
                 ).pack(side="left")
        self._lang_combo = ttk.Combobox(
            bar, textvariable=self._lang_var, state="readonly", width=10)
        self._lang_combo.pack(side="left", padx=(2, 8))
        self._lang_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._host._reload_candidates())

        # Aspect ratio + encode preset
        tk.Label(bar, text=tr("clip_tool.aspect_label"), bg="white"
                 ).pack(side="left")
        self._aspect_var = tk.StringVar(value="9:16")
        ttk.Combobox(bar, textvariable=self._aspect_var,
                      values=_ASPECTS, state="readonly", width=6
                      ).pack(side="left", padx=(2, 8))
        self._aspect_var.trace_add("write", lambda *_: self._on_output_changed())

        tk.Label(bar, text=tr("clip_tool.encode_label"), bg="white"
                 ).pack(side="left")
        self._encode_var = tk.StringVar(value="medium")
        ttk.Combobox(bar, textvariable=self._encode_var,
                      values=_ENCODE_PRESETS, state="readonly", width=10
                      ).pack(side="left", padx=(2, 8))
        self._encode_var.trace_add("write", lambda *_: self._on_output_changed())

        # Preset section (apply / save-as / overwrite / delete)
        tk.Label(bar, text=tr("clip_tool.preset_section"), bg="white"
                 ).pack(side="left", padx=(12, 2))
        self._preset_combo = ttk.Combobox(
            bar, textvariable=self._preset_name_var,
            state="readonly", width=22)
        self._preset_combo.pack(side="left", padx=(2, 4))
        ttk.Button(bar, text=tr("clip_tool.btn_apply"),
                   command=self._on_preset_applied, width=6
                   ).pack(side="left", padx=(2, 0))
        ttk.Button(bar, text=tr("clip_tool.btn_save_as"),
                   command=self._on_preset_save_as, width=10
                   ).pack(side="left", padx=(2, 0))
        ttk.Button(bar, text=tr("clip_tool.btn_overwrite"),
                   command=self._on_preset_overwrite, width=8
                   ).pack(side="left", padx=(2, 0))
        ttk.Button(bar, text=tr("clip_tool.btn_delete"),
                   command=self._on_preset_delete, width=6
                   ).pack(side="left", padx=(2, 0))

        # Status line (right-aligned)
        tk.Label(bar, textvariable=self._status_var, bg="white",
                 fg="#666").pack(side="right", padx=(4, 0))

    def _build_preview(self, parent) -> None:
        crop_bar = tk.Frame(parent, bg="white")
        crop_bar.pack(fill="x", padx=4, pady=(4, 2))
        tk.Label(crop_bar, text=tr("clip_tool.tab1_global_crop_label"),
                 bg="white").pack(side="left")
        ttk.Button(crop_bar, text=tr("clip_tool.btn_apply_crop_to_all"),
                   command=self._on_apply_crop_to_all
                   ).pack(side="right")

        self._preview = CompositionPreview(
            parent, on_crop_changed=self._on_crop_changed,
            width=420, height=420)
        self._preview.widget.pack(fill="both", expand=True,
                                    padx=4, pady=(0, 4))

    def _build_component_list(self, parent) -> None:
        header = tk.Frame(parent, bg="white")
        header.pack(fill="x", padx=4, pady=(2, 2))
        tk.Label(header, text="组件", bg="white",
                 font=("TkDefaultFont", 10, "bold")).pack(side="left")

        # [+ Add] menu button on the right
        self._add_mb = ttk.Menubutton(header, text="+ 添加")
        self._add_menu = tk.Menu(self._add_mb, tearoff=0)
        self._add_mb["menu"] = self._add_menu
        self._add_mb.pack(side="right")
        ttk.Button(header, text="删除", width=5,
                   command=self._on_remove).pack(side="right", padx=(2, 2))
        ttk.Button(header, text="↓", width=2,
                   command=self._on_move_down).pack(side="right", padx=(2, 0))
        ttk.Button(header, text="↑", width=2,
                   command=self._on_move_up).pack(side="right", padx=(2, 0))

        wrap = ttk.Frame(parent); wrap.pack(fill="both", expand=True,
                                              padx=4, pady=(0, 4))
        self._comp_tree = ttk.Treeview(
            wrap, columns=("on", "kind", "name"), show="headings",
            selectmode="browse", height=8)
        self._comp_tree.heading("on", text="")
        self._comp_tree.heading("kind", text="类型")
        self._comp_tree.heading("name", text="名称")
        self._comp_tree.column("on", width=24, anchor="center", stretch=False)
        self._comp_tree.column("kind", width=120, anchor="w", stretch=False)
        self._comp_tree.column("name", width=140, anchor="w", stretch=True)
        vsb = ttk.Scrollbar(wrap, orient="vertical",
                             command=self._comp_tree.yview)
        self._comp_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._comp_tree.pack(side="left", fill="both", expand=True)
        self._comp_tree.bind("<<TreeviewSelect>>", self._on_list_select)
        # Click in the "on" column toggles enabled
        self._comp_tree.bind("<Button-1>", self._on_tree_click)

        self._rebuild_add_menu()

    def _build_property_pane(self, parent) -> None:
        # Scrollable container so long property panels can fit
        outer = ttk.Frame(parent); outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(
                       scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(inner_id, width=e.width))
        self._property_frame = inner
        self._render_empty_property_pane()

    # ── component list ops ────────────────────────────────────────────────

    def _reload_component_list(self) -> None:
        if self._comp_tree is None:
            return
        self._comp_tree.delete(*self._comp_tree.get_children())
        for i, c in enumerate(self._host.config.components):
            spec = cc.spec_for_instance(c)
            kind_label = (tr(spec.name_key)
                            if spec and spec.name_key.startswith("clip.")
                            else c.get("kind", ""))
            # Spec name_key may not be registered in i18n yet — fall back
            # to a hard-coded Chinese label.
            kind_label = _KIND_LABELS.get(c.get("kind", ""), kind_label)
            checkbox = "☑" if c.get("enabled", True) else "☐"
            self._comp_tree.insert(
                "", "end", iid=str(i),
                values=(checkbox, kind_label, c.get("name", "")))
        if self._selected_idx is not None:
            iid = str(self._selected_idx)
            if self._comp_tree.exists(iid):
                self._comp_tree.selection_set(iid)
            else:
                self._selected_idx = None
                self._render_empty_property_pane()

    def _rebuild_add_menu(self) -> None:
        self._add_menu.delete(0, "end")
        existing_kinds = {c.get("kind")
                            for c in self._host.config.components}
        for spec in cc.all_specs():
            label = _KIND_LABELS.get(spec.kind, spec.kind)
            disabled = (not spec.multi_instance) and (
                spec.kind in existing_kinds)
            self._add_menu.add_command(
                label=label, state=("disabled" if disabled else "normal"),
                command=lambda k=spec.kind: self._on_add(k))

    def _on_add(self, kind: str) -> None:
        spec = cc.spec_for_kind(kind)
        if spec is None:
            return
        duration = self._host._full_video_duration()
        instance = spec.default_instance(duration or 0.0)
        self._host.config.components.append(instance)
        self._selected_idx = len(self._host.config.components) - 1
        self._host._save_all()
        self._reload_component_list()
        self._rebuild_add_menu()
        self._render_property_for_selected()
        self.schedule_preview_refresh()

    def _on_remove(self) -> None:
        if self._selected_idx is None:
            return
        if not messagebox.askyesno("VideoCraft",
                                     "删除选中的组件？",
                                     parent=self._host.master):
            return
        del self._host.config.components[self._selected_idx]
        self._selected_idx = None
        self._host._save_all()
        self._reload_component_list()
        self._rebuild_add_menu()
        self._render_empty_property_pane()
        self.schedule_preview_refresh()

    def _on_move_up(self) -> None:
        idx = self._selected_idx
        if idx is None or idx <= 0:
            return
        comps = self._host.config.components
        comps[idx - 1], comps[idx] = comps[idx], comps[idx - 1]
        self._selected_idx = idx - 1
        self._host._save_all()
        self._reload_component_list()
        self.schedule_preview_refresh()

    def _on_move_down(self) -> None:
        idx = self._selected_idx
        comps = self._host.config.components
        if idx is None or idx >= len(comps) - 1:
            return
        comps[idx + 1], comps[idx] = comps[idx], comps[idx + 1]
        self._selected_idx = idx + 1
        self._host._save_all()
        self._reload_component_list()
        self.schedule_preview_refresh()

    def _on_list_select(self, _e=None) -> None:
        sel = self._comp_tree.selection()
        if not sel:
            self._selected_idx = None
            self._render_empty_property_pane()
            return
        try:
            self._selected_idx = int(sel[0])
        except (TypeError, ValueError):
            self._selected_idx = None
            return
        self._render_property_for_selected()

    def _on_tree_click(self, evt) -> None:
        # Toggle enabled when user clicks the "on" column
        col = self._comp_tree.identify_column(evt.x)
        row = self._comp_tree.identify_row(evt.y)
        if col != "#1" or not row:
            return
        try:
            i = int(row)
        except (TypeError, ValueError):
            return
        comp = self._host.config.components[i]
        comp["enabled"] = not bool(comp.get("enabled", True))
        self._host._save_all()
        self._reload_component_list()
        self.schedule_preview_refresh()

    # ── property pane ─────────────────────────────────────────────────────

    def _render_empty_property_pane(self) -> None:
        if self._property_frame is None:
            return
        for child in self._property_frame.winfo_children():
            child.destroy()
        tk.Label(self._property_frame, text="未选中组件",
                  fg="#888").pack(pady=20)

    def _render_property_for_selected(self) -> None:
        if (self._property_frame is None
                or self._selected_idx is None):
            return
        for child in self._property_frame.winfo_children():
            child.destroy()
        comps = self._host.config.components
        if not (0 <= self._selected_idx < len(comps)):
            return
        instance = comps[self._selected_idx]
        spec = cc.spec_for_instance(instance)
        if spec is None or spec.build_property_panel is None:
            tk.Label(self._property_frame,
                      text=f"未知组件类型: {instance.get('kind', '')}",
                      fg="#c00").pack(pady=20)
            return
        ctx = self._build_project_context()
        spec.build_property_panel(
            self._property_frame, instance, ctx, self._on_property_changed)

    def _build_project_context(self) -> ProjectContext:
        duration = self._host._full_video_duration() or 0.0
        return ProjectContext(
            project=None,
            duration=duration,
            instance_dir=getattr(self._host, "_instance_dir",
                                  lambda: "")(),
            material_model=self._host.material_model,
            seek_to=None)

    def _on_property_changed(self) -> None:
        self._host._save_all()
        self._reload_component_list()
        self.schedule_preview_refresh()

    # ── preview ───────────────────────────────────────────────────────────

    def _do_preview_refresh(self) -> None:
        self._preview_job = None
        self._push_preview()

    def _push_preview(self) -> None:
        if self._preview is None:
            return
        host = self._host
        video_path = host.material_model.source_video_path
        if not os.path.isfile(video_path):
            return
        duration = host._full_video_duration()
        if duration <= 0:
            cues = host._full_srt_cues()
            duration = (cues[-1]["end"] + 60.0) if cues else 600.0
        if host._candidate_meta:
            first = host._candidate_meta[0]
            sample_hook = (first.get("hook")
                            or first.get("suggested_title")
                            or tr("clip_tool.sample_hook_placeholder"))
            sample_outro = first.get("outro") or ""
        else:
            sample_hook = tr("clip_tool.sample_hook_placeholder")
            sample_outro = ""
        self._preview.set_source(video_path, 0.0, 0.0)
        self._preview.set_geometry(host._output_geometry())
        if host._global_crop_rect is not None:
            self._preview.set_crop(host._global_crop_rect)
        self._preview.enable_crop_drag(True)
        aspect, short = host._preview_aspect_short_edge()
        tl = host._build_preview_timeline(
            0.0, duration, hook=sample_hook, outro=sample_outro)
        self._preview.set_timeline(
            tl, aspect=aspect, short_edge=short)

    def _repush_clip_preview(self) -> None:
        if getattr(self._host, "_detail", None) is not None:
            self._host._detail.push_preview()

    def _on_output_changed(self) -> None:
        # Output changes flow into host.config (5.5.c made the fields
        # flat primitives on the config dataclass).
        self.read_form_into_style()
        self._host._save_all()
        self.schedule_preview_refresh()
        self._repush_clip_preview()

    def _on_crop_changed(self, rect: dict) -> None:
        if not rect or "x" not in rect:
            return
        self._host._global_crop_rect = rect

    def _on_apply_crop_to_all(self) -> None:
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_apply_crop_to_all"),
                parent=self._host.master):
            return
        staging = self._host._global_crop_rect
        if staging is None:
            for idx, ov in list(self._host._clips_overrides.items()):
                ov.pop("crop_rect", None)
                if not ov:
                    self._host._clips_overrides.pop(idx, None)
        else:
            for idx in range(len(self._host._candidate_meta)):
                self._host._override(idx)["crop_rect"] = dict(staging)
        if getattr(self._host, "_detail", None) is not None:
            self._host._detail.refresh_crop()
        self._host._save_all()

    # ── preset operations ─────────────────────────────────────────────────
    #
    # Presets in 5.5.c only carry output settings (aspect / short_edge /
    # mode / encode_preset). Component templates stay per-project — they
    # don't roundtrip through the preset store. Persisting via the
    # legacy comp_presets module needs a CompositionStyle wrapper, so
    # we build one with default subtitle/watermark/hook_outro values
    # and only the output fields the user cares about.

    def _on_preset_applied(self) -> None:
        name = self._preset_name_var.get()
        if not name:
            return
        style = comp_presets.get_project_preset(
            self._host._project_store, name)
        if style is None:
            return
        cfg = self._host.config
        cfg.output_aspect = style.output.aspect
        cfg.output_short_edge = int(style.output.short_edge)
        cfg.output_mode = style.output.mode
        cfg.encode_preset = style.encode_preset
        comp_presets.set_last_used_project(
            self._host._project_store, name)
        comp_presets.save_project_store(self._host._project_store)
        self.populate_form_from_style()
        self._host._save_all()

    def _on_preset_save_as(self) -> None:
        name = simpledialog.askstring(
            tr("clip_tool.dlg_preset_save_title"),
            tr("clip_tool.dlg_preset_save_prompt"),
            parent=self._host.master)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self._host._project_store.get("presets", {}):
            messagebox.showwarning(
                "VideoCraft",
                tr("clip_tool.warn_preset_taken", name=name),
                parent=self._host.master)
            return
        self.read_form_into_style()
        comp_presets.upsert_project_preset(
            self._host._project_store, name, self._build_style_for_preset())
        comp_presets.set_last_used_project(
            self._host._project_store, name)
        comp_presets.save_project_store(self._host._project_store)
        self._preset_name_var.set(name)
        self.refresh_preset_combos()
        self._host._save_all()

    def _on_preset_overwrite(self) -> None:
        name = self._preset_name_var.get()
        if not name:
            return
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_preset_overwrite", name=name),
                parent=self._host.master):
            return
        self.read_form_into_style()
        comp_presets.upsert_project_preset(
            self._host._project_store, name, self._build_style_for_preset())
        comp_presets.save_project_store(self._host._project_store)
        self._host._save_all()

    def _on_preset_delete(self) -> None:
        name = self._preset_name_var.get()
        if not name:
            return
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_preset_delete", name=name),
                parent=self._host.master):
            return
        comp_presets.delete_project_preset(
            self._host._project_store, name)
        comp_presets.save_project_store(self._host._project_store)
        self._preset_name_var.set("")
        self.refresh_preset_combos()
        self._host._save_all()

    def _build_style_for_preset(self):
        """Wrap config's output fields into a CompositionStyle so the
        legacy preset store can persist them. subtitle / watermark /
        hook_outro use dataclass defaults — they're not meaningful in
        a preset under the new component model."""
        from core.composition.style import CompositionStyle, OutputGeometry
        cfg = self._host.config
        style = CompositionStyle()
        style.output = OutputGeometry(
            aspect=cfg.output_aspect,
            short_edge=int(cfg.output_short_edge),
            mode=cfg.output_mode)
        style.encode_preset = cfg.encode_preset
        return style


# ── Helpers ─────────────────────────────────────────────────────────────────

_KIND_LABELS = {
    "clip_subtitle": "字幕",
    "clip_text_watermark": "文字水印",
    "clip_image_watermark": "图片水印",
    "clip_hook_card": "Hook 卡片",
    "clip_outro_card": "Outro 卡片",
}
