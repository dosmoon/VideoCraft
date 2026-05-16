"""News-desk workbench — components-based editing.

The window has three middle panes:
  - Component list (left): all project components, ordered top→bottom = z
  - Preview (middle): WebView2 mirror of the burn
  - Property panel (right): the selected component's editor surface

Each component instance is a plain dict the spec owns; the host just
moves dicts around (add / delete / move up/down / serialize). At
render time the host iterates components in list order, asks each
spec for its render fragment, and assembles a CompositionRequest the
existing renderer consumes.

Per-instance config persisted at
  creations/news_desk/<instance>/config.json
holding preset name, components list, and bound_material (ADR-0005).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import tkinter as tk
from dataclasses import asdict, replace
from tkinter import filedialog, messagebox, simpledialog, ttk

from tools.base import ToolBase
from i18n import tr
from hub_logger import logger

import creations
from core.composition import presets as comp_presets
from core.composition.preview import CompositionPreview
from core.composition.render import (
    CompositionRequest, ExtraSubtitleSpec, ExtraWatermarkSpec,
    prepare_subtitle_cues, probe_video_resolution, render_composition,
)
from materials.news_video.model import NewsVideoModel
from core.composition.style import (
    CompositionStyle, SubtitleLineStyle, SubtitleStyle, WatermarkStyle,
)
from ui.dialog_utils import center_dialog_on_parent

# Importing the package triggers each component module's register()
# side effect, populating components.REGISTRY before _build_ui runs.
from creations.news_desk import components as nd_components


DERIVATIVE_TYPE = "news_desk"


# ── helpers ────────────────────────────────────────────────────────────────

_FS_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_filename(name: str, *, max_len: int = 60) -> str:
    """Strip filesystem-unfriendly characters from a chapter title so it
    can be embedded in a per-chapter mp4 filename. Returns the cleaned
    name, trimmed to max_len chars. Empty input → empty string."""
    s = (name or "").strip()
    s = _FS_BAD_CHARS.sub("", s)
    s = s.replace(" ", "_")
    if len(s) > max_len:
        s = s[:max_len].rstrip("_")
    return s


def _probe_duration(video_path: str) -> float:
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15)
        if out.returncode == 0:
            return float(out.stdout.strip())
    except Exception:
        pass
    return 0.0


def _rebase_overlays(overlays: list, ws: float, we: float) -> list:
    """Clip overlays into [ws, we] and rebase to a 0-based timeline.
    Used by the 20-s preview render to match ffmpeg's `-ss ws -to we`."""
    out: list = []
    for ov in overlays:
        start = float(getattr(ov, "start_sec", 0.0))
        end = float(getattr(ov, "end_sec", 0.0))
        if end <= ws or start >= we:
            continue
        new_start = max(0.0, start - ws)
        new_end = min(we - ws, end - ws)
        if new_end <= new_start:
            continue
        out.append(replace(ov, start_sec=new_start, end_sec=new_end))
    return out


# ── App ────────────────────────────────────────────────────────────────────

