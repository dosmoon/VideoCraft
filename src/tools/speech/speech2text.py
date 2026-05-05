from tools.base import ToolBase
from i18n import tr
import i18n
import os
import sys
import tkinter as tk
from tkinter import filedialog, ttk
import threading
from hub_logger import logger

from core import asr as core_asr

# Whisper-supported languages: ISO code -> (english_name, chinese_name).
# UN-6 first, then alphabetical. Kept local to the UI for combobox display;
# the canonical catalog used by core feature layer is in core/translate.py.
language_dict = {
    "ar": ("Arabic", "阿拉伯语"),
    "zh": ("Chinese", "中文"),
    "en": ("English", "英语"),
    "fr": ("French", "法语"),
    "ru": ("Russian", "俄语"),
    "es": ("Spanish", "西班牙语"),
    "af": ("Afrikaans", "南非荷兰语"),
    "am": ("Amharic", "阿姆哈拉语"),
    "as": ("Assamese", "阿萨姆语"),
    "az": ("Azerbaijani", "阿塞拜疆语"),
    "ba": ("Bashkir", "巴什基尔语"),
    "be": ("Belarusian", "白俄罗斯语"),
    "bg": ("Bulgarian", "保加利亚语"),
    "bn": ("Bengali", "孟加拉语"),
    "bo": ("Tibetan", "藏语"),
    "br": ("Breton", "布列塔尼语"),
    "bs": ("Bosnian", "波斯尼亚语"),
    "ca": ("Catalan", "加泰罗尼亚语"),
    "cs": ("Czech", "捷克语"),
    "cy": ("Welsh", "威尔士语"),
    "da": ("Danish", "丹麦语"),
    "de": ("German", "德语"),
    "el": ("Greek", "希腊语"),
    "et": ("Estonian", "爱沙尼亚语"),
    "eu": ("Basque", "巴斯克语"),
    "fa": ("Persian", "波斯语"),
    "fi": ("Finnish", "芬兰语"),
    "fo": ("Faroese", "法罗语"),
    "gl": ("Galician", "加利西亚语"),
    "gu": ("Gujarati", "古吉拉特语"),
    "ha": ("Hausa", "豪萨语"),
    "haw": ("Hawaiian", "夏威夷语"),
    "he": ("Hebrew", "希伯来语"),
    "hi": ("Hindi", "印地语"),
    "hr": ("Croatian", "克罗地亚语"),
    "ht": ("Haitian Creole", "海地克里奥尔语"),
    "hu": ("Hungarian", "匈牙利语"),
    "hy": ("Armenian", "亚美尼亚语"),
    "id": ("Indonesian", "印度尼西亚语"),
    "is": ("Icelandic", "冰岛语"),
    "it": ("Italian", "意大利语"),
    "ja": ("Japanese", "日语"),
    "jw": ("Javanese", "爪哇语"),
    "ka": ("Georgian", "格鲁吉亚语"),
    "kk": ("Kazakh", "哈萨克语"),
    "km": ("Khmer", "高棉语"),
    "kn": ("Kannada", "卡纳达语"),
    "ko": ("Korean", "韩语"),
    "la": ("Latin", "拉丁语"),
    "lb": ("Luxembourgish", "卢森堡语"),
    "lo": ("Lao", "老挝语"),
    "lt": ("Lithuanian", "立陶宛语"),
    "lv": ("Latvian", "拉脱维亚语"),
    "mg": ("Malagasy", "马达加斯加语"),
    "mi": ("Maori", "毛利语"),
    "mk": ("Macedonian", "马其顿语"),
    "ml": ("Malayalam", "马拉雅拉姆语"),
    "mn": ("Mongolian", "蒙古语"),
    "mr": ("Marathi", "马拉地语"),
    "ms": ("Malay", "马来语"),
    "mt": ("Maltese", "马耳他语"),
    "my": ("Myanmar", "缅甸语"),
    "ne": ("Nepali", "尼泊尔语"),
    "nl": ("Dutch", "荷兰语"),
    "nn": ("Nynorsk", "挪威尼诺斯克语"),
    "no": ("Norwegian", "挪威语"),
    "oc": ("Occitan", "奥克语"),
    "pa": ("Punjabi", "旁遮普语"),
    "pl": ("Polish", "波兰语"),
    "ps": ("Pashto", "普什图语"),
    "pt": ("Portuguese", "葡萄牙语"),
    "ro": ("Romanian", "罗马尼亚语"),
    "sa": ("Sanskrit", "梵语"),
    "sd": ("Sindhi", "信德语"),
    "si": ("Sinhala", "僧伽罗语"),
    "sk": ("Slovak", "斯洛伐克语"),
    "sl": ("Slovenian", "斯洛文尼亚语"),
    "sn": ("Shona", "绍纳语"),
    "so": ("Somali", "索马里语"),
    "sq": ("Albanian", "阿尔巴尼亚语"),
    "sr": ("Serbian", "塞尔维亚语"),
    "su": ("Sundanese", "巽他语"),
    "sv": ("Swedish", "瑞典语"),
    "sw": ("Swahili", "斯瓦希里语"),
    "ta": ("Tamil", "泰米尔语"),
    "te": ("Telugu", "泰卢固语"),
    "tg": ("Tajik", "塔吉克语"),
    "th": ("Thai", "泰语"),
    "tk": ("Turkmen", "土库曼语"),
    "tl": ("Filipino", "菲律宾语"),
    "tr": ("Turkish", "土耳其语"),
    "tt": ("Tatar", "鞑靼语"),
    "uk": ("Ukrainian", "乌克兰语"),
    "ur": ("Urdu", "乌尔都语"),
    "uz": ("Uzbek", "乌兹别克语"),
    "vi": ("Vietnamese", "越南语"),
    "yi": ("Yiddish", "意第绪语"),
    "yo": ("Yoruba", "约鲁巴语"),
    "yue": ("Cantonese", "粤语")
}


