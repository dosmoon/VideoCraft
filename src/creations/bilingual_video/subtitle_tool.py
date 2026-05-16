"""
合并字幕分割和添加功能的工具
将 SplitSubtitles.py 的字符宽度剪裁功能合并到 AddSubTitleToMovieWithFFMpeg.py 中，
提供统一的界面来处理字幕分割和视频字幕烧录。
"""

from tools.base import ToolBase
from core.composition import presets as comp_presets
from i18n import tr
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser, simpledialog, ttk
import os
import sys
import subprocess
import threading
import time
import json
import srt
from datetime import timedelta, datetime
from hub_logger import logger


# ── 纯工具函数（从 core 导入）───────────────────────────────────────────────



def _probe_video_duration(video_path: str) -> float:
    """Probe video duration in seconds. Returns 0.0 if ffprobe fails."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15,
        )
        if out.returncode == 0:
            return float(out.stdout.strip())
    except Exception as e:
        logger.error(f"ffprobe failed to read duration ({os.path.basename(video_path)}): {e}")
    return 0.0


def _probe_video_resolution(video_path: str) -> tuple[int, int]:
    """Probe (width, height). Returns (0, 0) on failure. Used to derive
    the effective aspect for passthrough renders/previews."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             video_path],
            capture_output=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if out.returncode == 0:
            w, h = out.stdout.strip().split(",")
            return (int(w), int(h))
    except Exception as e:
        logger.error(f"ffprobe failed to read resolution ({os.path.basename(video_path)}): {e}")
    return (0, 0)


# ── 主界面 class ─────────────────────────────────────────────────────────────

