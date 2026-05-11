"""
text2Video.py - 文字转视频工具集

三个独立工具：
  TTSApp         - 文字合成语音（Fish Audio TTS，支持单角色/多角色）
  SRTFromTextApp - 按文本+音频生成字幕 SRT（文本已知，按字符比例分配时间轴）
  AudioVideoApp  - 音频+图片合成视频（ffmpeg）
"""

from tools.base import ToolBase
from i18n import tr
import os
import tkinter as tk
from tkinter import filedialog, ttk
import threading
import subprocess
import tempfile

from core import tts as core_tts
from tools.router.voice_picker import VoiceSlot


# ══════════════════════════════════════════════════════════════════════════════
# 工具1：文字合成语音
# ══════════════════════════════════════════════════════════════════════════════

class TTSApp(ToolBase):
    def __init__(self, master):
        self.master = master
        master.title(tr("tool.tts.title"))
        master.geometry("820x680")
        master.resizable(True, True)

        self._stop_flag = False
        self._last_output = ""   # 记录最后生成的音频路径，供其他工具使用

        self._build_ui()

    def _build_ui(self):
        tab = self.master
        tab.columnconfigure(1, weight=1)

        # Provider dropdown was removed 2026-05-11 — voice + engine pick
        # now lives in VoiceSlot's [Pick voice…] dialog at use time
        # (single mode below has its own slot, multi mode each role has
        # its own slot, and dispatch reads provider from the picked
        # TTSVoice). No more shared "default TTS provider" config.

        row = 0
        mode_frame = tk.LabelFrame(tab, text=tr("tool.tts.mode_frame"), padx=8, pady=6)
        mode_frame.grid(row=row, column=0, columnspan=3, padx=10, pady=6, sticky="ew")
        self.mode_var = tk.StringVar(value="single")
        tk.Radiobutton(mode_frame, text=tr("tool.tts.mode_single"), variable=self.mode_var,
                       value="single", command=self._on_mode_change).pack(side=tk.LEFT, padx=15)
        tk.Radiobutton(mode_frame, text=tr("tool.tts.mode_multi"), variable=self.mode_var,
                       value="multi", command=self._on_mode_change).pack(side=tk.LEFT, padx=15)

        # 单角色
        self.single_frame = tk.LabelFrame(tab, text=tr("tool.tts.single_frame"), padx=10, pady=8)
        self.single_frame.grid(row=2, column=0, columnspan=3, padx=10, pady=4, sticky="ew")
        self.single_frame.columnconfigure(1, weight=1)
        tk.Label(self.single_frame, text=tr("tool.tts.voice_label")).grid(
            row=0, column=0, padx=5, pady=6, sticky="e")
        self._single_voice_slot = VoiceSlot(self.single_frame)
        self._single_voice_slot.grid(row=0, column=1, sticky="ew", padx=5)
        tk.Label(self.single_frame, text=tr("tool.tts.input_text")).grid(row=1, column=0, padx=5, pady=6, sticky="ne")
        self.single_text = tk.Text(self.single_frame, height=8, width=55, wrap=tk.WORD)
        self.single_text.grid(row=1, column=1, columnspan=2, sticky="ew", padx=5)
        self.single_text.insert(tk.END, tr("tool.tts.single_placeholder"))

        # 多角色
        self.multi_frame = tk.LabelFrame(tab, text=tr("tool.tts.multi_frame"), padx=10, pady=8)
        self.multi_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=4, sticky="ew")
        self.multi_frame.columnconfigure(1, weight=1)
        hdr = tk.Frame(self.multi_frame)
        hdr.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 4))
        tk.Label(hdr, text=tr("tool.tts.role_name_hdr"), width=12, font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=4)
        tk.Label(hdr, text=tr("tool.tts.voice_label"),
                 font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=4)
        # roles entries: (name_var, voice_slot, frame). Each role's
        # voice_slot is independent — a dialogue can mix engines (e.g.
        # narrator on edge_tts, child on fish_audio).
        self.roles = []
        self.roles_frame = tk.Frame(self.multi_frame)
        self.roles_frame.grid(row=1, column=0, columnspan=4, sticky="ew")
        self._add_role(tr("tool.tts.default_role1"))
        self._add_role(tr("tool.tts.default_role2"))
        tk.Button(self.multi_frame, text=tr("tool.tts.add_role"),
                  command=lambda: self._add_role("")).grid(row=2, column=0, pady=6, sticky="w")
        tk.Label(self.multi_frame, text=tr("tool.tts.dialog_text")).grid(row=3, column=0, padx=5, pady=6, sticky="ne")
        self.multi_text = tk.Text(self.multi_frame, height=8, width=55, wrap=tk.WORD)
        self.multi_text.grid(row=3, column=1, columnspan=3, sticky="ew", padx=5)
        self.multi_text.insert(tk.END, tr("tool.tts.dialog_placeholder"))
        tk.Label(self.multi_frame, text=tr("tool.tts.dialog_hint"),
                 fg="gray", font=("Arial", 8)).grid(row=4, column=1, sticky="w", padx=5)

        # 公共参数
        row = 4
        common = tk.Frame(tab)
        common.grid(row=row, column=0, columnspan=3, padx=10, pady=4, sticky="ew")
        tk.Label(common, text=tr("tool.tts.output_format")).pack(side=tk.LEFT, padx=(0, 4))
        self.audio_format_var = tk.StringVar(value="mp3")
        ttk.Combobox(common, textvariable=self.audio_format_var,
                     values=["mp3", "wav", "opus"], state="readonly", width=8).pack(side=tk.LEFT, padx=(0, 20))
        tk.Label(common, text=tr("tool.tts.speed")).pack(side=tk.LEFT, padx=(0, 4))
        self.speed_var = tk.DoubleVar(value=1.0)
        tk.Scale(common, variable=self.speed_var, from_=0.5, to=2.0, resolution=0.1,
                 orient=tk.HORIZONTAL, length=160).pack(side=tk.LEFT)
        self.speed_lbl = tk.Label(common, text="1.0x", width=5)
        self.speed_lbl.pack(side=tk.LEFT)
        self.speed_var.trace('w', lambda *_: self.speed_lbl.config(text=f"{self.speed_var.get():.1f}x"))

        row = 5
        tk.Label(tab, text=tr("tool.tts.output_file")).grid(row=row, column=0, padx=10, pady=6, sticky="e")
        self.output_path_var = tk.StringVar(value="output.mp3")
        tk.Entry(tab, textvariable=self.output_path_var, width=50).grid(row=row, column=1, sticky="ew")
        tk.Button(tab, text=tr("tool.tts.browse"), command=self._select_output).grid(row=row, column=2, padx=10)

        row = 6
        btn_frame = tk.Frame(tab)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=10)
        self.generate_btn = tk.Button(btn_frame, text=tr("tool.tts.btn_generate"), command=self.start_generation,
                                      width=18, bg="#2196F3", fg="white", font=("Arial", 10, "bold"))
        self.generate_btn.pack(side=tk.LEFT, padx=8)
        self.stop_btn = tk.Button(btn_frame, text=tr("tool.tts.btn_stop"), command=self._stop_generation,
                                  width=8, state="disabled")
        self.stop_btn.pack(side=tk.LEFT, padx=4)

        row = 7
        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(tab, variable=self.progress_var, maximum=100, length=500).grid(
            row=row, column=0, columnspan=3, padx=10, pady=(4, 0), sticky="ew")
        row = 8
        self.status_var = tk.StringVar(value="")
        tk.Label(tab, textvariable=self.status_var, fg="blue", anchor="w").grid(
            row=row, column=0, columnspan=3, padx=10, pady=4, sticky="ew")

        self._on_mode_change()

    def _add_role(self, name=""):
        f = tk.Frame(self.roles_frame)
        f.pack(fill="x", pady=2)
        name_var = tk.StringVar(value=name)
        tk.Entry(f, textvariable=name_var, width=12).pack(side=tk.LEFT, padx=4)
        voice_slot = VoiceSlot(f, label_width=44)
        voice_slot.pack(side=tk.LEFT, padx=4, fill="x", expand=True)
        role = (name_var, voice_slot, f)
        self.roles.append(role)
        tk.Button(f, text="✕", command=lambda r=role: self._remove_role(r), width=2).pack(side=tk.LEFT)

    def _remove_role(self, role):
        if len(self.roles) <= 1:
            return
        role[2].destroy()
        self.roles.remove(role)

    def _on_mode_change(self):
        if self.mode_var.get() == "single":
            self.single_frame.grid()
            self.multi_frame.grid_remove()
        else:
            self.single_frame.grid_remove()
            self.multi_frame.grid()

    def _select_output(self):
        fmt = self.audio_format_var.get()
        path = filedialog.asksaveasfilename(
            title=tr("tool.tts.dialog_select_output"),
            defaultextension=f".{fmt}",
            filetypes=[(f"{fmt.upper()} files", f"*.{fmt}"), ("All files", "*.*")]
        )
        if path:
            self.output_path_var.set(path)

    def start_generation(self):
        # Provider readiness is checked at dispatch time per-voice — the
        # picker only lets users pick voices from configured providers,
        # but we revalidate here in case state shifted (key removed
        # since the pick, gateway went offline, etc.).
        self._stop_flag = False
        self.generate_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress_var.set(0)
        self.status_var.set(tr("tool.tts.status_preparing"))
        self.set_busy()
        t = threading.Thread(
            target=self._run_single if self.mode_var.get() == "single" else self._run_multi,
            daemon=True)
        t.start()

    def _stop_generation(self):
        self._stop_flag = True
        self.status_var.set(tr("tool.tts.status_stopping"))

    def _finish_generation(self):
        """Re-enable the action buttons. Tab status is set by the _run_* caller
        (set_done on success, set_error on failure, set_warning on stop)."""
        self.master.after(0, lambda: self.generate_btn.config(state="normal"))
        self.master.after(0, lambda: self.stop_btn.config(state="disabled"))

    def _run_single(self):
        try:
            voice = self._single_voice_slot.voice
            text = self.single_text.get("1.0", tk.END).strip()
            output = self.output_path_var.get().strip()
            if voice is None or not voice.voice_id:
                self._show_error(tr("tool.tts.error_no_voice_picked")); return
            if not text:
                self._show_error(tr("tool.tts.error_no_text")); return
            if not output:
                self._show_error(tr("tool.tts.error_no_output")); return

            self.status_var.set(tr("tool.tts.status_calling_api"))
            self.progress_var.set(10)

            # Map streaming byte count to a pseudo 10%-90% progress bar
            # (total size is unknown until the stream completes).
            def on_progress(written, _total, _msg):
                pct = min(90, 10 + written // 1024)
                self.master.after(0, lambda p=pct: self.progress_var.set(p))

            try:
                core_tts.synthesize_text(
                    text, output,
                    voice_id=voice.voice_id,
                    audio_format=self.audio_format_var.get(),
                    provider=voice.provider,
                    should_cancel=lambda: self._stop_flag,
                    on_progress=on_progress,
                )
            except InterruptedError:
                self.status_var.set(tr("tool.tts.status_stopped"))
                return

            self._last_output = output
            self.progress_var.set(100)
            self.status_var.set(tr("tool.tts.status_done_single", output=output))
            self.set_done()
        except Exception as e:
            self.status_var.set(tr("tool.tts.status_fail", e=e))
            self.set_error(tr("tool.tts.error_tts_single_failed", e=e))
        finally:
            self._finish_generation()

    def _run_multi(self):
        try:
            # role_map_full: name -> (provider, voice_id) — each role
            # carries its own engine pick.
            role_map_full: dict[str, tuple[str, str]] = {}
            for nv, slot, _ in self.roles:
                name = nv.get().strip()
                if not name:
                    continue
                if slot.voice is None or not slot.voice.voice_id:
                    self._show_error(tr("tool.tts.error_role_no_voice", role=name))
                    return
                role_map_full[name] = (slot.voice.provider, slot.voice.voice_id)
            if not role_map_full:
                self._show_error(tr("tool.tts.error_no_role_voice")); return

            # parse_dialogue still expects {name: voice_id} for matching;
            # voice_id value isn't used by the parser — only the key matters.
            role_keys = {name: vid for name, (_, vid) in role_map_full.items()}
            raw = self.multi_text.get("1.0", tk.END).strip()
            segments = core_tts.parse_dialogue(raw, role_keys)
            if not segments:
                self._show_error(tr("tool.tts.error_no_valid_dialog")); return
            output = self.output_path_var.get().strip()
            if not output:
                self._show_error(tr("tool.tts.error_no_output")); return

            total = len(segments)

            def on_progress(i, total_segs, role):
                if role == "merging":
                    self.master.after(0,
                        lambda: self.status_var.set(tr("tool.tts.status_merging")))
                    self.master.after(0, lambda: self.progress_var.set(90))
                else:
                    self.master.after(0, lambda idx=i, r=role: self.status_var.set(
                        tr("tool.tts.status_generating_seg",
                           i=idx + 1, total=total_segs, role=r)))
                    self.master.after(0,
                        lambda idx=i: self.progress_var.set(int(idx / total_segs * 85)))

            try:
                core_tts.synthesize_dialogue(
                    segments, role_map_full, output,
                    audio_format=self.audio_format_var.get(),
                    should_cancel=lambda: self._stop_flag,
                    on_progress=on_progress,
                )
            except InterruptedError:
                self.status_var.set(tr("tool.tts.status_stopped"))
                return

            self._last_output = output
            self.progress_var.set(100)
            self.status_var.set(tr("tool.tts.status_done_multi", total=total, output=output))
            self.set_done()
        except Exception as e:
            self.status_var.set(tr("tool.tts.status_fail", e=e))
            self.set_error(tr("tool.tts.error_tts_multi_failed", e=e))
        finally:
            self._finish_generation()

    def _show_error(self, msg):
        self.master.after(0, lambda: __import__('tkinter').messagebox.showerror(
            tr("dialog.common.error"), msg, parent=self.master))


# ══════════════════════════════════════════════════════════════════════════════
# 工具2：文本 → SRT 字幕
# ══════════════════════════════════════════════════════════════════════════════

class SRTFromTextApp(ToolBase):
    """
    文本已知（来自 TTS 工具），根据音频总时长按字符比例分配时间轴，生成 SRT。
    不需要 ASR，适合文字视频制作流水线的字幕步骤。
    """

    def __init__(self, master):
        self.master = master
        master.title(tr("tool.tts_srt.title"))
        master.geometry("780x620")
        master.resizable(True, True)
        self._build_ui()

    def _build_ui(self):
        tab = self.master
        tab.columnconfigure(1, weight=1)

        row = 0
        tk.Label(tab, text=tr("tool.tts_srt.audio_label")).grid(row=row, column=0, padx=10, pady=8, sticky="e")
        self.audio_var = tk.StringVar()
        tk.Entry(tab, textvariable=self.audio_var, width=50, state='readonly').grid(
            row=row, column=1, sticky="ew")
        tk.Button(tab, text=tr("tool.tts_srt.btn_pick"), command=self._select_audio).grid(row=row, column=2, padx=10)

        row += 1
        self.duration_var = tk.StringVar(value="")
        tk.Label(tab, textvariable=self.duration_var, fg="gray",
                 font=("Arial", 8)).grid(row=row, column=1, sticky="w", padx=4)

        row += 1
        tk.Label(tab, text=tr("tool.tts_srt.text_label")).grid(row=row, column=0, padx=10, pady=8, sticky="ne")
        self.text_box = tk.Text(tab, height=12, width=55, wrap=tk.WORD)
        self.text_box.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(0, 10))
        self.text_box.insert(tk.END, tr("tool.tts.dialog_placeholder"))

        row += 1
        hint_frame = tk.Frame(tab)
        hint_frame.grid(row=row, column=1, sticky="w", padx=4, pady=2)
        tk.Label(hint_frame, text=tr("tool.tts_srt.text_hint"),
                 fg="gray", font=("Arial", 8)).pack(side=tk.LEFT)

        row += 1
        opt_frame = tk.LabelFrame(tab, text=tr("tool.tts_srt.segment_frame"), padx=10, pady=6)
        opt_frame.grid(row=row, column=0, columnspan=3, padx=10, pady=6, sticky="ew")

        tk.Label(opt_frame, text=tr("tool.tts_srt.max_chars")).pack(side=tk.LEFT, padx=(0, 4))
        self.max_chars_var = tk.IntVar(value=30)
        tk.Spinbox(opt_frame, textvariable=self.max_chars_var, from_=10, to=100,
                   width=6).pack(side=tk.LEFT, padx=(0, 20))
        tk.Label(opt_frame, text=tr("tool.tts_srt.gap")).pack(side=tk.LEFT, padx=(0, 4))
        self.gap_var = tk.DoubleVar(value=0.3)
        tk.Spinbox(opt_frame, textvariable=self.gap_var, from_=0.0, to=2.0,
                   increment=0.1, format="%.1f", width=6).pack(side=tk.LEFT)

        row += 1
        tk.Label(tab, text=tr("tool.tts_srt.output_label")).grid(row=row, column=0, padx=10, pady=8, sticky="e")
        self.output_var = tk.StringVar(value="output.srt")
        tk.Entry(tab, textvariable=self.output_var, width=50).grid(row=row, column=1, sticky="ew")
        tk.Button(tab, text=tr("tool.tts_srt.browse"), command=self._select_output).grid(row=row, column=2, padx=10)

        row += 1
        tk.Button(tab, text=tr("tool.tts_srt.btn_generate"), command=self._generate,
                  bg="#FF9800", fg="white", width=18, font=("Arial", 10, "bold")).grid(
            row=row, column=0, columnspan=3, pady=14)

        row += 1
        self.status_var = tk.StringVar(value="")
        tk.Label(tab, textvariable=self.status_var, fg="blue", anchor="w").grid(
            row=row, column=0, columnspan=3, padx=10, pady=4, sticky="ew")

    def _select_audio(self):
        path = filedialog.askopenfilename(
            title=tr("tool.tts_srt.dialog_select_audio"),
            filetypes=[(tr("tool.tts_srt.filter_audio"), "*.mp3 *.wav *.m4a *.aac *.ogg *.flac"),
                       (tr("tool.tts_srt.filter_all"), "*.*")]
        )
        if path:
            self.audio_var.set(path)
            dur = self._get_duration(path)
            if dur > 0:
                self.duration_var.set(tr("tool.tts_srt.duration_fmt", dur=dur))
            else:
                self.duration_var.set(tr("tool.tts_srt.duration_unavailable"))

    def _select_output(self):
        path = filedialog.asksaveasfilename(
            title=tr("tool.tts_srt.dialog_save_srt"), defaultextension=".srt",
            filetypes=[("SRT files", "*.srt"), ("All files", "*.*")]
        )
        if path:
            self.output_var.set(path)

    def _generate(self):
        from core.srt_from_text import (
            get_audio_duration, split_text_to_segments, build_srt_content,
        )

        audio = self.audio_var.get().strip()
        if not audio or not os.path.exists(audio):
            self.status_var.set(tr("tool.tts_srt.error_no_audio"))
            return
        raw = self.text_box.get("1.0", tk.END).strip()
        if not raw:
            self.status_var.set(tr("tool.tts_srt.error_no_text"))
            return
        output = self.output_var.get().strip()
        if not output:
            self.status_var.set(tr("tool.tts_srt.error_no_output"))
            return

        self.set_busy()
        try:
            duration = get_audio_duration(audio)
            if duration <= 0:
                self.set_error(tr("tool.tts_srt.error_cannot_get_duration"))
                self.status_var.set(tr("tool.tts_srt.error_cannot_get_duration"))
                return

            segments = split_text_to_segments(raw, self.max_chars_var.get())
            srt_content = build_srt_content(segments, duration, self.gap_var.get())

            with open(output, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            self.status_var.set(tr("tool.tts_srt.status_done", count=len(segments), output=output))
            self.set_done()
        except Exception as e:
            self.set_error(tr("tool.tts_srt.error_srt_failed", e=e))
            self.status_var.set(tr("tool.tts_srt.status_fail", e=e))


# ══════════════════════════════════════════════════════════════════════════════
# 工具3：音频 + 图片 合成视频
# ══════════════════════════════════════════════════════════════════════════════

from core.subtitle_ops import (
    split_srt_to_file,
    build_subtitle_style,
    escape_ffmpeg_path,
    LAYOUT_DEFAULTS,
    hex_color_to_ass,
)


class AudioVideoApp(ToolBase):
    """多章节音频合成视频：每章节独立配置音频/字幕/背景图/背景视频，最终合并为单一输出。"""

    def __init__(self, master):
        self.master = master
        master.title(tr("tool.audio_video.title"))
        master.geometry("1180x860")
        master.resizable(True, True)
        self.chapters = []          # list of chapter dicts
        self._ffmpeg_proc = None
        self._stop_flag = False
        self._build_ui()

    # ── UI 构建 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        tab = self.master
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(0, weight=1)

        # ── 左侧：章节列表 ──
        left = tk.Frame(tab)
        left.grid(row=0, column=0, padx=6, pady=6, sticky="nsew")
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        hdr = tk.Frame(left)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        tk.Label(hdr, text=tr("tool.audio_video.chapter_list"), font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        tk.Button(hdr, text=tr("tool.audio_video.add_chapter"), command=self._add_chapter,
                  bg="#2196F3", fg="white", width=14).pack(side=tk.RIGHT, padx=4)

        # 可滚动容器
        self._chap_canvas = tk.Canvas(left, borderwidth=1, relief=tk.SUNKEN, bg="#f0f0f0")
        _sb = ttk.Scrollbar(left, orient="vertical", command=self._chap_canvas.yview)
        self._chap_canvas.configure(yscrollcommand=_sb.set)
        self._chap_canvas.grid(row=1, column=0, sticky="nsew")
        _sb.grid(row=1, column=1, sticky="ns")
        self._chap_inner = tk.Frame(self._chap_canvas, bg="#f0f0f0")
        self._chap_win = self._chap_canvas.create_window((0, 0), window=self._chap_inner, anchor="nw")
        self._chap_inner.bind("<Configure>", lambda e: self._chap_canvas.configure(
            scrollregion=self._chap_canvas.bbox("all")))
        self._chap_canvas.bind("<Configure>", lambda e: self._chap_canvas.itemconfig(
            self._chap_win, width=e.width))
        self._chap_canvas.bind("<Enter>",
            lambda e: self._chap_canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self._chap_canvas.bind("<Leave>",
            lambda e: self._chap_canvas.unbind_all("<MouseWheel>"))

        # 输出文件
        out_f = tk.Frame(left)
        out_f.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 2))
        tk.Label(out_f, text=tr("tool.audio_video.output_video_label")).pack(side=tk.LEFT, padx=4)
        self.video_output_var = tk.StringVar(value="output.mp4")
        tk.Entry(out_f, textvariable=self.video_output_var, width=38).pack(
            side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        tk.Button(out_f, text=tr("tool.audio_video.browse"), command=self._select_video_output,
                  width=6).pack(side=tk.LEFT, padx=4)

        # ── 右侧：全局设置 ──
        right = tk.Frame(tab)
        right.grid(row=0, column=1, padx=6, pady=6, sticky="nsew")
        self._build_right_panel(right)

        # ── 底部：按钮 + 进度 ──
        bottom = tk.Frame(tab)
        bottom.grid(row=1, column=0, columnspan=2, pady=6, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        btn_row = tk.Frame(bottom)
        btn_row.grid(row=0, column=0)
        self.generate_btn = tk.Button(btn_row, text=tr("tool.audio_video.btn_compose"), command=self._start,
                                      width=22, height=2, bg="#4CAF50", fg="white",
                                      font=("Arial", 11, "bold"))
        self.generate_btn.pack(side=tk.LEFT, padx=10)
        self.stop_btn = tk.Button(btn_row, text=tr("tool.audio_video.btn_stop"), command=self._stop,
                                  width=8, height=2, state="disabled")
        self.stop_btn.pack(side=tk.LEFT, padx=4)

        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(bottom, variable=self.progress_var, maximum=100, length=700).grid(
            row=1, column=0, padx=12, pady=(6, 0), sticky="ew")
        self.status_var = tk.StringVar(value="")
        tk.Label(bottom, textvariable=self.status_var, fg="blue",
                 font=("Arial", 9), anchor="w").grid(
            row=2, column=0, padx=12, pady=2, sticky="ew")

        # 默认添加第一章节
        self._add_chapter()

    def _build_right_panel(self, right):
        # 视频配置
        cfg = tk.LabelFrame(right, text=tr("tool.audio_video.video_config"), padx=8, pady=8)
        cfg.pack(fill="x", padx=4, pady=4)

        tk.Label(cfg, text=tr("tool.audio_video.orientation"), font=("Arial", 9, "bold")).grid(
            row=0, column=0, padx=4, pady=4, sticky="w")
        self.orientation_var = tk.StringVar(value="horizontal")
        ori_f = tk.Frame(cfg)
        ori_f.grid(row=0, column=1, columnspan=2, sticky="w", padx=4)
        tk.Radiobutton(ori_f, text=tr("tool.audio_video.horizontal"), variable=self.orientation_var,
                       value="horizontal", command=self._on_orientation).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(ori_f, text=tr("tool.audio_video.vertical"), variable=self.orientation_var,
                       value="vertical", command=self._on_orientation).pack(side=tk.LEFT, padx=5)

        tk.Label(cfg, text=tr("tool.audio_video.resolution")).grid(row=1, column=0, padx=4, pady=4, sticky="e")
        self.resolution_var = tk.StringVar(value="1920x1080 (1080p)")
        self.resolution_combo = ttk.Combobox(cfg, textvariable=self.resolution_var,
                                              state="readonly", width=26)
        self._update_resolution()
        self.resolution_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=4)

        tk.Label(cfg, text=tr("tool.audio_video.bg_fill")).grid(row=2, column=0, padx=4, pady=4, sticky="e")
        bg_f = tk.Frame(cfg)
        bg_f.grid(row=2, column=1, columnspan=2, sticky="w", padx=4)
        self.bg_color_var = tk.StringVar(value="#000000")
        tk.Entry(bg_f, textvariable=self.bg_color_var, width=9, state='readonly').pack(side=tk.LEFT, padx=2)
        self.bg_preview = tk.Canvas(bg_f, width=22, height=18, bg="#000000",
                                    relief=tk.SUNKEN, borderwidth=1)
        self.bg_preview.pack(side=tk.LEFT, padx=2)
        tk.Button(bg_f, text=tr("tool.audio_video.pick"), command=self._choose_bg, width=7).pack(side=tk.LEFT, padx=2)

        tk.Label(cfg, text=tr("tool.audio_video.fps")).grid(row=3, column=0, padx=4, pady=4, sticky="e")
        self.fps_var = tk.StringVar(value="30")
        ttk.Combobox(cfg, textvariable=self.fps_var, values=["24", "25", "30", "60"],
                     state="readonly", width=8).grid(row=3, column=1, sticky="w", padx=4)

        tk.Label(cfg, text=tr("tool.audio_video.codec")).grid(row=4, column=0, padx=4, pady=4, sticky="e")
        self.codec_var = tk.StringVar(value="libx264")
        ttk.Combobox(cfg, textvariable=self.codec_var,
                     values=["libx264 (H.264)", "libx265 (H.265/HEVC)", "mpeg4"],
                     state="readonly", width=22).grid(row=4, column=1, columnspan=2, sticky="w", padx=4)

        # 字幕设置（全局）
        sub_frame = tk.LabelFrame(right, text=tr("tool.audio_video.sub_frame"), padx=8, pady=8)
        sub_frame.pack(fill="x", padx=4, pady=4)
        sub_frame.columnconfigure(1, weight=1)

        self.sub_split_var = tk.BooleanVar(value=True)
        tk.Checkbutton(sub_frame, text=tr("tool.audio_video.sub_split"),
                       variable=self.sub_split_var,
                       font=("Arial", 9, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

        tk.Label(sub_frame, text=tr("tool.audio_video.max_chars_label")).grid(row=1, column=0, padx=4, pady=5, sticky="e")
        self.sub_max_chars_var = tk.IntVar(value=20)
        tk.Spinbox(sub_frame, textvariable=self.sub_max_chars_var,
                   from_=5, to=80, width=6).grid(row=1, column=1, sticky="w", padx=4)
        tk.Label(sub_frame, text=tr("tool.audio_video.chars_hint"),
                 fg="gray", font=("Arial", 8)).grid(row=1, column=2, sticky="w")

        self.sub_is_chinese_var = tk.BooleanVar(value=True)
        tk.Checkbutton(sub_frame, text=tr("tool.audio_video.zh_priority"),
                       variable=self.sub_is_chinese_var).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=4, pady=2)

        tk.Label(sub_frame, text=tr("tool.audio_video.sub_color")).grid(row=3, column=0, padx=4, pady=5, sticky="e")
        sub_color_f = tk.Frame(sub_frame)
        sub_color_f.grid(row=3, column=1, columnspan=2, sticky="w", padx=4)
        self.sub_color_var = tk.StringVar(value="#FFFFFF")
        tk.Entry(sub_color_f, textvariable=self.sub_color_var, width=9, state='readonly').pack(side=tk.LEFT, padx=2)
        self.sub_color_preview = tk.Canvas(sub_color_f, width=22, height=18, bg="#FFFFFF",
                                            relief=tk.SUNKEN, borderwidth=1)
        self.sub_color_preview.pack(side=tk.LEFT, padx=2)
        tk.Button(sub_color_f, text=tr("tool.audio_video.pick"), command=self._choose_sub_color, width=7).pack(side=tk.LEFT, padx=2)

        tk.Label(sub_frame, text=tr("tool.audio_video.sub_fontsize")).grid(row=4, column=0, padx=4, pady=5, sticky="e")
        self.sub_fontsize_var = tk.IntVar(value=28)
        tk.Spinbox(sub_frame, textvariable=self.sub_fontsize_var,
                   from_=10, to=72, width=6).grid(row=4, column=1, sticky="w", padx=4)
        tk.Label(sub_frame, text=tr("tool.audio_video.fontsize_hint"),
                 fg="gray", font=("Arial", 8)).grid(row=4, column=2, sticky="w")

        tk.Label(sub_frame, text=tr("tool.audio_video.margin_v")).grid(row=5, column=0, padx=4, pady=5, sticky="e")
        self.sub_margin_v_var = tk.IntVar(value=80)
        tk.Spinbox(sub_frame, textvariable=self.sub_margin_v_var,
                   from_=10, to=300, width=6).grid(row=5, column=1, sticky="w", padx=4)
        tk.Label(sub_frame, text=tr("tool.audio_video.margin_hint"),
                 fg="gray", font=("Arial", 8)).grid(row=5, column=2, sticky="w")

        # 水印设置
        wm_frame = tk.LabelFrame(right, text=tr("tool.audio_video.wm_frame"), padx=8, pady=8)
        wm_frame.pack(fill="x", padx=4, pady=4)
        wm_frame.columnconfigure(1, weight=1)

        self.watermark_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(wm_frame, text=tr("tool.audio_video.wm_enabled"), variable=self.watermark_enabled_var,
                       font=("Arial", 9, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

        tk.Label(wm_frame, text=tr("tool.audio_video.wm_text_label")).grid(row=1, column=0, padx=4, pady=5, sticky="e")
        self.watermark_text_var = tk.StringVar(value="老猿世界观察")
        tk.Entry(wm_frame, textvariable=self.watermark_text_var, width=26).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=4)

        tk.Label(wm_frame, text=tr("tool.audio_video.wm_color_label")).grid(row=2, column=0, padx=4, pady=5, sticky="e")
        wm_color_f = tk.Frame(wm_frame)
        wm_color_f.grid(row=2, column=1, columnspan=2, sticky="w", padx=4)
        self.watermark_color_var = tk.StringVar(value="#80ffff")
        tk.Entry(wm_color_f, textvariable=self.watermark_color_var, width=9, state='readonly').pack(side=tk.LEFT, padx=2)
        self.wm_color_preview = tk.Canvas(wm_color_f, width=22, height=18, bg="#80ffff",
                                           relief=tk.SUNKEN, borderwidth=1)
        self.wm_color_preview.pack(side=tk.LEFT, padx=2)
        tk.Button(wm_color_f, text=tr("tool.audio_video.pick"), command=self._choose_wm_color, width=7).pack(side=tk.LEFT, padx=2)

        tk.Label(wm_frame, text=tr("tool.audio_video.wm_alpha")).grid(row=3, column=0, padx=4, pady=5, sticky="e")
        self.watermark_opacity_var = tk.DoubleVar(value=0.5)
        tk.Scale(wm_frame, from_=0.1, to=1.0, resolution=0.1, orient=tk.HORIZONTAL,
                 variable=self.watermark_opacity_var, length=180).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=4)

        tk.Label(wm_frame, text=tr("tool.audio_video.wm_position")).grid(row=4, column=0, padx=4, pady=5, sticky="e")
        self.watermark_position_var = tk.StringVar(value=tr("tool.audio_video.wm_pos_topright"))
        ttk.Combobox(wm_frame, textvariable=self.watermark_position_var,
                     values=[tr("tool.audio_video.wm_pos_topright"),
                             tr("tool.audio_video.wm_pos_topleft"),
                             tr("tool.audio_video.wm_pos_bottomright"),
                             tr("tool.audio_video.wm_pos_bottomleft")],
                     state="readonly", width=24).grid(row=4, column=1, columnspan=2, sticky="ew", padx=4)

    # ── 章节管理 ─────────────────────────────────────────────────────────────

    def _on_mousewheel(self, event):
        self._chap_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _add_chapter(self):
        chap = {
            'audio': tk.StringVar(),
            'srt':   tk.StringVar(),
            'image': tk.StringVar(),
            'video': tk.StringVar(),
            'frame': None,
        }
        idx = len(self.chapters) + 1
        frame = tk.LabelFrame(self._chap_inner, text=tr("tool.audio_video.chapter_fmt", idx=idx),
                              padx=8, pady=6, font=("Arial", 9, "bold"))
        frame.pack(fill="x", padx=6, pady=4)
        frame.columnconfigure(1, weight=1)
        chap['frame'] = frame

        all_files = tr("tool.audio_video.filter_all")
        AUDIO_FT = [(tr("tool.audio_video.filter_audio"), "*.mp3 *.wav *.m4a *.aac *.ogg *.flac"), (all_files, "*.*")]
        SRT_FT   = [(tr("tool.audio_video.filter_srt"),  "*.srt"), (all_files, "*.*")]
        IMG_FT   = [(tr("tool.audio_video.filter_image"), "*.jpg *.jpeg *.png *.bmp *.webp"), (all_files, "*.*")]
        VID_FT   = [(tr("tool.audio_video.filter_video"), "*.mp4 *.avi *.mov *.mkv *.webm"), (all_files, "*.*")]

        rows = [
            (0, tr("tool.audio_video.audio_label"),  chap['audio'], AUDIO_FT, ""),
            (1, tr("tool.audio_video.srt_label"),    chap['srt'],   SRT_FT,   tr("tool.audio_video.optional")),
            (2, tr("tool.audio_video.image_label"),  chap['image'], IMG_FT,   tr("tool.audio_video.optional")),
            (3, tr("tool.audio_video.video_label"),  chap['video'], VID_FT,   tr("tool.audio_video.optional_on_image")),
        ]
        for r, lbl, var, ft, hint in rows:
            tk.Label(frame, text=lbl, width=10, anchor="e").grid(
                row=r, column=0, padx=4, pady=3, sticky="e")
            tk.Entry(frame, textvariable=var, width=34, state='readonly').grid(
                row=r, column=1, sticky="ew", padx=4)
            tk.Button(frame, text=tr("tool.audio_video.pick_short"), width=5,
                      command=lambda v=var, f=ft: self._pick_file(v, f)).grid(
                row=r, column=2, padx=2)
            tk.Button(frame, text=tr("tool.audio_video.clear_short"), width=4,
                      command=lambda v=var: v.set("")).grid(row=r, column=3, padx=2)
            if hint:
                tk.Label(frame, text=hint, fg="gray", font=("Arial", 7)).grid(
                    row=r, column=4, sticky="w", padx=2)

        tk.Button(frame, text=tr("tool.audio_video.delete_chapter"), fg="red", font=("Arial", 8),
                  command=lambda c=chap: self._remove_chapter(c)).grid(
            row=4, column=0, columnspan=5, pady=(6, 2))

        self.chapters.append(chap)

    def _remove_chapter(self, chap):
        if len(self.chapters) <= 1:
            return
        chap['frame'].destroy()
        self.chapters.remove(chap)
        for i, c in enumerate(self.chapters):
            c['frame'].config(text=tr("tool.audio_video.chapter_fmt", idx=i + 1))

    def _pick_file(self, var, file_types):
        path = filedialog.askopenfilename(filetypes=file_types)
        if path:
            var.set(path)

    # ── 右侧控件辅助 ──────────────────────────────────────────────────────────

    def _select_video_output(self):
        path = filedialog.asksaveasfilename(
            title=tr("tool.audio_video.output_dialog_title"), defaultextension=".mp4",
            filetypes=[(tr("tool.audio_video.filter_mp4"), "*.mp4"),
                       (tr("tool.audio_video.filter_all"), "*.*")])
        if path:
            self.video_output_var.set(path)

    def _on_orientation(self):
        self._update_resolution()
        ori = self.orientation_var.get()
        d = LAYOUT_DEFAULTS.get(ori, LAYOUT_DEFAULTS["horizontal"])
        self.sub_max_chars_var.set(d["max_chars_zh"])
        self.sub_fontsize_var.set(d["fontsize"])
        self.sub_margin_v_var.set(d["margin_v"])

    def _update_resolution(self):
        if self.orientation_var.get() == "horizontal":
            opts = ["1920x1080 (1080p)", "1280x720 (720p)", "3840x2160 (4K)", "2560x1440 (2K)"]
            default = "1920x1080 (1080p)"
        else:
            opts = ["1080x1920 (1080p)", "720x1280 (720p)",
                    "2160x3840 (4K)", "1440x2560 (2K)"]
            default = "1080x1920 (1080p)"
        self.resolution_combo['values'] = opts
        if self.resolution_var.get() not in opts:
            self.resolution_var.set(default)

    def _choose_bg(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor(title=tr("tool.audio_video.bg_color_title"),
                                  initialcolor=self.bg_color_var.get())
        if c[1]:
            self.bg_color_var.set(c[1]); self.bg_preview.config(bg=c[1])

    def _choose_sub_color(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor(title=tr("tool.audio_video.sub_color_title"),
                                  initialcolor=self.sub_color_var.get())
        if c[1]:
            self.sub_color_var.set(c[1]); self.sub_color_preview.config(bg=c[1])

    def _choose_wm_color(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor(title=tr("tool.audio_video.wm_color_title"),
                                  initialcolor=self.watermark_color_var.get())
        if c[1]:
            self.watermark_color_var.set(c[1]); self.wm_color_preview.config(bg=c[1])

    # ── 合成逻辑 ──────────────────────────────────────────────────────────────

    def _start(self):
        mb = __import__('tkinter').messagebox
        for i, c in enumerate(self.chapters):
            audio = c['audio'].get().strip()
            if not audio or not os.path.exists(audio):
                mb.showerror(tr("dialog.common.error"),
                             tr("tool.audio_video.error_no_audio_chapter", idx=i + 1))
                return
        output = self.video_output_var.get().strip()
        if not output:
            mb.showerror(tr("dialog.common.error"), tr("tool.audio_video.error_no_output"))
            return
        self._stop_flag = False
        self.generate_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress_var.set(0)
        self.status_var.set(tr("tool.audio_video.status_preparing"))
        self.set_busy()
        threading.Thread(target=self._generate, args=(output,), daemon=True).start()

    def _stop(self):
        self._stop_flag = True
        if self._ffmpeg_proc and self._ffmpeg_proc.poll() is None:
            self._ffmpeg_proc.terminate()
        self.status_var.set(tr("tool.audio_video.status_stopping"))

    def _generate(self, output):
        import re as _re
        tmp_segments = []   # temp video files per chapter
        tmp_srts = []       # 分割后的中间 SRT 文件（保留，不删除）
        try:
            res_str = self.resolution_var.get().split(" ")[0]
            width, height = map(int, res_str.split('x'))
            fps = int(self.fps_var.get())
            codec = self.codec_var.get().split(" ")[0]
            bg_hex = self._hex_to_ffmpeg(self.bg_color_var.get())
            orientation = self.orientation_var.get()

            subtitle_style = build_subtitle_style(
                orientation=orientation,
                fontsize=self.sub_fontsize_var.get(),
                color=self.sub_color_var.get(),
                margin_v=self.sub_margin_v_var.get(),
            )
            watermark_filter = (self._build_watermark(height)
                                if self.watermark_enabled_var.get() else None)

            total = len(self.chapters)
            for i, chap in enumerate(self.chapters):
                if self._stop_flag:
                    self.status_var.set(tr("tool.audio_video.status_stopped")); return

                self.status_var.set(tr("tool.audio_video.status_chapter_progress", i=i + 1, total=total))
                base_pct = i / total * 95

                audio = chap['audio'].get().strip()
                srt   = chap['srt'].get().strip()
                image = chap['image'].get().strip()
                video = chap['video'].get().strip()

                duration = self._get_duration(audio)
                if duration <= 0:
                    raise RuntimeError(tr("tool.audio_video.error_chapter_duration", i=i + 1))

                # Handle subtitle line wrap split
                burn_srt = None
                if srt and os.path.exists(srt):
                    burn_srt = srt
                    if self.sub_split_var.get():
                        tmp_srt = srt.replace('.srt', f'_split_ch{i}.srt')
                        try:
                            split_srt_to_file(srt,
                                              max_chars=self.sub_max_chars_var.get(),
                                              is_chinese=self.sub_is_chinese_var.get(),
                                              output_path=tmp_srt)
                            burn_srt = tmp_srt
                            tmp_srts.append(tmp_srt)
                        except Exception as e:
                            self.status_var.set(tr("tool.audio_video.error_chapter_split", i=i + 1, e=e))

                # 临时输出文件
                tmp_f = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
                tmp_f.close()
                tmp_segments.append(tmp_f.name)

                cmd = self._build_chapter_cmd(
                    audio=audio,
                    image=image if image and os.path.exists(image) else None,
                    bg_video=video if video and os.path.exists(video) else None,
                    srt=burn_srt,
                    width=width, height=height, fps=fps, codec=codec,
                    bg_hex=bg_hex, duration=duration,
                    subtitle_style=subtitle_style,
                    watermark_filter=watermark_filter,
                    output=tmp_f.name,
                )

                self._ffmpeg_proc = subprocess.Popen(
                    cmd, stderr=subprocess.PIPE, text=True,
                    encoding='utf-8', errors='replace')

                for line in self._ffmpeg_proc.stderr:
                    if self._stop_flag:
                        self._ffmpeg_proc.terminate()
                        self.status_var.set(tr("tool.audio_video.status_stopped")); return
                    m = _re.search(r'time=(\d+):(\d+):([\d.]+)', line)
                    if m and duration > 0:
                        elapsed = (int(m.group(1)) * 3600 +
                                   int(m.group(2)) * 60 + float(m.group(3)))
                        self.progress_var.set(
                            base_pct + min(1.0, elapsed / duration) / total * 95)

                self._ffmpeg_proc.wait()
                if self._ffmpeg_proc.returncode != 0:
                    raise RuntimeError(tr("tool.audio_video.error_chapter_ffmpeg", i=i + 1))

            if self._stop_flag:
                return

            # Merge all chapters
            if len(tmp_segments) == 1:
                import shutil
                shutil.copy2(tmp_segments[0], output)
            else:
                self.status_var.set(tr("tool.audio_video.status_merging", total=total))
                self.progress_var.set(96)
                self._concat_videos(tmp_segments, output)

            self.progress_var.set(100)
            self.status_var.set(tr("tool.audio_video.status_done", total=total, output=output))
            self.set_done()
            __import__('tkinter').messagebox.showinfo(
                tr("tool.audio_video.success_title"),
                tr("tool.audio_video.success_msg", output=output))

        except Exception as e:
            self.status_var.set(tr("tool.audio_video.status_fail"))
            self.set_error(tr("tool.audio_video.error_compose_failed", e=e))
            __import__('tkinter').messagebox.showerror(
                tr("dialog.common.error"),
                tr("tool.audio_video.error_dialog_compose", e=e))
        finally:
            self.master.after(0, lambda: self.generate_btn.config(state="normal"))
            self.master.after(0, lambda: self.stop_btn.config(state="disabled"))
            self._ffmpeg_proc = None
            for f in tmp_segments:
                try: os.unlink(f)
                except Exception as cleanup_e:
                    logger.error(f"Failed to clean up temp file {f}: {cleanup_e}")
            # Split SRTs are kept as intermediate artifacts (not removed)

    def _build_chapter_cmd(self, audio, image, bg_video, srt, width, height,
                            fps, codec, bg_hex, duration, subtitle_style,
                            watermark_filter, output):
        """为单个章节构建 ffmpeg 命令列表。

        图层顺序：背景图（底） → 背景视频（叠上） → 字幕 → 水印
        """
        scale_pad = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                     f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={bg_hex}")

        if image and bg_video:
            # 两路视觉输入：[0]=bg_image  [1]=bg_video  [2]=audio
            inputs = [
                'ffmpeg',
                '-loop', '1', '-t', str(duration), '-i', image,
                '-stream_loop', '-1', '-i', bg_video,
                '-i', audio,
            ]
            fc = [
                f"[0:v]{scale_pad}[base]",
                (f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                 f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2[ov]"),
                "[base][ov]overlay=0:0[v0]",
            ]
            last, cnt = "v0", 1
            if srt:
                srt_ff = escape_ffmpeg_path(srt)
                nxt = f"v{cnt}"; cnt += 1
                fc.append(f"[{last}]subtitles='{srt_ff}':force_style='{subtitle_style}'[{nxt}]")
                last = nxt
            if watermark_filter:
                nxt = f"v{cnt}"
                fc.append(f"[{last}]{watermark_filter}[{nxt}]")
                last = nxt
            return inputs + [
                '-filter_complex', ';'.join(fc),
                '-map', f'[{last}]', '-map', '2:a',
                '-c:v', codec, '-c:a', 'aac', '-b:a', '192k',
                '-r', str(fps), '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', '-t', str(duration), '-y', output,
            ]

        elif image:
            # 仅背景图
            inputs = ['ffmpeg', '-loop', '1', '-t', str(duration), '-i', image, '-i', audio]
            vf = [scale_pad]
            if srt:
                srt_ff = escape_ffmpeg_path(srt)
                vf.append(f"subtitles='{srt_ff}':force_style='{subtitle_style}'")
            if watermark_filter:
                vf.append(watermark_filter)
            return inputs + [
                '-vf', ','.join(vf),
                '-map', '0:v', '-map', '1:a',
                '-c:v', codec, '-c:a', 'aac', '-b:a', '192k',
                '-r', str(fps), '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', '-y', output,
            ]

        elif bg_video:
            # 仅背景视频（循环到音频时长）
            inputs = ['ffmpeg', '-stream_loop', '-1', '-i', bg_video, '-i', audio]
            vf = [scale_pad]
            if srt:
                srt_ff = escape_ffmpeg_path(srt)
                vf.append(f"subtitles='{srt_ff}':force_style='{subtitle_style}'")
            if watermark_filter:
                vf.append(watermark_filter)
            return inputs + [
                '-vf', ','.join(vf),
                '-map', '0:v', '-map', '1:a',
                '-c:v', codec, '-c:a', 'aac', '-b:a', '192k',
                '-r', str(fps), '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', '-t', str(duration), '-y', output,
            ]

        else:
            # 纯色背景
            inputs = ['ffmpeg',
                      '-f', 'lavfi',
                      '-i', f'color=c={bg_hex}:s={width}x{height}:r={fps}',
                      '-i', audio]
            vf = []
            if srt:
                srt_ff = escape_ffmpeg_path(srt)
                vf.append(f"subtitles='{srt_ff}':force_style='{subtitle_style}'")
            if watermark_filter:
                vf.append(watermark_filter)
            cmd = inputs
            if vf:
                cmd = cmd + ['-vf', ','.join(vf)]
            return cmd + [
                '-map', '0:v', '-map', '1:a',
                '-c:v', codec, '-c:a', 'aac', '-b:a', '192k',
                '-r', str(fps), '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', '-t', str(duration), '-y', output,
            ]

    def _concat_videos(self, files, output):
        lf = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8')
        for f in files:
            lf.write(f"file '{f}'\n")
        lf.close()
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                 '-i', lf.name, '-c', 'copy', output],
                capture_output=True, check=True)
        finally:
            os.unlink(lf.name)

    def _get_duration(self, path):
        try:
            r = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', path],
                capture_output=True, encoding="utf-8", errors="replace", check=True)
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    def _hex_to_ffmpeg(self, hex_color):
        h = hex_color.lstrip('#')
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        return f"0x{h.upper()}"

    def _build_watermark(self, height):
        text = self.watermark_text_var.get().strip()
        if not text:
            return None
        color = self.watermark_color_var.get().lstrip('#')
        font_size = int(36 * height / 1080)
        opacity = self.watermark_opacity_var.get()
        pos_raw = self.watermark_position_var.get()
        pos = pos_raw.split('(')[1].split(')')[0] if '(' in pos_raw else pos_raw
        margin = int(30 * height / 1080)
        coords = {
            "topright":    (f"w-tw-{margin}", str(margin)),
            "topleft":     (str(margin), str(margin)),
            "bottomright": (f"w-tw-{margin}", f"h-th-{margin}"),
            "bottomleft":  (str(margin), f"h-th-{margin}"),
        }
        x, y = coords.get(pos, coords["topright"])
        escaped = text.replace(":", "\\:").replace("'", "")
        return (f"drawtext=text='{escaped}':fontcolor={color}@{opacity}:"
                f"fontsize={font_size}:font='Microsoft YaHei':x={x}:y={y}:"
                f"borderw=2:bordercolor=black")


# ── 每日要闻合成 ─────────────────────────────────────────────────────────────

_NEWS_RESOLUTIONS = {
    "horizontal": ["1920x1080 (1080p)", "1280x720 (720p)"],
    "vertical":   ["1080x1920 (1080p)", "720x1280 (720p)"],
}


class DailyNewsApp(ToolBase):
    """
    每日要闻合成：音频 + 背景图 + 稿子文字(.txt)滚动 → 视频。
    文字在屏幕中间区域（1/4 ~ 3/4）匀速向上滚动，时长与音频同步。
    """

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.daily_news.title"))
        master.geometry("700x640")
        self._ffmpeg_proc = None
        self.progress_var = tk.DoubleVar(value=0)
        self.status_var   = tk.StringVar(value=tr("tool.daily_news.status_ready"))
        self._build_ui()
        if initial_file and os.path.exists(initial_file):
            self.audio_path_var.set(initial_file)

    def _build_ui(self):
        f = self.master
        pad = {"padx": 8, "pady": 4}

        # ── File selection ──
        files = tk.LabelFrame(f, text=tr("tool.daily_news.files_frame"), padx=8, pady=6)
        files.pack(fill="x", **pad)
        files.columnconfigure(1, weight=1)

        def file_row(parent, row, label, var, cmd):
            tk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=4, pady=5)
            tk.Entry(parent, textvariable=var, width=44).grid(row=row, column=1, sticky="ew", padx=4)
            tk.Button(parent, text=tr("tool.daily_news.browse"), width=6, command=cmd).grid(row=row, column=2, padx=4)

        self.audio_path_var  = tk.StringVar()
        self.image_path_var  = tk.StringVar()
        self.script_path_var = tk.StringVar()
        self.output_var      = tk.StringVar(value="daily_news.mp4")
        file_row(files, 0, tr("tool.daily_news.audio_file"),   self.audio_path_var,  self._sel_audio)
        file_row(files, 1, tr("tool.daily_news.bg_image"),     self.image_path_var,  self._sel_image)
        file_row(files, 2, tr("tool.daily_news.script_file"),  self.script_path_var, self._sel_script)
        file_row(files, 3, tr("tool.daily_news.output_video"), self.output_var,      self._sel_output)

        # ── Script preview ──
        preview = tk.LabelFrame(f, text=tr("tool.daily_news.preview_frame"), padx=6, pady=4)
        preview.pack(fill="both", expand=True, **pad)
        vsb = tk.Scrollbar(preview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.script_preview = tk.Text(preview, height=7, wrap=tk.WORD,
                                      font=("Microsoft YaHei", 10),
                                      state="disabled", yscrollcommand=vsb.set,
                                      bg="#f8f8f8")
        self.script_preview.pack(fill="both", expand=True)
        vsb.config(command=self.script_preview.yview)

        # ── Layout settings ──
        cfg = tk.LabelFrame(f, text=tr("tool.daily_news.layout_frame"), padx=8, pady=6)
        cfg.pack(fill="x", **pad)
        cfg.columnconfigure(1, weight=1)
        cfg.columnconfigure(3, weight=1)

        # Orientation + resolution
        tk.Label(cfg, text=tr("tool.daily_news.orientation")).grid(row=0, column=0, sticky="e", padx=4, pady=4)
        ori_f = tk.Frame(cfg)
        ori_f.grid(row=0, column=1, sticky="w", padx=4)
        self.orientation_var = tk.StringVar(value="vertical")
        tk.Radiobutton(ori_f, text=tr("tool.daily_news.horizontal_label"), variable=self.orientation_var,
                       value="horizontal", command=self._on_orientation).pack(side=tk.LEFT)
        tk.Radiobutton(ori_f, text=tr("tool.daily_news.vertical_label"), variable=self.orientation_var,
                       value="vertical", command=self._on_orientation).pack(side=tk.LEFT, padx=8)

        tk.Label(cfg, text=tr("tool.daily_news.resolution")).grid(row=0, column=2, sticky="e", padx=4)
        self.resolution_var = tk.StringVar(value=_NEWS_RESOLUTIONS["vertical"][0])
        self.resolution_combo = ttk.Combobox(cfg, textvariable=self.resolution_var,
                                             values=_NEWS_RESOLUTIONS["vertical"],
                                             state="readonly", width=18)
        self.resolution_combo.grid(row=0, column=3, sticky="w", padx=4)

        tk.Label(cfg, text=tr("tool.daily_news.fps")).grid(row=1, column=0, sticky="e", padx=4, pady=4)
        self.fps_var = tk.StringVar(value="30")
        ttk.Combobox(cfg, textvariable=self.fps_var, values=["24", "25", "30"],
                     state="readonly", width=6).grid(row=1, column=1, sticky="w", padx=4)

        tk.Label(cfg, text=tr("tool.daily_news.fontsize")).grid(row=1, column=2, sticky="e", padx=4)
        self.fontsize_var = tk.IntVar(value=48)
        tk.Spinbox(cfg, textvariable=self.fontsize_var, from_=16, to=80,
                   width=6).grid(row=1, column=3, sticky="w", padx=4)

        tk.Label(cfg, text=tr("tool.daily_news.line_gap")).grid(row=2, column=0, sticky="e", padx=4, pady=4)
        self.line_spacing_var = tk.IntVar(value=12)
        tk.Spinbox(cfg, textvariable=self.line_spacing_var, from_=0, to=60,
                   width=6).grid(row=2, column=1, sticky="w", padx=4)

        # Font color
        tk.Label(cfg, text=tr("tool.daily_news.font_color")).grid(row=2, column=2, sticky="e", padx=4)
        color_f = tk.Frame(cfg)
        color_f.grid(row=2, column=3, sticky="w", padx=4)
        self.font_color_var = tk.StringVar(value="#FF8C00")
        self._color_preview = tk.Canvas(color_f, width=22, height=18, bg="#FF8C00",
                                        relief=tk.SUNKEN, borderwidth=1)
        self._color_preview.pack(side=tk.LEFT, padx=2)
        tk.Entry(color_f, textvariable=self.font_color_var, width=9,
                 state='readonly').pack(side=tk.LEFT)
        tk.Button(color_f, text=tr("tool.daily_news.pick"), width=5,
                  command=self._choose_color).pack(side=tk.LEFT, padx=4)

        # Background fill
        tk.Label(cfg, text=tr("tool.daily_news.bg_fill")).grid(row=3, column=0, sticky="e", padx=4, pady=4)
        bg_f = tk.Frame(cfg)
        bg_f.grid(row=3, column=1, sticky="w", padx=4)
        self.bg_color_var = tk.StringVar(value="#000000")
        self._bg_preview = tk.Canvas(bg_f, width=22, height=18, bg="#000000",
                                     relief=tk.SUNKEN, borderwidth=1)
        self._bg_preview.pack(side=tk.LEFT, padx=2)
        tk.Entry(bg_f, textvariable=self.bg_color_var, width=9,
                 state='readonly').pack(side=tk.LEFT)
        tk.Button(bg_f, text=tr("tool.daily_news.pick"), width=5,
                  command=self._choose_bg).pack(side=tk.LEFT, padx=4)

        # Text background + alpha
        tk.Label(cfg, text=tr("tool.daily_news.text_bg")).grid(row=3, column=2, sticky="e", padx=4, pady=4)
        txtbg_f = tk.Frame(cfg)
        txtbg_f.grid(row=3, column=3, sticky="w", padx=4)
        self.text_bg_color_var = tk.StringVar(value="#AAAAAA")
        self._text_bg_preview = tk.Canvas(txtbg_f, width=22, height=18, bg="#AAAAAA",
                                          relief=tk.SUNKEN, borderwidth=1)
        self._text_bg_preview.pack(side=tk.LEFT, padx=2)
        tk.Entry(txtbg_f, textvariable=self.text_bg_color_var, width=9,
                 state='readonly').pack(side=tk.LEFT)
        tk.Button(txtbg_f, text=tr("tool.daily_news.pick"), width=5,
                  command=self._choose_text_bg).pack(side=tk.LEFT, padx=4)

        tk.Label(cfg, text=tr("tool.daily_news.text_bg_alpha")).grid(row=4, column=0, sticky="e", padx=4, pady=4)
        alpha_f = tk.Frame(cfg)
        alpha_f.grid(row=4, column=1, columnspan=3, sticky="w", padx=4)
        self.text_bg_alpha_var = tk.IntVar(value=50)
        tk.Scale(alpha_f, variable=self.text_bg_alpha_var, from_=0, to=100,
                 orient=tk.HORIZONTAL, length=160, resolution=5).pack(side=tk.LEFT)
        tk.Label(alpha_f, text=tr("tool.daily_news.alpha_hint"),
                 fg="gray", font=("Arial", 8)).pack(side=tk.LEFT, padx=6)

        # Watermark
        tk.Label(cfg, text=tr("tool.daily_news.wm_text")).grid(row=5, column=0, sticky="e", padx=4, pady=4)
        wm_left = tk.Frame(cfg)
        wm_left.grid(row=5, column=1, columnspan=3, sticky="w", padx=4)
        self.watermark_var = tk.StringVar(value="DailyLeaders")
        tk.Entry(wm_left, textvariable=self.watermark_var, width=20).pack(side=tk.LEFT, padx=2)
        tk.Label(wm_left, text=tr("tool.daily_news.wm_color_label"), fg="gray").pack(side=tk.LEFT, padx=(10, 2))
        self.wm_color_var = tk.StringVar(value="#ADD8E6")
        self._wm_preview  = tk.Canvas(wm_left, width=22, height=18, bg="#ADD8E6",
                                      relief=tk.SUNKEN, borderwidth=1)
        self._wm_preview.pack(side=tk.LEFT, padx=2)
        tk.Entry(wm_left, textvariable=self.wm_color_var, width=9,
                 state='readonly').pack(side=tk.LEFT)
        tk.Button(wm_left, text=tr("tool.daily_news.pick"), width=5,
                  command=self._choose_wm_color).pack(side=tk.LEFT, padx=4)
        tk.Label(wm_left, text=tr("tool.daily_news.wm_fontsize"), fg="gray").pack(side=tk.LEFT, padx=(10, 2))
        self.wm_fontsize_var = tk.IntVar(value=72)
        tk.Spinbox(wm_left, textvariable=self.wm_fontsize_var,
                   from_=16, to=200, width=5).pack(side=tk.LEFT)
        tk.Label(wm_left, text=tr("tool.daily_news.wm_hint"),
                 fg="gray", font=("Arial", 8)).pack(side=tk.LEFT, padx=4)

        # ── Progress + buttons ──
        ctrl = tk.Frame(f)
        ctrl.pack(fill="x", padx=8, pady=4)
        self.generate_btn = tk.Button(ctrl, text=tr("tool.daily_news.btn_start"), bg="#0078d4", fg="white",
                                      font=("Arial", 10, "bold"), width=12,
                                      command=self._start)
        self.generate_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = tk.Button(ctrl, text=tr("tool.daily_news.btn_stop"), width=8, state="disabled",
                                  command=self._stop)
        self.stop_btn.pack(side=tk.LEFT, padx=4)
        tk.Label(ctrl, textvariable=self.status_var, fg="gray").pack(side=tk.LEFT, padx=8)

        ttk.Progressbar(f, variable=self.progress_var, maximum=100).pack(
            fill="x", padx=8, pady=(0, 8))

    # ── 方向切换 ──

    def _on_orientation(self):
        ori = self.orientation_var.get()
        opts = _NEWS_RESOLUTIONS[ori]
        self.resolution_combo['values'] = opts
        self.resolution_var.set(opts[0])
        self.fontsize_var.set(38 if ori == "horizontal" else 32)

    # ── 文件选择 ──

    def _sel_audio(self):
        p = filedialog.askopenfilename(
            title=tr("tool.daily_news.dialog_audio"),
            filetypes=[("Audio", "*.mp3;*.wav;*.m4a;*.aac"), ("All", "*.*")])
        if p:
            self.audio_path_var.set(p)
            base = os.path.splitext(p)[0]
            self.output_var.set(base + "_news.mp4")

    def _sel_image(self):
        p = filedialog.askopenfilename(
            title=tr("tool.daily_news.dialog_image"),
            filetypes=[("Image", "*.jpg;*.jpeg;*.png;*.bmp"), ("All", "*.*")])
        if p:
            self.image_path_var.set(p)

    def _sel_script(self):
        p = filedialog.askopenfilename(
            title=tr("tool.daily_news.dialog_script"),
            filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if p:
            self.script_path_var.set(p)
            try:
                with open(p, encoding='utf-8') as fh:
                    content = fh.read()
            except UnicodeDecodeError:
                with open(p, encoding='gbk', errors='replace') as fh:
                    content = fh.read()
            self.script_preview.config(state='normal')
            self.script_preview.delete('1.0', tk.END)
            self.script_preview.insert('1.0', content)
            self.script_preview.config(state='disabled')

    def _sel_output(self):
        p = filedialog.asksaveasfilename(
            title=tr("tool.daily_news.dialog_save"), defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4")])
        if p:
            self.output_var.set(p)

    def _choose_color(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor(color=self.font_color_var.get(),
                                  title=tr("tool.daily_news.dialog_font_color"))[1]
        if c:
            self.font_color_var.set(c)
            self._color_preview.configure(bg=c)

    def _choose_bg(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor(color=self.bg_color_var.get(),
                                  title=tr("tool.daily_news.dialog_bg_fill"))[1]
        if c:
            self.bg_color_var.set(c)
            self._bg_preview.configure(bg=c)

    def _choose_text_bg(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor(color=self.text_bg_color_var.get(),
                                  title=tr("tool.daily_news.dialog_text_bg"))[1]
        if c:
            self.text_bg_color_var.set(c)
            self._text_bg_preview.configure(bg=c)

    def _choose_wm_color(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor(color=self.wm_color_var.get(),
                                  title=tr("tool.daily_news.dialog_wm_color"))[1]
        if c:
            self.wm_color_var.set(c)
            self._wm_preview.configure(bg=c)

    # ── 合成逻辑 ──

    def _start(self):
        audio       = self.audio_path_var.get().strip()
        image       = self.image_path_var.get().strip()
        script_path = self.script_path_var.get().strip()
        output      = self.output_var.get().strip()
        mb = __import__('tkinter').messagebox
        if not audio or not os.path.exists(audio):
            mb.showerror(tr("dialog.common.error"), tr("tool.daily_news.error_no_audio")); return
        if not image or not os.path.exists(image):
            mb.showerror(tr("dialog.common.error"), tr("tool.daily_news.error_no_image")); return
        if not script_path or not os.path.exists(script_path):
            mb.showerror(tr("dialog.common.error"), tr("tool.daily_news.error_no_script")); return
        if not output:
            mb.showerror(tr("dialog.common.error"), tr("tool.daily_news.error_no_output")); return
        # Read script
        try:
            with open(script_path, encoding='utf-8') as fh:
                script = fh.read().strip()
        except UnicodeDecodeError:
            with open(script_path, encoding='gbk', errors='replace') as fh:
                script = fh.read().strip()
        if not script:
            mb.showerror(tr("dialog.common.error"), tr("tool.daily_news.error_empty_script")); return
        self.generate_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress_var.set(0)
        self.status_var.set(tr("tool.daily_news.status_preparing"))
        self.set_busy()
        threading.Thread(target=self._generate,
                         args=(audio, image, output, script), daemon=True).start()

    def _stop(self):
        if self._ffmpeg_proc and self._ffmpeg_proc.poll() is None:
            self._ffmpeg_proc.terminate()
            self.status_var.set(tr("tool.daily_news.status_stopped"))

    def _get_duration(self, path):
        try:
            r = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', path],
                capture_output=True, encoding="utf-8", errors="replace", check=True)
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    def _add_watermark(self, base_img, text, color_hex, fontsize_wm, margin=20):
        """在 base_img 右上角绘制水印（黑色描边）。"""
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(base_img)
        font = None
        for fp in ["C:/Windows/Fonts/msyhbd.ttc",
                   "C:/Windows/Fonts/msyh.ttc",
                   "C:/Windows/Fonts/arialbd.ttf",
                   "C:/Windows/Fonts/arial.ttf"]:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, fontsize_wm)
                    break
                except Exception:
                    continue
        if font is None:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x  = base_img.width - tw - margin
        y  = margin
        r  = int(color_hex.lstrip('#')[0:2], 16)
        g  = int(color_hex.lstrip('#')[2:4], 16)
        b  = int(color_hex.lstrip('#')[4:6], 16)
        # 描边
        for dx, dy in [(-2,0),(2,0),(0,-2),(0,2),(-1,-1),(1,1),(-1,1),(1,-1)]:
            draw.text((x+dx, y+dy), text, font=font, fill=(0, 0, 0, 220))
        draw.text((x, y), text, font=font, fill=(r, g, b, 255))
        return base_img

    def _render_scroll_image(self, script, width, fontsize, line_gap, font_color_hex,
                              text_bg_hex="#AAAAAA", text_bg_alpha=50):
        """
        用 PIL 把稿子渲染为一张透明 PNG（宽=视频宽，高=文字总高度）。
        左右各留 10% 边距，自动按像素宽度换行。
        返回 (临时文件路径, 图片总高度px)。
        """
        from PIL import Image, ImageDraw, ImageFont
        import tempfile

        margin_x   = int(width * 0.10)
        text_area_w = int(width * 0.80)
        line_height = fontsize + line_gap

        # 加载字体
        font = None
        for fp in ["C:/Windows/Fonts/msyh.ttc",
                   "C:/Windows/Fonts/msyhbd.ttc",
                   "C:/Windows/Fonts/simhei.ttf"]:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, fontsize)
                    break
                except Exception:
                    continue
        if font is None:
            font = ImageFont.load_default()

        # 用 PIL 度量宽度来精确换行（支持中英文混排）
        dummy = Image.new('RGBA', (1, 1))
        draw_dummy = ImageDraw.Draw(dummy)

        def measure_w(s):
            bbox = draw_dummy.textbbox((0, 0), s, font=font)
            return bbox[2] - bbox[0]

        lines = []
        for para in script.splitlines():
            para = para.strip()
            if not para:
                lines.append("")
                continue
            cur = ""
            for ch in para:
                test = cur + ch
                if measure_w(test) > text_area_w and cur:
                    lines.append(cur)
                    cur = ch
                else:
                    cur = test
            if cur:
                lines.append(cur)

        img_h = max(len(lines) * line_height + line_gap, 1)
        img = Image.new('RGBA', (width, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        r = int(font_color_hex[0:2], 16)
        g = int(font_color_hex[2:4], 16)
        b = int(font_color_hex[4:6], 16)

        # 文字背景矩形
        br = int(text_bg_hex.lstrip('#')[0:2], 16)
        bg_g = int(text_bg_hex.lstrip('#')[2:4], 16)
        bb = int(text_bg_hex.lstrip('#')[4:6], 16)
        bg_a = int(text_bg_alpha / 100 * 255)
        if bg_a > 0:
            pad = line_gap
            bg_layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
            bg_draw  = ImageDraw.Draw(bg_layer)
            bg_draw.rectangle(
                [margin_x - pad, 0, margin_x + text_area_w + pad, img_h],
                fill=(br, bg_g, bb, bg_a)
            )
            img = Image.alpha_composite(img, bg_layer)
            draw = ImageDraw.Draw(img)

        for i, line in enumerate(lines):
            if not line:
                continue
            y = i * line_height + line_gap
            # 描边/阴影
            for dx, dy in [(-2,0),(2,0),(0,-2),(0,2),(-1,-1),(1,1),(-1,1),(1,-1)]:
                draw.text((margin_x + dx, y + dy), line, font=font, fill=(0, 0, 0, 160))
            draw.text((margin_x, y), line, font=font, fill=(r, g, b, 255))

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='_scroll.png')
        tmp.close()
        img.save(tmp.name, 'PNG')
        return tmp.name, img_h

    def _generate(self, audio, image, output, script):
        tmp_png = None
        try:
            res_str = self.resolution_var.get().split(" ")[0]
            width, height = map(int, res_str.split("x"))
            fps        = int(self.fps_var.get())
            fontsize   = self.fontsize_var.get()
            line_gap   = self.line_spacing_var.get()
            font_color = self.font_color_var.get().lstrip('#')
            bg_color   = self.bg_color_var.get().lstrip('#')

            total_dur = self._get_duration(audio)
            if total_dur <= 0:
                raise RuntimeError(tr("tool.daily_news.error_no_duration"))

            text_bg_color = self.text_bg_color_var.get().lstrip('#')
            text_bg_alpha = self.text_bg_alpha_var.get()
            wm_text       = self.watermark_var.get().strip()
            wm_color      = self.wm_color_var.get()
            wm_fontsize   = self.wm_fontsize_var.get()

            # Render text layer via PIL
            self.status_var.set(tr("tool.daily_news.status_rendering_layer"))
            tmp_png, text_h = self._render_scroll_image(
                script, width, fontsize, line_gap, font_color,
                text_bg_hex=text_bg_color, text_bg_alpha=text_bg_alpha)

            # 滚动范围：文字顶部从 3H/4 进入，全部滚出 H/4 上方
            # 总位移 = H/2 + text_h，速度 = 总位移 / 时长
            total_disp = height * 0.5 + text_h
            speed      = total_disp / total_dur
            # overlay y 表达式（eval=frame 使 t 在每帧更新）
            y_expr = f"{height * 3 // 4} - t*{speed:.4f}"

            bg_hex    = f"0x{bg_color.upper()}"
            bg_filter = (f"[0:v]scale={width}:{height}:"
                         f"force_original_aspect_ratio=decrease,"
                         f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:"
                         f"color={bg_hex}[bg]")
            ov_filter = f"[bg][1:v]overlay=0:'{y_expr}':eval=frame[out]"

            # 水印（固定右上角，不跟着滚动）
            if wm_text:
                wm_color_hex = wm_color.lstrip('#')
                wm_fs = wm_fontsize
                margin_wm = max(16, int(width * 0.02))
                wm_esc = wm_text.replace(":", "\\:").replace("'", "")
                wm_filter = (
                    f"[out]drawtext=text='{wm_esc}':"
                    f"font='Microsoft YaHei':"
                    f"fontsize={wm_fs}:"
                    f"fontcolor=0x{wm_color_hex.upper()}:"
                    f"x=w-tw-{margin_wm}:y={margin_wm}:"
                    f"borderw=2:bordercolor=black[v]"
                )
                filter_complex = f"{bg_filter};{ov_filter};{wm_filter}"
            else:
                filter_complex = f"{bg_filter};{ov_filter.replace('[out]','[v]')}"

            cmd = [
                'ffmpeg',
                '-loop', '1', '-i', image,    # 0: 背景图
                '-i', tmp_png,                  # 1: 文字 PNG
                '-i', audio,                    # 2: 音频
                '-filter_complex', filter_complex,
                '-map', '[v]', '-map', '2:a',
                '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k',
                '-shortest', '-r', str(fps), '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', '-y', output,
            ]

            self.status_var.set(tr("tool.daily_news.status_composing"))
            import re as _re
            self._ffmpeg_proc = subprocess.Popen(
                cmd, stderr=subprocess.PIPE, text=True,
                encoding='utf-8', errors='replace')
            for line in self._ffmpeg_proc.stderr:
                m = _re.search(r'time=(\d+):(\d+):([\d.]+)', line)
                if m and total_dur > 0:
                    elapsed = (int(m.group(1)) * 3600 +
                               int(m.group(2)) * 60 +
                               float(m.group(3)))
                    self.progress_var.set(min(99, elapsed / total_dur * 100))
            self._ffmpeg_proc.wait()
            if self._ffmpeg_proc.returncode != 0:
                raise RuntimeError(tr("tool.daily_news.error_ffmpeg_exit"))

            self.progress_var.set(100)
            self.status_var.set(tr("tool.daily_news.status_done", output=output))
            self.set_done()
            __import__('tkinter').messagebox.showinfo(
                tr("tool.daily_news.dialog_done_title"),
                tr("tool.daily_news.dialog_done_msg", output=output))

        except Exception as e:
            self.status_var.set(tr("tool.daily_news.status_fail"))
            self.set_error(tr("tool.daily_news.error_compose_failed", e=e))
            __import__('tkinter').messagebox.showerror(
                tr("dialog.common.error"),
                tr("tool.daily_news.error_dialog_compose", e=e))
        finally:
            self.master.after(0, lambda: self.generate_btn.config(state="normal"))
            self.master.after(0, lambda: self.stop_btn.config(state="disabled"))
            self._ffmpeg_proc = None
            if tmp_png and os.path.exists(tmp_png):
                try:
                    os.unlink(tmp_png)
                except Exception as cleanup_e:
                    logger.error(f"Failed to clean up temp PNG {tmp_png}: {cleanup_e}")


# ── 兼容旧入口（Hub 直接引用 Text2VideoApp 时不报错）──────────────────────────
Text2VideoApp = TTSApp


if __name__ == "__main__":
    import sys
    tool = sys.argv[1] if len(sys.argv) > 1 else "tts"
    root = tk.Tk()
    if tool == "srt":
        SRTFromTextApp(root)
    elif tool == "video":
        AudioVideoApp(root)
    else:
        TTSApp(root)
    root.mainloop()
