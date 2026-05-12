"""
合并字幕分割和添加功能的工具
将 SplitSubtitles.py 的字符宽度剪裁功能合并到 AddSubTitleToMovieWithFFMpeg.py 中，
提供统一的界面来处理字幕分割和视频字幕烧录。
"""

from tools.base import ToolBase
from core import burn_presets
from i18n import tr
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser, simpledialog, ttk
import os
import sys
import subprocess
import threading
import time
import re
import json
import srt
from datetime import timedelta, datetime
from hub_logger import logger


# ── 纯工具函数（从 core 导入）───────────────────────────────────────────────

from core.subtitle_ops import (
    split_subtitle,
    process_srt_split,
    escape_ffmpeg_path,
    hex_color_to_ass,
    hex_color_to_drawtext,
)


def _infer_lang_tag(srt_path: str) -> str:
    """从 SRT 文件名末尾推断语言码（如 video_en.srt → 'en'），推断失败返回 'sub'。"""
    if not srt_path:
        return "sub"
    base = os.path.splitext(os.path.basename(srt_path))[0]
    parts = base.rsplit("_", 1)
    if len(parts) == 2 and 1 <= len(parts[1]) <= 5 and parts[1].replace("-", "").isalpha():
        return parts[1]
    return "sub"


def _compute_default_output_path(video_path: str, sub1_path: str = None, sub2_path: str = None) -> str:
    """Default output path: same dir as input video, name = Video_<lang>+<lang>.mp4.

    The base name is literal "Video" (per user preference) rather than the
    source video stem, so presets and downstream tooling can expect a
    predictable filename. Duplicate or failed language tags are collapsed.
    """
    out_dir = os.path.dirname(os.path.abspath(video_path)) if video_path else ""
    tags: list = []
    for p in (sub1_path, sub2_path):
        if not p:
            continue
        tag = _infer_lang_tag(p)
        if tag and tag not in tags:
            tags.append(tag)
    name = "Video_" + "+".join(tags) + ".mp4" if tags else "Video.mp4"
    return os.path.join(out_dir, name) if out_dir else name


def get_video_resolution(video_path):
    """获取视频分辨率"""
    try:
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
               '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video_path]
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=10)
        if result.returncode == 0:
            width, height = map(int, result.stdout.strip().split(','))
            return width, height
    except Exception as e:
        logger.error(f"ffprobe failed to read resolution ({os.path.basename(video_path)}): {e}")
    return None, None


# ── 主界面 class ─────────────────────────────────────────────────────────────