class SubtitleToolApp(ToolBase):
    """双语字幕烧录工具 — Toplevel 内嵌版。"""

    def __init__(self, master, project, instance_name):
        """Project-mode-only entry point. Both `project` (Project) and
        `instance_name` (str) are required — bilingual burn is a project
        derivative, never a standalone tool, since the 2026-05 milestone.
        Per-instance state lives under
        <project>/derivatives/bilingual_video/<instance>/."""
        if project is None or not instance_name:
            raise ValueError(
                "SubtitleToolApp requires both project and instance_name; "
                "standalone mode is no longer supported.")

        self.master = master
        master.title(tr("tool.subtitle.title"))
        master.geometry("900x650")

        self.project = project
        self.instance_name = instance_name

        # 状态变量
        self.video_duration = 0.0
        self._src_w = 0
        self._src_h = 0
        self.processing = False

        # Tk 变量
        self.watermark_text_var          = tk.StringVar(value="字幕By老猿@OldApeTalk")
        self.watermark_txt_alpha_var     = tk.DoubleVar(value=60.0)   # 文字透明度
        self.watermark_color_var         = tk.StringVar(value="#00ffff")
        self.watermark_fontsize_var      = tk.IntVar(value=48)
        self.watermark_show_var          = tk.BooleanVar(value=True)
        # 图片/文字水印（单选）: "image" | "text"
        self.watermark_type_var          = tk.StringVar(value="image")
        self.watermark_img_path_var      = tk.StringVar(value=self._default_watermark_path())
        self.watermark_img_scale_var     = tk.DoubleVar(value=0.25)
        self.watermark_img_alpha_var     = tk.DoubleVar(value=100.0)  # 图片透明度

        self.sub1_fontsize_var  = tk.IntVar(value=24)
        self.sub1_color_var     = tk.StringVar(value="#FFFF00")
        self.sub1_show_var      = tk.BooleanVar(value=True)
        self.sub2_fontsize_var  = tk.IntVar(value=24)
        self.sub2_color_var     = tk.StringVar(value="#FFFFFF")
        self.sub2_show_var      = tk.BooleanVar(value=True)

        self.sub1_is_chinese_var = tk.BooleanVar(value=True)
        self.sub2_is_chinese_var = tk.BooleanVar(value=False)

        # Normalized layout — Tk vars hold percent (0-100) for ergonomic
        # spinbox display; _form_to_style divides by 100 to produce the
        # CompositionStyle fractions consumed by both renderers.
        self.sub_position_var          = tk.StringVar(value="bottom")
        self.sub_block_margin_pct_var  = tk.DoubleVar(value=8.0)
        self.sub_track_gap_pct_var     = tk.DoubleVar(value=12.0)
        self.wm_margin_x_pct_var       = tk.DoubleVar(value=2.5)
        self.wm_margin_y_pct_var       = tk.DoubleVar(value=2.5)

        self.encode_preset_var  = tk.StringVar(value="veryfast")

        # Live-preview plumbing.
        self._preview = None
        self._preview_refresh_after = None

        self._build_ui()

        # Load preset store and apply last-used preset (after Tk vars exist).
        self._preset_store = comp_presets.load_biliburn_store()
        last_name = comp_presets.get_last_used_biliburn(self._preset_store)
        last_style = comp_presets.get_biliburn_preset(
                          self._preset_store, last_name) \
            or comp_presets.get_biliburn_preset(
                          self._preset_store,
                          comp_presets.BUILTIN_DEFAULT_BILIBURN)
        if last_style is not None:
            self._apply_style(last_style)
        self._refresh_preset_combo(select=last_name)
        # Persist once so the file exists on first run.
        comp_presets.save_biliburn_store(self._preset_store)

        # Apply project-mode constraints (source/output lock, SRT picker
        # redirect, config restore) AFTER all base UI + presets are set up.
        self._enter_project_mode()

    def _build_ui(self):
        """Single-page workbench (aligned with clip tab1):
          - top: source video + duration
          - middle: PanedWindow [ scrollable style form | live WebView preview ]
          - bottom: progress labels + bar + 开始烧录 button.

        Pack order matters: bottom is packed FIRST with side='bottom' so
        the burn button is guaranteed visible even when the middle pane
        would otherwise grow past the available height.
        """
        root = self.master
        main = tk.Frame(root)
        main.pack(fill="both", expand=True)

        # ── Bottom: progress + burn (pack first so it reserves space) ─────
        bottom = tk.Frame(main)
        bottom.pack(side="bottom", fill="x", padx=8, pady=(4, 8))
        self.btn_merge = tk.Button(
            bottom, text=tr("tool.subtitle.action.start"),
            width=20, height=2, command=self._merge_videos,
            bg="#2563eb", fg="white", activebackground="#1e40af",
            activeforeground="white", relief="flat",
            font=("Microsoft YaHei UI", 10, "bold"))
        self.btn_merge.pack(side="right", padx=(8, 0))
        self.label_elapsed = tk.Label(
            bottom, text=tr("tool.subtitle.progress.elapsed_zero"),
            width=14, anchor="w")
        self.label_elapsed.pack(side="left")
        self.label_remaining = tk.Label(
            bottom, text=tr("tool.subtitle.progress.remaining_unknown"),
            width=14, anchor="w")
        self.label_remaining.pack(side="left", padx=(8, 0))
        self.progress_bar = ttk.Progressbar(
            bottom, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(side="left", padx=12, fill="x", expand=True)

        # ── Top: source video info ────────────────────────────────────────
        top = tk.Frame(main)
        top.pack(side="top", fill="x", padx=8, pady=(8, 4))
        tk.Label(top, text=tr("tool.subtitle.video.label")
                 ).pack(side="left")
        self.entry_video = tk.Entry(top, width=50, state="readonly",
                                      readonlybackground="white")
        self.entry_video.pack(side="left", fill="x", expand=True, padx=(4, 4))
        tk.Button(top, text=tr("tool.subtitle.browse"),
                  command=self._select_video).pack(side="left")
        self.label_duration = tk.Label(
            top, text=tr("tool.subtitle.progress.duration_unknown"),
            fg="#666")
        self.label_duration.pack(side="left", padx=(12, 0))

        # ── Middle: form | preview (fills remaining space) ────────────────
        pw = ttk.PanedWindow(main, orient="horizontal")
        pw.pack(side="top", fill="both", expand=True, padx=4, pady=(0, 4))
        form_outer = ttk.Frame(pw)
        preview_outer = ttk.Frame(pw)
        pw.add(form_outer, weight=3)
        pw.add(preview_outer, weight=4)

        canvas = tk.Canvas(form_outer, highlightthickness=0)
        sb = ttk.Scrollbar(form_outer, orient="vertical",
                           command=canvas.yview)
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

        from core.composition.preview import CompositionPreview
        self._preview = CompositionPreview(
            preview_outer, width=480, height=540)
        self._preview.widget.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_form(self, parent: ttk.Frame) -> None:
        # ── Preset ────────────────────────────────────────────────────────
        preset = ttk.LabelFrame(parent, text=tr("tool.subtitle.preset.frame_title"))
        preset.pack(fill="x", padx=6, pady=(6, 4))
        self.preset_combo = ttk.Combobox(preset, width=30, state="readonly")
        self.preset_combo.grid(row=0, column=0, columnspan=4,
                                 padx=4, pady=4, sticky="ew")
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        self.btn_preset_save = ttk.Button(
            preset, text=tr("tool.subtitle.preset.save"),
            command=self._on_preset_save)
        self.btn_preset_save.grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        ttk.Button(preset, text=tr("tool.subtitle.preset.save_as"),
                   command=self._on_preset_save_as).grid(
                       row=1, column=1, padx=2, pady=2, sticky="ew")
        self.btn_preset_delete = ttk.Button(
            preset, text=tr("tool.subtitle.preset.delete"),
            command=self._on_preset_delete)
        self.btn_preset_delete.grid(row=1, column=2, padx=2, pady=2, sticky="ew")
        ttk.Button(preset, text=tr("tool.subtitle.preset.reset_default"),
                   command=self._on_preset_reset_default).grid(
                       row=1, column=3, padx=2, pady=2, sticky="ew")
        for c in range(4):
            preset.columnconfigure(c, weight=1)

        # ── Subtitles (paths) ─────────────────────────────────────────────
        srts = ttk.LabelFrame(parent, text=tr("tool.subtitle.sub1.frame_title"))
        srts.pack(fill="x", padx=6, pady=4)
        row = ttk.Frame(srts); row.pack(fill="x", padx=4, pady=2)
        self.entry_sub1 = tk.Entry(row)
        self.entry_sub1.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text=tr("tool.subtitle.browse"),
                   command=self._select_subtitle1).pack(side="left")

        row = ttk.Frame(srts); row.pack(fill="x", padx=4, pady=2)
        ttk.Checkbutton(row, text=tr("tool.subtitle.sub.show"),
                        variable=self.sub1_show_var).pack(side="left")
        ttk.Label(row, text=tr("tool.subtitle.sub.fontsize")
                  ).pack(side="left", padx=(8, 0))
        ttk.Spinbox(row, from_=10, to=60, width=4,
                    textvariable=self.sub1_fontsize_var
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("tool.subtitle.sub.color")
                  ).pack(side="left", padx=(8, 0))
        ttk.Entry(row, width=8, textvariable=self.sub1_color_var
                  ).pack(side="left", padx=(4, 0))
        ttk.Button(row, text=tr("tool.subtitle.sub.choose"),
                   command=self._choose_sub1_color
                   ).pack(side="left", padx=(2, 0))

        row = ttk.Frame(srts); row.pack(fill="x", padx=4, pady=2)
        ttk.Checkbutton(row, text=tr("tool.subtitle.sub.is_chinese"),
                        variable=self.sub1_is_chinese_var
                        ).pack(side="left")

        srt2 = ttk.LabelFrame(parent, text=tr("tool.subtitle.sub2.frame_title"))
        srt2.pack(fill="x", padx=6, pady=4)
        row = ttk.Frame(srt2); row.pack(fill="x", padx=4, pady=2)
        self.entry_sub2 = tk.Entry(row)
        self.entry_sub2.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text=tr("tool.subtitle.browse"),
                   command=self._select_subtitle2).pack(side="left")

        row = ttk.Frame(srt2); row.pack(fill="x", padx=4, pady=2)
        ttk.Checkbutton(row, text=tr("tool.subtitle.sub.show"),
                        variable=self.sub2_show_var).pack(side="left")
        ttk.Label(row, text=tr("tool.subtitle.sub.fontsize")
                  ).pack(side="left", padx=(8, 0))
        ttk.Spinbox(row, from_=10, to=60, width=4,
                    textvariable=self.sub2_fontsize_var
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("tool.subtitle.sub.color")
                  ).pack(side="left", padx=(8, 0))
        ttk.Entry(row, width=8, textvariable=self.sub2_color_var
                  ).pack(side="left", padx=(4, 0))
        ttk.Button(row, text=tr("tool.subtitle.sub.choose"),
                   command=self._choose_sub2_color
                   ).pack(side="left", padx=(2, 0))

        row = ttk.Frame(srt2); row.pack(fill="x", padx=4, pady=2)
        ttk.Checkbutton(row, text=tr("tool.subtitle.sub.is_chinese"),
                        variable=self.sub2_is_chinese_var
                        ).pack(side="left")

        # ── Subtitle layout (normalized pct — single source of truth
        #    shared by libass burn + WebView preview) ───────────────────
        layout = ttk.LabelFrame(parent, text=tr("tool.subtitle.layout.frame_title"))
        layout.pack(fill="x", padx=6, pady=4)

        row = ttk.Frame(layout); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.subtitle.layout.anchor")).pack(side="left")
        ttk.Radiobutton(row, text=tr("tool.subtitle.layout.bottom"),
                        variable=self.sub_position_var, value="bottom"
                        ).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(row, text=tr("tool.subtitle.layout.top"),
                        variable=self.sub_position_var, value="top"
                        ).pack(side="left", padx=(4, 0))

        row = ttk.Frame(layout); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.subtitle.layout.block_margin")
                  ).pack(side="left")
        ttk.Spinbox(row, from_=0, to=30, increment=0.5, width=6, format="%.1f",
                    textvariable=self.sub_block_margin_pct_var
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text="%").pack(side="left")
        ttk.Label(row, text=tr("tool.subtitle.layout.track_gap")
                  ).pack(side="left", padx=(16, 0))
        ttk.Spinbox(row, from_=0, to=25, increment=0.5, width=6, format="%.1f",
                    textvariable=self.sub_track_gap_pct_var
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text="%").pack(side="left")

        # ── Watermark ─────────────────────────────────────────────────────
        wm = ttk.LabelFrame(parent, text=tr("tool.subtitle.watermark.frame_title"))
        wm.pack(fill="x", padx=6, pady=4)

        # Enable + type radios
        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        ttk.Checkbutton(row, text=tr("tool.subtitle.sub.show"),
                        variable=self.watermark_show_var).pack(side="left")
        ttk.Radiobutton(row, text=tr("tool.subtitle.watermark.image_radio"),
                        variable=self.watermark_type_var, value="image"
                        ).pack(side="left", padx=(12, 4))
        ttk.Radiobutton(row, text=tr("tool.subtitle.watermark.text_radio"),
                        variable=self.watermark_type_var, value="text"
                        ).pack(side="left")

        # Image controls
        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        wm_img_files = self._scan_watermark_images()
        wm_img_names = [os.path.basename(f) for f in wm_img_files]
        self._wm_img_combo = ttk.Combobox(
            row, values=wm_img_names, width=18, state="readonly")
        cur_name = os.path.basename(self.watermark_img_path_var.get())
        if cur_name in wm_img_names:
            self._wm_img_combo.set(cur_name)
        elif wm_img_names:
            self._wm_img_combo.set(wm_img_names[0])
        self._wm_img_combo.bind("<<ComboboxSelected>>", self._on_wm_img_selected)
        self._wm_img_combo.pack(side="left", padx=(0, 4))
        ttk.Button(row, text=tr("tool.subtitle.browse"),
                   command=self._select_watermark_image).pack(side="left")
        ttk.Label(row, text=tr("tool.subtitle.watermark.scale")
                  ).pack(side="left", padx=(8, 0))
        ttk.Spinbox(row, from_=0.05, to=0.5, increment=0.05, width=5,
                    format="%.2f",
                    textvariable=self.watermark_img_scale_var
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("tool.subtitle.watermark.alpha")
                  ).pack(side="left", padx=(8, 0))
        ttk.Spinbox(row, from_=0, to=100, width=5,
                    textvariable=self.watermark_img_alpha_var
                    ).pack(side="left", padx=(4, 0))

        # Text controls
        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        ttk.Combobox(row, textvariable=self.watermark_text_var,
                     values=["字幕By老猿@OldApeTalk", "字幕制作By 老猿",
                             "@VideoCraftNews"]
                     ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.subtitle.sub.fontsize")).pack(side="left")
        ttk.Spinbox(row, from_=10, to=100, width=4,
                    textvariable=self.watermark_fontsize_var
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("tool.subtitle.sub.color")
                  ).pack(side="left", padx=(8, 0))
        ttk.Entry(row, textvariable=self.watermark_color_var, width=8
                  ).pack(side="left", padx=(4, 0))
        ttk.Button(row, text=tr("tool.subtitle.sub.choose"),
                   command=self._choose_watermark_color
                   ).pack(side="left", padx=(2, 0))
        ttk.Label(row, text=tr("tool.subtitle.watermark.alpha")
                  ).pack(side="left", padx=(8, 0))
        ttk.Spinbox(row, from_=0, to=100, width=5,
                    textvariable=self.watermark_txt_alpha_var
                    ).pack(side="left", padx=(4, 0))

        # Watermark normalized margins from anchored corner.
        row = ttk.Frame(wm); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.subtitle.watermark.margin_x")
                  ).pack(side="left")
        ttk.Spinbox(row, from_=0, to=10, increment=0.5, width=6, format="%.1f",
                    textvariable=self.wm_margin_x_pct_var
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text="%").pack(side="left")
        ttk.Label(row, text=tr("tool.subtitle.watermark.margin_y")
                  ).pack(side="left", padx=(16, 0))
        ttk.Spinbox(row, from_=0, to=10, increment=0.5, width=6, format="%.1f",
                    textvariable=self.wm_margin_y_pct_var
                    ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text="%").pack(side="left")

        # ── Encoder ───────────────────────────────────────────────────────
        enc = ttk.LabelFrame(parent, text=tr("tool.subtitle.encoder.frame_title"))
        enc.pack(fill="x", padx=6, pady=4)
        row = ttk.Frame(enc); row.pack(fill="x", padx=4, pady=2)
        ttk.Label(row, text=tr("tool.subtitle.orientation.encode_label")
                  ).pack(side="left")
        ttk.Combobox(row, textvariable=self.encode_preset_var,
                     values=("ultrafast", "superfast", "veryfast",
                             "faster", "fast", "medium"),
                     state="readonly", width=12
                     ).pack(side="left", padx=(4, 0))
        ttk.Label(row, text=tr("tool.subtitle.orientation.encode_hint"),
                  foreground="gray").pack(side="left", padx=(8, 0))

        # ── Output (readonly) ─────────────────────────────────────────────
        out = ttk.LabelFrame(parent, text=tr("tool.subtitle.output.label"))
        out.pack(fill="x", padx=6, pady=4)
        row = ttk.Frame(out); row.pack(fill="x", padx=4, pady=2)
        self.entry_output = tk.Entry(row, state="readonly",
                                       readonlybackground="white")
        self.entry_output.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text=tr("tool.subtitle.browse"),
                   command=self._select_output).pack(side="left")

        self._wire_preview_traces()

    def _wire_preview_traces(self) -> None:
        """trace_add every form var that affects the preview render so
        edits get pushed into the WebView with a 200ms debounce."""
        for var in (
            self.sub1_show_var, self.sub1_fontsize_var, self.sub1_color_var,
            self.sub1_is_chinese_var,
            self.sub2_show_var, self.sub2_fontsize_var, self.sub2_color_var,
            self.sub2_is_chinese_var,
            self.sub_position_var, self.sub_block_margin_pct_var,
            self.sub_track_gap_pct_var,
            self.watermark_show_var, self.watermark_type_var,
            self.watermark_text_var, self.watermark_color_var,
            self.watermark_fontsize_var, self.watermark_txt_alpha_var,
            self.watermark_img_path_var, self.watermark_img_scale_var,
            self.watermark_img_alpha_var,
            self.wm_margin_x_pct_var, self.wm_margin_y_pct_var,
            self.encode_preset_var,
        ):
            var.trace_add("write", lambda *_a: self._schedule_preview_refresh())

    def _schedule_preview_refresh(self) -> None:
        """Debounce form edits — coalesce a burst of var changes into one
        preview rebuild after 200ms idle."""
        if self._preview_refresh_after is not None:
            try:
                self.master.after_cancel(self._preview_refresh_after)
            except Exception:
                pass
        self._preview_refresh_after = self.master.after(
            200, self._push_preview)

    def _push_preview(self) -> None:
        """Snapshot current form → CompositionStyle, push to WebView. Both
        SRT cue streams flow through core.composition.prepare_subtitle_cues
        so what the preview overlays matches the burn output exactly
        (max_chars wrap applied at the cue level, never visual wrapping
        in the JS layer)."""
        self._preview_refresh_after = None
        if self._preview is None:
            return
        style = self._form_to_style()
        try:
            self._preview.set_style(style)
        except Exception as e:
            logger.debug(f"Preview style push failed: {e}")
            return

        # Effective aspect/short_edge for the cue-wrap budget. Passthrough
        # uses the probed source dims so wrap budgets scale with the real
        # output canvas (e.g. wider for 4K landscape than for 9:16 1080).
        if style.output.mode == "passthrough" and self._src_w and self._src_h:
            eff_aspect = f"{self._src_w}:{self._src_h}"
            eff_short_edge = min(self._src_w, self._src_h)
        else:
            eff_aspect = style.output.aspect
            eff_short_edge = style.output.short_edge

        from core.composition import prepare_subtitle_cues
        sub1_path = self.entry_sub1.get().strip()
        sub2_path = self.entry_sub2.get().strip()
        sub1_cues = prepare_subtitle_cues(
            sub1_path, style.subtitle.sub1,
            aspect=eff_aspect, short_edge=eff_short_edge)
        sub2_cues = prepare_subtitle_cues(
            sub2_path, style.subtitle.sub2,
            aspect=eff_aspect, short_edge=eff_short_edge)
        try:
            self._preview.set_cues(sub1_cues)
            self._preview.set_cues_secondary(sub2_cues)
        except Exception as e:
            logger.debug(f"Preview cues push failed: {e}")

    # ── 图片水印辅助 ────────────────────────────────────────────────────────

    @staticmethod
    def _project_root():
        """返回项目根目录（Logo/ 所在目录）。"""
        # __file__ = .../src/creations/bilingual_video/subtitle_tool.py → up 4 levels
        return os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))

    def _scan_watermark_images(self):
        """扫描 Logo/ 目录下所有 WaterMark*.png，返回绝对路径列表。"""
        import glob as _glob
        logo_dir = os.path.join(self._project_root(), "Logo")
        return sorted(_glob.glob(os.path.join(logo_dir, "WaterMark*.png")))

    def _default_watermark_path(self):
        """返回默认水印图片路径（优先 WaterMark1.png，否则取第一个）。"""
        files = self._scan_watermark_images()
        preferred = os.path.join(self._project_root(), "Logo", "WaterMark1.png")
        if preferred in files:
            return preferred
        return files[0] if files else ""

    def _select_watermark_image(self):
        path = filedialog.askopenfilename(
            title=tr("tool.subtitle.dialog.select_watermark_image"),
            filetypes=[(tr("tool.subtitle.filter.png"), "*.png"),
                       (tr("tool.subtitle.filter.all_files"), "*.*")]
        )
        if path:
            self.watermark_img_path_var.set(path)
            # 同步刷新下拉列表
            self._refresh_wm_img_combo()

    def _refresh_wm_img_combo(self):
        """刷新水印图片 Combobox 列表，并尝试匹配当前路径。"""
        files = self._scan_watermark_images()
        names = [os.path.basename(f) for f in files]
        self._wm_img_combo['values'] = names
        cur = self.watermark_img_path_var.get()
        cur_name = os.path.basename(cur)
        if cur_name in names:
            self._wm_img_combo.set(cur_name)

    def _on_wm_img_selected(self, event=None):
        """Combobox 选中时更新完整路径。"""
        name = self._wm_img_combo.get()
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.watermark_img_path_var.set(os.path.join(base, "Logo", name))

    # ── 文件选择 ────────────────────────────────────────────────────────────

    def _select_video(self):
        """Source video is locked to the project. "Browse" opens the source
        folder so the user can verify which file the project points at."""
        try:
            os.startfile(os.path.dirname(self.project.source_video_path))
        except OSError:
            pass

    def _select_subtitle1(self):
        picked = self._pick_project_subtitle(tr("subtitle_tool.project.pick_primary"))
        if picked:
            snap = self._ensure_srt_snapshot(picked) or picked
            self.entry_sub1.delete(0, tk.END)
            self.entry_sub1.insert(0, snap)
            self._save_instance_config()
            self._schedule_preview_refresh()

    def _select_subtitle2(self):
        picked = self._pick_project_subtitle(tr("subtitle_tool.project.pick_secondary"))
        if picked:
            snap = self._ensure_srt_snapshot(picked) or picked
            self.entry_sub2.delete(0, tk.END)
            self.entry_sub2.insert(0, snap)
            self._save_instance_config()
            self._schedule_preview_refresh()

    def _select_output(self):
        """Output is locked under derivatives/<type>/<inst>/output.mp4.
        The "Browse" button opens the folder so the user can confirm."""
        try:
            os.makedirs(os.path.dirname(self.entry_output.get()), exist_ok=True)
            os.startfile(os.path.dirname(self.entry_output.get()))
        except OSError:
            pass

    # ── Project mode ────────────────────────────────────────────────────────

    def _enter_project_mode(self) -> None:
        """Lock paths to project canonical locations + restore prior config.
        Called from __init__ after the base UI is built."""
        # Window title shows the derivative type + instance for clarity.
        from core import derivative_types
        type_disp = derivative_types.display_name("bilingual_video")
        self.master.title(tr("subtitle_tool.project.title", type=type_disp, instance=self.instance_name))

        # Lock the source video field.
        self.entry_video.config(state="normal")
        self.entry_video.delete(0, tk.END)
        self.entry_video.insert(0, self.project.source_video_path)
        self.entry_video.config(state="readonly")

        # Lock the output field to derivatives/<type>/<instance>/output.mp4.
        inst_dir = self.project.derivative_dir(
            "bilingual_video", self.instance_name)
        os.makedirs(inst_dir, exist_ok=True)
        output_path = os.path.join(inst_dir, "output.mp4")
        self.entry_output.config(state="normal")
        self.entry_output.delete(0, tk.END)
        self.entry_output.insert(0, output_path)
        self.entry_output.config(state="readonly")

        # Restore SRT selections + style params from instance config.json.
        self._load_instance_config()

        # Probe duration + resolution so the top bar shows duration and the
        # preview/burn passthrough path knows the effective aspect (= source
        # dims) without re-probing per refresh.
        self.video_duration = _probe_video_duration(self.project.source_video_path)
        self._src_w, self._src_h = _probe_video_resolution(
            self.project.source_video_path)
        if self.video_duration > 0:
            hms = time.strftime('%H:%M:%S', time.gmtime(self.video_duration))
            self.label_duration.config(
                text=tr("tool.subtitle.progress.duration_fmt", hms=hms))

        # Point the live WebView preview at the source video and push the
        # current style + cues so the user sees their preset choices land.
        if self._preview is not None:
            try:
                self._preview.set_source(self.project.source_video_path, 0.0, 0.0)
            except Exception as e:
                logger.debug(f"Preview set_source failed: {e}")
            self._push_preview()

    def _pick_project_subtitle(self, title: str) -> str | None:
        """Modal combobox dialog showing <project>/subtitles/*.srt.

        Returns absolute path of the picked SRT or None if cancelled.
        """
        from core import lang_names
        subs_dir = self.project.subtitles_dir
        files = []
        try:
            for fn in sorted(os.listdir(subs_dir)):
                if fn.endswith(".srt"):
                    files.append(fn)
        except OSError:
            pass
        if not files:
            messagebox.showinfo(
                "VideoCraft",
                tr("subtitle_tool.project.no_subs"),
                parent=self.master,
            )
            return None

        win = tk.Toplevel(self.master)
        win.title(title)
        win.transient(self.master)
        win.grab_set()
        win.resizable(False, False)

        # Build labeled options
        items: list[tuple[str, str]] = []  # (filename, display_label)
        for fn in files:
            iso = fn[:-4]
            try:
                friendly = lang_names.friendly_name(iso, "zh")
            except Exception:
                friendly = iso
            items.append((fn, f"{friendly} ({fn})"))

        var = tk.StringVar(value=items[0][1])

        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title,
                  font=("Microsoft YaHei UI", 11, "bold")
                  ).pack(anchor="w", pady=(0, 8))
        ttk.Label(body, text=tr("subtitle_tool.project.available_subs")).pack(anchor="w")
        ttk.Combobox(body, textvariable=var,
                     values=[lbl for _, lbl in items],
                     state="readonly", width=30,
                     ).pack(fill="x", pady=(4, 12))

        chosen: list[str | None] = [None]

        def on_ok():
            disp = var.get()
            for fn, lbl in items:
                if lbl == disp:
                    chosen[0] = os.path.join(subs_dir, fn)
                    break
            win.destroy()

        def on_cancel():
            chosen[0] = None
            win.destroy()

        def on_clear():
            chosen[0] = ""  # empty string = clear selection
            win.destroy()

        btns = ttk.Frame(body)
        btns.pack(fill="x")
        ttk.Button(btns, text=tr("dialog.common.btn_cancel"), command=on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_ok"), command=on_ok
                   ).pack(side="right")
        ttk.Button(btns, text=tr("subtitle_tool.project.btn_clear"), command=on_clear
                   ).pack(side="left")

        # Center
        win.update_idletasks()
        pw = self.master.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - win.winfo_width()) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")

        win.wait_window()
        return chosen[0]

    def _instance_dir(self) -> str:
        return self.project.derivative_dir(
            "bilingual_video", self.instance_name)

    def _instance_config_path(self) -> str:
        return os.path.join(self._instance_dir(), "config.json")

    # ── SRT snapshot (per-instance immutable source) ─────────────────────
    #
    # Per the derivative snapshot principle: when the user picks an SRT we
    # immediately copy it into the instance dir as source-subtitles.<iso>.srt.
    # From that point on the workbench reads ONLY from the snapshot, so
    # upstream regeneration in <project>/subtitles/ cannot affect already-
    # rendered outputs or the burned subtitle text for this instance.

    def _srt_snapshot_path(self, iso: str) -> str:
        return os.path.join(self._instance_dir(), f"source-subtitles.{iso}.srt")

    def _ensure_srt_snapshot(self, upstream_srt: str | None) -> str | None:
        """Copy <project>/subtitles/<iso>.srt → instance snapshot path
        if not already present. Returns the snapshot path, or None when
        the iso can't be derived / upstream is missing / copy fails.

        Idempotent: existing snapshot is left untouched. To force a
        re-snapshot the user must delete the instance dir."""
        if not upstream_srt:
            return None
        iso = os.path.splitext(os.path.basename(upstream_srt))[0]
        if not iso:
            return None
        snap = self._srt_snapshot_path(iso)
        if os.path.isfile(snap):
            return snap
        if not os.path.isfile(upstream_srt):
            return None
        try:
            os.makedirs(self._instance_dir(), exist_ok=True)
            import shutil
            shutil.copy2(upstream_srt, snap)
            return snap
        except OSError as e:
            logger.warning(f"Failed to snapshot SRT {upstream_srt} → {snap}: {e}")
            return None

    def _extract_srt_iso(self, srt_path: str) -> str | None:
        """Derive the ISO code from either a snapshot path
        (source-subtitles.<iso>.srt) or a plain upstream/standalone SRT
        (<iso>.srt). Returns None when neither shape matches."""
        if not srt_path:
            return None
        fn = os.path.basename(srt_path)
        prefix = "source-subtitles."
        if fn.startswith(prefix) and fn.endswith(".srt"):
            iso = fn[len(prefix):-4]
            return iso or None
        if fn.endswith(".srt"):
            iso = fn[:-4]
            return iso or None
        return None

    def _load_instance_config(self) -> None:
        """Restore SRT selections + style params from the instance's
        config.json. Snapshot is the authoritative SRT — when the config
        references one (or carries the legacy upstream filename), we
        resolve the iso, lazy-backfill the snapshot from upstream if
        missing, then put the snapshot path into the entry field."""
        path = self._instance_config_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            return

        def _resolve_and_fill(entry, iso: str | None) -> None:
            if not iso:
                return
            snap = self._srt_snapshot_path(iso)
            if not os.path.isfile(snap):
                # Lazy backfill: pre-snapshot-principle instances (and
                # instances whose dir got cleaned) get a one-shot copy
                # from upstream on first re-open.
                upstream = os.path.join(self.project.subtitles_dir,
                                          f"{iso}.srt")
                self._ensure_srt_snapshot(upstream)
            chosen = snap if os.path.isfile(snap) else None
            if chosen:
                entry.delete(0, tk.END)
                entry.insert(0, chosen)

        # New schema: primary_srt_iso / secondary_srt_iso store the iso
        # directly. Legacy schema stored primary_srt = "<iso>.srt" (the
        # upstream filename) — extract iso and treat the same way.
        primary_iso = cfg.get("primary_srt_iso")
        if primary_iso is None and cfg.get("primary_srt"):
            primary_iso = os.path.splitext(cfg["primary_srt"])[0] or None
        _resolve_and_fill(self.entry_sub1, primary_iso)

        secondary_iso = cfg.get("secondary_srt_iso")
        if secondary_iso is None and cfg.get("secondary_srt"):
            secondary_iso = os.path.splitext(cfg["secondary_srt"])[0] or None
        _resolve_and_fill(self.entry_sub2, secondary_iso)

        # Style payload — accept either the current CompositionStyle dict
        # ("subtitle" key present, nested) or the legacy flat burn_presets
        # shape ("sub1_fontsize" etc.). The latter is lazy-migrated on
        # touch — no separate migration script.
        params = cfg.get("params")
        if isinstance(params, dict):
            from core.composition.presets import (composition_style_from_dict,
                                                    PresetSchemaError)
            try:
                if "subtitle" in params and isinstance(params["subtitle"], dict):
                    style = composition_style_from_dict(params)
                else:
                    style = self._legacy_flat_to_style(params)
                self._apply_style(style)
            except (PresetSchemaError, TypeError, ValueError, KeyError):
                pass

    def _save_instance_config(self) -> None:
        """Persist SRT iso choices + style params to the instance's
        config.json. The selected SRT entry holds the snapshot path
        (source-subtitles.<iso>.srt); we save just the iso so the
        snapshot path can be re-derived without hard-coding it."""
        sub1 = self.entry_sub1.get().strip()
        sub2 = self.entry_sub2.get().strip()
        from core.composition.presets import composition_style_to_dict
        cfg = {
            "schema_version": 2,
            "primary_srt_iso": self._extract_srt_iso(sub1),
            "secondary_srt_iso": self._extract_srt_iso(sub2),
            "params": composition_style_to_dict(self._form_to_style()),
        }
        # Preserve burned_at if it already exists.
        path = self._instance_config_path()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                if isinstance(old, dict) and old.get("burned_at"):
                    cfg["burned_at"] = old["burned_at"]
            except (OSError, json.JSONDecodeError):
                pass
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # transient FS issue; user just loses the autosave snapshot

    def _mark_instance_burned(self) -> None:
        """Stamp burned_at into config.json after a successful burn."""
        path = self._instance_config_path()
        cfg: dict = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if not isinstance(cfg, dict):
                    cfg = {}
            except (OSError, json.JSONDecodeError):
                cfg = {}
        cfg["burned_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _write_publish_sidecar(self) -> None:
        """Render publish.md next to output.mp4 so the user has a
        copy-paste-ready YouTube description + chapter block.

        Best-effort: video is already on disk, sidecar is nice-to-have,
        any failure is swallowed and logged.
        """
        try:
            from creations.bilingual_video.publish import render_bilingual_publish

            cfg_path = self._instance_config_path()
            inst_dir = os.path.dirname(cfg_path)
            cfg: dict = {}
            if os.path.isfile(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)

            lang_iso = (cfg.get("primary_srt_iso") or "").strip() \
                or os.path.splitext((cfg.get("primary_srt") or "").strip())[0] \
                or (self.project.meta.language.source or "zh")

            # Pull chapters from the source project's analysis.json
            # if it exists; absence means the user hasn't generated one
            # — publish.md then renders without a chapter block.
            chapters: list[dict] = []
            ch_path = os.path.join(
                self.project.subtitles_dir,
                f"{lang_iso}.analysis.json")
            if os.path.isfile(ch_path):
                try:
                    with open(ch_path, "r", encoding="utf-8") as f:
                        ch_data = json.load(f)
                    chapters = list(ch_data.get("chapters") or [])
                except (OSError, json.JSONDecodeError):
                    pass

            # Adapted SRTs sit in the instance dir as subtitles_*.srt.
            try:
                adapted = sorted(
                    n for n in os.listdir(inst_dir)
                    if n.startswith("subtitles_") and n.endswith(".srt"))
            except OSError:
                adapted = []

            md = render_bilingual_publish(
                project_title=self.project.meta.source.title,
                source_url=self.project.meta.source.url,
                chapters=chapters,
                adapted_srts=adapted,
                burned_at=cfg.get("burned_at", ""),
                lang_iso=lang_iso,
            )
            out_path = os.path.join(inst_dir, "publish.md")
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
        except Exception as e:
            logger.warning(f"publish.md write skipped: {e}")

    # ── 颜色选择 ────────────────────────────────────────────────────────────

    def _choose_watermark_color(self):
        color = colorchooser.askcolor(title=tr("tool.subtitle.dialog.choose_watermark_color"))
        if color and color[1]:
            self.watermark_color_var.set(color[1])

    def _choose_sub1_color(self):
        color = colorchooser.askcolor(title=tr("tool.subtitle.dialog.choose_sub1_color"))
        if color and color[1]:
            self.sub1_color_var.set(color[1])

    def _choose_sub2_color(self):
        color = colorchooser.askcolor(title=tr("tool.subtitle.dialog.choose_sub2_color"))
        if color and color[1]:
            self.sub2_color_var.set(color[1])

    # ── Style ↔ Form converters (preset / config payload shape) ──────────
    #
    # The bilingual burn preset and per-instance config both store a
    # CompositionStyle dict — same shape clip uses, just always passthrough
    # mode. _form_to_style() snapshots Tk vars to a CompositionStyle,
    # _apply_style() pushes one back into the Tk vars.
    # Subtitle line-wrap budget is always auto-computed from aspect +
    # fontsize + is_chinese (via compute_subtitle_max_chars). No manual
    # override anymore — the UI used to expose split toggle + max_chars
    # spinbox, but with auto enabled the user never needed to touch it.

    def _form_to_style(self) -> 'CompositionStyle':
        from core.composition import (
            CompositionStyle, OutputGeometry, SubtitleStyle,
            SubtitleLineStyle, WatermarkStyle,
        )
        return CompositionStyle(
            output=OutputGeometry(mode="passthrough"),
            encode_preset=self.encode_preset_var.get(),
            subtitle=SubtitleStyle(
                sub1=SubtitleLineStyle(
                    enabled=bool(self.sub1_show_var.get()),
                    fontsize=int(self.sub1_fontsize_var.get()),
                    color=self.sub1_color_var.get(),
                    bold=True,
                    is_chinese=bool(self.sub1_is_chinese_var.get()),
                ),
                sub2=SubtitleLineStyle(
                    enabled=bool(self.sub2_show_var.get()),
                    fontsize=int(self.sub2_fontsize_var.get()),
                    color=self.sub2_color_var.get(),
                    bold=False,
                    is_chinese=bool(self.sub2_is_chinese_var.get()),
                ),
                position=self.sub_position_var.get() or "bottom",
                block_margin_pct=float(self.sub_block_margin_pct_var.get()) / 100.0,
                track_gap_pct=float(self.sub_track_gap_pct_var.get()) / 100.0,
            ),
            watermark=WatermarkStyle(
                enabled=bool(self.watermark_show_var.get()),
                type=self.watermark_type_var.get(),
                text=self.watermark_text_var.get(),
                text_fontsize=int(self.watermark_fontsize_var.get()),
                text_color=self.watermark_color_var.get(),
                text_opacity=int(self.watermark_txt_alpha_var.get()),
                image_path=self.watermark_img_path_var.get(),
                image_scale=float(self.watermark_img_scale_var.get()),
                image_opacity=int(self.watermark_img_alpha_var.get()),
                position="top-right",
                margin_x_pct=float(self.wm_margin_x_pct_var.get()) / 100.0,
                margin_y_pct=float(self.wm_margin_y_pct_var.get()) / 100.0,
            ),
        )

    def _apply_style(self, style: 'CompositionStyle') -> None:
        """Push a CompositionStyle into the Tk vars."""
        sub = style.subtitle
        for src, show, fsize, color, is_cn in (
            (sub.sub1, self.sub1_show_var, self.sub1_fontsize_var,
             self.sub1_color_var, self.sub1_is_chinese_var),
            (sub.sub2, self.sub2_show_var, self.sub2_fontsize_var,
             self.sub2_color_var, self.sub2_is_chinese_var),
        ):
            try:
                show.set(bool(src.enabled))
                fsize.set(int(src.fontsize))
                color.set(src.color)
                is_cn.set(bool(src.is_chinese))
            except tk.TclError:
                pass

        # Normalized layout fields (percent in the UI, fraction in the schema).
        try:
            self.sub_position_var.set(sub.position or "bottom")
            self.sub_block_margin_pct_var.set(round(sub.block_margin_pct * 100.0, 1))
            self.sub_track_gap_pct_var.set(round(sub.track_gap_pct * 100.0, 1))
        except tk.TclError:
            pass

        wm = style.watermark
        try:
            self.watermark_show_var.set(bool(wm.enabled))
            self.watermark_type_var.set(wm.type or "image")
            self.watermark_text_var.set(wm.text or "")
            self.watermark_fontsize_var.set(int(wm.text_fontsize))
            self.watermark_color_var.set(wm.text_color)
            self.watermark_txt_alpha_var.set(float(wm.text_opacity))
            self.watermark_img_path_var.set(wm.image_path or "")
            self.watermark_img_scale_var.set(float(wm.image_scale))
            self.watermark_img_alpha_var.set(float(wm.image_opacity))
            self.wm_margin_x_pct_var.set(round(wm.margin_x_pct * 100.0, 1))
            self.wm_margin_y_pct_var.set(round(wm.margin_y_pct * 100.0, 1))
        except tk.TclError:
            pass

        try:
            self.encode_preset_var.set(style.encode_preset or "veryfast")
        except tk.TclError:
            pass

        # Watermark image path may be empty (builtin default) or stale →
        # fall back to first available image under Logo/.
        cur_img = self.watermark_img_path_var.get()
        if not cur_img or not os.path.exists(cur_img):
            self.watermark_img_path_var.set(self._default_watermark_path())
        if hasattr(self, "_wm_img_combo"):
            self._refresh_wm_img_combo()

    def _legacy_flat_to_style(self, flat: dict) -> 'CompositionStyle':
        """Convert a pre-S4 burn_presets-flat-dict params payload into a
        CompositionStyle. Used only on lazy load of legacy instance
        config.json files. The legacy split/max_chars fields are
        discarded — auto wrap is the only behavior now."""
        from core.composition import (
            CompositionStyle, OutputGeometry, SubtitleStyle,
            SubtitleLineStyle, WatermarkStyle,
        )
        return CompositionStyle(
            output=OutputGeometry(mode="passthrough"),
            encode_preset=str(flat.get("encode_preset", "veryfast")),
            subtitle=SubtitleStyle(
                sub1=SubtitleLineStyle(
                    enabled=bool(flat.get("sub1_show", True)),
                    fontsize=int(flat.get("sub1_fontsize", 24)),
                    color=str(flat.get("sub1_color", "#FFFF00")),
                    bold=True,
                    is_chinese=bool(flat.get("sub1_is_chinese", True)),
                ),
                sub2=SubtitleLineStyle(
                    enabled=bool(flat.get("sub2_show", True)),
                    fontsize=int(flat.get("sub2_fontsize", 24)),
                    color=str(flat.get("sub2_color", "#FFFFFF")),
                    bold=False,
                    is_chinese=bool(flat.get("sub2_is_chinese", False)),
                ),
                position="bottom",
            ),
            watermark=WatermarkStyle(
                enabled=bool(flat.get("watermark_show", True)),
                type=str(flat.get("watermark_type", "image")),
                text=str(flat.get("watermark_text", "")),
                text_fontsize=int(flat.get("watermark_fontsize", 48)),
                text_color=str(flat.get("watermark_color", "#00ffff")),
                text_opacity=int(float(flat.get("watermark_txt_alpha", 60))),
                image_path=str(flat.get("watermark_img_path", "")),
                image_scale=float(flat.get("watermark_img_scale", 0.25)),
                image_opacity=int(float(flat.get("watermark_img_alpha", 100))),
                position="top-right",
            ),
        )

    # ── Preset combo wiring ──────────────────────────────────────────────

    def _refresh_preset_combo(self, select: str = None) -> None:
        names = comp_presets.list_biliburn_presets(self._preset_store)
        self.preset_combo["values"] = names
        if select and select in names:
            self.preset_combo.set(select)
        elif names:
            self.preset_combo.set(names[0])
        self._update_preset_button_state()

    def _update_preset_button_state(self) -> None:
        is_builtin = comp_presets.is_builtin_biliburn(self.preset_combo.get())
        state = "disabled" if is_builtin else "normal"
        self.btn_preset_save.config(state=state)
        self.btn_preset_delete.config(state=state)

    def _on_preset_selected(self, event=None) -> None:
        name = self.preset_combo.get()
        style = comp_presets.get_biliburn_preset(self._preset_store, name)
        if style is None:
            return
        self._apply_style(style)
        comp_presets.set_last_used_biliburn(self._preset_store, name)
        comp_presets.save_biliburn_store(self._preset_store)
        self._update_preset_button_state()

    def _on_preset_save(self) -> None:
        name = self.preset_combo.get()
        if comp_presets.is_builtin_biliburn(name):
            messagebox.showinfo(tr("dialog.common.info"),
                                tr("tool.subtitle.preset.default_protected"))
            return
        comp_presets.upsert_biliburn_preset(
            self._preset_store, name, self._form_to_style())
        comp_presets.save_biliburn_store(self._preset_store)
        messagebox.showinfo(tr("tool.subtitle.preset.saved_title"),
                            tr("tool.subtitle.preset.saved_msg", name=name))

    def _on_preset_save_as(self) -> None:
        name = simpledialog.askstring(
            tr("tool.subtitle.preset.save_as_title"),
            tr("tool.subtitle.preset.save_as_prompt"),
            parent=self.master,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self._preset_store.get("presets", {}):
            if not messagebox.askyesno(
                tr("tool.subtitle.preset.overwrite_title"),
                tr("tool.subtitle.preset.overwrite_confirm", name=name),
            ):
                return
        comp_presets.upsert_biliburn_preset(
            self._preset_store, name, self._form_to_style())
        comp_presets.set_last_used_biliburn(self._preset_store, name)
        comp_presets.save_biliburn_store(self._preset_store)
        self._refresh_preset_combo(select=name)

    def _on_preset_delete(self) -> None:
        name = self.preset_combo.get()
        if comp_presets.is_builtin_biliburn(name):
            return
        if not messagebox.askyesno(
            tr("tool.subtitle.preset.delete_title"),
            tr("tool.subtitle.preset.delete_confirm", name=name),
        ):
            return
        comp_presets.delete_biliburn_preset(self._preset_store, name)
        comp_presets.save_biliburn_store(self._preset_store)
        self._refresh_preset_combo(select=comp_presets.BUILTIN_DEFAULT_BILIBURN)
        default_style = comp_presets.get_biliburn_preset(
            self._preset_store, comp_presets.BUILTIN_DEFAULT_BILIBURN)
        if default_style is not None:
            self._apply_style(default_style)

    def _on_preset_reset_default(self) -> None:
        """Reload the Default preset values into the UI without changing
        last_used."""
        style = comp_presets.get_biliburn_preset(
            self._preset_store, comp_presets.BUILTIN_DEFAULT_BILIBURN)
        if style is not None:
            self._apply_style(style)

    # ── 辅助 ────────────────────────────────────────────────────────────────

    def _update_progress(self, progress, elapsed, remaining):
        self.progress_bar['value'] = progress
        elapsed_hms = time.strftime('%H:%M:%S', time.gmtime(elapsed))
        self.label_elapsed.config(text=tr("tool.subtitle.progress.elapsed_fmt", hms=elapsed_hms))
        if remaining > 0:
            remaining_hms = time.strftime('%H:%M:%S', time.gmtime(remaining))
            self.label_remaining.config(text=tr("tool.subtitle.progress.remaining_fmt", hms=remaining_hms))
        else:
            self.label_remaining.config(text=tr("tool.subtitle.progress.remaining_calc"))

    # ── 主流程 ──────────────────────────────────────────────────────────────

    def _merge_videos(self):
        if self.processing:
            messagebox.showwarning(tr("dialog.common.warning"),
                                   tr("tool.subtitle.warning.processing"))
            return

        video_path = self.entry_video.get()
        sub1_path  = self.entry_sub1.get()
        sub2_path  = self.entry_sub2.get()

        show_sub1 = self.sub1_show_var.get()
        show_sub2 = self.sub2_show_var.get()

        if not video_path:
            messagebox.showerror(tr("dialog.common.error"), tr("tool.subtitle.error.no_video"))
            return
        if not os.path.exists(video_path):
            messagebox.showerror(tr("dialog.common.error"),
                                 tr("tool.subtitle.error.video_not_found", path=video_path))
            return
        if show_sub1 and not sub1_path:
            messagebox.showerror(tr("dialog.common.error"), tr("tool.subtitle.error.no_sub1"))
            return
        if show_sub2 and not sub2_path:
            messagebox.showerror(tr("dialog.common.error"), tr("tool.subtitle.error.no_sub2"))
            return
        if not show_sub1 and not show_sub2:
            messagebox.showerror(tr("dialog.common.error"), tr("tool.subtitle.error.no_subtitle"))
            return
        sub1_name = tr("tool.subtitle.sub1_name")
        sub2_name = tr("tool.subtitle.sub2_name")
        for p, name in ([(sub1_path, sub1_name)] if show_sub1 else []) + \
                       ([(sub2_path, sub2_name)] if show_sub2 else []):
            if not os.path.exists(p):
                messagebox.showerror(tr("dialog.common.error"),
                                     tr("tool.subtitle.error.sub_not_found", name=name, path=p))
                return

        # ── Subtitle adaptation + export ──
        # When a SRT is selected, we always export it next to output.mp4
        # as a shippable deliverable (user can upload it to YouTube etc).
        # If wrap-split is on, the exported file is the line-wrapped form
        # adapted for screen display; otherwise it's a copy of the source.
        # Shippable sidecar SRT lands at derivative_dir/subtitles_<iso>.srt
        # so the user can upload it alongside output.mp4 to YouTube etc.
        # When the SRT is a snapshot (source-subtitles.<iso>.srt) we strip
        # that prefix so the deliverable is named by language alone.
        def _adapted_path(src_srt: str) -> str:
            base = os.path.basename(src_srt)
            stem, _ = os.path.splitext(base)
            prefix = "source-subtitles."
            if stem.startswith(prefix):
                stem = stem[len(prefix):]
            inst_dir = self.project.derivative_dir(
                "bilingual_video", self.instance_name)
            os.makedirs(inst_dir, exist_ok=True)
            return os.path.join(inst_dir, f"subtitles_{stem}.srt")

        # _write_adapted produces the shippable sidecar by routing the
        # source SRT through prepare_subtitle_cues — same auto-wrap the
        # burn applies. One core helper, two consumers (sidecar + render),
        # zero policy drift.
        from core.composition import prepare_subtitle_cues
        from core.composition.style import SubtitleLineStyle as _SLS

        def _write_adapted(src_srt: str, line: _SLS,
                            aspect: str, short_edge: int) -> str:
            dst = _adapted_path(src_srt)
            cues = prepare_subtitle_cues(
                src_srt, line, aspect=aspect, short_edge=short_edge)
            if not cues:
                # Fall back to a plain copy so the sidecar still ships.
                if os.path.abspath(dst) != os.path.abspath(src_srt):
                    import shutil
                    shutil.copy2(src_srt, dst)
                return dst
            from datetime import timedelta
            subs = [srt.Subtitle(
                        index=i + 1,
                        start=timedelta(seconds=c["start"]),
                        end=timedelta(seconds=c["end"]),
                        content=c["text"])
                    for i, c in enumerate(cues)]
            with open(dst, 'w', encoding='utf-8') as f:
                f.write(srt.compose(subs))
            return dst

        # Effective aspect/short_edge for the auto-wrap budget — passthrough
        # uses probed source dims.
        _eff_aspect = (f"{self._src_w}:{self._src_h}"
                        if (self._src_w and self._src_h) else "16:9")
        _eff_short_edge = (min(self._src_w, self._src_h)
                            if (self._src_w and self._src_h) else 1080)

        temp_sub1_path = sub1_path
        temp_sub2_path = sub2_path
        try:
            if show_sub1:
                temp_sub1_path = _write_adapted(
                    sub1_path,
                    _SLS(enabled=True, fontsize=int(self.sub1_fontsize_var.get()),
                          is_chinese=bool(self.sub1_is_chinese_var.get())),
                    _eff_aspect, _eff_short_edge)
            if show_sub2:
                temp_sub2_path = _write_adapted(
                    sub2_path,
                    _SLS(enabled=True, fontsize=int(self.sub2_fontsize_var.get()),
                          is_chinese=bool(self.sub2_is_chinese_var.get())),
                    _eff_aspect, _eff_short_edge)
        except Exception as e:
            messagebox.showerror(tr("tool.subtitle.error.split_failed_title"), str(e))
            return

        # Resolve absolute paths. Output is locked to the instance dir by
        # _enter_project_mode; entry_output is readonly so it can't be
        # blanked, but guard anyway.
        video_path_abs = os.path.abspath(video_path)
        output_path = os.path.abspath(self.entry_output.get().strip())
        if not output_path:
            messagebox.showerror(tr("dialog.common.error"),
                                 tr("tool.subtitle.error.output_dir_missing", dir=""))
            return
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.isdir(out_dir):
            messagebox.showerror(tr("dialog.common.error"),
                                 tr("tool.subtitle.error.output_dir_missing", dir=out_dir))
            return

        # Build the CompositionRequest from Tk vars. Bilingual burn runs
        # the composition engine in passthrough mode so source resolution
        # and aspect are preserved verbatim. _form_to_style is the shared
        # converter — same dataclass goes into config.json and preset.
        from core.composition import CompositionRequest, render_composition

        style = self._form_to_style()
        # show_sub1/show_sub2 in render must respect the live Tk checkbox
        # which can disagree with the form-snapshot if the user touched it
        # mid-burn. Honor the validated values from earlier in this fn.
        style.subtitle.sub1.enabled = show_sub1
        style.subtitle.sub2.enabled = show_sub2
        encode_preset = style.encode_preset

        # Resolve duration. self.video_duration is populated when the user
        # selects a video; fall back to a probe if it didn't take.
        duration = float(self.video_duration or 0.0)
        if duration <= 0:
            duration = _probe_video_duration(video_path_abs)
        if duration <= 0:
            messagebox.showerror(tr("dialog.common.error"),
                                 tr("tool.subtitle.warning.no_ffprobe"))
            return

        req = CompositionRequest(
            source_video=video_path_abs,
            start_sec=0.0,
            end_sec=duration,
            output_path=output_path,
            style=style,
            source_srt=temp_sub1_path if show_sub1 else None,
            source_srt_secondary=temp_sub2_path if show_sub2 else None,
        )

        crf_map = {'ultrafast': 28, 'superfast': 26, 'veryfast': 25,
                   'faster': 24, 'fast': 23, 'medium': 23}
        crf = crf_map.get(encode_preset, 25)

        self.processing = True
        self.btn_merge.config(state=tk.DISABLED)
        self.progress_bar['value'] = 0
        self.label_elapsed.config(text=tr("tool.subtitle.progress.elapsed_zero"))
        self.label_remaining.config(text=tr("tool.subtitle.progress.remaining_unknown"))
        self.set_busy()

        threading.Thread(
            target=self._run_composition,
            args=(req, crf, render_composition, output_path),
            daemon=True
        ).start()

    def _run_composition(self, req, crf, render_fn, output_path):
        """Drive composition.render_composition from a worker thread and
        bridge its (stage, pct) progress callback to the Tk progress bar."""
        start_time = time.time()

        def on_progress(stage, pct):
            if pct < 0 or pct > 100:
                return
            elapsed = time.time() - start_time
            remaining = ((elapsed / pct) * (100 - pct)) if pct > 0 else 0.0
            self.master.after(0, self._update_progress, pct, elapsed, remaining)

        try:
            render_fn(req, on_progress=on_progress, crf=crf)
            logger.info(f"Subtitle burn complete → {os.path.basename(output_path)}")
            # Project-mode: record burned_at so the sidebar can show a
            # "已烧录" hint and future-you can find this output again.
            self._mark_instance_burned()
            self._write_publish_sidecar()
            self.set_done()
        except InterruptedError:
            self.set_error(tr("tool.subtitle.error.burn_generic",
                              e="cancelled"))
        except Exception as e:
            logger.exception("Subtitle burn failed")
            self.set_error(tr("tool.subtitle.error.burn_generic", e=e))
        finally:
            self.processing = False
            self.master.after(0, lambda: self.btn_merge.config(state=tk.NORMAL))