class NewsDeskApp(ToolBase):
    """News-desk derivative workbench — components edition."""

    def __init__(self, master, project, instance_name):
        if project is None or not instance_name:
            raise ValueError(
                "NewsDeskApp requires both project and instance_name.")

        self.master = master
        self.project = project
        self.instance_name = instance_name

        # Slice Q (ADR-0005): pick or recall the bound material instance.
        from creations import material_binding
        config_path = os.path.join(
            project.creation_instance_dir("news_desk", instance_name),
            "config.json")
        bound = material_binding.get_or_bind(master, project, config_path)
        if bound is None:
            raise RuntimeError("News desk: material binding cancelled.")
        self.material_type, self.material_instance_id = bound
        # Single handle the workbench + every component uses to read
        # upstream material data. Components must NOT reach into the
        # material plugin's path helpers directly — ask the model.
        self.material_model = NewsVideoModel(
            self.project, self.material_instance_id)

        master.title(tr("tool.news_desk.title", instance=instance_name))
        master.geometry("1200x720")

        # Project state.
        self._duration = 0.0
        self._src_w = 0
        self._src_h = 0
        self._processing = False
        self._skip_sidecar = False

        # Components — the editable model. Each entry is a dict the
        # owning spec understands. Order is z-order: index 0 = topmost.
        self._components: list[dict] = []

        # Preset still stored (mostly preserves output geometry / fonts);
        # subtitle / watermark / overlay_styles fields are now
        # superseded by components and ignored at render time.
        self._preset_store = comp_presets.load_news_desk_store()
        last_name = comp_presets.get_last_used_news_desk(self._preset_store)
        self._current_style: CompositionStyle = (
            comp_presets.get_news_desk_preset(self._preset_store, last_name)
            or comp_presets.get_news_desk_preset(
                self._preset_store, comp_presets.BUILTIN_DEFAULT_NEWS_DESK)
            or CompositionStyle()
        )
        self._current_preset_name = last_name

        self._preview: CompositionPreview | None = None

        self._build_ui()
        self._enter_project_mode()

    # ── UI build ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = self.master

        # Bottom: status + progress.
        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="x", padx=8, pady=(4, 8))
        self.label_status = ttk.Label(bottom, text="", foreground="#666")
        self.label_status.pack(side="left", padx=(0, 8))
        self.progress = ttk.Progressbar(
            bottom, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)

        # Top: source + duration + ⋯ menu.
        top = ttk.Frame(root)
        top.pack(side="top", fill="x", padx=8, pady=(8, 4))
        ttk.Label(top, text=tr("tool.news_desk.source.label")
                  ).pack(side="left")
        self.entry_video = ttk.Entry(top, state="readonly")
        self.entry_video.pack(side="left", fill="x", expand=True, padx=(4, 8))
        self.label_duration = ttk.Label(top, text="", foreground="#666")
        self.label_duration.pack(side="left")

        self.top_menubtn = ttk.Menubutton(
            top, text=tr("tool.news_desk.menu.button"), direction="below")
        self.top_menu = tk.Menu(self.top_menubtn, tearoff=0)
        self.top_menubtn["menu"] = self.top_menu
        self.top_menubtn.pack(side="left", padx=(8, 0))

        # Layout per docs/draft/news_desk-ux-v0.3.md §2 (still valid in
        # v0.4 — only the bottom-left content changed from "全片属性栏 +
        # 组件列表" to a single layer list):
        #
        #   ┌──────────────────────┬────────────┐
        #   │   Preview (top)      │ Properties │
        #   ├──────────────────────┤ (full      │
        #   │   Layer list (bot)   │  height)   │
        #   └──────────────────────┴────────────┘
        #
        # Outer = horizontal split (left workspace / right inspector).
        # Left = vertical split (preview on top / list on bottom).
        outer_pw = ttk.PanedWindow(root, orient="horizontal")
        outer_pw.pack(side="top", fill="both", expand=True,
                       padx=4, pady=(0, 4))

        left_outer = ttk.Frame(outer_pw)
        props_outer = ttk.Frame(outer_pw)
        outer_pw.add(left_outer, weight=4)
        outer_pw.add(props_outer, weight=3)

        left_pw = ttk.PanedWindow(left_outer, orient="vertical")
        left_pw.pack(fill="both", expand=True)
        preview_outer = ttk.Frame(left_pw)
        list_outer = ttk.Frame(left_pw)
        left_pw.add(preview_outer, weight=5)
        left_pw.add(list_outer, weight=4)

        self._preview = CompositionPreview(
            preview_outer, width=520, height=400)
        self._preview.widget.pack(fill="both", expand=True, padx=4, pady=4)

        self._build_list_pane(list_outer)
        self._build_property_pane(props_outer)

    # ── List pane ──────────────────────────────────────────────────────────

    def _build_list_pane(self, parent: ttk.Frame) -> None:
        wrap = ttk.LabelFrame(parent, text=tr("tool.news_desk.list.frame"))
        wrap.pack(fill="both", expand=True, padx=4, pady=4)

        cols = ("kind", "name")
        self.list_tree = ttk.Treeview(
            wrap, columns=cols, show="headings", height=14)
        self.list_tree.heading("kind", text=tr("tool.news_desk.list.col.kind"))
        self.list_tree.heading("name", text=tr("tool.news_desk.list.col.name"))
        self.list_tree.column("kind", width=110, anchor="w", stretch=False)
        self.list_tree.column("name", width=180, anchor="w")
        self.list_tree.pack(side="top", fill="both", expand=True,
                              padx=4, pady=4)
        self.list_tree.bind("<<TreeviewSelect>>", self._on_list_select)

        btns = ttk.Frame(wrap); btns.pack(side="top", fill="x", padx=4, pady=2)
        self.add_menubtn = ttk.Menubutton(
            btns, text=tr("tool.news_desk.list.add"), direction="above")
        self.add_menu = tk.Menu(self.add_menubtn, tearoff=0)
        self.add_menubtn["menu"] = self.add_menu
        self.add_menubtn.pack(side="left", padx=2)
        ttk.Button(btns, text=tr("tool.news_desk.delete"),
                   command=self._delete_selected).pack(side="left", padx=2)
        ttk.Button(btns, text=tr("tool.news_desk.list.move_up"), width=3,
                   command=self._move_selected_up).pack(side="left", padx=2)
        ttk.Button(btns, text=tr("tool.news_desk.list.move_down"), width=3,
                   command=self._move_selected_down).pack(side="left", padx=2)

    def _rebuild_add_menu(self) -> None:
        m = self.add_menu
        m.delete(0, "end")
        existing_kinds = {c.get("kind") for c in self._components}
        for spec in nd_components.all_specs():
            label = tr(spec.add_label_key)
            if not spec.multi_instance and spec.kind in existing_kinds:
                m.add_command(label=tr("tool.news_desk.list.singleton_exists",
                                          name=label),
                               state="disabled")
            else:
                m.add_command(label=label,
                               command=lambda s=spec: self._add_component(s))

    def _refresh_list(self) -> None:
        prev_iid = self.list_tree.selection()[0] if self.list_tree.selection() else None
        self.list_tree.delete(*self.list_tree.get_children())
        for i, comp in enumerate(self._components):
            spec = nd_components.spec_for_instance(comp)
            kind_label = tr(spec.name_key) if spec else comp.get("kind", "?")
            name = comp.get("name", "")
            iid = f"i:{i}"
            tags = () if comp.get("enabled", True) else ("disabled",)
            self.list_tree.insert(
                "", "end", iid=iid, values=(kind_label, name), tags=tags)
        self.list_tree.tag_configure("disabled", foreground="#888")
        if prev_iid and prev_iid in self.list_tree.get_children(""):
            self.list_tree.selection_set(prev_iid)
        self._rebuild_add_menu()

    def _selected_index(self) -> int:
        sel = self.list_tree.selection()
        if not sel:
            return -1
        iid = sel[0]
        if not iid.startswith("i:"):
            return -1
        try:
            return int(iid[2:])
        except ValueError:
            return -1

    def _on_list_select(self, _evt=None) -> None:
        self._refresh_property_pane()

    # ── Property pane ──────────────────────────────────────────────────────

    def _build_property_pane(self, parent: ttk.Frame) -> None:
        wrap = ttk.LabelFrame(parent, text=tr("tool.news_desk.props.frame"))
        wrap.pack(fill="both", expand=True, padx=4, pady=4)

        # Scrollable container — property forms can be tall.
        canvas = tk.Canvas(wrap, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._props_inner = ttk.Frame(canvas)
        self._props_inner_id = canvas.create_window(
            (0, 0), window=self._props_inner, anchor="nw")

        def _on_inner_config(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_config(e):
            canvas.itemconfigure(self._props_inner_id, width=e.width)
        self._props_inner.bind("<Configure>", _on_inner_config)
        canvas.bind("<Configure>", _on_canvas_config)

        self._refresh_property_pane()

    def _refresh_property_pane(self) -> None:
        for child in self._props_inner.winfo_children():
            child.destroy()
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._components):
            ttk.Label(self._props_inner,
                      text=tr("tool.news_desk.props.empty"),
                      foreground="#666", wraplength=240, justify="left"
                      ).pack(anchor="w", padx=8, pady=8)
            return

        comp = self._components[idx]
        spec = nd_components.spec_for_instance(comp)
        if spec is None:
            ttk.Label(self._props_inner,
                      text=f"Unknown kind: {comp.get('kind')}",
                      foreground="#a00").pack(anchor="w", padx=8, pady=8)
            return

        ctx = nd_components.ProjectContext(
            project=self.project,
            material_model=self.material_model, duration=self._duration,
            instance_dir=self._instance_dir(),
            seek_to=(self._preview.seek if self._preview else None))

        # Spec-built body.
        body = ttk.Frame(self._props_inner)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        spec.build_property_panel(body, comp, ctx, self._on_panel_changed)

        # Import buttons (one per declared source).
        if spec.import_sources:
            ttk.Separator(self._props_inner, orient="horizontal"
                           ).pack(fill="x", padx=8, pady=4)
            for src in spec.import_sources:
                ttk.Button(self._props_inner, text=tr(src.label_key),
                           command=lambda s=spec, src=src:
                               self._run_import(s, src)
                           ).pack(fill="x", padx=8, pady=2)

    def _on_panel_changed(self) -> None:
        """Live-edit notification from a property panel. Sync the list
        row + preview + persist. Avoid full list rebuild so user keeps
        focus on the field they're editing."""
        idx = self._selected_index()
        if 0 <= idx < len(self._components):
            comp = self._components[idx]
            spec = nd_components.spec_for_instance(comp)
            kind_label = tr(spec.name_key) if spec else comp.get("kind", "?")
            name = comp.get("name", "")
            tags = () if comp.get("enabled", True) else ("disabled",)
            self.list_tree.item(f"i:{idx}",
                                  values=(kind_label, name), tags=tags)
        self._save_instance_config()
        self._push_preview()

    def _run_import(self, spec, source) -> None:
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._components):
            return
        comp = self._components[idx]
        ctx = nd_components.ProjectContext(
            project=self.project,
            material_model=self.material_model, duration=self._duration,
            instance_dir=self._instance_dir())
        try:
            source.handler(comp, ctx)
        except Exception as e:
            logger.warning(f"import {spec.kind}/{source.label_key} failed: {e}")
            messagebox.showerror("VideoCraft", str(e), parent=self.master)
            return
        # Imports may rewrite many fields — refresh the panel + list.
        self._refresh_property_pane()
        self._refresh_list()
        self._save_instance_config()
        self._push_preview()

    # ── Component operations ──────────────────────────────────────────────

    def _add_component(self, spec: nd_components.ComponentSpec) -> None:
        if not spec.multi_instance:
            for c in self._components:
                if c.get("kind") == spec.kind:
                    return
        instance = spec.default_instance(self._duration)
        # Insert at z position dictated by spec.default_z. List order:
        # higher default_z → closer to top of list (earlier index).
        # Find first existing component whose default_z is lower.
        insert_at = len(self._components)
        for i, c in enumerate(self._components):
            other_spec = nd_components.spec_for_instance(c)
            if other_spec and other_spec.default_z < spec.default_z:
                insert_at = i
                break
        self._components.insert(insert_at, instance)
        self._refresh_list()
        self.list_tree.selection_set(f"i:{insert_at}")
        self._refresh_property_pane()
        self._save_instance_config()
        self._push_preview()

    def _delete_selected(self) -> None:
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._components):
            return
        del self._components[idx]
        self._refresh_list()
        self._refresh_property_pane()
        self._save_instance_config()
        self._push_preview()

    def _move_selected_up(self) -> None:
        idx = self._selected_index()
        if idx <= 0:
            return
        self._components[idx - 1], self._components[idx] = \
            self._components[idx], self._components[idx - 1]
        self._refresh_list()
        self.list_tree.selection_set(f"i:{idx - 1}")
        self._refresh_property_pane()
        self._save_instance_config()
        self._push_preview()

    def _move_selected_down(self) -> None:
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._components) - 1:
            return
        self._components[idx + 1], self._components[idx] = \
            self._components[idx], self._components[idx + 1]
        self._refresh_list()
        self.list_tree.selection_set(f"i:{idx + 1}")
        self._refresh_property_pane()
        self._save_instance_config()
        self._push_preview()

    # ── Top-bar ⋯ menu (preset + render actions) ──────────────────────────

    def _rebuild_top_menu(self) -> None:
        m = self.top_menu
        m.delete(0, "end")

        pmenu = tk.Menu(m, tearoff=0)
        names = comp_presets.list_news_desk_presets(self._preset_store)
        cur = self._current_preset_name or ""
        if cur:
            pmenu.add_command(
                label=tr("tool.news_desk.menu.preset.current", name=cur),
                state="disabled")
            pmenu.add_separator()
        for name in names:
            pmenu.add_radiobutton(
                label=name, value=name,
                variable=tk.StringVar(value=cur),
                command=lambda n=name: self._select_preset(n))
        pmenu.add_separator()
        pmenu.add_command(label=tr("tool.news_desk.preset.save"),
                           command=self._on_preset_save)
        pmenu.add_command(label=tr("tool.news_desk.preset.save_as"),
                           command=self._on_preset_save_as)
        pmenu.add_command(label=tr("tool.news_desk.preset.delete"),
                           command=self._on_preset_delete)
        m.add_cascade(label=tr("tool.news_desk.menu.preset"), menu=pmenu)

        m.add_separator()
        m.add_command(label=tr("tool.news_desk.action.preview_render"),
                       command=self._do_preview_render)
        m.add_command(label=tr("tool.news_desk.action.export"),
                       command=self._do_export)

    def _select_preset(self, name: str) -> None:
        style = comp_presets.get_news_desk_preset(self._preset_store, name)
        if style is None:
            return
        self._current_style = style
        self._current_preset_name = name
        comp_presets.set_last_used_news_desk(self._preset_store, name)
        comp_presets.save_news_desk_store(self._preset_store)
        self._save_instance_config()
        self._push_preview()
        self._rebuild_top_menu()

    def _on_preset_save(self) -> None:
        name = self._current_preset_name
        if not name or comp_presets.is_builtin_news_desk(name):
            return self._on_preset_save_as()
        comp_presets.upsert_news_desk_preset(
            self._preset_store, name, self._current_style)
        comp_presets.save_news_desk_store(self._preset_store)

    def _on_preset_save_as(self) -> None:
        name = simpledialog.askstring(
            "VideoCraft", tr("tool.news_desk.preset.save_as.prompt"),
            parent=self.master)
        if not name:
            return
        comp_presets.upsert_news_desk_preset(
            self._preset_store, name, self._current_style)
        comp_presets.set_last_used_news_desk(self._preset_store, name)
        comp_presets.save_news_desk_store(self._preset_store)
        self._current_preset_name = name
        self._save_instance_config()
        self._rebuild_top_menu()

    def _on_preset_delete(self) -> None:
        name = self._current_preset_name
        if not name:
            return
        if comp_presets.is_builtin_news_desk(name):
            messagebox.showinfo(
                "VideoCraft",
                tr("tool.news_desk.preset.delete.builtin_protected"),
                parent=self.master)
            return
        if not comp_presets.delete_news_desk_preset(self._preset_store, name):
            return
        comp_presets.save_news_desk_store(self._preset_store)
        names = comp_presets.list_news_desk_presets(self._preset_store)
        if names:
            self._select_preset(names[0])
        else:
            self._rebuild_top_menu()

    # ── Project mode ──────────────────────────────────────────────────────

    def _enter_project_mode(self) -> None:
        type_disp = creations.display_name(DERIVATIVE_TYPE)
        self.master.title(tr("tool.news_desk.project.title",
                              type=type_disp, instance=self.instance_name))

        src = self.material_model.source_video_path
        self.entry_video.config(state="normal")
        self.entry_video.delete(0, tk.END)
        self.entry_video.insert(0, src)
        self.entry_video.config(state="readonly")

        os.makedirs(self._instance_dir(), exist_ok=True)

        self._load_instance_config()

        if os.path.isfile(src):
            self._duration = _probe_duration(src)
            self._src_w, self._src_h = probe_video_resolution(src)
            if self._duration > 0:
                hms = time.strftime("%H:%M:%S", time.gmtime(self._duration))
                self.label_duration.config(
                    text=tr("tool.news_desk.duration_fmt", hms=hms))

        self._rebuild_top_menu()
        self._refresh_list()
        self._refresh_property_pane()

        if self._preview is not None:
            try:
                self._preview.set_source(src, 0.0, 0.0)
            except Exception as e:
                logger.warning(f"news_desk: preview set_source failed: {e}")
        self._push_preview()

        comp_presets.save_news_desk_store(self._preset_store)

    # ── Per-instance paths + config ───────────────────────────────────────

    def _instance_dir(self) -> str:
        return self.project.creation_instance_dir(DERIVATIVE_TYPE, self.instance_name)

    def _config_path(self) -> str:
        return os.path.join(self._instance_dir(), "config.json")

    def _output_path(self) -> str:
        return os.path.join(self._instance_dir(), "output.mp4")

    def _load_instance_config(self) -> None:
        path = self._config_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"news_desk config load failed: {e}")
            return
        if not isinstance(cfg, dict):
            return

        # Restore preset (may have been deleted between sessions).
        name = cfg.get("preset_name")
        if isinstance(name, str):
            style = comp_presets.get_news_desk_preset(self._preset_store, name)
            if style is not None:
                self._current_style = style
                self._current_preset_name = name

        # Components list — pre-alpha schema is just `components: [...]`.
        components = cfg.get("components")
        if isinstance(components, list):
            self._components = [c for c in components if isinstance(c, dict)]
        else:
            self._components = []

    def _save_instance_config(self) -> None:
        cfg = {
            "preset_name": self._current_preset_name,
            "components": self._components,
        }
        path = self._config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ── Render translation: components → CompositionRequest fragments ────

    def _build_render_inputs(self) -> tuple[CompositionStyle,
                                              list[ExtraSubtitleSpec],
                                              list[WatermarkStyle], list]:
        """Translate the current components list into:
          (CompositionStyle with sub1/sub2 + style.watermark disabled,
           list of ExtraSubtitleSpec — one per enabled subtitle component,
           list of WatermarkStyle — one per enabled watermark component,
           overlay list — chapter cards, lower thirds, etc.).
        Renderer + preview are then driven by these uniformly.
        """
        # Start from preset's CompositionStyle but reset the parts
        # components own (subtitle + watermark). Preserves output
        # geometry, encode preset, hook/outro, overlay style library.
        style = replace(self._current_style,
                          subtitle=SubtitleStyle(),
                          watermark=WatermarkStyle(enabled=False))

        ctx = nd_components.ProjectContext(
            project=self.project,
            material_model=self.material_model, duration=self._duration,
            instance_dir=self._instance_dir())

        # Component list position drives z-order: top of list = topmost
        # render layer. We assign z = (N - index) * 1000 so each
        # component lands at a unique z with room (the *1000 spacing
        # leaves slots for overlay-internal z if a single component
        # produces multiple specs — though in practice today it doesn't).
        overlays: list = []
        extra_subs: list[ExtraSubtitleSpec] = []
        extra_wms: list[ExtraWatermarkSpec] = []
        total = len(self._components)

        for index, comp in enumerate(self._components):
            spec = nd_components.spec_for_instance(comp)
            if spec is None:
                continue
            try:
                frag = spec.to_overlays(comp, ctx) or {}
            except Exception as e:
                logger.warning(
                    f"news_desk: {spec.kind} render fragment failed: {e}")
                continue
            z = (total - index) * 1000

            ov = frag.get("overlays")
            if isinstance(ov, list):
                for o in ov:
                    # Overlay specs already carry z_order (used as a
                    # tie-breaker for fine ordering inside one component);
                    # we override with the list-derived z so UI order
                    # wins. The overlay dataclasses are mutable.
                    try:
                        o.z_order = z
                    except Exception:
                        pass
                    overlays.append(o)

            wm = frag.get("watermark")
            if wm is not None:
                extra_wms.append(ExtraWatermarkSpec(watermark=wm, z_order=z))

            sub = frag.get("subtitle")
            if sub is not None:
                srt_path = sub.get("srt_path") or ""
                if srt_path:
                    extra_subs.append(ExtraSubtitleSpec(
                        srt_path=srt_path,
                        line=sub["line"],
                        position=sub.get("position", "bottom"),
                        block_margin_pct=sub.get("block_margin_pct", 0.09),
                        z_order=z,
                    ))

        # All subtitles + watermarks ride the N-track render path. The
        # legacy sub1/sub2 + style.watermark slots are kept disabled —
        # news_desk components are independent instances by design (each
        # carries its own position + style), not a shared-layout pair.
        style.subtitle.sub1.enabled = False
        style.subtitle.sub2.enabled = False

        return style, extra_subs, extra_wms, overlays

    # ── Preview push ──────────────────────────────────────────────────────

    def _push_preview(self) -> None:
        if self._preview is None:
            return
        try:
            style, extra_subs, extra_wms, overlays = self._build_render_inputs()
            self._preview.set_style(style)
            self._preview.set_overlays(overlays)
            short = (min(self._src_w, self._src_h)
                      if self._src_w and self._src_h else 1080)
            aspect = (f"{self._src_w}:{self._src_h}"
                       if self._src_w and self._src_h else "16:9")
            # Legacy sub1/sub2 stack stays empty — news_desk components
            # ride the N-track extras path, where each track anchors
            # independently (no shared track_gap).
            self._preview.set_cues([])
            self._preview.set_cues_secondary([])
            sub_payload = []
            for es in extra_subs:
                cues = prepare_subtitle_cues(
                    es.srt_path, es.line, aspect=aspect, short_edge=short)
                sub_payload.append({
                    "line": {
                        "fontsize": es.line.fontsize,
                        "color": es.line.color,
                        "bold": es.line.bold,
                        "is_chinese": es.line.is_chinese,
                        "bg_color": es.line.bg_color,
                        "bg_opacity": es.line.bg_opacity,
                        "bg_padding_x_pct": es.line.bg_padding_x_pct,
                    },
                    "position": es.position,
                    "block_margin_pct": es.block_margin_pct,
                    "cues": cues,
                    "z_order": es.z_order,
                })
            self._preview.set_extra_subtitles(sub_payload)
            wm_payload = []
            for ews in extra_wms:
                w = ews.watermark
                wm_payload.append({
                    "enabled": w.enabled,
                    "type": w.type,
                    "text": w.text,
                    "text_fontsize": w.text_fontsize,
                    "text_color": w.text_color,
                    "text_opacity": w.text_opacity,
                    "image_path": w.image_path,
                    "image_scale": w.image_scale,
                    "image_opacity": w.image_opacity,
                    "position": w.position,
                    "margin_x_pct": w.margin_x_pct,
                    "margin_y_pct": w.margin_y_pct,
                    "z_order": ews.z_order,
                })
            self._preview.set_extra_watermarks(wm_payload)
        except Exception as e:
            logger.warning(f"news_desk preview push failed: {e}")

    # ── Export ─────────────────────────────────────────────────────────────

    def _first_enabled_subtitle_comp(self) -> dict | None:
        """Pick the canonical subtitle component for transcript/chapter
        text generation: the first enabled subtitle in list order. Users
        with multiple subtitle tracks (e.g. zh+en) disable the one they
        don't want as the transcript source."""
        for comp in self._components:
            if (comp.get("kind") == "subtitle"
                    and comp.get("enabled", True)
                    and comp.get("srt_path")):
                return comp
        return None

    def _chapter_schedule(self) -> list[dict]:
        """The chapter component's snapshotted schedule, or [] when no
        chapter component exists / it's empty. Per ADR-0003 we read this
        instead of touching upstream analysis.json."""
        for comp in self._components:
            if comp.get("kind") == "chapter":
                return list(comp.get("schedule") or [])
        return []

    def _candidate_titles(self) -> list[str]:
        """Snapshotted candidate titles from the chapter component.
        Same upstream source (analysis.json) as schedule, snapshotted
        together at import time. Empty list when user hasn't imported
        or analysis had no titles."""
        for comp in self._components:
            if comp.get("kind") == "chapter":
                titles = comp.get("titles") or []
                return [str(t).strip() for t in titles if str(t).strip()]
        return []

    @staticmethod
    def _chapters_for_publish(schedule: list[dict]) -> list[dict]:
        """Convert chapter component's schedule dicts to the shape
        publish.py / build_chapter_transcript_text expect.

        Schedule entries carry start_sec/end_sec (floats) + title +
        refined + key_points. Publish wants start/end as HH:MM:SS
        strings on top of that, so callers can render YouTube-style
        timestamp lines. We add the strings here (chapters_io has the
        canonical formatter)."""
        from core.chapters_io import fmt_time_str
        out: list[dict] = []
        for ch in schedule:
            start_sec = float(ch.get("start_sec") or 0.0)
            end_sec = float(ch.get("end_sec") or 0.0)
            out.append({
                "start":      fmt_time_str(start_sec),
                "end":        fmt_time_str(end_sec),
                "start_sec":  start_sec,
                "end_sec":    end_sec,
                "title":      str(ch.get("title", "")),
                "refined":    str(ch.get("refined", "")),
                "key_points": list(ch.get("key_points") or []),
            })
        return out

    def _show_export_options_dialog(self) -> dict | None:
        """Ask the user which deliverables to include in this export.

        Per ADR-0003 the dialog reads off instance state — there's no
        "pick a subtitle language" question because the user already
        picked when they imported subtitle components. Options that
        depend on missing inputs (transcript with no subtitle, chapter
        split with no chapter component) get disabled with an
        explanatory hint.

        Returns {publish, transcript, chapter_videos} on confirm,
        None on cancel. The main mp4 is always produced.
        """
        sub_comp = self._first_enabled_subtitle_comp()
        schedule = self._chapter_schedule()
        has_subtitle = sub_comp is not None
        has_chapters = bool(schedule)

        dlg = tk.Toplevel(self.master)
        dlg.title(tr("tool.news_desk.export_dialog.title"))
        dlg.transient(self.master.winfo_toplevel())
        dlg.grab_set()
        dlg.minsize(500, 300)

        # Pack actions FIRST so they pin to the bottom even if body grows.
        btns = ttk.Frame(dlg)
        btns.pack(side="bottom", fill="x", padx=12, pady=(0, 10))

        body = ttk.Frame(dlg)
        body.pack(fill="both", expand=True, padx=14, pady=12)

        ttk.Label(body,
                  text=tr("tool.news_desk.export_dialog.intro"),
                  wraplength=460, justify="left", foreground="#444"
                  ).pack(anchor="w", pady=(0, 10))

        v_publish        = tk.BooleanVar(value=True)
        v_transcript     = tk.BooleanVar(value=False)
        v_chapter_videos = tk.BooleanVar(value=False)

        opts_spec = [
            (v_publish,
             "tool.news_desk.export_dialog.opt_publish",
             True, ""),
            (v_transcript,
             "tool.news_desk.export_dialog.opt_transcript",
             has_subtitle,
             "" if has_subtitle else tr("tool.news_desk.export_dialog.no_subtitle_hint")),
            (v_chapter_videos,
             "tool.news_desk.export_dialog.opt_chapter_videos",
             has_chapters,
             "" if has_chapters else tr("tool.news_desk.export_dialog.no_chapter_hint")),
        ]

        for var, key, enabled, hint in opts_spec:
            row = ttk.Frame(body)
            row.pack(anchor="w", pady=3, fill="x")
            cb = ttk.Checkbutton(row, text=tr(key), variable=var)
            cb.pack(side="left")
            if not enabled:
                var.set(False)
                cb.configure(state="disabled")
                if hint:
                    ttk.Label(row, text=hint, foreground="#888",
                              font=("TkDefaultFont", 8)
                              ).pack(side="left", padx=(8, 0))

        result: dict | None = None

        def _on_confirm():
            nonlocal result
            result = {
                "publish":        v_publish.get(),
                "transcript":     v_transcript.get(),
                "chapter_videos": v_chapter_videos.get(),
            }
            dlg.destroy()

        ttk.Button(btns,
                   text=tr("tool.news_desk.export_dialog.confirm"),
                   command=_on_confirm
                   ).pack(side="right")
        ttk.Button(btns,
                   text=tr("tool.news_desk.export_dialog.cancel"),
                   command=dlg.destroy
                   ).pack(side="right", padx=(0, 8))
        dlg.bind("<Escape>", lambda _e: dlg.destroy())

        center_dialog_on_parent(dlg, self.master)
        self.master.wait_window(dlg)
        return result

    def _do_export(self) -> None:
        if self._processing:
            return
        src = self.material_model.source_video_path
        if not os.path.isfile(src):
            messagebox.showerror("VideoCraft",
                                  tr("tool.news_desk.error.source_missing"),
                                  parent=self.master)
            return
        if self._duration <= 0:
            self._duration = _probe_duration(src)
        if self._duration <= 0:
            messagebox.showerror("VideoCraft",
                                  tr("tool.news_desk.error.duration"),
                                  parent=self.master)
            return

        opts = self._show_export_options_dialog()
        if opts is None:
            return    # user cancelled

        out = self._output_path()
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if os.path.exists(out):
            if not messagebox.askyesno(
                "VideoCraft",
                tr("tool.news_desk.confirm.overwrite", path=out),
                parent=self.master):
                return

        self._save_instance_config()
        self._export_opts = opts
        self._processing = True
        self._skip_sidecar = False
        self.set_busy()
        self.top_menubtn.config(state="disabled")
        self.label_status.config(
            text=tr("tool.news_desk.status.rendering"))
        self.progress["value"] = 0

        style, extra_subs, extra_wms, overlays = self._build_render_inputs()
        req = CompositionRequest(
            source_video=src,
            start_sec=0.0, end_sec=self._duration,
            output_path=out,
            style=style,
            overlays=overlays,
            extra_subtitles=extra_subs,
            extra_watermarks=extra_wms,
        )
        threading.Thread(
            target=self._export_thread, args=(req,), daemon=True).start()

    def _do_preview_render(self) -> None:
        if self._processing:
            return
        src = self.material_model.source_video_path
        if not os.path.isfile(src):
            messagebox.showerror("VideoCraft",
                                  tr("tool.news_desk.error.source_missing"),
                                  parent=self.master)
            return
        if self._duration <= 0:
            self._duration = _probe_duration(src)
        if self._duration <= 0:
            messagebox.showerror("VideoCraft",
                                  tr("tool.news_desk.error.duration"),
                                  parent=self.master)
            return

        # Anchor: first overlay's start_sec, else t=0.
        style, extra_subs, extra_wms, overlays = self._build_render_inputs()
        anchor = overlays[0].start_sec if overlays else 0.0
        lead_in = 2.0
        window_len = 20.0
        ws = max(0.0, anchor - lead_in)
        we = min(self._duration, ws + window_len)
        if we - ws < 4.0:
            ws = max(0.0, we - window_len)
        if we <= ws:
            messagebox.showerror("VideoCraft",
                                  tr("tool.news_desk.error.duration"),
                                  parent=self.master)
            return

        rebased = _rebase_overlays(overlays, ws, we)
        out = os.path.join(self._instance_dir(), "output.preview.mp4")
        os.makedirs(os.path.dirname(out), exist_ok=True)

        self._save_instance_config()
        self._processing = True
        self._skip_sidecar = True
        self.set_busy()
        self.top_menubtn.config(state="disabled")
        self.label_status.config(
            text=tr("tool.news_desk.status.preview_rendering",
                    start=f"{ws:.1f}", end=f"{we:.1f}"))
        self.progress["value"] = 0

        req = CompositionRequest(
            source_video=src,
            start_sec=ws, end_sec=we,
            output_path=out,
            style=style,
            overlays=rebased,
            extra_subtitles=extra_subs,
            extra_watermarks=extra_wms,
        )
        threading.Thread(
            target=self._export_thread, args=(req,), daemon=True).start()

    def _export_thread(self, req: CompositionRequest) -> None:
        def _on_progress(_stage: str, pct: int):
            try:
                self.master.after(0, self.progress.config, {"value": pct})
            except Exception:
                pass
        try:
            result = render_composition(req, on_progress=_on_progress)
            self.master.after(0, self._on_export_done, result)
        except Exception as e:
            import traceback
            logger.error(f"news_desk render failed: {e}\n{traceback.format_exc()}")
            self.master.after(0, self._on_export_failed, str(e))

    def _on_export_done(self, result) -> None:
        self._processing = False
        self.set_done()
        self.top_menubtn.config(state="normal")
        self.label_status.config(
            text=tr("tool.news_desk.status.done", path=result.output_path))
        self.progress["value"] = 100
        if getattr(self, "_skip_sidecar", False):
            self._skip_sidecar = False
            return

        opts = getattr(self, "_export_opts", None) or {}

        # Per ADR-0003: read everything from instance state.
        sub_comp = self._first_enabled_subtitle_comp()
        srt_path = self._srt_path_for_subtitle_comp(sub_comp)
        sub_is_chinese = bool((sub_comp or {}).get("is_chinese", False))
        sub_lang_iso = self._lang_iso_for_subtitle_comp(sub_comp)
        chapters = self._chapter_schedule()

        if opts.get("publish", True):
            try:
                self._write_publish_sidecar(
                    chapters=chapters,
                    srt_path=srt_path,
                    sub_lang_iso=sub_lang_iso)
            except Exception as e:
                logger.warning(f"news_desk publish.md write skipped: {e}")

        if opts.get("transcript"):
            self._write_transcript_artifact(srt_path, sub_lang_iso)
        if opts.get("chapter_videos"):
            self._write_chapter_videos_artifact(
                result.output_path, chapters)

    # ── Optional artifacts ────────────────────────────────────────────────

    def _srt_path_for_subtitle_comp(self, comp: dict | None) -> str:
        """Resolve a subtitle component's snapshot SRT to an absolute
        filesystem path. Returns "" when comp is None/no path."""
        if not comp:
            return ""
        from creations.news_desk.components.subtitle import _resolve_srt_path
        ctx = nd_components.ProjectContext(
            project=self.project,
            material_model=self.material_model, duration=self._duration,
            instance_dir=self._instance_dir())
        return _resolve_srt_path(comp, ctx)

    def _lang_iso_for_subtitle_comp(self, comp: dict | None) -> str:
        """Best-effort lang_iso for the chosen subtitle. We don't store
        the iso on the component (the SRT is the snapshot — language is
        a label, not a join key). is_chinese boolean → "zh" / "en"
        approximation is good enough for transcript headers."""
        if not comp:
            try:
                return self.project.meta.language.source or "zh"
            except AttributeError:
                return "zh"
        return "zh" if comp.get("is_chinese") else "en"

    def _write_transcript_artifact(self, srt_path: str,
                                     lang_iso: str) -> None:
        from core.subtitle_analysis_runners import build_transcript_text
        from core.io_utils import atomic_write_text
        if not srt_path or not os.path.isfile(srt_path):
            logger.warning(
                "news_desk: " + tr("tool.news_desk.export.transcript_skipped",
                                    reason=tr("tool.news_desk.export.no_srt")))
            return
        try:
            text = build_transcript_text(srt_path, lang_iso)
            out = os.path.join(self._instance_dir(), "transcript.md")
            atomic_write_text(out, text)
        except Exception as e:
            logger.warning(
                "news_desk: " + tr("tool.news_desk.export.transcript_skipped",
                                    reason=str(e)))

    def _write_chapter_videos_artifact(self, main_mp4: str,
                                          chapters: list[dict]) -> None:
        """Split the rendered main.mp4 into per-chapter mp4 files inside
        <instance_dir>/chapters/. Uses KEYFRAME_SNAP so each split is a
        stream copy (fast, no re-encode); cut starts may snap a few
        frames earlier to the nearest prior I-frame.
        """
        from core.video_split import split_one, SplitMode, probe_keyframes
        from core.chapters_io import parse_time_str
        if not os.path.isfile(main_mp4):
            logger.warning(
                "news_desk: " + tr("tool.news_desk.export.chapter_videos_skipped",
                                    reason="main mp4 missing"))
            return
        if not chapters:
            logger.warning(
                "news_desk: " + tr("tool.news_desk.export.chapter_videos_skipped",
                                    reason=tr("tool.news_desk.export.no_chapters")))
            return
        out_dir = os.path.join(self._instance_dir(), "chapters")
        os.makedirs(out_dir, exist_ok=True)
        try:
            kfs = probe_keyframes(main_mp4)
        except Exception as e:
            logger.warning(
                "news_desk: " + tr("tool.news_desk.export.chapter_videos_skipped",
                                    reason=f"keyframe probe failed: {e}"))
            return

        for i, ch in enumerate(chapters, start=1):
            start = float(ch.get("start_sec")
                          or parse_time_str(ch.get("start", "")) or 0.0)
            end = float(ch.get("end_sec")
                        or parse_time_str(ch.get("end", "")) or 0.0)
            duration = end - start
            if duration <= 0.1:
                continue
            title = _sanitize_filename(ch.get("title", ""))
            name = f"{i:02d}-{title}.mp4" if title else f"{i:02d}.mp4"
            out_path = os.path.join(out_dir, name)
            try:
                split_one(main_mp4, start, duration, out_path,
                          mode=SplitMode.KEYFRAME_SNAP, keyframes=kfs)
            except Exception as e:
                logger.warning(
                    f"news_desk: chapter {i} split failed: {e}")

    def _write_publish_sidecar(self, *,
                                  chapters: list[dict] | None = None,
                                  srt_path: str = "",
                                  sub_lang_iso: str = "") -> None:
        """Render publish.md. Per ADR-0003 inputs come from the export
        flow (instance state), not from re-scanning upstream.

        - chapters: snapshotted schedule from chapter component
        - srt_path: snapshot SRT (for per-chapter transcript section)
        - sub_lang_iso: zh/en — drives headers / chapter detail text
        """
        from creations.news_desk.publish import render_news_desk_publish
        from datetime import datetime as _dt
        # context.json is the single source of truth for publish.
        # basic_info is AI input only — never bleeds into the artifact.
        # When AI Fill hasn't run, ctx is empty and publish.md degrades
        # to a chapters-only doc (publish.py omits empty sections).
        ctx = self.material_model.read_context()

        try:
            fallback_lang = self.project.meta.language.source or "zh"
            project_title = self.project.meta.source.title
            source_url = self.project.meta.source.url
        except AttributeError:
            fallback_lang, project_title, source_url = "zh", None, None
        effective_lang = sub_lang_iso or fallback_lang

        # Chapters come from the chapter component's snapshotted schedule.
        # Normalize to the same shape publish.py / chapter_transcript
        # builder expect (start/end/start_sec/end_sec/title/refined/...).
        chapters = chapters if chapters is not None else self._chapter_schedule()
        chapters = self._chapters_for_publish(chapters)

        # adapted subtitles: only the local snapshot for this derivative.
        adapted: list[str] = []
        for comp in self._components:
            if comp.get("kind") == "subtitle" and comp.get("srt_path"):
                adapted.append(comp["srt_path"])

        md = render_news_desk_publish(
            project_title=project_title,
            source_url=source_url,
            context=ctx.to_dict(),
            chapters=chapters,
            candidate_titles=self._candidate_titles(),
            lower_thirds=[],
            adapted_srts=adapted,
            rendered_at=_dt.now().strftime("%Y-%m-%d %H:%M"),
            lang_iso=effective_lang,
            transcript_srt_path=srt_path,
        )
        out = os.path.join(self._instance_dir(), "publish.md")
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)

    def _on_export_failed(self, msg: str) -> None:
        self._processing = False
        self._skip_sidecar = False
        self.set_error(msg)
        self.top_menubtn.config(state="normal")
        self.label_status.config(
            text=tr("tool.news_desk.status.failed"))
        self.progress["value"] = 0
        messagebox.showerror("VideoCraft", msg, parent=self.master)
