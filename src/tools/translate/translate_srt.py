import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from tools.base import ToolBase
from hub_logger import logger
from core.ai.errors import AIError
from ui.ai_error_dialog import show_ai_error

# Per architecture principle 1, the UI does not import core.ai directly;
# the actual AI call happens inside core.translate. Routing (which model
# to use for translation) is configured in the AI Console matrix.
from core.translate import (
    SUPPORTED_LANGUAGES,
    get_language_options,
    get_lang_code,
    translate_srt_file,
)

# 尝试导入pydub，如果不可用则设置为None
# 注意：split_audio_by_size 为未来音频处理功能预留，当前未使用
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    AudioSegment = None
    PYDUB_AVAILABLE = False


def split_audio_by_size(audio_path, max_size_kb=100):
    """按文件大小分割音频，确保每段不超过max_size_kb KB"""
    if not PYDUB_AVAILABLE:
        raise ImportError("pydub不可用，无法进行音频分割。请安装pydub: pip install pydub")

    audio = AudioSegment.from_file(audio_path)
    max_size_bytes = max_size_kb * 1024

    # 估算每秒音频大小（粗略）
    sample_rate = audio.frame_rate
    channels = audio.channels
    bytes_per_second = sample_rate * channels * 2  # 16-bit

    # 计算段长（秒）
    segment_length_sec = max_size_bytes / bytes_per_second
    segment_length_ms = int(segment_length_sec * 1000)

    # 确保不小于1秒
    segment_length_ms = max(segment_length_ms, 1000)

    segments = []
    duration_ms = len(audio)

    for i in range(0, duration_ms, segment_length_ms):
        start_time = i
        end_time = min(i + segment_length_ms, duration_ms)

        # 提取段
        segment = audio[start_time:end_time]

        # 检查实际大小，如果仍超过限制，进一步分割
        temp_path = f"temp_segment_{i//segment_length_ms}.wav"
        segment.export(temp_path, format="wav")

        actual_size = os.path.getsize(temp_path)
        if actual_size > max_size_bytes:
            # 如果仍大，进一步分割成更小段
            sub_segments = split_audio_by_size(temp_path, max_size_kb // 2)
            segments.extend(sub_segments)
            os.remove(temp_path)
        else:
            segments.append({
                'path': temp_path,
                'start_ms': start_time,
                'end_ms': end_time,
                'size_kb': actual_size / 1024
            })

    return segments


# ===================== GUI 主界面 =====================
class TranslateApp(ToolBase):
    def __init__(self, master, initial_file: str = None):
        from i18n import tr

        self.master = master
        master.title(tr("tool.translate.title"))
        master.geometry("700x430")
        master.resizable(False, False)

        language_options = get_language_options()

        # ── Row 0: 源语言 ──────────────────────────────────────────────────────
        tk.Label(master, text=tr("tool.translate.source_lang")).grid(row=0, column=0, padx=10, pady=5, sticky="e")
        self.source_lang_var = tk.StringVar(value="English (英语)")
        self.source_combo = ttk.Combobox(master, textvariable=self.source_lang_var,
                                         values=language_options, state="readonly", width=30)
        self.source_combo.grid(row=0, column=1, columnspan=2, sticky="w", padx=(0, 10))

        # ── Row 1: 目标语言 ────────────────────────────────────────────────────
        tk.Label(master, text=tr("tool.translate.target_lang")).grid(row=1, column=0, padx=10, pady=5, sticky="e")
        self.target_lang_var = tk.StringVar(value="Chinese (中文)")
        self.target_combo = ttk.Combobox(master, textvariable=self.target_lang_var,
                                         values=language_options, state="readonly", width=30)
        self.target_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=(0, 10))

        # ── Row 2: 批次大小 ────────────────────────────────────────────────────
        tk.Label(master, text=tr("tool.translate.batch_size")).grid(row=2, column=0, padx=10, pady=5, sticky="e")
        self.batch_size_var = tk.StringVar(value="100")
        batch_size_frame = tk.Frame(master)
        batch_size_frame.grid(row=2, column=1, columnspan=2, sticky="w", padx=(0, 10))
        ttk.Radiobutton(batch_size_frame, text="30",  variable=self.batch_size_var, value="30" ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(batch_size_frame, text="50",  variable=self.batch_size_var, value="50" ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(batch_size_frame, text="100", variable=self.batch_size_var, value="100").pack(side=tk.LEFT, padx=5)
        tk.Label(batch_size_frame, text="(批次越大越快，但可能影响准确性)",
                 font=("Arial", 8), fg="gray").pack(side=tk.LEFT, padx=5)

        # ── Row 3: SRT 文件 ────────────────────────────────────────────────────
        tk.Label(master, text=tr("tool.translate.source_label")).grid(row=3, column=0, padx=10, pady=10, sticky="e")
        self.srt_path_var = tk.StringVar()
        tk.Entry(master, textvariable=self.srt_path_var, width=50).grid(row=3, column=1, sticky="w")
        tk.Button(master, text=tr("tool.translate.browse"), command=self.select_srt).grid(row=3, column=2, padx=10)

        # ── Row 4: Prompt 提示 ─────────────────────────────────────────────────
        # Per architecture principle 4 the prompt is not editable here;
        # tune it via AI 控制台 → Prompts tab if needed.
        tk.Label(master, text=tr("tool.translate.prompt_managed_hint"),
                 fg="gray", font=("Arial", 8), wraplength=560, justify="left",
                 ).grid(row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(2, 0))

        # ── Row 5: 翻译按钮 ────────────────────────────────────────────────────
        self.trans_btn = tk.Button(master, text=tr("tool.translate.btn_start"),
                                   command=self.translate_srt, width=20)
        self.trans_btn.grid(row=5, column=1, pady=20)

        # ── Row 6: 状态栏 ──────────────────────────────────────────────────────
        self.status_var = tk.StringVar()
        tk.Label(master, textvariable=self.status_var, fg="blue").grid(
            row=6, column=0, columnspan=3, pady=5)

        if initial_file:
            self.srt_path_var.set(initial_file)

    def select_srt(self):
        path = filedialog.askopenfilename(title="选择SRT文件", filetypes=[("SRT files", "*.srt")])
        if path:
            self.srt_path_var.set(path)

    def _run_translation(self, srt_path, source_lang, target_lang, batch_size):
        """Worker thread: delegate to core.translate, post status to main thread."""
        from i18n import tr as _tr

        def status(msg):
            self.master.after(0, self.status_var.set, msg)

        def finish():
            self.master.after(0, lambda: self.trans_btn.config(
                state="normal", text=_tr("tool.translate.btn_start")))

        def on_progress(_done, _total, msg):
            status(msg)

        try:
            output_file = translate_srt_file(
                srt_path,
                source_lang=source_lang,
                target_lang=target_lang,
                batch_size=batch_size,
                progress_cb=on_progress,
                log_cb=print,
            )
            status(f"翻译完成，已保存: {output_file}")
            logger.info(f"翻译完成 → {os.path.basename(output_file)}")
            self.set_done()

        except AIError as e:
            # Structured AI error → dialog with Kind-driven recovery actions.
            self.set_error(str(e))
            status(f"✗ {e}")
            self.master.after(0, lambda err=e: show_ai_error(self.master, err))
        except Exception as e:
            self.set_error(f"翻译失败: {e}")
            status(f"✗ 翻译失败: {e}")
        finally:
            finish()

    def translate_srt(self):
        srt_path    = self.srt_path_var.get()
        source_lang = get_lang_code(self.source_lang_var.get())
        target_lang = get_lang_code(self.target_lang_var.get())
        batch_size  = int(self.batch_size_var.get())

        if not srt_path or not os.path.exists(srt_path):
            self.status_var.set("⚠ 请选择有效的SRT文件")
            return
        if source_lang == target_lang:
            self.status_var.set("⚠ 源语言和目标语言不能相同")
            return

        from i18n import tr as _tr
        self.trans_btn.config(state="disabled", text=_tr("tool.translate.btn_running"))
        self.status_var.set(_tr("tool.translate.status_reading"))
        self.set_busy()

        threading.Thread(
            target=self._run_translation,
            args=(srt_path, source_lang, target_lang, batch_size),
            daemon=True
        ).start()


# 启动主界面
if __name__ == "__main__":
    root = tk.Tk()
    app = TranslateApp(root)
    root.mainloop()
