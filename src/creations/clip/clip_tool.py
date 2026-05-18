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
import subprocess
import tkinter as tk
from datetime import datetime, timezone
from tkinter import messagebox, ttk
from typing import Optional

from materials.news_video.model import NewsVideoModel

from tools.base import ToolBase
from core.composition import (
    CompositionRequest, render_composition,
)
from core.composition import presets as comp_presets
from core.composition.preview import CompositionPreview
from creations.clip.candidates import HotclipsRepo
from creations.clip.clip_editor import ClipDetailPanel
from creations.clip.config import (
    BoundMaterial, ClipInstanceConfig, now_iso,
)
from creations.clip.render_queue import RenderJob, RenderQueue
from creations.clip.style_panel import StylePanel
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


def _config_path_for(project, instance_name: str) -> str:
    return os.path.join(
        project.creation_instance_dir("clip", instance_name), "config.json")


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
        # config.json is owned end-to-end by self.config; the picker UI
        # fires only when bound_material is missing.
        self._config_path = _config_path_for(project, instance_name)
        self.config = ClipInstanceConfig.load(self._config_path)
        if self.config.bound_material is None:
            from creations import material_binding
            picked = material_binding.show_material_picker(master, project)
            if picked is None:
                raise RuntimeError("Clip: material binding cancelled.")
            mt, mi = picked
            self.config.bound_material = BoundMaterial(
                type_name=mt, instance_name=mi, bound_at=now_iso())
            self.config.save(self._config_path)
        self.material_type = self.config.bound_material.type_name
        self.material_instance_id = self.config.bound_material.instance_name
        self.material_model = NewsVideoModel(project, self.material_instance_id)
        self._hotclips = HotclipsRepo(
            project.creation_instance_dir("clip", instance_name),
            self.material_model)

        # ── Data state ────────────────────────────────────────────────────
        self._lang_var = tk.StringVar()
        self._candidate_vars: list[tk.BooleanVar] = []   # parallel to _candidate_meta
        self._candidate_meta: list[dict] = []
        self._candidate_rows: list[dict] = []            # widget refs per row
        self._hotclips_data: dict = {}

        # ── Composition state ─────────────────────────────────────────────
        # Preset stores stay (preset apply / save still use them); the
        # legacy _current_style dataclass is gone — output settings,
        # encode_preset, and component templates live on self.config now.
        self._project_store = comp_presets.load_project_store()
        self._hook_outro_store = comp_presets.load_hook_outro_store()
        last = comp_presets.get_last_used_project(self._project_store)
        self._preset_name_var = tk.StringVar(value=last)
        # Tab 1 staging rect: pure in-memory UI scratchpad, NOT persisted
        # and NOT a fallback for clips without overrides. Users push it
        # onto clips explicitly via "apply crop to all".
        self._global_crop_rect: Optional[dict] = None
        self._clips_overrides: dict[int, dict] = {}      # idx -> override fields

        # ── UI handles, filled in build phase ─────────────────────────────
        self._style: Optional[StylePanel] = None
        self._detail: Optional[ClipDetailPanel] = None

        # ── Render state ──────────────────────────────────────────────────
        self._render_queue: Optional[RenderQueue] = None
        self._render_status: dict[int, str] = {}    # candidate idx -> status
        self._current_render_idx: Optional[int] = None
        self._rendered: list[dict] = []

        self._build_ui()
        self._restore_persisted_state()
        self._reload_languages()
        self._style.populate_form_from_style()

    def destroy_hook(self):
        if self._style is not None:
            self._style.destroy_preview()
        if self._detail is not None:
            self._detail.destroy_preview()

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

        self._style = StylePanel(
            self._tab_style, self,
            lang_var=self._lang_var,
            preset_name_var=self._preset_name_var)
        self._build_tab_clips()
        self._build_tab_export()

    # ── (Style tab body lives in StylePanel) ─────────────────────────────
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
        self._detail = ClipDetailPanel(detail, self)

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
    # joined with `_`. The hook suffix means the user can scan the
    # output folder by content rather than opening every .md. Hook-less
    # clips fall back to the bare `clip_NNN` form. All file ops resolve
    # via _existing_clip_files() so both shapes are addressable.

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
        """All on-disk files belonging to a given output index, covering
        both `clip_NNN.{mp4,json,md}` (no hook) and `clip_NNN_<hook>.{...}`
        shapes. Used for conflict checks, deletion, and pre-render
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

    def _full_video_duration(self) -> float:
        """Source video duration in seconds, 0.0 when unknown. Used by the
        Style-tab preview to bound the synthetic timeline range; clip-tab
        preview already has explicit per-clip windows."""
        try:
            meta = self.material_model.get_source_meta()
            return float(meta.duration_sec or 0.0)
        except Exception:
            return 0.0

    def _preview_aspect_short_edge(self) -> tuple[str, int]:
        return self.config.output_aspect, int(self.config.output_short_edge)

    def _output_geometry(self):
        """Build an OutputGeometry from the flat config fields. Called
        per render — cheap construction, no caching needed."""
        from core.composition.style import OutputGeometry
        return OutputGeometry(
            aspect=self.config.output_aspect,
            short_edge=int(self.config.output_short_edge),
            mode=self.config.output_mode)

    def _build_preview_timeline(self, start: float, end: float, *,
                                  hook: str = "", outro: str = ""):
        """Compose a CompositionTimeline for [start, end] using the current
        style + the instance's source SRT. Single-source for both render
        and preview — set_timeline pushes the same IR ffmpeg renders."""
        from creations.clip.composer import compile_for_candidate
        from core.composition.compile import ClipRange
        return compile_for_candidate(
            self.config.components,
            ClipRange(start_sec=start, end_sec=end),
            hook_text=hook, outro_text=outro,
            srt_by_lang=self._srt_by_lang(),
        )

    def _effective_outro(self, idx: int) -> str:
        if not (0 <= idx < len(self._candidate_meta)):
            return ""
        hot = self._candidate_meta[idx]
        ov = self._clips_overrides.get(idx) or {}
        if "outro_text" in ov:
            return str(ov["outro_text"])
        # AI hotclips schema: `outro` is the closing CTA line. .get()
        # is defensive against AI output occasionally violating the
        # schema's required-fields contract.
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
        """Per-clip crop or None (= center default at render time).

        The Tab 1 "staging" rect (`_global_crop_rect`) is NOT a fallback;
        it's a pure UI scratchpad. Users push it onto clips explicitly via
        the "apply crop to all" button — see StylePanel._on_apply_crop_to_all.
        """
        ov = self._clips_overrides.get(idx) or {}
        rect = ov.get("crop_rect")
        return rect if rect else None

    # ── Persistence ──────────────────────────────────────────────────────

    def _restore_persisted_state(self) -> None:
        cfg = self.config
        if cfg.source_subtitle:
            self._lang_var.set(cfg.source_subtitle)
        if cfg.preset_name:
            self._preset_name_var.set(cfg.preset_name)
        self._clips_overrides = dict(cfg.clips_overrides)
        # Drop rendered entries whose mp4 no longer exists on disk
        inst = self._instance_dir()
        self._rendered = [
            r for r in cfg.rendered
            if isinstance(r, dict) and os.path.isfile(
                os.path.join(inst, r.get("file", "")))
        ]
        # Selected indices applied after candidates load (deferred to _reload_candidates)
        self._pending_selection = set(cfg.selected_clip_indices)

    def _save_all(self) -> None:
        """Push live UI state into self.config and persist via the single writer."""
        self.config.source_subtitle = self._lang_var.get()
        self.config.selected_clip_indices = [
            i for i, v in enumerate(self._candidate_vars) if v.get()]
        self.config.preset_name = self._preset_name_var.get()
        self.config.clips_overrides = dict(self._clips_overrides)
        self.config.rendered = list(self._rendered)
        self.config.save(self._config_path)

    # ── Hotclips snapshot (per-instance immutable source) ────────────────

    # When the user picks a language and the instance doesn't yet have its
    # own copy of <lang>.hotclips.json, we snapshot upstream into the
    # instance dir. From that point on the workbench reads ONLY from the
    # snapshot — upstream regeneration cannot corrupt per-clip overrides
    # or already-rendered outputs. Stage 1: hotclips only; SRT and source
    # video remain shared upstream (regeneration of those is rare and
    # currently produces near-identical output).

    # ── Language / candidate loading ─────────────────────────────────────

    def _reload_languages(self) -> None:
        langs = self._hotclips.list_available_langs()
        lang_combo = self._style.lang_combo
        status_var = self._style.status_var
        lang_combo["values"] = langs
        if not langs:
            status_var.set(tr("clip_tool.status_no_hotclips"))
            lang_combo.configure(state="disabled")
            self._render_btn.configure(state="disabled")
            return
        lang_combo.configure(state="readonly")
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
        data = self._hotclips.load_hotclips(lang)
        if data is None:
            self._style.status_var.set(tr("clip_tool.status_load_failed",
                                     error="hotclips source not found"))
            return
        self._hotclips_data = data
        clips = data.get("clips") or []
        self._style.status_var.set(tr("clip_tool.status_loaded", n=len(clips)))

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
            self._detail.show(first_sel)

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
            w.bind("<Button-1>", lambda _e, i=idx: self._detail.show(i))
            for child in w.winfo_children():
                if isinstance(child, tk.Label):
                    child.bind("<Button-1>",
                               lambda _e, i=idx: self._detail.show(i))
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
        from core.composition.style import SubtitleLineStyle
        # Pick the first enabled subtitle component for char-wrap params
        # (components-list order = outer-to-inner z); fall back to
        # defaults if none is configured.
        sub1_comp = next((c for c in self.config.components
                            if c.get("kind") == "clip_subtitle"
                            and c.get("enabled", True)), None)
        if sub1_comp is not None:
            line = SubtitleLineStyle(
                enabled=True,
                fontsize=int(sub1_comp.get("fontsize", 24)),
                color=sub1_comp.get("color", "#FFFFFF"),
                bold=bool(sub1_comp.get("bold", False)),
                is_chinese=bool(sub1_comp.get("is_chinese", False)),
                bg_color=sub1_comp.get("bg_color", "#000000"),
                bg_opacity=int(sub1_comp.get("bg_opacity", 0)),
                bg_padding_x_pct=float(sub1_comp.get(
                    "bg_padding_x_pct", 0.0)))
        else:
            line = SubtitleLineStyle(enabled=True)
        return prepare_subtitle_cues(
            srt_path, line,
            aspect=self.config.output_aspect,
            short_edge=int(self.config.output_short_edge))

    def _resolve_source_srt(self) -> Optional[str]:
        return self._hotclips.resolve_source_srt(self._lang_var.get())

    def _srt_by_lang(self) -> dict[str, str]:
        """Map every language with an available SRT to its path so the
        composer can resolve subtitle components by their `language`
        field. Broader than the hotclips-langs list — any SRT the
        material has can be picked as a subtitle burn source."""
        out: dict[str, str] = {}
        for lang in self._hotclips.list_subtitle_langs():
            p = self._hotclips.resolve_source_srt(lang)
            out[lang] = p or ""
        return out

    # ── Tab 1: global crop handler + apply-to-all ────────────────────────

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
        video_path = self.material_model.source_video_path
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

        self._style.read_form_into_style()
        self._save_all()

        # Build jobs
        srt_by_lang = self._srt_by_lang()
        jobs: list[RenderJob] = []
        for out_idx, src_idx in enumerate(selected, 1):
            if out_idx in skip_indices:
                continue
            start, end = self._effective_start_end(src_idx)
            if end <= start:
                continue
            base = self._clip_basename(out_idx, src_idx)
            out_path = os.path.join(inst, base + ".mp4")
            from creations.clip.composer import compile_for_candidate
            from core.composition.compile import ClipRange
            timeline = compile_for_candidate(
                self.config.components,
                ClipRange(start_sec=start, end_sec=end),
                hook_text=self._effective_hook(src_idx),
                outro_text=self._effective_outro(src_idx),
                srt_by_lang=srt_by_lang,
            )
            jobs.append(RenderJob(
                out_idx=out_idx, src_idx=src_idx,
                request=CompositionRequest(
                    source_video=video_path,
                    start_sec=start, end_sec=end,
                    output_path=out_path,
                    output_geometry=self._output_geometry(),
                    encode_preset=self.config.encode_preset,
                    crop_rect=self._effective_crop(src_idx),
                    timeline=timeline,
                )))

        if not jobs:
            messagebox.showinfo(
                "VideoCraft", tr("clip_tool.warn_no_valid_plan"),
                parent=self.master)
            return

        for job in jobs:
            self._render_status[job.src_idx] = "queued"
        self._refresh_render_tv()
        self._start_render_queue(jobs)

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

    def _start_render_queue(self, jobs: list[RenderJob]) -> None:
        """Spin up a one-shot RenderQueue for `jobs`. UI gets put into
        the busy state synchronously here; reset happens in
        _on_render_done after the queue's all-done callback fires."""
        self._render_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self.set_busy(tr("clip_tool.rendering"))
        self._render_queue = RenderQueue(
            self.master,
            on_progress=self._on_render_progress,
            on_succeeded=self._on_clip_succeeded,
            on_failed=self._on_clip_failed,
            on_all_done=self._on_render_done,
            cleanup_stale_fn=self._cleanup_stale_for_out_idx,
        )
        self._render_queue.start(jobs)

    def _cleanup_stale_for_out_idx(self, out_idx: int,
                                     new_basename: str) -> None:
        """Worker-thread callback: wipe any prior paired files for
        `out_idx` whose basename differs from the upcoming render. A
        hook edit changes basename, so we must clear the old shape or
        end up with two paired sets for one logical clip."""
        for stale in self._existing_clip_files(out_idx):
            if os.path.splitext(os.path.basename(stale))[0] == new_basename:
                continue
            try:
                os.unlink(stale)
            except OSError:
                pass

    def _on_clip_succeeded(self, job: RenderJob, result) -> None:
        """Tk-thread callback after one job's render returned. Writes
        sidecars + bookkeeping + refreshes the render table."""
        req = job.request
        self._write_sidecar(req, result, job.out_idx, job.src_idx)
        self._write_publish_sidecar(req.output_path)
        self._render_status[job.src_idx] = "done"
        self._rendered = [
            r for r in self._rendered
            if int(r.get("output_index") or -1) != job.out_idx
        ]
        self._rendered.insert(0, {
            "file": os.path.basename(req.output_path),
            "source_clip_idx": job.src_idx,
            "output_index": job.out_idx,
            "duration_sec": result.duration_sec,
            "rendered_at": datetime.now(timezone.utc)
                            .isoformat(timespec="seconds"),
        })
        self._refresh_render_tv()

    def _on_clip_failed(self, job: RenderJob, error_msg: str) -> None:
        """Tk-thread callback after one job's render raised."""
        self._render_status[job.src_idx] = "failed"
        self._set_failure_reason(job.src_idx, error_msg)
        self._refresh_render_tv()

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
        # Cancelled jobs landed in "queued" via on_failed never firing —
        # restore that signal for queued-but-unfinished items.
        for src_idx, status in list(self._render_status.items()):
            if status == "in_progress":
                self._render_status[src_idx] = "queued"
        self._save_all()
        self._refresh_render_tv()
        was_cancelled = (self._render_queue is not None
                          and self._render_queue.is_cancelled)
        self._render_queue = None
        if was_cancelled:
            self.set_warning(tr("clip_tool.cancelled_msg"))
        elif last_error:
            self.set_warning(tr("clip_tool.done_with_warning"))
        else:
            self.set_done()

    def _on_cancel_render(self) -> None:
        if self._render_queue is not None:
            self._render_queue.cancel()

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
        video_path = self.material_model.source_video_path
        if not os.path.isfile(video_path):
            return
        start, end = self._effective_start_end(src_idx)
        if end <= start:
            return
        base = self._clip_basename(out_idx, src_idx)
        out_path = os.path.join(self._instance_dir(), base + ".mp4")
        self._style.read_form_into_style()
        from creations.clip.composer import compile_for_candidate
        from core.composition.compile import ClipRange
        timeline = compile_for_candidate(
            self.config.components,
            ClipRange(start_sec=start, end_sec=end),
            hook_text=self._effective_hook(src_idx),
            outro_text="",
            srt_by_lang=self._srt_by_lang(),
        )
        req = CompositionRequest(
            source_video=video_path,
            start_sec=start, end_sec=end,
            output_path=out_path,
            output_geometry=self._output_geometry(),
            encode_preset=self.config.encode_preset,
            crop_rect=self._effective_crop(src_idx),
            timeline=timeline,
        )
        self._start_render_queue(
            [RenderJob(out_idx=out_idx, src_idx=src_idx, request=req)])

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
