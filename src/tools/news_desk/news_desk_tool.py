"""News-desk workbench — bilingual subtitles + LowerThird name plates +
TopicStrip chapter markers, rendered through composition core.

v0.1 shell: minimal but functional.
  - Locked source / output paths (project derivative mode only).
  - Preset combo (news_desk store) — picks subtitle look + overlay style lib.
  - Two SRT pickers (sub1 / sub2) for bilingual burn.
  - Overlay list editor: add/edit/delete LowerThird + TopicStrip rows.
  - "Auto-derive" buttons:
      * LowerThird ← source/basic_info.json (host + bio + affiliation)
      * TopicStrip ← any subtitles/<iso>.analysis.json (one strip per chapter)
  - WebView preview mirrors the burn (subtitle cues + overlays).
  - Export button → render_composition → derivatives/news_desk/<inst>/output.mp4

Per-instance config persisted at
  derivatives/news_desk/<instance>/config.json
holding preset name, SRT selections (relative to project folder), and the
overlay list (each entry is `overlay_to_dict` output, kind-discriminated).
"""

from __future__ import annotations

import json
import os
import threading
import time
import tkinter as tk
from dataclasses import asdict
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from tools.base import ToolBase
from i18n import tr
from hub_logger import logger

from core import derivative_types
from core.composition import presets as comp_presets
from core.composition.overlays import (
    LowerThirdOverlay, TopicStripOverlay,
    overlay_to_dict, overlay_from_dict,
)
from core.composition.preview import CompositionPreview
from core.composition.render import (
    CompositionRequest, prepare_subtitle_cues, render_composition,
)
from core.composition.style import (
    CompositionStyle, LowerThirdStyle, TopicStripStyle,
    OVERLAY_STYLE_CLASSES,
)
from core import source_context
from core import chapters_io


DERIVATIVE_TYPE = "news_desk"


# ── helper: probe source resolution for preview / passthrough ──────────────

def _probe_resolution(video_path: str) -> tuple[int, int]:
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             video_path],
            capture_output=True, encoding="utf-8", errors="replace", timeout=10)
        if out.returncode == 0:
            w, h = out.stdout.strip().split(",")
            return int(w), int(h)
    except Exception:
        pass
    return 0, 0


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


# ── App ─────────────────────────────────────────────────────────────────────

