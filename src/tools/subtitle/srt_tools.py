from tools.base import ToolBase
from i18n import tr
import os
import sys
import tkinter as tk
from tkinter import filedialog
import threading
from hub_logger import logger

# Hub 内嵌时 core 包在 src/ 下，独立运行时也在同一目录
_SRC = os.path.dirname(os.path.abspath(__file__))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
from core import srt_ops


# ===================== 通用工具 =====================

def _resolve_output(input_path, output_var, default_name):
    """若输出路径为相对路径，解析为与输入文件同目录的绝对路径并写回 StringVar。"""
    output_path = output_var.get()
    if not os.path.isabs(output_path):
        output_path = os.path.join(os.path.dirname(input_path), output_path)
        output_var.set(output_path)
    return output_path


def _ensure_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d)


# ===================== 独立操作窗口 =====================

class SrtExtractSubtitlesApp(ToolBase):
    """Tab 1: Extract subtitle text — standalone window."""

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.srt.extract_subs.title"))
        master.geometry("800x500")

        self.srt_var = tk.StringVar()
        self.output_var = tk.StringVar(value="AllSubtitles.txt")
        self.status_var = tk.StringVar()

        if initial_file:
            self.srt_var.set(initial_file)
            self.output_var.set(os.path.join(os.path.dirname(initial_file), "AllSubtitles.txt"))

        self._build_ui()

    def _build_ui(self):
        master = self.master

        left = tk.Frame(master)
        left.pack(side=tk.LEFT, fill=tk.BOTH, padx=10, pady=10)
        right = tk.Frame(master)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(0, 10), pady=10)

        tk.Label(left, text=tr("tool.srt.common.srt_file")).grid(row=0, column=0, padx=5, pady=10, sticky="e")
        tk.Entry(left, textvariable=self.srt_var, width=40).grid(row=0, column=1, sticky="w")
        tk.Button(left, text=tr("tool.srt.common.browse"), command=self._select_srt).grid(row=0, column=2, padx=10)

        tk.Label(left, text=tr("tool.srt.common.output_file")).grid(row=1, column=0, padx=5, pady=5, sticky="e")
        tk.Entry(left, textvariable=self.output_var, width=40).grid(row=1, column=1, sticky="w")
        tk.Button(left, text=tr("tool.srt.common.browse"), command=self._select_output).grid(row=1, column=2, padx=10)

        self._btn = tk.Button(left, text=tr("tool.srt.extract_subs.btn_run"), command=self._run, width=20)
        self._btn.grid(row=2, column=1, pady=25)

        tk.Label(left, textvariable=self.status_var, fg="blue").grid(row=3, column=0, columnspan=3, pady=10)

        hdr = tk.Frame(right)
        hdr.pack(fill=tk.X, pady=(0, 5))
        tk.Label(hdr, text=tr("tool.srt.extract_subs.preview_label"), font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        tk.Button(hdr, text=tr("tool.srt.common.copy_btn"), command=self._copy, width=12).pack(side=tk.RIGHT, padx=5)

        tf = tk.Frame(right)
        tf.pack(fill=tk.BOTH, expand=True)
        sy = tk.Scrollbar(tf)
        sy.pack(side=tk.RIGHT, fill=tk.Y)
        sx = tk.Scrollbar(tf, orient=tk.HORIZONTAL)
        sx.pack(side=tk.BOTTOM, fill=tk.X)
        self._text = tk.Text(tf, wrap=tk.WORD, yscrollcommand=sy.set,
                             xscrollcommand=sx.set, font=("Consolas", 10))
        self._text.pack(fill=tk.BOTH, expand=True)
        sy.config(command=self._text.yview)
        sx.config(command=self._text.xview)

    def _select_srt(self):
        path = filedialog.askopenfilename(title=tr("tool.srt.common.select_srt_title"),
                                          filetypes=[(tr("tool.srt.common.filter.srt"), "*.srt")])
        if path:
            self.srt_var.set(path)
            self.output_var.set(os.path.join(os.path.dirname(path), "AllSubtitles.txt"))

    def _select_output(self):
        path = filedialog.asksaveasfilename(title=tr("tool.srt.common.select_output_title"),
                                            defaultextension=".txt",
                                            filetypes=[(tr("tool.srt.common.filter.txt"), "*.txt")])
        if path:
            self.output_var.set(path)

    def _run(self):
        srt_path = self.srt_var.get()
        if not srt_path or not os.path.exists(srt_path):
            self.status_var.set(tr("tool.srt.common.error_no_srt"))
            return
        output_path = _resolve_output(srt_path, self.output_var, "AllSubtitles.txt")
        try:
            _ensure_dir(output_path)
        except Exception as e:
            self.status_var.set(tr("tool.srt.common.error_cannot_create_dir", e=e))
            return

        self.status_var.set(tr("tool.srt.extract_subs.status_extracting"))
        self._btn.config(state="disabled")

        def _work():
            try:
                text = srt_ops.extract_all_subtitles(srt_path)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                self.status_var.set(tr("tool.srt.common.status_done_fmt",
                                       filename=os.path.basename(output_path)))
                self.master.after(0, lambda: (self._text.delete("1.0", tk.END),
                                              self._text.insert("1.0", text)))
                self.set_done()
            except Exception as e:
                self.status_var.set(tr("tool.srt.common.status_fail_fmt", e=e))
                self.set_error(tr("tool.srt.extract_subs.error_failed", e=e))
            finally:
                self.master.after(0, lambda: self._btn.config(state="normal"))

        self.set_busy()
        threading.Thread(target=_work, daemon=True).start()

    def _copy(self):
        content = self._text.get("1.0", tk.END).strip()
        if not content:
            self.status_var.set(tr("tool.srt.common.copy_nothing"))
            return
        self.master.clipboard_clear()
        self.master.clipboard_append(content)
        self.master.update()
        self.status_var.set(tr("tool.srt.common.copy_done"))


class SrtGenerateSegmentsApp(ToolBase):
    """Tab 2: 生成分段描述 — 独立窗口版.

    Prompt 不再在 UI 中暴露；使用 core.srt_ops 内置的默认 prompt，符合
    架构原则 4（prompts 对 UI 隐藏）。未来 L16 Prompt hub 就位后，
    用户可在统一的 Prompt 管理页调整。
    """

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.srt.gen_segments.title"))
        master.geometry("750x220")

        self.srt_var = tk.StringVar()
        self.output_var = tk.StringVar(value="subs.txt")
        self.status_var = tk.StringVar()

        if initial_file:
            self.srt_var.set(initial_file)
            self.output_var.set(os.path.join(os.path.dirname(initial_file), "subs.txt"))

        self._build_ui()

    def _build_ui(self):
        f = self.master

        tk.Label(f, text=tr("tool.srt.common.srt_file")).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        tk.Entry(f, textvariable=self.srt_var, width=50).grid(row=0, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"), command=self._select_srt).grid(row=0, column=2, padx=10)

        tk.Label(f, text=tr("tool.srt.common.output_file")).grid(row=1, column=0, padx=10, pady=5, sticky="e")
        tk.Entry(f, textvariable=self.output_var, width=50).grid(row=1, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"), command=self._select_output).grid(row=1, column=2, padx=10)

        self._btn = tk.Button(f, text=tr("tool.srt.gen_segments.btn_run"), command=self._run, width=20)
        self._btn.grid(row=2, column=1, pady=25)

        tk.Label(f, textvariable=self.status_var, fg="blue").grid(
            row=3, column=0, columnspan=3, pady=10)

    def _select_srt(self):
        path = filedialog.askopenfilename(title=tr("tool.srt.common.select_srt_title"),
                                          filetypes=[(tr("tool.srt.common.filter.srt"), "*.srt")])
        if path:
            self.srt_var.set(path)
            self.output_var.set(os.path.join(os.path.dirname(path), "subs.txt"))

    def _select_output(self):
        path = filedialog.asksaveasfilename(title=tr("tool.srt.common.select_output_title"),
                                            defaultextension=".txt",
                                            filetypes=[(tr("tool.srt.common.filter.txt"), "*.txt")])
        if path:
            self.output_var.set(path)

    def _run(self):
        srt_path = self.srt_var.get()
        if not srt_path or not os.path.exists(srt_path):
            self.status_var.set(tr("tool.srt.common.error_no_srt"))
            return
        output_path = _resolve_output(srt_path, self.output_var, "subs.txt")
        try:
            _ensure_dir(output_path)
        except Exception as e:
            self.status_var.set(tr("tool.srt.common.error_cannot_create_dir", e=e))
            return

        self.status_var.set(tr("tool.srt.gen_segments.status_running"))
        self._btn.config(state="disabled")

        def _work():
            try:
                result = srt_ops.generate_youtube_segments(srt_path)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result)
                self.status_var.set(tr("tool.srt.gen_segments.status_done"))
                logger.info(tr("tool.srt.gen_segments.log_done", filename=os.path.basename(output_path)))
                self.set_done()
            except Exception as e:
                self.set_error(tr("tool.srt.gen_segments.error_failed", e=e))
                self.status_var.set(tr("tool.srt.gen_segments.status_fail"))
            finally:
                self.master.after(0, lambda: self._btn.config(state="normal"))

        self.set_busy()
        threading.Thread(target=_work, daemon=True).start()


class SrtExtractParagraphsApp(ToolBase):
    """Tab 3：提取段落内容 — 独立窗口版。"""

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.srt.extract_paragraphs.title"))
        master.geometry("750x300")

        self.srt_var = tk.StringVar()
        self.segments_var = tk.StringVar()
        self.output_var = tk.StringVar(value="subs-segment.txt")
        self.status_var = tk.StringVar()

        if initial_file:
            self.srt_var.set(initial_file)
            self.output_var.set(os.path.join(os.path.dirname(initial_file), "subs-segment.txt"))

        self._build_ui()

    def _build_ui(self):
        f = self.master
        tk.Label(f, text=tr("tool.srt.common.srt_file")).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        tk.Entry(f, textvariable=self.srt_var, width=50).grid(row=0, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"), command=self._select_srt).grid(row=0, column=2, padx=10)

        tk.Label(f, text=tr("tool.srt.extract_paragraphs.segments_label")).grid(row=1, column=0, padx=10, pady=5, sticky="e")
        tk.Entry(f, textvariable=self.segments_var, width=50).grid(row=1, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"), command=self._select_segments).grid(row=1, column=2, padx=10)

        tk.Label(f, text=tr("tool.srt.common.output_file")).grid(row=2, column=0, padx=10, pady=5, sticky="e")
        tk.Entry(f, textvariable=self.output_var, width=50).grid(row=2, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"), command=self._select_output).grid(row=2, column=2, padx=10)

        self._btn = tk.Button(f, text=tr("tool.srt.extract_paragraphs.btn_run"), command=self._run, width=20)
        self._btn.grid(row=3, column=1, pady=25)

        tk.Label(f, textvariable=self.status_var, fg="blue").grid(
            row=4, column=0, columnspan=3, pady=10)

    def _select_srt(self):
        path = filedialog.askopenfilename(title=tr("tool.srt.common.select_srt_title"),
                                          filetypes=[(tr("tool.srt.common.filter.srt"), "*.srt")])
        if path:
            self.srt_var.set(path)
            self.output_var.set(os.path.join(os.path.dirname(path), "subs-segment.txt"))

    def _select_segments(self):
        path = filedialog.askopenfilename(title=tr("tool.srt.common.select_output_title"),
                                          filetypes=[(tr("tool.srt.common.filter.txt"), "*.txt")])
        if path:
            self.segments_var.set(path)

    def _select_output(self):
        path = filedialog.asksaveasfilename(title=tr("tool.srt.common.select_output_title"),
                                            defaultextension=".txt",
                                            filetypes=[(tr("tool.srt.common.filter.txt"), "*.txt")])
        if path:
            self.output_var.set(path)

    def _run(self):
        srt_path = self.srt_var.get()
        segments_path = self.segments_var.get()
        if not srt_path or not os.path.exists(srt_path):
            self.status_var.set(tr("tool.srt.common.error_no_srt"))
            return
        if not segments_path or not os.path.exists(segments_path):
            self.status_var.set(tr("tool.srt.extract_paragraphs.error_no_segments"))
            return
        output_path = _resolve_output(srt_path, self.output_var, "subs-segment.txt")
        try:
            _ensure_dir(output_path)
        except Exception as e:
            self.status_var.set(tr("tool.srt.common.error_cannot_create_dir", e=e))
            return

        self.status_var.set(tr("tool.srt.extract_paragraphs.status_running"))
        self._btn.config(state="disabled")

        def _work():
            try:
                result = srt_ops.extract_paragraphs_from_segments(srt_path, segments_path)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result)
                self.status_var.set(tr("tool.srt.extract_paragraphs.status_done"))
                logger.info(tr("tool.srt.extract_paragraphs.log_done",
                               filename=os.path.basename(output_path)))
                self.set_done()
            except Exception as e:
                self.set_error(tr("tool.srt.extract_paragraphs.error_failed", e=e))
                self.status_var.set(tr("tool.srt.extract_paragraphs.status_fail"))
            finally:
                self.master.after(0, lambda: self._btn.config(state="normal"))

        self.set_busy()
        threading.Thread(target=_work, daemon=True).start()


class SrtRefineSegmentsApp(ToolBase):
    """Tab 4: 精炼分段 — 独立窗口版.

    Prompt 不再暴露在 UI（见 SrtGenerateSegmentsApp 的同理说明）。
    """

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.srt.refine.title"))
        master.geometry("750x220")

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value="subs-segment-refined.txt")
        self.status_var = tk.StringVar()

        if initial_file:
            self.input_var.set(initial_file)
            self.output_var.set(
                os.path.join(os.path.dirname(initial_file), "subs-segment-refined.txt"))

        self._build_ui()

    def _build_ui(self):
        f = self.master
        tk.Label(f, text=tr("tool.srt.refine.input_label")).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        tk.Entry(f, textvariable=self.input_var, width=50).grid(row=0, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"), command=self._select_input).grid(row=0, column=2, padx=10)

        tk.Label(f, text=tr("tool.srt.common.output_file")).grid(row=1, column=0, padx=10, pady=5, sticky="e")
        tk.Entry(f, textvariable=self.output_var, width=50).grid(row=1, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"), command=self._select_output).grid(row=1, column=2, padx=10)

        self._btn = tk.Button(f, text=tr("tool.srt.refine.btn_run"), command=self._run, width=20)
        self._btn.grid(row=2, column=1, pady=25)

        tk.Label(f, textvariable=self.status_var, fg="blue").grid(
            row=3, column=0, columnspan=3, pady=10)

    def _select_input(self):
        path = filedialog.askopenfilename(title=tr("tool.srt.common.select_output_title"),
                                          filetypes=[(tr("tool.srt.common.filter.txt"), "*.txt")])
        if path:
            self.input_var.set(path)
            self.output_var.set(
                os.path.join(os.path.dirname(path), "subs-segment-refined.txt"))

    def _select_output(self):
        path = filedialog.asksaveasfilename(title=tr("tool.srt.common.select_output_title"),
                                            defaultextension=".txt",
                                            filetypes=[(tr("tool.srt.common.filter.txt"), "*.txt")])
        if path:
            self.output_var.set(path)

    def _run(self):
        input_path = self.input_var.get()
        if not input_path or not os.path.exists(input_path):
            self.status_var.set(tr("tool.srt.refine.error_no_input"))
            return
        output_path = _resolve_output(input_path, self.output_var, "subs-segment-refined.txt")
        try:
            _ensure_dir(output_path)
        except Exception as e:
            self.status_var.set(tr("tool.srt.common.error_cannot_create_dir", e=e))
            return

        self.status_var.set(tr("tool.srt.refine.status_running"))
        self._btn.config(state="disabled")

        def _work():
            try:
                result = srt_ops.refine_segment_descriptions(input_path)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result)
                self.status_var.set(tr("tool.srt.refine.status_done"))
                logger.info(tr("tool.srt.refine.log_done", filename=os.path.basename(output_path)))
                self.set_done()
            except Exception as e:
                self.set_error(tr("tool.srt.refine.error_failed", e=e))
                self.status_var.set(tr("tool.srt.refine.status_fail"))
            finally:
                self.master.after(0, lambda: self._btn.config(state="normal"))

        self.set_busy()
        threading.Thread(target=_work, daemon=True).start()


class SrtGenerateTitlesApp(ToolBase):
    """Tab 5: 生成标题 — 独立窗口版.

    Prompt 不再暴露在 UI（见 SrtGenerateSegmentsApp 的同理说明）。
    """

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.srt.gen_titles.title"))
        master.geometry("750x220")

        self.subs_var = tk.StringVar()
        self.output_var = tk.StringVar(value="titles.txt")
        self.status_var = tk.StringVar()

        if initial_file:
            self.subs_var.set(initial_file)
            self.output_var.set(os.path.join(os.path.dirname(initial_file), "titles.txt"))

        self._build_ui()

    def _build_ui(self):
        f = self.master
        tk.Label(f, text=tr("tool.srt.gen_titles.subs_label")).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        tk.Entry(f, textvariable=self.subs_var, width=50).grid(row=0, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"), command=self._select_subs).grid(row=0, column=2, padx=10)

        tk.Label(f, text=tr("tool.srt.common.output_file")).grid(row=1, column=0, padx=10, pady=5, sticky="e")
        tk.Entry(f, textvariable=self.output_var, width=50).grid(row=1, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"), command=self._select_output).grid(row=1, column=2, padx=10)

        self._btn = tk.Button(f, text=tr("tool.srt.gen_titles.btn_run"), command=self._run, width=20)
        self._btn.grid(row=2, column=1, pady=25)

        tk.Label(f, textvariable=self.status_var, fg="blue").grid(
            row=3, column=0, columnspan=3, pady=10)

    def _select_subs(self):
        path = filedialog.askopenfilename(title=tr("tool.srt.common.select_output_title"),
                                          filetypes=[(tr("tool.srt.common.filter.txt"), "*.txt")])
        if path:
            self.subs_var.set(path)
            self.output_var.set(os.path.join(os.path.dirname(path), "titles.txt"))

    def _select_output(self):
        path = filedialog.asksaveasfilename(title=tr("tool.srt.common.select_output_title"),
                                            defaultextension=".txt",
                                            filetypes=[(tr("tool.srt.common.filter.txt"), "*.txt")])
        if path:
            self.output_var.set(path)

    def _run(self):
        subs_path = self.subs_var.get()
        if not subs_path or not os.path.exists(subs_path):
            self.status_var.set(tr("tool.srt.gen_titles.error_no_subs"))
            return
        output_path = _resolve_output(subs_path, self.output_var, "titles.txt")
        try:
            _ensure_dir(output_path)
        except Exception as e:
            self.status_var.set(tr("tool.srt.common.error_cannot_create_dir", e=e))
            return

        self.status_var.set(tr("tool.srt.gen_titles.status_running"))
        self._btn.config(state="disabled")

        def _work():
            try:
                result = srt_ops.generate_video_titles(subs_path)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result)
                self.status_var.set(tr("tool.srt.gen_titles.status_done"))
                logger.info(tr("tool.srt.gen_titles.log_done", filename=os.path.basename(output_path)))
                self.set_done()
            except Exception as e:
                self.set_error(tr("tool.srt.gen_titles.error_failed", e=e))
                self.status_var.set(tr("tool.srt.gen_titles.status_fail"))
            finally:
                self.master.after(0, lambda: self._btn.config(state="normal"))

        self.set_busy()
        threading.Thread(target=_work, daemon=True).start()


class SrtGeneratePackApp(ToolBase):
    """One-shot pack: titles + segments + refined in a single AI call.

    Writes 4 sibling files derived from the user-chosen base path:
      <base>.json, <base>-titles.txt, <base>-segments.txt, <base>-refined.txt
    """

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.srt.gen_pack.title"))
        master.geometry("780x230")

        self.srt_var = tk.StringVar()
        self.output_var = tk.StringVar(value="subs_pack.json")
        self.status_var = tk.StringVar()

        if initial_file:
            self.srt_var.set(initial_file)
            self.output_var.set(os.path.join(os.path.dirname(initial_file),
                                             "subs_pack.json"))

        self._build_ui()

    def _build_ui(self):
        f = self.master

        tk.Label(f, text=tr("tool.srt.common.srt_file")).grid(
            row=0, column=0, padx=10, pady=10, sticky="e")
        tk.Entry(f, textvariable=self.srt_var, width=50).grid(
            row=0, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"),
                  command=self._select_srt).grid(row=0, column=2, padx=10)

        tk.Label(f, text=tr("tool.srt.gen_pack.output_base")).grid(
            row=1, column=0, padx=10, pady=5, sticky="e")
        tk.Entry(f, textvariable=self.output_var, width=50).grid(
            row=1, column=1, sticky="w")
        tk.Button(f, text=tr("tool.srt.common.browse"),
                  command=self._select_output).grid(row=1, column=2, padx=10)

        self._btn = tk.Button(f, text=tr("tool.srt.gen_pack.btn_run"),
                              command=self._run, width=24)
        self._btn.grid(row=2, column=1, pady=20)

        tk.Label(f, textvariable=self.status_var, fg="blue", wraplength=720,
                 justify="left").grid(row=3, column=0, columnspan=3, pady=10)

    def _select_srt(self):
        path = filedialog.askopenfilename(
            title=tr("tool.srt.common.select_srt_title"),
            filetypes=[(tr("tool.srt.common.filter.srt"), "*.srt")])
        if path:
            self.srt_var.set(path)
            self.output_var.set(os.path.join(os.path.dirname(path),
                                             "subs_pack.json"))

    def _select_output(self):
        path = filedialog.asksaveasfilename(
            title=tr("tool.srt.common.select_output_title"),
            defaultextension=".json",
            filetypes=[(tr("tool.srt.common.filter.json"), "*.json"),
                       (tr("tool.srt.common.filter.txt"), "*.txt")])
        if path:
            self.output_var.set(path)

    def _run(self):
        srt_path = self.srt_var.get()
        if not srt_path or not os.path.exists(srt_path):
            self.status_var.set(tr("tool.srt.common.error_no_srt"))
            return
        output_path = _resolve_output(srt_path, self.output_var,
                                      "subs_pack.json")
        try:
            _ensure_dir(output_path)
        except Exception as e:
            self.status_var.set(
                tr("tool.srt.common.error_cannot_create_dir", e=e))
            return

        self.status_var.set(tr("tool.srt.gen_pack.status_running"))
        self._btn.config(state="disabled")

        def _work():
            try:
                pack = srt_ops.generate_subtitle_pack(srt_path)
                paths = srt_ops.write_subtitle_pack(pack, output_path)
                self.status_var.set(tr(
                    "tool.srt.gen_pack.status_done",
                    json_name=os.path.basename(paths["json"]),
                    titles_name=os.path.basename(paths["titles"]),
                    chapters_name=os.path.basename(paths["chapters"]),
                    description_name=os.path.basename(paths["description"]),
                ))
                logger.info(tr("tool.srt.gen_pack.log_done",
                               filename=os.path.basename(paths["json"])))
                self.set_done()
            except Exception as e:
                self.set_error(tr("tool.srt.gen_pack.error_failed", e=e))
                self.status_var.set(tr("tool.srt.gen_pack.status_fail"))
            finally:
                self.master.after(0, lambda: self._btn.config(state="normal"))

        self.set_busy()
        threading.Thread(target=_work, daemon=True).start()