class SubtitleToolApp(ToolBase):
    """双语字幕烧录工具 — Toplevel 内嵌版。"""

    # Maps preset-file key → the Tk variable attribute name on self.
    # Keep in sync with presets.BUILTIN_DEFAULT_PARAMS. watermark_date is
    # intentionally excluded: it always resets to today on open.
    _PARAM_VARS = {
        "watermark_text":          "watermark_text_var",
        "watermark_txt_alpha":     "watermark_txt_alpha_var",
        "watermark_color":         "watermark_color_var",
        "watermark_fontsize":      "watermark_fontsize_var",
        "watermark_show":          "watermark_show_var",
        "watermark_show_date":     "watermark_show_date_var",
        "watermark_date_color":    "watermark_date_color_var",
        "watermark_date_fontsize": "watermark_date_fontsize_var",
        "watermark_date_alpha":    "watermark_date_alpha_var",
        "watermark_type":          "watermark_type_var",
        "watermark_img_path":      "watermark_img_path_var",
        "watermark_img_scale":     "watermark_img_scale_var",
        "watermark_img_alpha":     "watermark_img_alpha_var",
        "sub1_fontsize":   "sub1_fontsize_var",
        "sub1_color":      "sub1_color_var",
        "sub1_show":       "sub1_show_var",
        "sub2_fontsize":   "sub2_fontsize_var",
        "sub2_color":      "sub2_color_var",
        "sub2_show":       "sub2_show_var",
        "split_sub1":      "split_sub1_var",
        "sub1_max_chars":  "sub1_max_chars_var",
        "sub1_is_chinese": "sub1_is_chinese_var",
        "split_sub2":      "split_sub2_var",
        "sub2_max_chars":  "sub2_max_chars_var",
        "sub2_is_chinese": "sub2_is_chinese_var",
        "orientation":     "orientation_var",
        "encode_preset":   "encode_preset_var",
        "auto_output":     "auto_output_var",
    }

    def __init__(self, master, initial_file=None, project=None,
                 instance_name=None):
        """Standalone mode: master + optional initial_file (legacy behavior).

        Project mode: pass `project` (Project) + `instance_name` (str). The
        tool then locks source / output paths to project canonical positions,
        replaces the SRT file pickers with project-subtitle pickers, and
        persists per-instance config under
        <project>/derivatives/bilingual_video/<instance>/config.json.
        """
        self.master = master
        master.title(tr("tool.subtitle.title"))
        master.geometry("900x650")

        # Project-mode plumbing (None in standalone mode).
        self.project = project
        self.instance_name = instance_name
        self._project_mode = (project is not None and instance_name is not None)

        # 状态变量
        self.video_duration = 0.0
        self.processing = False

        # Tk 变量
        self.watermark_text_var          = tk.StringVar(value="字幕By老猿@OldApeTalk")
        self.watermark_txt_alpha_var     = tk.DoubleVar(value=60.0)   # 文字透明度
        self.watermark_color_var         = tk.StringVar(value="#00ffff")
        self.watermark_fontsize_var      = tk.IntVar(value=48)
        self.watermark_show_var          = tk.BooleanVar(value=True)
        self.watermark_show_date_var     = tk.BooleanVar(value=False)
        self.watermark_date_var          = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.watermark_date_color_var    = tk.StringVar(value="#505050")
        self.watermark_date_fontsize_var = tk.IntVar(value=36)
        self.watermark_date_alpha_var    = tk.DoubleVar(value=80.0)   # 日期透明度
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

        self.split_sub1_var     = tk.BooleanVar(value=True)
        self.sub1_max_chars_var = tk.IntVar(value=20)
        self.sub1_is_chinese_var = tk.BooleanVar(value=True)
        self.split_sub2_var     = tk.BooleanVar(value=True)
        self.sub2_max_chars_var = tk.IntVar(value=50)
        self.sub2_is_chinese_var = tk.BooleanVar(value=False)

        self.orientation_var    = tk.StringVar(value="horizontal")
        self.encode_preset_var  = tk.StringVar(value="veryfast")
        self.auto_output_var    = tk.BooleanVar(value=True)

        self._build_ui()
        self._update_split_settings()

        # Load preset store and apply last-used preset (after Tk vars exist,
        # after _update_split_settings so preset values are authoritative).
        self._preset_store = burn_presets.load_store()
        last_name = burn_presets.get_last_used(self._preset_store)
        last_params = burn_presets.get_preset(self._preset_store, last_name) \
            or burn_presets.get_preset(self._preset_store, burn_presets.BUILTIN_DEFAULT_NAME)
        if last_params:
            self._apply_params(last_params)
        self._refresh_preset_combo(select=last_name)
        # Persist once so the file exists on first run.
        burn_presets.save_store(self._preset_store)

        if initial_file and os.path.exists(initial_file):
            ext = os.path.splitext(initial_file)[1].lower()
            if ext == ".srt":
                self.entry_sub1.delete(0, tk.END)
                self.entry_sub1.insert(0, initial_file)
            elif ext in (".mp4", ".mkv", ".avi", ".mov"):
                self.entry_video.delete(0, tk.END)
                self.entry_video.insert(0, initial_file)
            self._maybe_update_output_path()

        # Apply project-mode constraints (source/output lock, SRT picker
        # redirect, config restore) AFTER all base UI + presets are set up so
        # we override whatever standalone-mode initialization put in place.
        if self._project_mode:
            self._enter_project_mode()

    def _build_ui(self):
        root = self.master

        # 预设栏
        frame_preset = tk.LabelFrame(root, text=tr("tool.subtitle.preset.frame_title"), padx=10, pady=5)
        frame_preset.grid(row=0, column=0, columnspan=3, padx=15, pady=(10, 2), sticky="we")
        tk.Label(frame_preset, text=tr("tool.subtitle.preset.current_label")).grid(row=0, column=0, padx=(0, 5))
        self.preset_combo = ttk.Combobox(frame_preset, width=24, state="readonly")
        self.preset_combo.grid(row=0, column=1, padx=2)
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        self.btn_preset_save = tk.Button(frame_preset, text=tr("tool.subtitle.preset.save"), width=6,
                                         command=self._on_preset_save)
        self.btn_preset_save.grid(row=0, column=2, padx=3)
        tk.Button(frame_preset, text=tr("tool.subtitle.preset.save_as"), width=8,
                  command=self._on_preset_save_as).grid(row=0, column=3, padx=3)
        self.btn_preset_delete = tk.Button(frame_preset, text=tr("tool.subtitle.preset.delete"), width=6,
                                           command=self._on_preset_delete)
        self.btn_preset_delete.grid(row=0, column=4, padx=3)
        tk.Button(frame_preset, text=tr("tool.subtitle.preset.reset_default"), width=10,
                  command=self._on_preset_reset_default).grid(row=0, column=5, padx=3)

        # 视频文件
        tk.Label(root, text=tr("tool.subtitle.video.label")).grid(row=1, column=0, padx=10, pady=(15, 2), sticky="e")
        self.entry_video = tk.Entry(root, width=55)
        self.entry_video.grid(row=1, column=1, padx=5, pady=(15, 2))
        tk.Button(root, text=tr("tool.subtitle.browse"), command=self._select_video).grid(row=1, column=2, padx=10, pady=(15, 2))

        # 输出文件
        tk.Label(root, text=tr("tool.subtitle.output.label")).grid(row=2, column=0, padx=10, pady=(2, 10), sticky="e")
        self.entry_output = tk.Entry(root, width=55)
        self.entry_output.grid(row=2, column=1, padx=5, pady=(2, 10))
        frame_out_actions = tk.Frame(root)
        frame_out_actions.grid(row=2, column=2, padx=10, pady=(2, 10), sticky="w")
        tk.Button(frame_out_actions, text=tr("tool.subtitle.browse"), command=self._select_output).pack(side=tk.LEFT)
        tk.Checkbutton(frame_out_actions, text=tr("tool.subtitle.output.auto"), variable=self.auto_output_var).pack(side=tk.LEFT, padx=(4, 0))

        # 屏幕方向设置
        frame_orientation = tk.LabelFrame(root, text=tr("tool.subtitle.orientation.frame_title"), padx=10, pady=5)
        frame_orientation.grid(row=3, column=0, columnspan=3, padx=15, pady=5, sticky="we")

        tk.Radiobutton(frame_orientation, text=tr("tool.subtitle.orientation.horizontal"), variable=self.orientation_var,
                       value="horizontal", command=self._update_split_settings).grid(row=0, column=0, padx=20)
        tk.Radiobutton(frame_orientation, text=tr("tool.subtitle.orientation.vertical"), variable=self.orientation_var,
                       value="vertical", command=self._update_split_settings).grid(row=0, column=1, padx=20)
        tk.Radiobutton(frame_orientation, text=tr("tool.subtitle.orientation.square"), variable=self.orientation_var,
                       value="square", command=self._update_split_settings).grid(row=0, column=2, padx=20)

        tk.Label(frame_orientation, text=tr("tool.subtitle.orientation.encode_label")).grid(row=0, column=3, padx=(40, 5), sticky="e")
        encode_preset_combo = ttk.Combobox(
            frame_orientation, textvariable=self.encode_preset_var,
            values=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"],
            width=12, state="readonly")
        encode_preset_combo.grid(row=0, column=4, padx=5)
        tk.Label(frame_orientation, text=tr("tool.subtitle.orientation.encode_hint"),
                 font=("Arial", 8), fg="gray").grid(row=0, column=5, padx=5)

        # 字幕1（中文）
        frame_sub1 = tk.LabelFrame(root, text=tr("tool.subtitle.sub1.frame_title"), padx=5, pady=5)
        frame_sub1.grid(row=4, column=0, columnspan=3, padx=10, pady=5, sticky="we")
        self.entry_sub1 = tk.Entry(frame_sub1, width=35)
        self.entry_sub1.grid(row=0, column=0, padx=5)
        tk.Button(frame_sub1, text=tr("tool.subtitle.browse"), command=self._select_subtitle1).grid(row=0, column=1, padx=5)
        tk.Label(frame_sub1, text=tr("tool.subtitle.sub.fontsize")).grid(row=0, column=2, padx=2)
        tk.Spinbox(frame_sub1, from_=10, to=60, width=4, textvariable=self.sub1_fontsize_var).grid(row=0, column=3, padx=2)
        tk.Label(frame_sub1, text=tr("tool.subtitle.sub.color")).grid(row=0, column=4, padx=2)
        tk.Entry(frame_sub1, width=8, textvariable=self.sub1_color_var).grid(row=0, column=5, padx=2)
        tk.Button(frame_sub1, text=tr("tool.subtitle.sub.choose"), command=self._choose_sub1_color).grid(row=0, column=6, padx=2)
        tk.Checkbutton(frame_sub1, text=tr("tool.subtitle.sub.show"), variable=self.sub1_show_var).grid(row=0, column=7, padx=5)

        tk.Checkbutton(frame_sub1, text=tr("tool.subtitle.sub.split"), variable=self.split_sub1_var).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        tk.Label(frame_sub1, text=tr("tool.subtitle.sub.max_chars")).grid(row=1, column=1, padx=2)
        tk.Spinbox(frame_sub1, from_=10, to=100, width=4, textvariable=self.sub1_max_chars_var).grid(row=1, column=2, padx=2)
        tk.Checkbutton(frame_sub1, text=tr("tool.subtitle.sub.is_chinese"), variable=self.sub1_is_chinese_var).grid(row=1, column=3, padx=5)

        # 字幕2（英文）
        frame_sub2 = tk.LabelFrame(root, text=tr("tool.subtitle.sub2.frame_title"), padx=5, pady=5)
        frame_sub2.grid(row=5, column=0, columnspan=3, padx=10, pady=5, sticky="we")
        self.entry_sub2 = tk.Entry(frame_sub2, width=35)
        self.entry_sub2.grid(row=0, column=0, padx=5)
        tk.Button(frame_sub2, text=tr("tool.subtitle.browse"), command=self._select_subtitle2).grid(row=0, column=1, padx=5)
        tk.Label(frame_sub2, text=tr("tool.subtitle.sub.fontsize")).grid(row=0, column=2, padx=2)
        tk.Spinbox(frame_sub2, from_=10, to=60, width=4, textvariable=self.sub2_fontsize_var).grid(row=0, column=3, padx=2)
        tk.Label(frame_sub2, text=tr("tool.subtitle.sub.color")).grid(row=0, column=4, padx=2)
        tk.Entry(frame_sub2, width=8, textvariable=self.sub2_color_var).grid(row=0, column=5, padx=2)
        tk.Button(frame_sub2, text=tr("tool.subtitle.sub.choose"), command=self._choose_sub2_color).grid(row=0, column=6, padx=2)
        tk.Checkbutton(frame_sub2, text=tr("tool.subtitle.sub.show"), variable=self.sub2_show_var).grid(row=0, column=7, padx=5)

        tk.Checkbutton(frame_sub2, text=tr("tool.subtitle.sub.split"), variable=self.split_sub2_var).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        tk.Label(frame_sub2, text=tr("tool.subtitle.sub.max_chars")).grid(row=1, column=1, padx=2)
        tk.Spinbox(frame_sub2, from_=10, to=100, width=4, textvariable=self.sub2_max_chars_var).grid(row=1, column=2, padx=2)
        tk.Checkbutton(frame_sub2, text=tr("tool.subtitle.sub.is_chinese"), variable=self.sub2_is_chinese_var).grid(row=1, column=3, padx=5)

        # 水印设置
        frame_watermark = tk.LabelFrame(root, text=tr("tool.subtitle.watermark.frame_title"), padx=10, pady=5)
        frame_watermark.grid(row=6, column=0, columnspan=3, padx=15, pady=5, sticky="we")

        # Row 0：图片水印（单选）
        tk.Radiobutton(frame_watermark, text=tr("tool.subtitle.watermark.image_radio"),
                       variable=self.watermark_type_var, value="image").grid(row=0, column=0, sticky="e")
        wm_img_files = self._scan_watermark_images()
        wm_img_names = [os.path.basename(f) for f in wm_img_files]
        self._wm_img_combo = ttk.Combobox(frame_watermark, values=wm_img_names, width=16, state="readonly")
        cur_name = os.path.basename(self.watermark_img_path_var.get())
        if cur_name in wm_img_names:
            self._wm_img_combo.set(cur_name)
        elif wm_img_names:
            self._wm_img_combo.set(wm_img_names[0])
        self._wm_img_combo.bind("<<ComboboxSelected>>", self._on_wm_img_selected)
        self._wm_img_combo.grid(row=0, column=1, padx=4)
        tk.Button(frame_watermark, text=tr("tool.subtitle.browse"), command=self._select_watermark_image).grid(row=0, column=2, padx=3)
        tk.Label(frame_watermark, text=tr("tool.subtitle.watermark.scale")).grid(row=0, column=3, sticky="e")
        tk.Spinbox(frame_watermark, from_=0.05, to=0.5, increment=0.05, width=5, format="%.2f",
                   textvariable=self.watermark_img_scale_var).grid(row=0, column=4, padx=2)
        tk.Label(frame_watermark, text=tr("tool.subtitle.watermark.alpha")).grid(row=0, column=5, sticky="e")
        tk.Scale(frame_watermark, from_=0, to=100, orient=tk.HORIZONTAL,
                 variable=self.watermark_img_alpha_var, length=80).grid(row=0, column=6, padx=3)
        tk.Checkbutton(frame_watermark, text=tr("tool.subtitle.sub.show"),
                       variable=self.watermark_show_var).grid(row=0, column=7, padx=5)

        # Row 1：文字水印（单选）
        tk.Radiobutton(frame_watermark, text=tr("tool.subtitle.watermark.text_radio"),
                       variable=self.watermark_type_var, value="text").grid(row=1, column=0, sticky="e")
        ttk.Combobox(frame_watermark, textvariable=self.watermark_text_var, width=20,
                     values=["字幕By老猿@OldApeTalk", "字幕制作By 老猿",
                             "@VideoCraftNews"]).grid(row=1, column=1, padx=4)
        tk.Label(frame_watermark, text=tr("tool.subtitle.sub.fontsize")).grid(row=1, column=2, sticky="e")
        tk.Spinbox(frame_watermark, from_=10, to=100, width=4,
                   textvariable=self.watermark_fontsize_var).grid(row=1, column=3, padx=2)
        tk.Label(frame_watermark, text=tr("tool.subtitle.sub.color")).grid(row=1, column=4, sticky="e")
        tk.Entry(frame_watermark, textvariable=self.watermark_color_var, width=9).grid(row=1, column=5, padx=2)
        tk.Button(frame_watermark, text=tr("tool.subtitle.sub.choose"),
                  command=self._choose_watermark_color).grid(row=1, column=6, padx=2)
        tk.Label(frame_watermark, text=tr("tool.subtitle.watermark.alpha")).grid(row=1, column=7, sticky="e")
        tk.Scale(frame_watermark, from_=0, to=100, orient=tk.HORIZONTAL,
                 variable=self.watermark_txt_alpha_var, length=80).grid(row=1, column=8, padx=3)

        # Row 2：日期（独立字号 + 颜色 + 透明度）
        tk.Checkbutton(frame_watermark, text=tr("tool.subtitle.watermark.show_date"),
                       variable=self.watermark_show_date_var).grid(row=2, column=0, sticky="e", padx=5)
        tk.Entry(frame_watermark, textvariable=self.watermark_date_var,
                 width=12).grid(row=2, column=1, sticky="w", padx=4)
        tk.Label(frame_watermark, text=tr("tool.subtitle.sub.fontsize")).grid(row=2, column=2, sticky="e")
        tk.Spinbox(frame_watermark, from_=10, to=100, width=4,
                   textvariable=self.watermark_date_fontsize_var).grid(row=2, column=3, padx=2)
        tk.Label(frame_watermark, text=tr("tool.subtitle.sub.color")).grid(row=2, column=4, sticky="e")
        tk.Entry(frame_watermark, textvariable=self.watermark_date_color_var, width=9).grid(row=2, column=5, padx=2)
        tk.Button(frame_watermark, text=tr("tool.subtitle.sub.choose"),
                  command=self._choose_date_color).grid(row=2, column=6, padx=2)
        tk.Label(frame_watermark, text=tr("tool.subtitle.watermark.alpha")).grid(row=2, column=7, sticky="e")
        tk.Scale(frame_watermark, from_=0, to=100, orient=tk.HORIZONTAL,
                 variable=self.watermark_date_alpha_var, length=80).grid(row=2, column=8, padx=3)

        # Progress row: three compact time labels + progress bar + merge button,
        # all on a single row to save vertical space.
        frame_progress = tk.Frame(root)
        frame_progress.grid(row=7, column=0, columnspan=3, padx=15, pady=10, sticky="we")
        frame_progress.columnconfigure(3, weight=1)   # progress_bar column stretches

        self.label_duration  = tk.Label(frame_progress, text=tr("tool.subtitle.progress.duration_unknown"), width=14, anchor="w")
        self.label_duration.grid(row=0, column=0, padx=(0, 4))
        self.label_elapsed   = tk.Label(frame_progress, text=tr("tool.subtitle.progress.elapsed_zero"), width=14, anchor="w")
        self.label_elapsed.grid(row=0, column=1, padx=(0, 4))
        self.label_remaining = tk.Label(frame_progress, text=tr("tool.subtitle.progress.remaining_unknown"), width=14, anchor="w")
        self.label_remaining.grid(row=0, column=2, padx=(0, 8))

        self.progress_bar = ttk.Progressbar(frame_progress, orient=tk.HORIZONTAL,
                                            mode='determinate')
        self.progress_bar.grid(row=0, column=3, sticky="we", padx=(0, 8))

        self.btn_merge = tk.Button(frame_progress, text=tr("tool.subtitle.action.start"),
                                   width=18, command=self._merge_videos)
        self.btn_merge.grid(row=0, column=4)

    # ── 图片水印辅助 ────────────────────────────────────────────────────────

    @staticmethod
    def _project_root():
        """返回项目根目录（Logo/ 所在目录）。"""
        # __file__ = .../src/tools/subtitle/subtitle_tool.py → 上移4级
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
        if self._project_mode:
            # Source video is locked to the project. "Browse" just opens the
            # source folder so the user can verify the file.
            try:
                os.startfile(os.path.dirname(self.project.source_video_path))
            except OSError:
                pass
            return
        file_path = filedialog.askopenfilename(
            title=tr("tool.subtitle.dialog.select_video"),
            filetypes=[(tr("tool.subtitle.filter.video"), "*.mp4 *.avi *.mov *.mkv"),
                       (tr("tool.subtitle.filter.all_files"), "*.*")]
        )
        if not file_path:
            return
        self.entry_video.delete(0, tk.END)
        self.entry_video.insert(0, file_path)
        self._maybe_update_output_path()
        # 获取视频时长
        try:
            subprocess.run(['ffprobe', '-version'], capture_output=True, check=True, timeout=5)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            messagebox.showerror(tr("dialog.common.error"), tr("tool.subtitle.warning.no_ffprobe"))
            self.video_duration = 0.0
            self.label_duration.config(text=tr("tool.subtitle.progress.duration_no_ffmpeg"))
            return

        try:
            cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                   '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
            result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=10)
            if result.returncode != 0:
                cmd2 = ['ffprobe', '-i', file_path, '-v', 'quiet',
                        '-print_format', 'json', '-show_format']
                result2 = subprocess.run(cmd2, capture_output=True, encoding="utf-8", errors="replace", timeout=10)
                if result2.returncode == 0:
                    duration_str = json.loads(result2.stdout)['format']['duration']
                else:
                    raise Exception(f"ffprobe failed: {result.stderr.strip()}")
            else:
                duration_str = result.stdout.strip()
            self.video_duration = float(duration_str)
            hms = time.strftime('%H:%M:%S', time.gmtime(self.video_duration))
            self.label_duration.config(text=tr("tool.subtitle.progress.duration_fmt", hms=hms))
        except subprocess.TimeoutExpired:
            self.video_duration = 0.0
            self.label_duration.config(text=tr("tool.subtitle.progress.duration_timeout"))
            messagebox.showwarning(tr("dialog.common.warning"), tr("tool.subtitle.warning.duration_timeout"))
        except Exception as e:
            self.video_duration = 0.0
            self.label_duration.config(text=tr("tool.subtitle.progress.duration_unknown"))
            messagebox.showwarning(tr("dialog.common.warning"),
                                   tr("tool.subtitle.warning.duration_failed", e=e))

    def _select_subtitle1(self):
        if self._project_mode:
            picked = self._pick_project_subtitle("选择主字幕")
            if picked:
                self.entry_sub1.delete(0, tk.END)
                self.entry_sub1.insert(0, picked)
                self._save_instance_config()
            return
        path = filedialog.askopenfilename(
            title=tr("tool.subtitle.dialog.select_sub1"),
            filetypes=[(tr("tool.subtitle.filter.srt"), "*.srt"),
                       (tr("tool.subtitle.filter.all_files"), "*.*")]
        )
        if path:
            self.entry_sub1.delete(0, tk.END)
            self.entry_sub1.insert(0, path)
            self._maybe_update_output_path()

    def _select_subtitle2(self):
        if self._project_mode:
            picked = self._pick_project_subtitle("选择副字幕(双语)")
            if picked:
                self.entry_sub2.delete(0, tk.END)
                self.entry_sub2.insert(0, picked)
                self._save_instance_config()
            return
        path = filedialog.askopenfilename(
            title=tr("tool.subtitle.dialog.select_sub2"),
            filetypes=[(tr("tool.subtitle.filter.srt"), "*.srt"),
                       (tr("tool.subtitle.filter.all_files"), "*.*")]
        )
        if path:
            self.entry_sub2.delete(0, tk.END)
            self.entry_sub2.insert(0, path)
            self._maybe_update_output_path()

    def _select_output(self):
        if self._project_mode:
            # Output is locked under derivatives/. "Browse" opens the folder.
            try:
                os.makedirs(os.path.dirname(self.entry_output.get()), exist_ok=True)
                os.startfile(os.path.dirname(self.entry_output.get()))
            except OSError:
                pass
            return
        video = self.entry_video.get()
        current = self.entry_output.get().strip()
        if current:
            init_dir = os.path.dirname(current) or os.path.dirname(video) or os.getcwd()
            init_name = os.path.basename(current)
        else:
            default = _compute_default_output_path(
                video, self.entry_sub1.get() or None, self.entry_sub2.get() or None
            )
            init_dir = os.path.dirname(default) or os.getcwd()
            init_name = os.path.basename(default)
        path = filedialog.asksaveasfilename(
            title=tr("tool.subtitle.dialog.select_output"),
            defaultextension=".mp4",
            filetypes=[(tr("tool.subtitle.filter.mp4"), "*.mp4"),
                       (tr("tool.subtitle.filter.all_files"), "*.*")],
            initialdir=init_dir,
            initialfile=init_name,
        )
        if path:
            self.entry_output.delete(0, tk.END)
            self.entry_output.insert(0, path)
            # Manual choice implies the user wants to fix the name.
            self.auto_output_var.set(False)

    def _maybe_update_output_path(self):
        """Regenerate entry_output from current video/subtitle paths when auto is on."""
        if self._project_mode:
            # Project mode: output is locked to derivatives/<type>/<inst>/output.mp4.
            return
        if not self.auto_output_var.get():
            return
        video = self.entry_video.get()
        if not video:
            return
        path = _compute_default_output_path(
            video,
            self.entry_sub1.get() or None if hasattr(self, "entry_sub1") else None,
            self.entry_sub2.get() or None if hasattr(self, "entry_sub2") else None,
        )
        self.entry_output.delete(0, tk.END)
        self.entry_output.insert(0, path)

    # ── Project mode ────────────────────────────────────────────────────────

    def _enter_project_mode(self) -> None:
        """Lock paths to project canonical locations + restore prior config.

        Called from __init__ after the standalone UI is fully built.
        Modifies titles, entry contents, and entry states; redirects picker
        button callbacks via the `if self._project_mode:` branches above.
        """
        # Window title shows the derivative type + instance for clarity.
        from core import derivative_types
        type_disp = derivative_types.display_name("bilingual_video")
        self.master.title(f"{type_disp} — {self.instance_name}")

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
        self.auto_output_var.set(False)
        self.entry_output.config(state="normal")
        self.entry_output.delete(0, tk.END)
        self.entry_output.insert(0, output_path)
        self.entry_output.config(state="readonly")

        # Restore SRT selections + style params from instance config.json.
        self._load_instance_config()

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
                "项目还没有字幕。请先在 Sidebar 的 Subtitles 区域生成。",
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
        ttk.Label(body, text="可用字幕:").pack(anchor="w")
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
        ttk.Button(btns, text="取消", command=on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="确定", command=on_ok
                   ).pack(side="right")
        ttk.Button(btns, text="清除选择", command=on_clear
                   ).pack(side="left")

        # Center
        win.update_idletasks()
        pw = self.master.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - win.winfo_width()) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")

        win.wait_window()
        return chosen[0]

    def _instance_config_path(self) -> str:
        inst_dir = self.project.derivative_dir(
            "bilingual_video", self.instance_name)
        return os.path.join(inst_dir, "config.json")

    def _load_instance_config(self) -> None:
        """Restore SRT selections + style params from the instance's config.json."""
        path = self._instance_config_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            return

        # SRT selections (stored as filenames relative to subtitles/)
        primary = cfg.get("primary_srt")
        if primary:
            p = os.path.join(self.project.subtitles_dir, primary)
            if os.path.isfile(p):
                self.entry_sub1.delete(0, tk.END)
                self.entry_sub1.insert(0, p)
        secondary = cfg.get("secondary_srt")
        if secondary:
            p = os.path.join(self.project.subtitles_dir, secondary)
            if os.path.isfile(p):
                self.entry_sub2.delete(0, tk.END)
                self.entry_sub2.insert(0, p)

        # Style params (uses _PARAM_VARS map)
        params = cfg.get("params")
        if isinstance(params, dict):
            self._apply_params(params)

    def _save_instance_config(self) -> None:
        """Snapshot SRT selections + style params to the instance's config.json."""
        if not self._project_mode:
            return
        sub1 = self.entry_sub1.get().strip()
        sub2 = self.entry_sub2.get().strip()
        cfg = {
            "schema_version": 1,
            "primary_srt": os.path.basename(sub1) if sub1 else None,
            "secondary_srt": os.path.basename(sub2) if sub2 else None,
            "params": self._collect_params(),
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
        if not self._project_mode:
            return
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

    # ── 颜色选择 ────────────────────────────────────────────────────────────

    def _choose_watermark_color(self):
        color = colorchooser.askcolor(title=tr("tool.subtitle.dialog.choose_watermark_color"))
        if color and color[1]:
            self.watermark_color_var.set(color[1])

    def _choose_date_color(self):
        color = colorchooser.askcolor(title=tr("tool.subtitle.dialog.choose_date_color"))
        if color and color[1]:
            self.watermark_date_color_var.set(color[1])

    def _choose_sub1_color(self):
        color = colorchooser.askcolor(title=tr("tool.subtitle.dialog.choose_sub1_color"))
        if color and color[1]:
            self.sub1_color_var.set(color[1])

    def _choose_sub2_color(self):
        color = colorchooser.askcolor(title=tr("tool.subtitle.dialog.choose_sub2_color"))
        if color and color[1]:
            self.sub2_color_var.set(color[1])

    # ── Preset 管理 ─────────────────────────────────────────────────────────

    def _collect_params(self) -> dict:
        """Snapshot current Tk variables into a plain-dict preset payload."""
        params = {}
        for key, attr in self._PARAM_VARS.items():
            var = getattr(self, attr, None)
            if var is not None:
                params[key] = var.get()
        return params

    def _apply_params(self, params: dict) -> None:
        """Push a preset payload into the Tk variables. Unknown/missing keys skipped."""
        for key, attr in self._PARAM_VARS.items():
            if key not in params:
                continue
            var = getattr(self, attr, None)
            if var is None:
                continue
            try:
                var.set(params[key])
            except tk.TclError:
                pass
        # watermark_img_path may be empty (builtin default) or stale path →
        # fall back to first available image under Logo/.
        cur_img = self.watermark_img_path_var.get()
        if not cur_img or not os.path.exists(cur_img):
            self.watermark_img_path_var.set(self._default_watermark_path())
        if hasattr(self, "_wm_img_combo"):
            self._refresh_wm_img_combo()

    def _refresh_preset_combo(self, select: str = None) -> None:
        names = burn_presets.list_preset_names(self._preset_store)
        self.preset_combo["values"] = names
        if select and select in names:
            self.preset_combo.set(select)
        elif names:
            self.preset_combo.set(names[0])
        self._update_preset_button_state()

    def _update_preset_button_state(self) -> None:
        is_default = self.preset_combo.get() == burn_presets.BUILTIN_DEFAULT_NAME
        state = "disabled" if is_default else "normal"
        self.btn_preset_save.config(state=state)
        self.btn_preset_delete.config(state=state)

    def _on_preset_selected(self, event=None) -> None:
        name = self.preset_combo.get()
        params = burn_presets.get_preset(self._preset_store, name)
        if params is None:
            return
        self._apply_params(params)
        burn_presets.set_last_used(self._preset_store, name)
        burn_presets.save_store(self._preset_store)
        self._update_preset_button_state()

    def _on_preset_save(self) -> None:
        name = self.preset_combo.get()
        if name == burn_presets.BUILTIN_DEFAULT_NAME:
            messagebox.showinfo(tr("dialog.common.info"),
                                tr("tool.subtitle.preset.default_protected"))
            return
        burn_presets.upsert_preset(self._preset_store, name, self._collect_params())
        burn_presets.save_store(self._preset_store)
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
        burn_presets.upsert_preset(self._preset_store, name, self._collect_params())
        burn_presets.set_last_used(self._preset_store, name)
        burn_presets.save_store(self._preset_store)
        self._refresh_preset_combo(select=name)

    def _on_preset_delete(self) -> None:
        name = self.preset_combo.get()
        if name == burn_presets.BUILTIN_DEFAULT_NAME:
            return
        if not messagebox.askyesno(
            tr("tool.subtitle.preset.delete_title"),
            tr("tool.subtitle.preset.delete_confirm", name=name),
        ):
            return
        burn_presets.delete_preset(self._preset_store, name)
        burn_presets.save_store(self._preset_store)
        self._refresh_preset_combo(select=burn_presets.BUILTIN_DEFAULT_NAME)
        # Re-apply Default after deletion so the UI reflects the fallback.
        default_params = burn_presets.get_preset(self._preset_store, burn_presets.BUILTIN_DEFAULT_NAME)
        if default_params:
            self._apply_params(default_params)

    def _on_preset_reset_default(self) -> None:
        """Reload the Default preset values into the UI without changing last_used."""
        params = burn_presets.get_preset(self._preset_store, burn_presets.BUILTIN_DEFAULT_NAME)
        if params:
            self._apply_params(params)

    # ── 辅助 ────────────────────────────────────────────────────────────────

    def _update_split_settings(self):
        ori = self.orientation_var.get()
        if ori == "horizontal":
            self.sub1_max_chars_var.set(20)
            self.sub2_max_chars_var.set(50)
            self.sub1_fontsize_var.set(24)
            self.sub2_fontsize_var.set(24)
        elif ori == "square":
            self.sub1_max_chars_var.set(10)
            self.sub2_max_chars_var.set(25)
            self.sub1_fontsize_var.set(20)
            self.sub2_fontsize_var.set(16)
        else:  # vertical
            self.sub1_max_chars_var.set(10)
            self.sub2_max_chars_var.set(25)
            self.sub1_fontsize_var.set(14)
            self.sub2_fontsize_var.set(12)

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
        # Naming: project mode → derivative_dir/subtitles_<iso>.srt
        #         standalone   → next to source SRT with _split suffix
        def _adapted_path(src_srt: str) -> str:
            base = os.path.basename(src_srt)
            stem, _ = os.path.splitext(base)
            if self._project_mode:
                inst_dir = self.project.derivative_dir(
                    "bilingual_video", self.instance_name)
                os.makedirs(inst_dir, exist_ok=True)
                # Project SRTs are named by ISO (en.srt → subtitles_en.srt).
                return os.path.join(inst_dir, f"subtitles_{stem}.srt")
            # Standalone fallback (legacy): _split suffix next to source.
            return src_srt.replace('.srt', '_split.srt')

        def _write_adapted(src_srt: str, max_chars: int, is_chinese: bool,
                            do_split: bool) -> str:
            """Write the adapted SRT (split if requested, otherwise copy)
            to the derivative folder and return its path."""
            dst = _adapted_path(src_srt)
            if do_split:
                subs = process_srt_split(src_srt, max_chars, is_chinese)
                with open(dst, 'w', encoding='utf-8') as f:
                    f.write(srt.compose(subs))
            else:
                # Plain copy — user opted out of wrap, but still wants the
                # file alongside the burn output for separate upload.
                if os.path.abspath(dst) != os.path.abspath(src_srt):
                    import shutil
                    shutil.copy2(src_srt, dst)
            return dst

        temp_sub1_path = sub1_path
        temp_sub2_path = sub2_path
        try:
            if show_sub1:
                temp_sub1_path = _write_adapted(
                    sub1_path,
                    self.sub1_max_chars_var.get(),
                    self.sub1_is_chinese_var.get(),
                    self.split_sub1_var.get(),
                )
            if show_sub2:
                temp_sub2_path = _write_adapted(
                    sub2_path,
                    self.sub2_max_chars_var.get(),
                    self.sub2_is_chinese_var.get(),
                    self.split_sub2_var.get(),
                )
        except Exception as e:
            messagebox.showerror(tr("tool.subtitle.error.split_failed_title"), str(e))
            return

        # 路径处理
        video_path_abs = os.path.abspath(video_path)
        sub1_path_ff   = escape_ffmpeg_path(temp_sub1_path) if show_sub1 else None
        sub2_path_ff   = escape_ffmpeg_path(temp_sub2_path) if show_sub2 else None

        # 字幕样式
        font1 = "Microsoft YaHei"
        fontsize1 = self.sub1_fontsize_var.get()
        color1    = hex_color_to_ass(self.sub1_color_var.get())
        style1 = (f"Fontname={font1},Fontsize={fontsize1},PrimaryColour={color1},"
                  f"OutlineColour=&H00000000&,BorderStyle=1,Outline=2,Shadow=0,"
                  f"Bold=1,Alignment=2,MarginV=100")

        font2 = "Microsoft YaHei"
        fontsize2 = self.sub2_fontsize_var.get()
        color2    = hex_color_to_ass(self.sub2_color_var.get())
        style2 = (f"Fontname={font2},Fontsize={fontsize2},PrimaryColour={color2},"
                  f"OutlineColour=&H00000000&,BorderStyle=1,Outline=2,Shadow=0,"
                  f"Bold=0,Alignment=2,MarginV=50")

        output_path = self.entry_output.get().strip()
        if not output_path:
            output_path = _compute_default_output_path(
                video_path_abs,
                sub1_path if show_sub1 else None,
                sub2_path if show_sub2 else None,
            )
        # Normalize to absolute and verify parent directory exists.
        output_path = os.path.abspath(output_path)
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.isdir(out_dir):
            messagebox.showerror(tr("dialog.common.error"),
                                 tr("tool.subtitle.error.output_dir_missing", dir=out_dir))
            return

        width, height = get_video_resolution(video_path_abs)

        # 水印
        show_watermark           = self.watermark_show_var.get()
        wm_type                  = self.watermark_type_var.get()
        use_img_wm               = show_watermark and wm_type == "image"
        use_txt_wm               = show_watermark and wm_type == "text"
        show_date                = self.watermark_show_date_var.get()
        watermark_text           = self.watermark_text_var.get()
        watermark_color          = self.watermark_color_var.get()
        watermark_fontsize_base  = self.watermark_fontsize_var.get()
        watermark_ff_color       = hex_color_to_drawtext(watermark_color)
        txt_alpha                = round(self.watermark_txt_alpha_var.get() / 100, 2)
        img_alpha                = round(self.watermark_img_alpha_var.get() / 100, 2)
        watermark_fontsize       = int((height / 1080) * watermark_fontsize_base) if height else watermark_fontsize_base
        img_path                 = self.watermark_img_path_var.get()
        img_scale                = self.watermark_img_scale_var.get()
        img_exists               = use_img_wm and os.path.exists(img_path)

        date_ff_color            = hex_color_to_drawtext(self.watermark_date_color_var.get())
        date_fontsize_base       = self.watermark_date_fontsize_var.get()
        date_fontsize            = int((height / 1080) * date_fontsize_base) if height else date_fontsize_base
        date_alpha               = round(self.watermark_date_alpha_var.get() / 100, 2)

        # 文字水印 drawtext 片段
        def _txt_drawtext(y_expr="30"):
            return (f"drawtext=text='{watermark_text}':"
                    f"fontcolor={watermark_ff_color}@{txt_alpha}:"
                    f"fontsize={watermark_fontsize}:font='Microsoft YaHei':"
                    f"x=w-tw-30:y={y_expr}:borderw=2:bordercolor=black")

        # 日期 drawtext 片段（独立颜色/字号/透明度）
        def _date_drawtext(y_val):
            return (f"drawtext=text='{self.watermark_date_var.get()}':"
                    f"fontcolor={date_ff_color}@{date_alpha}:"
                    f"fontsize={date_fontsize}:font='Microsoft YaHei':"
                    f"x=w-tw-30:y={y_val}:borderw=2:bordercolor=black")

        use_filter_complex = img_exists

        # 精确计算日期 y 坐标（在主水印下方）
        if use_filter_complex:
            # 图片模式：用 PIL 读取图片实际尺寸计算缩放后高度
            try:
                from PIL import Image as _PILImg
                with _PILImg.open(img_path) as _im:
                    _orig_w, _orig_h = _im.size
                img_w_px = int((width or 1920) * img_scale)
                img_h_px = int(img_w_px * _orig_h / _orig_w)
            except Exception:
                img_w_px = int((width or 1920) * img_scale)
                img_h_px = img_w_px  # 无法读取时假设正方形
            date_y = 30 + img_h_px + 8
        else:
            # 文字模式：基于水印文字字号
            img_w_px = int((width or 1920) * img_scale)
            date_y = 30 + watermark_fontsize + 8

        if use_filter_complex:
            # ── filter_complex 路径（有图片水印）────────────────────────────
            img_path_ff = img_path.replace("\\", "/").replace(":", "\\:")
            fc_parts = []
            cur = "[0:v]"

            # 字幕滤镜
            if show_sub2 and sub2_path_ff:
                fc_parts.append(f"{cur}subtitles=filename='{sub2_path_ff}':force_style='{style2}'[s2]")
                cur = "[s2]"
            if show_sub1 and sub1_path_ff:
                fc_parts.append(f"{cur}subtitles=filename='{sub1_path_ff}':force_style='{style1}'[s1]")
                cur = "[s1]"

            # 图片水印源（含独立透明度）
            fc_parts.append(
                f"movie='{img_path_ff}',scale={img_w_px}:-1,"
                f"format=rgba,colorchannelmixer=aa={img_alpha}[wm]"
            )

            # overlay 链：图片叠加，日期独立追加
            overlay_chain = f"{cur}[wm]overlay=W-w-30:30"
            if show_date:
                overlay_chain += "," + _date_drawtext(date_y)
            overlay_chain += "[out]"
            fc_parts.append(overlay_chain)

            filter_complex = ";".join(fc_parts)
            vf = None
        else:
            # ── -vf 路径（文字水印或无水印）─────────────────────────────────
            filter_complex = None
            vf_filters = []
            if show_sub2 and sub2_path_ff:
                vf_filters.append(f"subtitles=filename='{sub2_path_ff}':force_style='{style2}'")
            if show_sub1 and sub1_path_ff:
                vf_filters.append(f"subtitles=filename='{sub1_path_ff}':force_style='{style1}'")
            if use_txt_wm and watermark_text.strip():
                vf_filters.append(_txt_drawtext("30"))
            if show_date:
                vf_filters.append(_date_drawtext(date_y))
            vf = ",".join(vf_filters)

        # 缓冲区
        if width and height:
            pixels = width * height
            if pixels >= 3840 * 2160:   bufsize = maxrate = '150M'
            elif pixels >= 2560 * 1440: bufsize = maxrate = '80M'
            elif pixels >= 1920 * 1080: bufsize = maxrate = '50M'
            else:                        bufsize = maxrate = '30M'
        else:
            bufsize = maxrate = '100M'

        crf_map = {'ultrafast': '28', 'superfast': '26', 'veryfast': '25',
                   'faster': '24', 'fast': '23', 'medium': '23'}
        preset = self.encode_preset_var.get()
        crf    = crf_map.get(preset, '25')

        cmd = ['ffmpeg', '-y', '-i', video_path_abs]
        if use_filter_complex and filter_complex:
            cmd += ['-filter_complex', filter_complex, '-map', '[out]', '-map', '0:a?']
        elif vf:
            cmd += ['-vf', vf]
        cmd += [
            '-c:v', 'libx264', '-preset', preset, '-crf', crf,
            '-threads', '0', '-bufsize', bufsize, '-maxrate', maxrate,
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart', output_path
        ]

        self.processing = True
        self.btn_merge.config(state=tk.DISABLED)
        self.progress_bar['value'] = 0
        self.label_elapsed.config(text=tr("tool.subtitle.progress.elapsed_zero"))
        self.label_remaining.config(text=tr("tool.subtitle.progress.remaining_unknown"))
        self.set_busy()

        threading.Thread(
            target=self._run_ffmpeg,
            args=(cmd, output_path, temp_sub1_path, temp_sub2_path, sub1_path, sub2_path),
            daemon=True
        ).start()

    def _run_ffmpeg(self, cmd, output_path, temp_sub1, temp_sub2, orig_sub1, orig_sub2):
        start_time = time.time()
        try:
            process = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
            duration_pattern = re.compile(r'Duration: (\d+):(\d+):(\d+\.\d+)')
            time_pattern     = re.compile(r'time=(\d+):(\d+):(\d+\.\d+)')
            total_duration   = self.video_duration if self.video_duration > 0 else None

            while True:
                line = process.stderr.readline()
                if not line:
                    break
                line = line.strip()
                if total_duration is None:
                    m = duration_pattern.search(line)
                    if m:
                        h, mi, s = map(float, m.groups())
                        total_duration = h * 3600 + mi * 60 + s
                m = time_pattern.search(line)
                if m:
                    h, mi, s = map(float, m.groups())
                    current_time = h * 3600 + mi * 60 + s
                    if total_duration and total_duration > 0:
                        progress  = (current_time / total_duration) * 100
                        elapsed   = time.time() - start_time
                        remaining = (elapsed / current_time) * (total_duration - current_time) if current_time > 0 else 0
                        self.master.after(0, self._update_progress, progress, elapsed, remaining)

            process.wait()
            if process.returncode == 0:
                # Clean up temp split SRTs
                for tmp, orig in [(temp_sub1, orig_sub1), (temp_sub2, orig_sub2)]:
                    if tmp != orig and os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except Exception as cleanup_e:
                            logger.error(f"Failed to clean up temp subtitle {tmp}: {cleanup_e}")
                logger.info(f"Subtitle burn complete → {os.path.basename(output_path)}")
                # Project-mode: record burned_at so the sidebar can show a
                # "已烧录" hint and future-you can find this output again.
                self._mark_instance_burned()
                self.set_done()
            else:
                self.set_error(tr("tool.subtitle.error.burn_ffmpeg", code=process.returncode))
        except Exception as e:
            self.set_error(tr("tool.subtitle.error.burn_generic", e=e))
        finally:
            self.processing = False
            self.master.after(0, lambda: self.btn_merge.config(state=tk.NORMAL))


if __name__ == "__main__":
    root = tk.Tk()
    initial = None
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        initial = sys.argv[1]
    app = SubtitleToolApp(root, initial_file=initial)
    root.mainloop()