def build_language_options() -> list:
    """Build the combobox option list based on current UI locale.
    In zh mode shows bilingual "English (英语)" form; in en mode shows
    plain English names so the list isn't cluttered with Chinese text."""
    un_languages = ["ar", "zh", "en", "fr", "ru", "es"]
    other_languages = sorted([code for code in language_dict if code not in un_languages])
    ordered = un_languages + other_languages

    auto = tr("tool.speech.auto_detect")
    if i18n.get_current_lang() == "zh":
        return [auto] + [
            f"{language_dict[code][0]} ({language_dict[code][1]})" for code in ordered
        ]
    return [auto] + [language_dict[code][0] for code in ordered]


class Speech2TextApp(ToolBase):
    """语音转字幕工具（LemonFox API）— Toplevel 内嵌版。"""

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.speech.title"))
        master.geometry("600x580")
        self._build_ui()
        if initial_file and os.path.exists(initial_file):
            self.entry_mp3_path.delete(0, tk.END)
            self.entry_mp3_path.insert(0, initial_file)
            self._auto_fill_output()

    def _build_ui(self):
        f = self.master

        # Source file
        tk.Label(f, text=tr("tool.speech.source_label")).pack(pady=(10, 2))
        row1 = tk.Frame(f)
        row1.pack(fill=tk.X, padx=10)
        self.entry_mp3_path = tk.Entry(row1, width=52)
        self.entry_mp3_path.pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(row1, text=tr("tool.speech.browse"), width=6,
                  command=self._select_mp3_file).pack(side=tk.LEFT, padx=(4, 0))

        # Output SRT
        tk.Label(f, text=tr("tool.speech.output_label")).pack(pady=(8, 2))
        row2 = tk.Frame(f)
        row2.pack(fill=tk.X, padx=10)
        self.entry_srt_path = tk.Entry(row2, width=52)
        self.entry_srt_path.pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(row2, text=tr("tool.speech.browse"), width=6,
                  command=self._select_srt_path).pack(side=tk.LEFT, padx=(4, 0))

        # Recognition language
        tk.Label(f, text=tr("tool.speech.language_label")).pack(pady=(8, 2))
        options = build_language_options()
        # Default to Auto Detect. Specifying a language makes Lemonfox/Whisper
        # treat it as "output in THIS language" (auto-translating when needed)
        # rather than "input audio is in this language", so Auto Detect is the
        # safer default unless the user explicitly wants translation.
        default_value = options[0]
        self.combo_language = tk.StringVar(value=default_value)
        self.combo_language.trace_add("write", lambda *_: self._auto_fill_output())
        combo_menu = ttk.Combobox(f, textvariable=self.combo_language,
                                  values=options, state="readonly", width=50)
        combo_menu.pack(fill=tk.X, padx=10)
        tk.Label(f, text=tr("tool.speech.language_tip"),
                 font=("Arial", 8), fg="gray", wraplength=560,
                 justify="left").pack(anchor="w", padx=10, pady=(2, 0))

        self.translate_var = tk.BooleanVar()
        tk.Checkbutton(f, text=tr("tool.speech.translate_to_en"),
                       variable=self.translate_var).pack(pady=(5, 0))

        self.speaker_var = tk.BooleanVar()
        tk.Checkbutton(f, text=tr("tool.speech.speaker_labels"),
                       variable=self.speaker_var).pack(pady=(0, 5))

        self.btn_transcribe = tk.Button(f, text=tr("tool.speech.btn_transcribe"),
                                        command=self._transcribe_audio,
                                        width=20, bg="#0078d4", fg="white")
        self.btn_transcribe.pack(pady=10)

        tk.Label(f, text=tr("tool.speech.log_label")).pack(pady=(0, 2))
        self.log_text = tk.Text(f, height=8, width=70)
        self.log_text.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

    def _auto_fill_output(self):
        """根据源文件路径和语言自动生成输出 SRT 路径（语言用 ISO 码）。"""
        src = self.entry_mp3_path.get().strip()
        if not src:
            return
        base = os.path.splitext(src)[0]
        lang = self.combo_language.get()
        if lang.startswith("Auto Detect") or lang.startswith(tr("tool.speech.auto_detect")):
            suffix = "auto"
        else:
            eng_name = lang.split(" (")[0]
            suffix = next(
                (code for code, (e, _) in language_dict.items() if e == eng_name),
                eng_name.lower()[:2]
            )
        out = f"{base}_{suffix}.srt"
        self.entry_srt_path.delete(0, tk.END)
        self.entry_srt_path.insert(0, out)

    def _select_mp3_file(self):
        file_path = filedialog.askopenfilename(
            title=tr("tool.speech.dialog.select_audio"),
            filetypes=[(tr("tool.speech.filter.audio_video"), "*.mp3;*.mp4;*.wav;*.m4a;*.mkv"),
                       (tr("tool.speech.filter.all_files"), "*.*")]
        )
        if file_path:
            self.entry_mp3_path.delete(0, tk.END)
            self.entry_mp3_path.insert(0, file_path)
            self._auto_fill_output()

    def _select_srt_path(self):
        src = self.entry_mp3_path.get().strip()
        init_dir = os.path.dirname(src) if src else ""
        file_path = filedialog.asksaveasfilename(
            title=tr("tool.speech.dialog.save_srt"),
            defaultextension=".srt",
            filetypes=[(tr("tool.speech.filter.srt"), "*.srt")],
            initialdir=init_dir,
        )
        if file_path:
            self.entry_srt_path.delete(0, tk.END)
            self.entry_srt_path.insert(0, file_path)

    def _log(self, msg: str):
        """Append a message to the log text widget. Must be called from the main thread."""
        self.log_text.insert(tk.END, msg)
        self.log_text.see(tk.END)

    def _is_auto_selection(self, selected_language: str) -> bool:
        return (selected_language.startswith("Auto Detect")
                or selected_language.startswith(tr("tool.speech.auto_detect")))

    def _transcribe_audio(self):
        """Validate inputs on the main thread, then launch a background thread for the
        transcription call so the UI stays responsive during the API request."""
        mp3_path = self.entry_mp3_path.get()
        selected_language = self.combo_language.get()

        if not mp3_path or not os.path.exists(mp3_path):
            self._log(tr("tool.speech.warning.no_audio"))
            return

        srt_path = self.entry_srt_path.get().strip()
        if not srt_path:
            self._log(tr("tool.speech.warning.no_output"))
            return

        # Resolve selected language -> (api_lang display name, expected ISO)
        if self._is_auto_selection(selected_language):
            api_lang = None
            expected_iso = None
        else:
            eng_name = selected_language.split(" (")[0]
            api_lang = eng_name.lower()
            expected_iso = next(
                (code for code, (e, _) in language_dict.items() if e == eng_name),
                eng_name.lower()[:2]
            )

        translate = self.translate_var.get()
        speaker   = self.speaker_var.get()

        self.btn_transcribe.config(state="disabled", text=tr("tool.speech.btn_running"))
        self.set_busy()
        self._log(tr("tool.speech.log.starting"))

        def _do_transcribe():
            def post_log(msg: str):
                self.master.after(0, self._log, msg)

            def post_btn(text: str):
                self.master.after(0, lambda t=text: self.btn_transcribe.config(text=t))

            def finish():
                self.master.after(0, lambda: self.btn_transcribe.config(
                    state="normal", text=tr("tool.speech.btn_transcribe")))

            def on_event(event_type: str, **kwargs):
                """Translate provider events to i18n log lines + button-text updates."""
                if event_type == "request_summary":
                    post_log(tr("tool.speech.log.request_summary", **kwargs))
                elif event_type == "request_summary_local":
                    post_log(tr("tool.speech.log.request_summary_local", **kwargs))
                elif event_type == "model_loading":
                    post_btn(tr("tool.speech.btn_loading_model"))
                    post_log(tr("tool.speech.log.model_loading", **kwargs))
                elif event_type == "model_loaded":
                    post_log(tr("tool.speech.log.model_loaded", **kwargs))
                elif event_type == "state_processing":
                    seg = kwargs.get("segment_count", 0)
                    el  = kwargs.get("elapsed", 0)
                    post_btn(tr("tool.speech.btn_processing_local", segment_count=seg, elapsed=el))
                    post_log(tr("tool.speech.log.state_processing", **kwargs))
                elif event_type == "state_done":
                    post_log(tr("tool.speech.log.state_done", **kwargs))
                elif event_type == "mime_fallback":
                    post_log(tr("tool.speech.warning.mime_fallback", **kwargs))
                elif event_type == "state_uploading":
                    attempt = kwargs.get("attempt")
                    max_att = kwargs.get("max_attempts")
                    percent = kwargs.get("percent", 0)
                    post_btn(tr("tool.speech.btn_uploading", percent=percent))
                    post_log(tr("tool.speech.log.state_uploading",
                                attempt=attempt, max=max_att, percent=percent))
                elif event_type == "state_waiting_start":
                    attempt = kwargs.get("attempt")
                    max_att = kwargs.get("max_attempts")
                    post_log(tr("tool.speech.log.state_waiting_start",
                                attempt=attempt, max=max_att))
                elif event_type == "state_waiting_tick":
                    attempt = kwargs.get("attempt")
                    max_att = kwargs.get("max_attempts")
                    elapsed = kwargs.get("elapsed", 0)
                    total   = kwargs.get("total", 0)
                    post_btn(tr("tool.speech.btn_waiting", elapsed=elapsed, total=total))
                    post_log(tr("tool.speech.log.state_waiting_tick",
                                attempt=attempt, max=max_att,
                                elapsed=elapsed, total=total))
                elif event_type.startswith("retry_"):
                    attempt = kwargs.get("attempt")
                    max_att = kwargs.get("max_attempts")
                    wait    = kwargs.get("wait", 0)
                    key = f"tool.speech.log.{event_type}"
                    post_log(tr(key, attempt=attempt, max=max_att, wait=wait))

            try:
                result = core_asr.transcribe_audio(
                    mp3_path,
                    srt_path,
                    expected_lang_iso=expected_iso,
                    language=api_lang,
                    translate=translate,
                    speaker_labels=speaker,
                    on_event=on_event,
                )

                detected      = result["detected_lang"]
                detected_iso  = result["detected_lang_iso"]
                final_srt     = result["srt_path"]
                json_path     = result["json_path"]
                lang_mismatch = result["lang_mismatch"]

                # Update the output-path entry if it was rewritten
                if final_srt != srt_path:
                    self.master.after(0, lambda p=final_srt: (
                        self.entry_srt_path.delete(0, tk.END),
                        self.entry_srt_path.insert(0, p),
                    ))

                # Log detected language (and log mismatch notice early so the
                # user sees it close to the detection line).
                if detected:
                    post_log(tr("tool.speech.log.detected_lang",
                                detected=detected, iso=detected_iso or ""))
                if lang_mismatch:
                    post_log(tr("tool.speech.log.lang_mismatch",
                                selected=expected_iso, detected=detected_iso))

                # Success logs
                post_log(tr("tool.speech.log.json_saved", path=json_path))
                post_log(tr("tool.speech.log.srt_saved", path=final_srt))
                post_log(tr("tool.speech.log.duration", seconds=result["duration"]))
                post_log(tr("tool.speech.log.segments", count=result["segment_count"]))
                if result["word_count"]:
                    post_log(tr("tool.speech.log.words", count=result["word_count"]))
                logger.info(tr("tool.speech.log.complete",
                               filename=os.path.basename(final_srt)))

                # Final tab status — warning takes priority over done, so call
                # set_warning LAST (otherwise set_done would flip the tab dot
                # from orange back to green, silently hiding the mismatch).
                # Note: lang_mismatch only meaningfully fires in Auto Detect
                # mode (see core.asr for why).
                if lang_mismatch:
                    self.set_warning(tr("tool.speech.warning.lang_mismatch",
                                        selected=expected_iso, detected=detected_iso))
                else:
                    self.set_done()

            except Exception as e:
                post_log(tr("tool.speech.error.generic", e=str(e)))
                self.set_error(tr("tool.speech.error.transcribe_failed", e=e))
            finally:
                finish()

        threading.Thread(target=_do_transcribe, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    initial = sys.argv[1] if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else None
    app = Speech2TextApp(root, initial_file=initial)
    root.mainloop()
