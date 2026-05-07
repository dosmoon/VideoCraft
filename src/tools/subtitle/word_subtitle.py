"""
WordSubtitleTool.py — 逐字字幕烧录工具

读取 ASR 输出的 verbose_json（含 words[] 逐字时间戳），生成 ASS 卡拉OK字幕
并通过 ffmpeg 烧录到视频中。

ASS 卡拉OK原理：
  \kf{cs}  — 填充动画，在 cs 百分之一秒内从 SecondaryColour 渐变到 PrimaryColour
  \k{cs}   — 即时切换，在第 cs 帧时瞬间切换颜色
  ASS Style 中：PrimaryColour = 高亮色（已播），SecondaryColour = 默认色（未播）
"""

from tools.base import ToolBase
from i18n import tr
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.subtitle_ops import escape_ffmpeg_path, hex_color_to_ass

try:
    from hub_logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class _Line:
    start: float
    end:   float
    words: List[dict]   # [{"word": str, "start": float, "end": float}, ...]


# ── ASS 模板 ──────────────────────────────────────────────────────────────────

_ASS_HEADER = """\
[Script Info]
Title: WordSubtitle
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,{fontsize},{highlight_ass},{unspoken_ass},{outline_ass},&H00000000&,{bold},0,0,0,100,100,0,0,1,2,0,2,10,10,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _seconds_to_ass_time(t: float) -> str:
    """秒 → ASS 时间格式 H:MM:SS.cc"""
    t = max(0.0, t)
    h  = int(t // 3600)
    m  = int((t % 3600) // 60)
    s  = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _get_video_resolution(video_path: str) -> tuple[int, int]:
    """用 ffprobe 探测视频分辨率，返回 (width, height)，失败返回 (1920, 1080)。"""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=s=x:p=0",
             video_path],
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
        ).strip()
        w, h = out.split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080


def _is_cjk(char: str) -> bool:
    cp = ord(char)
    return (0x4E00 <= cp <= 0x9FFF or
            0x3400 <= cp <= 0x4DBF or
            0x3000 <= cp <= 0x303F or
            0xFF00 <= cp <= 0xFFEF)


# ── 主类 ──────────────────────────────────────────────────────────────────────

class WordSubtitleApp(ToolBase):
    """逐字字幕烧录工具（Toplevel 内嵌版）。"""

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.word_subtitle.title"))
        master.geometry("720x700")
        self.processing = False
        self._build_ui()
        if initial_file and os.path.exists(initial_file):
            ext = os.path.splitext(initial_file)[1].lower()
            if ext == ".json":
                self.entry_json.insert(0, initial_file)
            elif ext in (".mp4", ".mkv", ".avi", ".mov", ".webm"):
                self.entry_video.insert(0, initial_file)
            self._auto_fill_output()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        f = self.master
        pad = dict(padx=10, pady=4)

        # ── Files ──
        file_frame = tk.LabelFrame(f, text=tr("tool.word_subtitle.frame_file"), padx=8, pady=6)
        file_frame.pack(fill="x", **pad)
        file_frame.columnconfigure(1, weight=1)
        self._build_file_row(file_frame, 0, tr("tool.word_subtitle.label_video"),  "entry_video",  self._select_video)
        self._build_file_row(file_frame, 1, tr("tool.word_subtitle.label_json"),   "entry_json",   self._select_json)
        self._build_file_row(file_frame, 2, tr("tool.word_subtitle.label_output"), "entry_output", self._select_output)

        # ── Subtitle style ──
        style_frame = tk.LabelFrame(f, text=tr("tool.word_subtitle.frame_style"), padx=8, pady=6)
        style_frame.pack(fill="x", **pad)

        self.fontsize_var        = tk.IntVar(value=60)
        self.pos_pct_var         = tk.IntVar(value=20)  # 0% = bottom, 100% = top
        self.bold_var            = tk.BooleanVar(value=True)
        self.unspoken_color_var  = tk.StringVar(value="#FFFFFF")
        self.highlight_color_var = tk.StringVar(value="#FFD700")
        self.outline_color_var   = tk.StringVar(value="#000000")

        # Row 0: fontsize / bold
        tk.Label(style_frame, text=tr("tool.word_subtitle.label_fontsize")).grid(row=0, column=0, sticky="e", padx=4, pady=3)
        tk.Spinbox(style_frame, from_=10, to=80, width=5,
                   textvariable=self.fontsize_var).grid(row=0, column=1, sticky="w", padx=4)
        tk.Checkbutton(style_frame, text=tr("tool.word_subtitle.label_bold"),
                       variable=self.bold_var).grid(row=0, column=2, columnspan=2, padx=8)

        # Row 1: vertical position slider
        tk.Label(style_frame, text=tr("tool.word_subtitle.label_vpos")).grid(row=1, column=0, sticky="e", padx=4, pady=(4, 0))
        pos_scale = tk.Scale(
            style_frame, from_=0, to=100, orient="horizontal",
            variable=self.pos_pct_var, length=260,
            showvalue=False,
        )
        pos_scale.grid(row=1, column=1, columnspan=3, sticky="w", padx=4)
        self._pos_label = tk.Label(style_frame, text="20%", width=5, anchor="w")
        self._pos_label.grid(row=1, column=4, sticky="w")
        tk.Label(style_frame, text=tr("tool.word_subtitle.label_vpos_hint"),
                 fg="gray", font=("", 8)).grid(row=2, column=1, columnspan=3, sticky="w", padx=4)
        self.pos_pct_var.trace_add("write",
            lambda *_: self._pos_label.config(text=f"{self.pos_pct_var.get()}%"))

        # Rows 3-5: colors
        color_rows = [
            (tr("tool.word_subtitle.label_unspoken"),  self.unspoken_color_var,  self._choose_unspoken_color),
            (tr("tool.word_subtitle.label_highlight"), self.highlight_color_var, self._choose_highlight_color),
            (tr("tool.word_subtitle.label_outline"),   self.outline_color_var,   self._choose_outline_color),
        ]
        self._color_previews = {}
        for r, (label, var, cmd) in enumerate(color_rows, start=3):
            tk.Label(style_frame, text=label).grid(row=r, column=0, sticky="e", padx=4, pady=3)
            tk.Entry(style_frame, textvariable=var, width=9).grid(
                row=r, column=1, sticky="w", padx=4)
            preview = tk.Label(style_frame, width=2, relief="solid", bg=var.get())
            preview.grid(row=r, column=2, sticky="w", padx=(0, 2))
            self._color_previews[id(var)] = (var, preview)
            var.trace_add("write", lambda *_, v=var, lbl=preview: self._sync_preview(v, lbl))
            tk.Button(style_frame, text=tr("tool.word_subtitle.btn_choose_color"), width=5,
                      command=cmd).grid(row=r, column=3, sticky="w", padx=4)

        # ── Line break & effect ──
        line_frame = tk.LabelFrame(f, text=tr("tool.word_subtitle.frame_line"), padx=8, pady=6)
        line_frame.pack(fill="x", **pad)

        self.line_mode_var = tk.StringVar(value="segment")
        tk.Radiobutton(line_frame, text=tr("tool.word_subtitle.radio_by_segment"),
                       variable=self.line_mode_var, value="segment",
                       command=self._on_line_mode_change).grid(
            row=0, column=0, sticky="w", padx=4)
        tk.Radiobutton(line_frame, text=tr("tool.word_subtitle.radio_by_chars"),
                       variable=self.line_mode_var, value="words",
                       command=self._on_line_mode_change).grid(
            row=0, column=1, sticky="w", padx=4)

        self.max_words_var = tk.IntVar(value=8)
        tk.Label(line_frame, text=tr("tool.word_subtitle.label_max_words")).grid(
            row=0, column=2, sticky="e", padx=(16, 2))
        self._spinbox_maxwords = tk.Spinbox(
            line_frame, from_=2, to=30, width=4,
            textvariable=self.max_words_var, state="disabled")
        self._spinbox_maxwords.grid(row=0, column=3, sticky="w", padx=4)

        self.kf_style_var = tk.StringVar(value=r"\kf")
        tk.Label(line_frame, text=tr("tool.word_subtitle.label_highlight_effect")).grid(row=1, column=0, sticky="e", padx=4, pady=4)
        ttk.Combobox(
            line_frame, textvariable=self.kf_style_var,
            state="readonly", width=24,
            values=[tr("tool.word_subtitle.kf_fill"), tr("tool.word_subtitle.kf_instant")],
        ).grid(row=1, column=1, columnspan=3, sticky="w", padx=4)

        # ── Encoding ──
        enc_frame = tk.LabelFrame(f, text=tr("tool.word_subtitle.frame_encode"), padx=8, pady=6)
        enc_frame.pack(fill="x", **pad)

        self.crf_var    = tk.IntVar(value=18)
        self.preset_var = tk.StringVar(value="fast")
        tk.Label(enc_frame, text="CRF:").grid(row=0, column=0, sticky="e", padx=4)
        tk.Spinbox(enc_frame, from_=0, to=51, width=4,
                   textvariable=self.crf_var).grid(row=0, column=1, sticky="w", padx=4)
        tk.Label(enc_frame, text="Preset:").grid(row=0, column=2, sticky="e", padx=(16, 4))
        ttk.Combobox(enc_frame, textvariable=self.preset_var, state="readonly", width=10,
                     values=["ultrafast", "fast", "medium", "slow"]).grid(
            row=0, column=3, sticky="w", padx=4)

        # ── 进度 ──
        self.progress_bar = ttk.Progressbar(f, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", padx=10, pady=(6, 0))
        self._progress_label = tk.Label(f, text="", fg="#555", font=("", 8))
        self._progress_label.pack()

        # ── 日志 ──
        log_frame = tk.Frame(f)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(2, 4))
        self.log_text = tk.Text(log_frame, height=7, state="disabled",
                                wrap="word", font=("Consolas", 9))
        vsb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        # ── Start button ──
        self.btn_start = tk.Button(f, text=tr("tool.word_subtitle.btn_start"), width=20,
                                   bg="#0078d4", fg="white",
                                   command=self._start_burn)
        self.btn_start.pack(pady=(0, 8))

    def _build_file_row(self, parent, row, label, attr, cmd):
        tk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=4, pady=3)
        entry = tk.Entry(parent, width=52)
        entry.grid(row=row, column=1, sticky="ew", padx=4)
        setattr(self, attr, entry)
        tk.Button(parent, text=tr("tool.word_subtitle.browse"), width=5, command=cmd).grid(row=row, column=2, padx=4)

    def _sync_preview(self, var: tk.StringVar, label: tk.Label):
        color = var.get().strip()
        if re.match(r'^#[0-9a-fA-F]{6}$', color):
            try:
                label.config(bg=color)
            except Exception:
                pass

    # ── 文件选择 ──────────────────────────────────────────────────────────────

    def _select_video(self):
        p = filedialog.askopenfilename(
            title=tr("tool.word_subtitle.dialog_video"),
            filetypes=[(tr("tool.word_subtitle.filter_video"), "*.mp4;*.mkv;*.avi;*.mov;*.webm"),
                       (tr("tool.word_subtitle.filter_all"), "*.*")])
        if p:
            self.entry_video.delete(0, tk.END)
            self.entry_video.insert(0, p)
            self._auto_fill_output()

    def _select_json(self):
        p = filedialog.askopenfilename(
            title=tr("tool.word_subtitle.dialog_json"),
            filetypes=[(tr("tool.word_subtitle.filter_json"), "*.json"),
                       (tr("tool.word_subtitle.filter_all"), "*.*")])
        if p:
            self.entry_json.delete(0, tk.END)
            self.entry_json.insert(0, p)
            self._auto_fill_output()

    def _select_output(self):
        video = self.entry_video.get().strip()
        init_dir = os.path.dirname(video) if video else ""
        p = filedialog.asksaveasfilename(
            title=tr("tool.word_subtitle.dialog_output"),
            defaultextension=".mp4",
            filetypes=[(tr("tool.word_subtitle.filter_mp4"), "*.mp4")],
            initialdir=init_dir)
        if p:
            self.entry_output.delete(0, tk.END)
            self.entry_output.insert(0, p)

    def _auto_fill_output(self):
        video = self.entry_video.get().strip()
        if not video:
            return
        stem = os.path.splitext(video)[0]
        self.entry_output.delete(0, tk.END)
        self.entry_output.insert(0, stem + "_karaoke.mp4")

    # ── Color pickers ────────────────────────────────────────────────────────

    def _choose_unspoken_color(self):
        c = colorchooser.askcolor(title=tr("tool.word_subtitle.dialog_color_unspoken"),
                                  initialcolor=self.unspoken_color_var.get())
        if c and c[1]:
            self.unspoken_color_var.set(c[1])

    def _choose_highlight_color(self):
        c = colorchooser.askcolor(title=tr("tool.word_subtitle.dialog_color_highlight"),
                                  initialcolor=self.highlight_color_var.get())
        if c and c[1]:
            self.highlight_color_var.set(c[1])

    def _choose_outline_color(self):
        c = colorchooser.askcolor(title=tr("tool.word_subtitle.dialog_color_outline"),
                                  initialcolor=self.outline_color_var.get())
        if c and c[1]:
            self.outline_color_var.set(c[1])

    # ── UI 状态 ───────────────────────────────────────────────────────────────

    def _on_line_mode_change(self):
        state = "normal" if self.line_mode_var.get() == "words" else "disabled"
        self._spinbox_maxwords.config(state=state)

    # ── 日志 ─────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, msg)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
        self.master.update_idletasks()

    # ── 核心算法 ──────────────────────────────────────────────────────────────

    def _is_cjk_content(self, text: str) -> bool:
        return any(_is_cjk(c) for c in text if c.strip())

    def _normalise_word(self, word_text: str) -> str:
        """CJK 内容去掉前导空格；英文保留（Whisper 的词带前导空格）。"""
        stripped = word_text.lstrip()
        if stripped and _is_cjk(stripped[0]):
            return stripped
        return word_text

    def _synthesise_words(self, segment: dict) -> list:
        """words[] 中无匹配词时，按字符数比例均分 segment 时间生成伪词列表。"""
        text  = segment.get("text", "").strip()
        start = segment["start"]
        end   = segment["end"]
        if not text:
            return []
        tokens = list(text.replace(" ", "")) if self._is_cjk_content(text) else text.split()
        if not tokens:
            return [{"word": text, "start": start, "end": end}]
        dur = (end - start) / len(tokens)
        result = []
        for i, tok in enumerate(tokens):
            prefix = "" if (tok and _is_cjk(tok[0])) else " "
            result.append({
                "word":  prefix + tok,
                "start": start + i * dur,
                "end":   start + (i + 1) * dur,
            })
        return result

    def _group_by_segment(self, words: list, segments: list) -> List[_Line]:
        lines = []
        max_n = self.max_words_var.get()
        for seg in segments:
            s0, s1 = seg["start"] - 0.05, seg["end"] + 0.05
            seg_words = [w for w in words if s0 <= w["start"] < s1]
            if not seg_words:
                seg_words = self._synthesise_words(seg)
            if not seg_words:
                continue
            # 句子过长时拆成多行
            if len(seg_words) > max_n * 2:
                for i in range(0, len(seg_words), max_n):
                    chunk = seg_words[i:i + max_n]
                    lines.append(_Line(chunk[0]["start"], chunk[-1]["end"], chunk))
            else:
                lines.append(_Line(
                    seg_words[0]["start"],
                    max(seg["end"], seg_words[-1]["end"]),
                    seg_words,
                ))
        return lines

    def _group_by_word_count(self, words: list, max_n: int) -> List[_Line]:
        lines = []
        for i in range(0, len(words), max_n):
            chunk = words[i:i + max_n]
            lines.append(_Line(chunk[0]["start"], chunk[-1]["end"], chunk))
        return lines

    def _build_karaoke_text(self, words: list, tag: str) -> str:
        """拼接带 \\kf / \\k 标签的卡拉OK文本串。"""
        parts = []
        prev_end = None
        for w in words:
            # 词间隙：插入无颜色的等待标签
            if prev_end is not None and w["start"] > prev_end + 0.02:
                gap_cs = int(round((w["start"] - prev_end) * 100))
                parts.append(f"{{\\k{gap_cs}}}")
            duration_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
            text = self._normalise_word(w.get("word", ""))
            parts.append(f"{{{tag}{duration_cs}}}{text}")
            prev_end = w["end"]
        return "".join(parts)

    def _build_ass(self, json_data: dict, style_cfg: dict) -> str:
        words    = list(json_data.get("words", []))
        segments = json_data.get("segments", [])
        total    = float(json_data.get("duration", 1e9))

        # 无逐字数据时合成
        if not words:
            self._log(tr("tool.word_subtitle.log_hint_no_words"))
            for seg in segments:
                words.extend(self._synthesise_words(seg))

        # 排序 & 时间合法性修正
        words = sorted(words, key=lambda w: float(w["start"]))
        for w in words:
            w["start"] = max(0.0, min(float(w["start"]), total))
            w["end"]   = max(w["start"] + 0.01, min(float(w["end"]), total))

        # 取高亮效果标签
        kf_tag = self.kf_style_var.get().split()[0]   # "\kf" 或 "\k"

        # 分行
        if self.line_mode_var.get() == "segment" and segments:
            lines = self._group_by_segment(words, segments)
        else:
            lines = self._group_by_word_count(words, self.max_words_var.get())

        # 垂直位置：\pos(cx, cy)，\an2 锚点在文字底部中央
        res_x   = style_cfg.get("play_res_x", 1920)
        res_y   = style_cfg.get("play_res_y", 1080)
        pos_pct = style_cfg.get("pos_pct", 8)
        cx      = res_x // 2
        cy      = int(res_y * (1.0 - pos_pct / 100.0))
        pos_tag = f"{{\\an2\\pos({cx},{cy})}}"

        # 生成 ASS 头
        ass = _ASS_HEADER.format(
            play_res_x   = res_x,
            play_res_y   = res_y,
            fontsize     = style_cfg["fontsize"],
            highlight_ass= hex_color_to_ass(style_cfg["highlight"]),
            unspoken_ass = hex_color_to_ass(style_cfg["unspoken"]),
            outline_ass  = hex_color_to_ass(style_cfg["outline"]),
            bold         = style_cfg["bold"],
        )

        # 生成 Dialogue 条目
        for line in lines:
            if not line.words:
                continue
            s_ts = _seconds_to_ass_time(line.start)
            e_ts = _seconds_to_ass_time(max(line.end, line.start + 0.1))
            kt   = self._build_karaoke_text(line.words, kf_tag)
            ass += f"Dialogue: 0,{s_ts},{e_ts},Default,,0,0,0,,{pos_tag}{kt}\n"

        return ass

    # ── 烧录流程 ──────────────────────────────────────────────────────────────

    def _start_burn(self):
        if self.processing:
            return
        video  = self.entry_video.get().strip()
        jpath  = self.entry_json.get().strip()
        output = self.entry_output.get().strip()

        label_video = tr("tool.word_subtitle.label_video_file")
        label_json = tr("tool.word_subtitle.label_json_file")
        for label, path in [(label_video, video), (label_json, jpath)]:
            if not path or not os.path.exists(path):
                messagebox.showerror(
                    tr("tool.word_subtitle.error_missing_file_title"),
                    tr("tool.word_subtitle.error_missing_file_msg", label=label))
                return
        if not output:
            messagebox.showerror(
                tr("tool.word_subtitle.error_missing_path_title"),
                tr("tool.word_subtitle.error_missing_path_msg"))
            return

        try:
            with open(jpath, "r", encoding="utf-8-sig") as fp:
                json_data = json.load(fp)
        except Exception as e:
            messagebox.showerror(tr("tool.word_subtitle.error_json_read_title"), str(e))
            return

        if "segments" not in json_data and "words" not in json_data:
            messagebox.showerror(
                tr("tool.word_subtitle.error_format_title"),
                tr("tool.word_subtitle.error_format_msg"))
            return

        res_w, res_h = _get_video_resolution(video)
        self._log(tr("tool.word_subtitle.log_resolution", w=res_w, h=res_h))

        style_cfg = {
            "fontsize":   self.fontsize_var.get(),
            "highlight":  self.highlight_color_var.get(),
            "unspoken":   self.unspoken_color_var.get(),
            "outline":    self.outline_color_var.get(),
            "bold":       1 if self.bold_var.get() else 0,
            "pos_pct":    self.pos_pct_var.get(),
            "play_res_x": res_w,
            "play_res_y": res_h,
        }

        ass_content = self._build_ass(json_data, style_cfg)

        ass_path = os.path.splitext(output)[0] + "_karaoke.ass"
        try:
            with open(ass_path, "w", encoding="utf-8-sig") as fp:
                fp.write(ass_content)
            self._log(tr("tool.word_subtitle.log_ass_written", filename=os.path.basename(ass_path)))
        except Exception as e:
            messagebox.showerror(tr("tool.word_subtitle.error_ass_write_title"), str(e))
            return

        escaped_ass = escape_ffmpeg_path(ass_path)
        cmd = [
            "ffmpeg", "-y",
            "-i", os.path.abspath(video),
            "-vf", f"ass='{escaped_ass}'",
            "-c:v", "libx264",
            "-preset", self.preset_var.get(),
            "-crf", str(self.crf_var.get()),
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            os.path.abspath(output),
        ]

        self.processing = True
        self.btn_start.config(state=tk.DISABLED)
        self.progress_bar["value"] = 0
        self._progress_label.config(text="")
        self.set_busy()
        threading.Thread(
            target=self._run_ffmpeg,
            args=(cmd, output, ass_path),
            daemon=True,
        ).start()

    def _run_ffmpeg(self, cmd, output_path, ass_path):
        start_time = time.time()
        dur_pat  = re.compile(r"Duration: (\d+):(\d+):(\d+\.\d+)")
        time_pat = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        total_dur = None

        def _run(c):
            proc = subprocess.Popen(
                c, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace")
            for line in proc.stderr:
                nonlocal total_dur
                line = line.strip()
                if total_dur is None:
                    m = dur_pat.search(line)
                    if m:
                        h, mi, s = map(float, m.groups())
                        total_dur = h * 3600 + mi * 60 + s
                m = time_pat.search(line)
                if m:
                    h, mi, s = map(float, m.groups())
                    cur = h * 3600 + mi * 60 + s
                    if total_dur and total_dur > 0 and cur > 0:
                        pct    = (cur / total_dur) * 100
                        elp    = time.time() - start_time
                        rem    = (elp / cur) * (total_dur - cur)
                        self.master.after(0, self._update_progress, pct, elp, rem)
            proc.wait()
            return proc.returncode

        try:
            rc = _run(cmd)
            if rc != 0:
                # -c:a copy fallback to AAC re-encode
                self.master.after(0, self._log, tr("tool.word_subtitle.log_copy_retry"))
                cmd2 = list(cmd)
                idx = cmd2.index("copy")
                cmd2[idx] = "aac"
                out_idx = cmd2.index(os.path.abspath(output_path))
                cmd2[out_idx:out_idx] = ["-b:a", "192k"]
                rc = _run(cmd2)

            if rc == 0:
                self.master.after(0, self._log,
                                  tr("tool.word_subtitle.log_complete",
                                     filename=os.path.basename(output_path)))
                logger.info(tr("tool.word_subtitle.log_done", filename=os.path.basename(output_path)))
                self.set_done()
            else:
                self.master.after(0, self._log, tr("tool.word_subtitle.log_ffmpeg_fail"))
                self.set_error(tr("tool.word_subtitle.error_burn_ffmpeg", rc=rc))
        except Exception as e:
            self.master.after(0, self._log, tr("tool.word_subtitle.log_exception", e=e))
            self.set_error(tr("tool.word_subtitle.error_burn_exception", e=e))
        finally:
            self.processing = False
            self.master.after(0, lambda: self.btn_start.config(state=tk.NORMAL))
            self.master.after(0, lambda: self.progress_bar.config(value=100))

    def _update_progress(self, pct: float, elapsed: float, remain: float):
        self.progress_bar["value"] = pct

        def _fmt(sec):
            sec = int(sec)
            return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"

        self._progress_label.config(
            text=tr("tool.word_subtitle.progress_label",
                    pct=pct, elapsed=_fmt(elapsed), remain=_fmt(remain)))


# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    initial = sys.argv[1] if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else None
    app = WordSubtitleApp(root, initial_file=initial)
    root.mainloop()