class NewsDeskApp(ToolBase):
    """News-desk derivative workbench."""

    def __init__(self, master, project, instance_name):
        if project is None or not instance_name:
            raise ValueError(
                "NewsDeskApp requires both project and instance_name.")

        self.master = master
        self.project = project
        self.instance_name = instance_name

        master.title(tr("tool.news_desk.title", instance=instance_name))
        master.geometry("1080x720")

        # State.
        self._duration = 0.0
        self._src_w = 0
        self._src_h = 0
        self._processing = False
        self._overlays: list = []      # typed overlay dataclass instances
        self._sub1_srt: str = ""       # absolute path; "" = no track
        self._sub2_srt: str = ""
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

        # Style-form Tk vars. Populated in _build_form, applied via
        # _apply_style_to_vars on preset load. _suppress_trace blocks the
        # write-back path while we're loading vars from a CompositionStyle.
        self._suppress_trace = False
        self._style_vars: dict = {}

        self._build_ui()
        self._enter_project_mode()

    # ── UI build ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = self.master

        # Bottom: export bar (packed first so it never gets squeezed out).
        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="x", padx=8, pady=(4, 8))
        self.btn_export = ttk.Button(
            bottom, text=tr("tool.news_desk.action.export"),
            command=self._do_export)
        self.btn_export.pack(side="right")
        self.label_status = ttk.Label(bottom, text="", foreground="#666")
        self.label_status.pack(side="left", padx=(0, 8))
        self.progress = ttk.Progressbar(
            bottom, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)

        # Top: source video info (read-only).
        top = ttk.Frame(root)
        top.pack(side="top", fill="x", padx=8, pady=(8, 4))
        ttk.Label(top, text=tr("tool.news_desk.source.label")
                  ).pack(side="left")
        self.entry_video = ttk.Entry(top, state="readonly")
        self.entry_video.pack(side="left", fill="x", expand=True, padx=(4, 8))
        self.label_duration = ttk.Label(top, text="", foreground="#666")
        self.label_duration.pack(side="left")

        # Middle: form | preview.
        pw = ttk.PanedWindow(root, orient="horizontal")
        pw.pack(side="top", fill="both", expand=True, padx=4, pady=(0, 4))
        form_outer = ttk.Frame(pw)
        preview_outer = ttk.Frame(pw)
        pw.add(form_outer, weight=2)
        pw.add(preview_outer, weight=3)

        self._build_form(form_outer)

        self._preview = CompositionPreview(
            preview_outer, width=520, height=560)
        self._preview.widget.pack(fill="both", expand=True, padx=4, pady=4)
        self._preview.enable_crop_drag(False)

    def _build_form(self, parent: ttk.Frame) -> None:
        # Preset.
        pf = ttk.LabelFrame(parent, text=tr("tool.news_desk.preset.frame"))
        pf.pack(fill="x", padx=6, pady=(6, 4))
        self.preset_combo = ttk.Combobox(pf, state="readonly")
        self.preset_combo.grid(row=0, column=0, columnspan=3,
                                 padx=4, pady=4, sticky="ew")
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_pick)
        ttk.Button(pf, text=tr("tool.news_desk.preset.save"),
                   command=self._on_preset_save
                   ).grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        ttk.Button(pf, text=tr("tool.news_desk.preset.save_as"),
                   command=self._on_preset_save_as
                   ).grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        ttk.Button(pf, text=tr("tool.news_desk.preset.delete"),
                   command=self._on_preset_delete
                   ).grid(row=1, column=2, padx=2, pady=2, sticky="ew")
        for c in range(3):
            pf.columnconfigure(c, weight=1)

        # Subtitles.
        sf = ttk.LabelFrame(parent, text=tr("tool.news_desk.subs.frame"))
        sf.pack(fill="x", padx=6, pady=4)

        row = ttk.Frame(sf); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.news_desk.sub1"), width=8
                  ).pack(side="left")
        self.entry_sub1 = ttk.Entry(row, state="readonly")
        self.entry_sub1.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text=tr("tool.news_desk.sub.pick"),
                   command=lambda: self._pick_srt(1)).pack(side="left")
        ttk.Button(row, text=tr("tool.news_desk.sub.clear"),
                   command=lambda: self._pick_srt(1, clear=True)
                   ).pack(side="left", padx=(2, 0))

        row = ttk.Frame(sf); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.news_desk.sub2"), width=8
                  ).pack(side="left")
        self.entry_sub2 = ttk.Entry(row, state="readonly")
        self.entry_sub2.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text=tr("tool.news_desk.sub.pick"),
                   command=lambda: self._pick_srt(2)).pack(side="left")
        ttk.Button(row, text=tr("tool.news_desk.sub.clear"),
                   command=lambda: self._pick_srt(2, clear=True)
                   ).pack(side="left", padx=(2, 0))

        # Style controls — minimal but enough that "Save Preset" captures
        # something meaningful. All edits flow back to self._current_style
        # via _on_style_var_changed and immediately push the preview.
        self._build_style_form(parent)

        # Overlays.
        of = ttk.LabelFrame(parent, text=tr("tool.news_desk.overlays.frame"))
        of.pack(fill="both", expand=True, padx=6, pady=4)

        cols = ("kind", "start", "end", "content")
        self.tree = ttk.Treeview(of, columns=cols, show="headings", height=8)
        self.tree.heading("kind",    text=tr("tool.news_desk.col.kind"))
        self.tree.heading("start",   text=tr("tool.news_desk.col.start"))
        self.tree.heading("end",     text=tr("tool.news_desk.col.end"))
        self.tree.heading("content", text=tr("tool.news_desk.col.content"))
        self.tree.column("kind",    width=90,  anchor="w")
        self.tree.column("start",   width=70,  anchor="e")
        self.tree.column("end",     width=70,  anchor="e")
        self.tree.column("content", width=240, anchor="w")
        self.tree.pack(side="top", fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<Double-1>", lambda _e: self._edit_selected())
        # Single-click any row → preview seeks to that overlay's start_sec
        # (handy for jumping straight to the spot you're editing).
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._seek_to_selected())

        btns = ttk.Frame(of); btns.pack(side="top", fill="x", padx=4, pady=2)
        ttk.Button(btns, text=tr("tool.news_desk.add.lower_third"),
                   command=self._add_lower_third).pack(side="left", padx=2)
        ttk.Button(btns, text=tr("tool.news_desk.add.topic_strip"),
                   command=self._add_topic_strip).pack(side="left", padx=2)
        ttk.Button(btns, text=tr("tool.news_desk.edit"),
                   command=self._edit_selected).pack(side="left", padx=2)
        ttk.Button(btns, text=tr("tool.news_desk.delete"),
                   command=self._delete_selected).pack(side="left", padx=2)

        btns2 = ttk.Frame(of); btns2.pack(side="top", fill="x", padx=4, pady=2)
        ttk.Button(btns2, text=tr("tool.news_desk.derive_lt"),
                   command=self._derive_lower_third_from_basic
                   ).pack(side="left", padx=2)
        ttk.Button(btns2, text=tr("tool.news_desk.derive_ts"),
                   command=self._derive_topic_strips_from_chapters
                   ).pack(side="left", padx=2)

    # ── Style form ──────────────────────────────────────────────────────────

    def _build_style_form(self, parent: ttk.Frame) -> None:
        # Subtitles section.
        sf = ttk.LabelFrame(parent, text=tr("tool.news_desk.style.sub.frame"))
        sf.pack(fill="x", padx=6, pady=4)

        # Position radio.
        row = ttk.Frame(sf); row.pack(fill="x", padx=4, pady=2)
        v_pos = tk.StringVar(value="bottom")
        ttk.Label(row, text=tr("tool.news_desk.style.sub.position"),
                  width=8).pack(side="left")
        for label, val in (("⬆ top", "top"), ("⬇ bottom", "bottom")):
            ttk.Radiobutton(row, text=label, variable=v_pos, value=val,
                            command=self._on_style_var_changed
                            ).pack(side="left", padx=(4, 0))
        self._style_vars["sub_position"] = v_pos

        for slot, default_show, default_size, default_color, default_cn in (
            (1, True,  28, "#FFFF00", True),
            (2, True,  24, "#FFFFFF", False),
        ):
            self._build_sub_row(sf, slot,
                                  default_show, default_size,
                                  default_color, default_cn)

        # LowerThird default style.
        lf = ttk.LabelFrame(parent, text=tr("tool.news_desk.style.lt.frame"))
        lf.pack(fill="x", padx=6, pady=4)
        row = ttk.Frame(lf); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.news_desk.style.lt.bg"),
                  width=8).pack(side="left")
        self._add_color_picker(row, "lt_bg_color", "#0F172A")
        ttk.Label(row, text=tr("tool.news_desk.style.lt.accent"),
                  width=10).pack(side="left", padx=(8, 0))
        self._add_color_picker(row, "lt_accent_color", "#C8102E")

        row = ttk.Frame(lf); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.news_desk.style.lt.title_size"),
                  width=10).pack(side="left")
        v = tk.IntVar(value=38)
        ttk.Spinbox(row, from_=14, to=96, width=5, textvariable=v,
                     command=self._on_style_var_changed
                     ).pack(side="left")
        v.trace_add("write", lambda *_: self._on_style_var_changed())
        self._style_vars["lt_title_fontsize"] = v
        ttk.Label(row, text=tr("tool.news_desk.style.lt.sub_size"),
                  width=10).pack(side="left", padx=(8, 0))
        v2 = tk.IntVar(value=24)
        ttk.Spinbox(row, from_=10, to=64, width=5, textvariable=v2,
                     command=self._on_style_var_changed
                     ).pack(side="left")
        v2.trace_add("write", lambda *_: self._on_style_var_changed())
        self._style_vars["lt_subtitle_fontsize"] = v2

        # TopicStrip default style.
        tf = ttk.LabelFrame(parent, text=tr("tool.news_desk.style.ts.frame"))
        tf.pack(fill="x", padx=6, pady=4)
        row = ttk.Frame(tf); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.news_desk.style.ts.bg"),
                  width=8).pack(side="left")
        self._add_color_picker(row, "ts_bg_color", "#1E40AF")
        ttk.Label(row, text=tr("tool.news_desk.style.ts.text"),
                  width=10).pack(side="left", padx=(8, 0))
        self._add_color_picker(row, "ts_text_color", "#FFFFFF")
        ttk.Label(row, text=tr("tool.news_desk.style.ts.size"),
                  width=8).pack(side="left", padx=(8, 0))
        v = tk.IntVar(value=26)
        ttk.Spinbox(row, from_=10, to=64, width=5, textvariable=v,
                     command=self._on_style_var_changed
                     ).pack(side="left")
        v.trace_add("write", lambda *_: self._on_style_var_changed())
        self._style_vars["ts_fontsize"] = v

    def _build_sub_row(self, parent, slot, dshow, dsize, dcolor, dcn):
        """Build one subtitle line's controls (sub1 or sub2)."""
        row = ttk.Frame(parent); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=f"sub{slot}", width=4).pack(side="left")

        v_show = tk.BooleanVar(value=dshow)
        ttk.Checkbutton(row, text=tr("tool.news_desk.style.sub.show"),
                         variable=v_show,
                         command=self._on_style_var_changed
                         ).pack(side="left", padx=(2, 0))
        self._style_vars[f"sub{slot}_enabled"] = v_show

        ttk.Label(row, text=tr("tool.news_desk.style.sub.size")
                  ).pack(side="left", padx=(6, 0))
        v_size = tk.IntVar(value=dsize)
        ttk.Spinbox(row, from_=10, to=72, width=4, textvariable=v_size,
                     command=self._on_style_var_changed
                     ).pack(side="left")
        v_size.trace_add("write", lambda *_: self._on_style_var_changed())
        self._style_vars[f"sub{slot}_fontsize"] = v_size

        ttk.Label(row, text=tr("tool.news_desk.style.sub.color")
                  ).pack(side="left", padx=(6, 0))
        self._add_color_picker(row, f"sub{slot}_color", dcolor)

        v_cn = tk.BooleanVar(value=dcn)
        ttk.Checkbutton(row, text=tr("tool.news_desk.style.sub.zh"),
                         variable=v_cn,
                         command=self._on_style_var_changed
                         ).pack(side="left", padx=(6, 0))
        self._style_vars[f"sub{slot}_is_chinese"] = v_cn

    def _add_color_picker(self, parent, key: str, default: str) -> None:
        v = tk.StringVar(value=default)
        ent = ttk.Entry(parent, textvariable=v, width=9)
        ent.pack(side="left")
        v.trace_add("write", lambda *_: self._on_style_var_changed())

        def _pick():
            current = v.get() or default
            res = colorchooser.askcolor(
                color=current, parent=self.master,
                title=tr("tool.news_desk.style.color_picker_title"))
            if res and res[1]:
                v.set(res[1].upper())
        ttk.Button(parent, text="🎨", width=2, command=_pick
                   ).pack(side="left", padx=(2, 0))
        self._style_vars[key] = v

    def _apply_style_to_vars(self, style: CompositionStyle) -> None:
        """Push a CompositionStyle into the style form's Tk vars. Trace
        callbacks are suppressed so the round-trip doesn't immediately
        write back and over-write the preset."""
        self._suppress_trace = True
        try:
            sub = style.subtitle
            self._style_vars["sub_position"].set(sub.position or "bottom")
            for slot, line in ((1, sub.sub1), (2, sub.sub2)):
                self._style_vars[f"sub{slot}_enabled"].set(bool(line.enabled))
                self._style_vars[f"sub{slot}_fontsize"].set(int(line.fontsize))
                self._style_vars[f"sub{slot}_color"].set(line.color or "#FFFFFF")
                self._style_vars[f"sub{slot}_is_chinese"].set(bool(line.is_chinese))

            from core.composition.style import resolve_overlay_style
            lt = resolve_overlay_style(
                style.overlay_styles, "lower_third", "default") \
                or LowerThirdStyle()
            self._style_vars["lt_bg_color"].set(lt.bg_color)
            self._style_vars["lt_accent_color"].set(lt.accent_color)
            self._style_vars["lt_title_fontsize"].set(int(lt.title_fontsize))
            self._style_vars["lt_subtitle_fontsize"].set(int(lt.subtitle_fontsize))

            ts = resolve_overlay_style(
                style.overlay_styles, "topic_strip", "default") \
                or TopicStripStyle()
            self._style_vars["ts_bg_color"].set(ts.bg_color)
            self._style_vars["ts_text_color"].set(ts.text_color)
            self._style_vars["ts_fontsize"].set(int(ts.fontsize))
        finally:
            self._suppress_trace = False

    def _on_style_var_changed(self, *_args) -> None:
        """Write form vars back into self._current_style + push preview."""
        if self._suppress_trace:
            return
        st = self._current_style
        sub = st.subtitle
        sub.position = self._style_vars["sub_position"].get() or "bottom"
        for slot, line in ((1, sub.sub1), (2, sub.sub2)):
            line.enabled = bool(self._style_vars[f"sub{slot}_enabled"].get())
            try:
                line.fontsize = int(self._style_vars[f"sub{slot}_fontsize"].get())
            except (tk.TclError, ValueError):
                pass
            line.color = self._style_vars[f"sub{slot}_color"].get() or line.color
            line.is_chinese = bool(self._style_vars[f"sub{slot}_is_chinese"].get())

        # Overlay style library — mutate the "default" entry in place so
        # any existing LowerThird/TopicStrip overlay using style_class=
        # "default" picks up the change.
        ostyles = st.overlay_styles or {}
        lt_dict = ostyles.setdefault("lower_third", {}).setdefault("default", {})
        lt_dict["bg_color"] = self._style_vars["lt_bg_color"].get()
        lt_dict["accent_color"] = self._style_vars["lt_accent_color"].get()
        try:
            lt_dict["title_fontsize"] = int(self._style_vars["lt_title_fontsize"].get())
            lt_dict["subtitle_fontsize"] = int(self._style_vars["lt_subtitle_fontsize"].get())
        except (tk.TclError, ValueError):
            pass

        ts_dict = ostyles.setdefault("topic_strip", {}).setdefault("default", {})
        ts_dict["bg_color"] = self._style_vars["ts_bg_color"].get()
        ts_dict["text_color"] = self._style_vars["ts_text_color"].get()
        try:
            ts_dict["fontsize"] = int(self._style_vars["ts_fontsize"].get())
        except (tk.TclError, ValueError):
            pass
        st.overlay_styles = ostyles

        self._save_instance_config()
        self._push_preview()

    # ── Project mode setup ──────────────────────────────────────────────────

    def _enter_project_mode(self) -> None:
        type_disp = derivative_types.display_name(DERIVATIVE_TYPE)
        self.master.title(tr("tool.news_desk.project.title",
                              type=type_disp, instance=self.instance_name))

        src = self.project.source_video_path
        self.entry_video.config(state="normal")
        self.entry_video.delete(0, tk.END)
        self.entry_video.insert(0, src)
        self.entry_video.config(state="readonly")

        os.makedirs(self._instance_dir(), exist_ok=True)

        self._load_instance_config()

        if os.path.isfile(src):
            self._duration = _probe_duration(src)
            self._src_w, self._src_h = _probe_resolution(src)
            if self._duration > 0:
                hms = time.strftime("%H:%M:%S", time.gmtime(self._duration))
                self.label_duration.config(
                    text=tr("tool.news_desk.duration_fmt", hms=hms))

        self._refresh_preset_combo(select=self._current_preset_name)
        self._apply_style_to_vars(self._current_style)
        self._refresh_overlay_tree()
        self._sync_srt_entries()

        if self._preview is not None:
            try:
                self._preview.set_source(src, 0.0, 0.0)
            except Exception as e:
                logger.debug(f"news_desk: preview set_source failed: {e}")
        self._push_preview()

        comp_presets.save_news_desk_store(self._preset_store)

    # ── Per-instance paths + config ─────────────────────────────────────────

    def _instance_dir(self) -> str:
        return self.project.derivative_dir(DERIVATIVE_TYPE, self.instance_name)

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
        # Restore SRT selections (stored relative to project folder).
        s1 = cfg.get("sub1_srt") or ""
        s2 = cfg.get("sub2_srt") or ""
        self._sub1_srt = self._abs_from_proj(s1) if s1 else ""
        self._sub2_srt = self._abs_from_proj(s2) if s2 else ""
        # Restore overlays.
        raw_ov = cfg.get("overlays") or []
        if isinstance(raw_ov, list):
            self._overlays = [overlay_from_dict(d) for d in raw_ov
                                if isinstance(d, dict)]

    def _save_instance_config(self) -> None:
        cfg = {
            "preset_name": self._current_preset_name,
            "sub1_srt": self._proj_relative(self._sub1_srt),
            "sub2_srt": self._proj_relative(self._sub2_srt),
            "overlays": [overlay_to_dict(o) for o in self._overlays],
        }
        path = self._config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _abs_from_proj(self, rel: str) -> str:
        return os.path.normpath(os.path.join(self.project.folder, rel))

    def _proj_relative(self, abs_path: str) -> str:
        if not abs_path:
            return ""
        try:
            return os.path.relpath(abs_path, self.project.folder).replace("\\", "/")
        except ValueError:
            return abs_path

    # ── Preset actions ──────────────────────────────────────────────────────

    def _refresh_preset_combo(self, *, select: str | None = None) -> None:
        names = comp_presets.list_news_desk_presets(self._preset_store)
        self.preset_combo["values"] = names
        if select and select in names:
            self.preset_combo.set(select)
        elif names:
            self.preset_combo.set(names[0])

    def _on_preset_pick(self, _evt=None) -> None:
        name = self.preset_combo.get()
        style = comp_presets.get_news_desk_preset(self._preset_store, name)
        if style is None:
            return
        self._current_style = style
        self._current_preset_name = name
        comp_presets.set_last_used_news_desk(self._preset_store, name)
        comp_presets.save_news_desk_store(self._preset_store)
        self._apply_style_to_vars(style)
        self._save_instance_config()
        self._push_preview()

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
        self._refresh_preset_combo(select=name)
        self._save_instance_config()

    def _on_preset_delete(self) -> None:
        name = self.preset_combo.get()
        if comp_presets.is_builtin_news_desk(name):
            messagebox.showinfo(
                "VideoCraft",
                tr("tool.news_desk.preset.delete.builtin_protected"),
                parent=self.master)
            return
        if not comp_presets.delete_news_desk_preset(self._preset_store, name):
            return
        comp_presets.save_news_desk_store(self._preset_store)
        self._refresh_preset_combo()
        self._on_preset_pick()

    # ── SRT picking ─────────────────────────────────────────────────────────

    def _pick_srt(self, slot: int, *, clear: bool = False) -> None:
        if clear:
            if slot == 1:
                self._sub1_srt = ""
            else:
                self._sub2_srt = ""
        else:
            initial = self.project.subtitles_dir
            path = filedialog.askopenfilename(
                parent=self.master,
                initialdir=initial if os.path.isdir(initial) else self.project.folder,
                title=tr("tool.news_desk.sub.pick"),
                filetypes=[("SRT", "*.srt"), ("All", "*.*")])
            if not path:
                return
            if slot == 1:
                self._sub1_srt = path
            else:
                self._sub2_srt = path
        self._sync_srt_entries()
        self._save_instance_config()
        self._push_preview()

    def _sync_srt_entries(self) -> None:
        for entry, val in ((self.entry_sub1, self._sub1_srt),
                            (self.entry_sub2, self._sub2_srt)):
            entry.config(state="normal")
            entry.delete(0, tk.END)
            if val:
                entry.insert(0, self._proj_relative(val))
            entry.config(state="readonly")

    # ── Overlay list ops ────────────────────────────────────────────────────

    def _refresh_overlay_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, ov in enumerate(self._overlays):
            kind = ov.kind
            start = f"{ov.start_sec:.1f}"
            end = f"{ov.end_sec:.1f}"
            if isinstance(ov, LowerThirdOverlay):
                content = f"{ov.title} | {ov.subtitle}"
            elif isinstance(ov, TopicStripOverlay):
                content = ov.topic_text
            else:
                content = ""
            self.tree.insert("", "end", iid=str(i),
                              values=(kind, start, end, content))

    def _seek_to_selected(self) -> None:
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._overlays):
            return
        if self._preview is None:
            return
        try:
            self._preview.seek(float(self._overlays[idx].start_sec))
        except Exception as e:
            logger.debug(f"news_desk seek failed: {e}")

    def _selected_index(self) -> int:
        sel = self.tree.selection()
        if not sel:
            return -1
        try:
            return int(sel[0])
        except ValueError:
            return -1

    def _add_lower_third(self) -> None:
        spec = LowerThirdOverlay(
            title="", subtitle="",
            start_sec=0.0, end_sec=max(10.0, self._duration),
            position="bottom-left",
        )
        if self._edit_overlay_dialog(spec):
            self._overlays.append(spec)
            self._after_overlays_changed()

    def _add_topic_strip(self) -> None:
        spec = TopicStripOverlay(
            topic_text="",
            start_sec=0.0, end_sec=max(10.0, self._duration),
        )
        if self._edit_overlay_dialog(spec):
            self._overlays.append(spec)
            self._after_overlays_changed()

    def _edit_selected(self) -> None:
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._overlays):
            return
        if self._edit_overlay_dialog(self._overlays[idx]):
            self._after_overlays_changed()

    def _delete_selected(self) -> None:
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._overlays):
            return
        del self._overlays[idx]
        self._after_overlays_changed()

    def _after_overlays_changed(self) -> None:
        self._refresh_overlay_tree()
        self._save_instance_config()
        self._push_preview()

    def _edit_overlay_dialog(self, spec) -> bool:
        """Modal editor for one overlay. Mutates `spec` in place. Returns
        True on OK, False on Cancel."""
        win = tk.Toplevel(self.master)
        win.title(tr("tool.news_desk.dialog.edit"))
        win.transient(self.master); win.grab_set(); win.resizable(False, False)
        body = ttk.Frame(win, padding=12); body.pack(fill="both", expand=True)

        # Common time fields.
        start_v = tk.DoubleVar(value=spec.start_sec)
        end_v   = tk.DoubleVar(value=spec.end_sec)

        row = ttk.Frame(body); row.pack(fill="x", pady=2)
        ttk.Label(row, text=tr("tool.news_desk.field.start"), width=10
                  ).pack(side="left")
        ttk.Spinbox(row, from_=0.0, to=99999.0, increment=0.5,
                    textvariable=start_v, width=10).pack(side="left")
        ttk.Label(row, text=tr("tool.news_desk.field.end"), width=10
                  ).pack(side="left", padx=(12, 0))
        ttk.Spinbox(row, from_=0.0, to=99999.0, increment=0.5,
                    textvariable=end_v, width=10).pack(side="left")

        if isinstance(spec, LowerThirdOverlay):
            title_v = tk.StringVar(value=spec.title)
            sub_v = tk.StringVar(value=spec.subtitle)
            pos_v = tk.StringVar(value=spec.position)

            row = ttk.Frame(body); row.pack(fill="x", pady=2)
            ttk.Label(row, text=tr("tool.news_desk.field.title"), width=10
                      ).pack(side="left")
            ttk.Entry(row, textvariable=title_v, width=42
                      ).pack(side="left", fill="x", expand=True)

            row = ttk.Frame(body); row.pack(fill="x", pady=2)
            ttk.Label(row, text=tr("tool.news_desk.field.subtitle"), width=10
                      ).pack(side="left")
            ttk.Entry(row, textvariable=sub_v, width=42
                      ).pack(side="left", fill="x", expand=True)

            row = ttk.Frame(body); row.pack(fill="x", pady=2)
            ttk.Label(row, text=tr("tool.news_desk.field.position"), width=10
                      ).pack(side="left")
            ttk.Combobox(row, textvariable=pos_v, state="readonly",
                          values=["bottom-left", "bottom-right"], width=20
                          ).pack(side="left")
        elif isinstance(spec, TopicStripOverlay):
            topic_v = tk.StringVar(value=spec.topic_text)
            row = ttk.Frame(body); row.pack(fill="x", pady=2)
            ttk.Label(row, text=tr("tool.news_desk.field.topic"), width=10
                      ).pack(side="left")
            ttk.Entry(row, textvariable=topic_v, width=42
                      ).pack(side="left", fill="x", expand=True)

        result = {"ok": False}
        def _ok():
            spec.start_sec = float(start_v.get())
            spec.end_sec = float(end_v.get())
            if isinstance(spec, LowerThirdOverlay):
                spec.title = title_v.get().strip()
                spec.subtitle = sub_v.get().strip()
                spec.position = pos_v.get() or "bottom-left"
            elif isinstance(spec, TopicStripOverlay):
                spec.topic_text = topic_v.get().strip()
            result["ok"] = True
            win.destroy()
        def _cancel():
            win.destroy()

        bf = ttk.Frame(body); bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text=tr("dialog.common.btn_cancel"), command=_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(bf, text=tr("dialog.common.btn_ok"), command=_ok
                   ).pack(side="right")

        win.update_idletasks()
        pw = self.master.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - win.winfo_width()) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.wait_window()
        return result["ok"]

    # ── Auto-derive ─────────────────────────────────────────────────────────

    def _derive_lower_third_from_basic(self) -> None:
        info = source_context.read_basic_info(self.project.source_dir)
        ctx = source_context.read_context(self.project.source_dir)
        if info.is_empty() and ctx.is_empty():
            messagebox.showinfo(
                "VideoCraft",
                tr("tool.news_desk.derive.no_basic"),
                parent=self.master)
            return
        title = info.host or ""
        # subtitle line: prefer host_bio + host_affiliation
        parts: list[str] = []
        if info.host_bio:
            parts.append(info.host_bio)
        if ctx.host_affiliation:
            parts.append(ctx.host_affiliation)
        sub = " · ".join(parts)
        spec = LowerThirdOverlay(
            title=title, subtitle=sub,
            start_sec=2.0, end_sec=max(12.0, min(self._duration, 30.0)),
            position="bottom-left",
        )
        self._overlays.append(spec)
        self._after_overlays_changed()

    def _derive_topic_strips_from_chapters(self) -> None:
        # Find any analysis.json in subtitles/.
        subs_dir = self.project.subtitles_dir
        chapters = self._load_any_chapters(subs_dir)
        if not chapters:
            messagebox.showinfo(
                "VideoCraft",
                tr("tool.news_desk.derive.no_chapters"),
                parent=self.master)
            return
        added = 0
        for ch in chapters:
            start_s = chapters_io.parse_time_str(ch.get("start", ""))
            end_s = chapters_io.parse_time_str(ch.get("end", ""))
            title = (ch.get("title") or "").strip()
            if not title or end_s <= start_s:
                continue
            self._overlays.append(TopicStripOverlay(
                topic_text=title, start_sec=start_s, end_sec=end_s))
            added += 1
        if added:
            self._after_overlays_changed()

    def _load_any_chapters(self, subs_dir: str) -> list[dict]:
        """Find any <iso>.analysis.json under subs_dir and return its
        chapter list. Picks the first one alphabetically."""
        if not os.path.isdir(subs_dir):
            return []
        for fn in sorted(os.listdir(subs_dir)):
            if fn.endswith(".analysis.json"):
                try:
                    env = chapters_io.load_analysis(os.path.join(subs_dir, fn))
                    chs = env.get("chapters") if isinstance(env, dict) else []
                    if isinstance(chs, list):
                        return chs
                except (OSError, json.JSONDecodeError):
                    continue
        return []

    # ── Preview push ────────────────────────────────────────────────────────

    def _push_preview(self) -> None:
        if self._preview is None:
            return
        try:
            self._preview.set_style(self._current_style)
            self._preview.set_overlays(self._overlays)
            # Subtitle cues: same prepare path the burn uses, so preview matches.
            short = (min(self._src_w, self._src_h)
                      if self._src_w and self._src_h else 1080)
            aspect = (f"{self._src_w}:{self._src_h}"
                       if self._src_w and self._src_h else "16:9")
            sub = self._current_style.subtitle
            if self._sub1_srt:
                cues1 = prepare_subtitle_cues(
                    self._sub1_srt, sub.sub1,
                    aspect=aspect, short_edge=short)
                self._preview.set_cues(cues1)
            else:
                self._preview.set_cues([])
            if self._sub2_srt:
                cues2 = prepare_subtitle_cues(
                    self._sub2_srt, sub.sub2,
                    aspect=aspect, short_edge=short)
                self._preview.set_cues_secondary(cues2)
            else:
                self._preview.set_cues_secondary([])
        except Exception as e:
            logger.debug(f"news_desk preview push failed: {e}")

    # ── Export ──────────────────────────────────────────────────────────────

    def _do_export(self) -> None:
        if self._processing:
            return
        src = self.project.source_video_path
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

        out = self._output_path()
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if os.path.exists(out):
            if not messagebox.askyesno(
                "VideoCraft",
                tr("tool.news_desk.confirm.overwrite", path=out),
                parent=self.master):
                return

        self._save_instance_config()
        self._processing = True
        self.set_busy()
        self.btn_export.config(state="disabled")
        self.label_status.config(
            text=tr("tool.news_desk.status.rendering"))
        self.progress["value"] = 0

        req = CompositionRequest(
            source_video=src,
            start_sec=0.0, end_sec=self._duration,
            output_path=out,
            style=self._current_style,
            source_srt=self._sub1_srt or None,
            source_srt_secondary=self._sub2_srt or None,
            overlays=list(self._overlays),
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
            logger.exception("news_desk render failed")
            self.master.after(0, self._on_export_failed, str(e))

    def _on_export_done(self, result) -> None:
        self._processing = False
        self.set_done()
        self.btn_export.config(state="normal")
        self.label_status.config(
            text=tr("tool.news_desk.status.done", path=result.output_path))
        self.progress["value"] = 100
        # Best-effort publish.md sidecar — video is already on disk; .md
        # failures are nice-to-have, never abort the success report.
        try:
            self._write_publish_sidecar()
        except Exception as e:
            logger.warning(f"news_desk publish.md write skipped: {e}")

    def _write_publish_sidecar(self) -> None:
        from tools.news_desk.publish import render_news_desk_publish
        from datetime import datetime as _dt
        bi = source_context.read_basic_info(self.project.source_dir)
        ctx = source_context.read_context(self.project.source_dir)

        # Pull chapters from the source project's analysis.json if any
        # exist. _load_any_chapters already handles the discovery.
        chapters = self._load_any_chapters(self.project.subtitles_dir)

        # LowerThird roster — strip overlay dataclasses to plain dicts so
        # the publish renderer stays decoupled from overlay types.
        lts = [{
            "title": ov.title,
            "subtitle": ov.subtitle,
            "start_sec": ov.start_sec,
            "end_sec": ov.end_sec,
        } for ov in self._overlays
              if isinstance(ov, LowerThirdOverlay)]

        # Adapted SRT pointers: rebased / split SRTs aren't kept on disk
        # (render writes them to %TEMP% and unlinks). Just point at the
        # source SRTs the user picked, project-relative for portability.
        adapted: list[str] = []
        for p in (self._sub1_srt, self._sub2_srt):
            if p:
                adapted.append(self._proj_relative(p))

        try:
            lang_iso = self.project.meta.language.source or "zh"
            project_title = self.project.meta.source.title
            source_url = self.project.meta.source.url
        except AttributeError:
            lang_iso, project_title, source_url = "zh", None, None

        md = render_news_desk_publish(
            project_title=project_title,
            source_url=source_url,
            basic_info=bi.to_dict(),
            context=ctx.to_dict(),
            chapters=chapters,
            lower_thirds=lts,
            adapted_srts=adapted,
            rendered_at=_dt.now().strftime("%Y-%m-%d %H:%M"),
            lang_iso=lang_iso,
        )
        out = os.path.join(self._instance_dir(), "publish.md")
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)

    def _on_export_failed(self, msg: str) -> None:
        self._processing = False
        self.set_error(msg)
        self.btn_export.config(state="normal")
        self.label_status.config(
            text=tr("tool.news_desk.status.failed"))
        self.progress["value"] = 0
        messagebox.showerror("VideoCraft", msg, parent=self.master)
