"""
VideoCraftHub.py - VS Code 风格主界面

布局：Menu 菜单栏 + 左侧 Sidebar 文件浏览器 + 右侧内容区 + 底部状态栏
工具以 tk.Toplevel 弹窗方式打开（有类的工具），或 subprocess（无类的工具）。
"""

import importlib.util
import io
from typing import Callable
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

# Windows GBK stdout/stderr → UTF-8，防止工具内 print(emoji) 抛 UnicodeEncodeError
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Cache-env hook is a holdover from the in-process ASR/TTS era: VideoCraft
# itself no longer loads ML weights (those moved to the aistack service),
# but apply_cache_env still wires user-data paths used elsewhere.
from core.paths import apply_cache_env as _apply_cache_env
_apply_cache_env()

from project import Project, get_recent_projects, file_icon
from operations import get_operations

# ── 工具注册表 ────────────────────────────────────────────────────────────────
# class: None → 用 subprocess 启动；有 class 名 → Toplevel 内嵌

_SRC = os.path.dirname(os.path.abspath(__file__))

TOOL_MAP = {
    "yt-dlp":      {"file": "tools/download/yt_dlp_tool.py",      "class": "YouTubeDownloader"},
    "speech2text": {"file": "tools/speech/speech2text.py",         "class": "Speech2TextApp"},
    "translate":   {"file": "tools/translate/translate_srt.py",    "class": "TranslateApp"},
    "subtitle":    {"file": "tools/subtitle/subtitle_tool.py",     "class": "SubtitleToolApp"},
    "word-subtitle": {"file": "tools/subtitle/word_subtitle.py",   "class": "WordSubtitleApp"},
    "srt-extract-subtitles":  {"file": "tools/subtitle/srt_tools.py", "class": "SrtExtractSubtitlesApp"},
    "srt-gen-segments":       {"file": "tools/subtitle/srt_tools.py", "class": "SrtGenerateSegmentsApp"},
    "srt-extract-paragraphs": {"file": "tools/subtitle/srt_tools.py", "class": "SrtExtractParagraphsApp"},
    "srt-refine":             {"file": "tools/subtitle/srt_tools.py", "class": "SrtRefineSegmentsApp"},
    "srt-gen-titles":         {"file": "tools/subtitle/srt_tools.py", "class": "SrtGenerateTitlesApp"},
    "srt-gen-pack":           {"file": "tools/subtitle/srt_tools.py", "class": "SrtGeneratePackApp"},
    "split-workbench": {"file": "tools/video/split_workbench.py",  "class": "SplitWorkbenchApp"},
    "concat-workbench": {"file": "tools/video/concat_workbench.py", "class": "ConcatWorkbenchApp"},
    "videotools":       {"file": "tools/video/video_tools.py", "class": "VideoToolsGUI"},
    "extract-audio":    {"file": "tools/video/video_tools.py", "class": "ExtractAudioApp"},
    "convert-bitrate":  {"file": "tools/video/video_tools.py", "class": "ConvertBitrateApp"},
    "adjust-volume":    {"file": "tools/video/video_tools.py", "class": "AdjustVolumeApp"},
    "extract-clip":     {"file": "tools/video/video_tools.py", "class": "ExtractClipApp"},
    "auto-split":       {"file": "tools/video/video_tools.py", "class": "AutoSplitApp"},
    "tts":            {"file": "tools/text2video/text2video.py", "class": "TTSApp"},
    "tts-srt":        {"file": "tools/text2video/text2video.py", "class": "SRTFromTextApp"},
    "tts-video":      {"file": "tools/text2video/text2video.py", "class": "AudioVideoApp"},
    "daily-news":     {"file": "tools/text2video/text2video.py", "class": "DailyNewsApp"},
    "media-composer": {"file": "tools/text2video/composer.py",   "class": "MediaSegmentComposerApp"},
    "tiktok-publish":   {"file": "tools/publish/tiktok_publish.py",  "class": "TikTokPublishApp"},
    "youtube-publish":  {"file": "tools/publish/youtube_publish.py", "class": "YouTubePublishApp"},
    "preferences":      {"file": "tools/preferences/preferences.py", "class": "PreferencesApp"},
    "ai-console":       {"file": "tools/router/ai_console.py",       "class": "AIConsoleApp"},
    "prompt-console":   {"file": "tools/router/prompt_console.py",   "class": "PromptConsoleApp"},
    "model-manager":    {"file": "tools/models/manager_window.py",   "class": "ModelManagerApp"},
    "clip-script":       {"file": "tools/program/clip_workbench.py",     "class": "ClipWorkbenchApp"},
}

# ── Tab 状态颜色 ──────────────────────────────────────────────────────────────

STATUS_COLORS = {
    "idle":    "#9e9e9e",   # gray: no task / freshly opened
    "running": "#2196F3",   # blue: running (distinct from warning orange)
    "done":    "#4caf50",   # green: success
    "warning": "#f0a500",   # orange: non-fatal, worth attention
    "error":   "#f44747",   # red: runtime failure
}


class ToolFrame(ttk.Frame):
    """
    工具容器。作为 master 传入工具类，静默吸收 Toplevel 专属方法
    (geometry / title / resizable)，并提供 set_status() 供工具回调。
    """
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._tool_title = ""
        self._set_status_cb: Callable[[str], None] | None = None  # 由 Hub 在创建后注入

    def geometry(self, spec=None):
        return ""

    def title(self, string=None):
        if string is not None:
            self._tool_title = string
        return self._tool_title

    def resizable(self, width=None, height=None):
        pass

    def set_status(self, status: str):
        """工具调用：set_status('running') / set_status('done')"""
        if self._set_status_cb:
            self._set_status_cb(status)


PREVIEW_TAB_KEY = "__preview__"


class TabBar(tk.Frame):
    """
    自定义横向 Tab 栏。每个 Tab 含彩色状态圆点 + 标题 + 关闭按钮。
    """
    def __init__(self, master, on_select, on_close, **kwargs):
        super().__init__(master, bg="#e8e8e8", height=34, **kwargs)
        self.pack_propagate(False)
        self._on_select = on_select
        self._on_close  = on_close
        self._tabs: dict[str, dict] = {}    # key → {frame, dot, title_lbl}
        self._active_key: str | None = None

    def add_tab(self, key: str, title: str, status: str = "idle",
                closable: bool = True) -> None:
        btn = tk.Frame(self, bg="#d0d0d0", cursor="hand2", padx=6, pady=0)
        btn.pack(side="left", padx=(4, 0), pady=3)

        dot = tk.Label(btn, text="●", fg=STATUS_COLORS[status],
                       bg="#d0d0d0", font=("", 8))
        dot.pack(side="left", pady=4)

        lbl = tk.Label(btn, text=f" {title} ", bg="#d0d0d0",
                       font=("Segoe UI", 9))
        lbl.pack(side="left", pady=4)

        cls_btn = None
        if closable:
            cls_btn = tk.Label(btn, text=" × ", bg="#d0d0d0",
                               font=("Segoe UI", 10), cursor="hand2",
                               fg="#666")
            cls_btn.pack(side="left", pady=4)
            cls_btn.bind("<Button-1>", lambda e, k=key: self._on_close(k))
            cls_btn.bind("<Enter>",    lambda e, w=cls_btn: w.configure(fg="#c00"))
            cls_btn.bind("<Leave>",    lambda e, w=cls_btn: w.configure(fg="#666"))

        for w in (btn, dot, lbl):
            w.bind("<Button-1>", lambda e, k=key: self._on_select(k))

        self._tabs[key] = {"frame": btn, "dot": dot, "title": lbl,
                           "close": cls_btn}
        self.set_active(key)

    def set_active(self, key: str) -> None:
        for k, t in self._tabs.items():
            is_active = (k == key)
            bg = "#ffffff" if is_active else "#d0d0d0"
            for w in t["frame"].winfo_children():
                w.configure(bg=bg)
            t["frame"].configure(bg=bg)
        self._active_key = key

    def set_status(self, key: str, status: str) -> None:
        if key in self._tabs:
            color = STATUS_COLORS.get(status, STATUS_COLORS["idle"])
            self._tabs[key]["dot"].configure(fg=color)

    def remove_tab(self, key: str) -> "str | None":
        """删除 Tab，返回应激活的下一个 key（无则返回 None）。"""
        if key not in self._tabs:
            return None
        self._tabs[key]["frame"].destroy()
        del self._tabs[key]
        remaining = list(self._tabs.keys())
        if remaining:
            nxt = remaining[-1]
            self.set_active(nxt)
            return nxt
        return None


# ── Sidebar helpers ──────────────────────────────────────────────────────────

def _sidebar_separator(parent: tk.Widget) -> None:
    """Thin horizontal divider between sidebar sections."""
    sep = tk.Frame(parent, bg="#d0d0d0", height=1)
    sep.pack(fill="x", padx=4, pady=4)


def _list_subtitle_srts(subtitles_dir: str) -> dict[str, str]:
    """Return {lang_code: filename} for every <lang>.srt file in subtitles/.

    Only files named like exactly `<lang>.srt` (no extra suffix) are
    surfaced — they're the canonical per-language subtitle files. Other
    files (e.g. raw ASR dumps, partials) are ignored for sidebar status.
    """
    if not os.path.isdir(subtitles_dir):
        return {}
    out: dict[str, str] = {}
    try:
        for name in os.listdir(subtitles_dir):
            if not name.lower().endswith(".srt"):
                continue
            stem = name[:-4]
            # Lang codes are 2-5 chars, alphabetic + optional dash (e.g. zh, en, zh-CN)
            if 1 < len(stem) <= 8 and all(c.isalpha() or c == "-" for c in stem):
                out[stem] = name
    except OSError:
        pass
    return out


def _fmt_duration(sec: float) -> str:
    """HH:MM:SS or MM:SS for source-video meta display."""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Hub 主类 ──────────────────────────────────────────────────────────────────

class VideoCraftHub:
    def __init__(self, root: tk.Tk, project: Project):
        """Construct the main hub. Project is REQUIRED (with-project single
        state, see docs/draft/project-restructure.md). To switch projects,
        set reopen_launcher=True and close the window — main loop reopens
        the launcher.
        """
        self.root = root
        self.project: Project = project
        # Signals to the main loop after Hub destroys itself:
        #   reopen_launcher=True + requested_project_path=None → show launcher
        #   reopen_launcher=True + requested_project_path=<p>  → open that project directly
        #   reopen_launcher=False                              → exit application
        self.reopen_launcher: bool = False
        self.requested_project_path: str | None = None

        self.root.title(f"VideoCraft — {self.project.name}")
        self.root.minsize(600, 400)

        # Load persisted layout (geometry / sash positions / zoom state).
        import hub_layout
        self._layout_store = hub_layout.load_layout()
        self.root.geometry(self._layout_store.get("geometry", "1280x800"))

        self._set_app_icon()

        # Wire the AI error dialog so any tool can call show_ai_error()
        # without plumbing the "open AI Console" navigation manually.
        from ui.ai_error_dialog import set_open_console_handler
        set_open_console_handler(lambda: self.open_tool("ai-console"))

        self._recent_menu: tk.Menu | None = None
        self._tool_instances: list = []   # 防止工具实例被 GC 回收
        self._last_snapshot: set = self._folder_snapshot(self.project.folder)
        self._status_var = tk.StringVar()
        self._status_var.set(self.project.folder)

        # Tab 系统
        self._tab_registry: dict[str, str] = {}      # tool_key → tool_key
        self._tab_frames: dict[str, ToolFrame] = {}  # tool_key → ToolFrame
        self._tab_bar: TabBar | None = None
        self._content_area: tk.Frame | None = None   # Tab 内容切换区
        self._preview_tab: tk.Frame | None = None   # permanent tab-0 content host
        self._preview_key: str | None = None        # identifies current preview content
        self._suppress_tree_select: bool = False    # set during sidebar refresh
        self._log_frame: tk.Frame | None = None
        self._log_strip: tk.Frame | None = None
        self._log_expanded: bool = False
        self._log_latest_var: tk.StringVar | None = None
        self._log_toggle_btn: tk.Button | None = None

        self._build_menu()
        self._build_layout()
        self._refresh_project_tab()
        self.refresh_sidebar()
        self._schedule_auto_refresh()

        # Apply zoom + sash positions after widgets have been realized.
        self.root.after(50, self._apply_saved_layout)

        # Persist layout on close.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_saved_layout(self):
        """Restore sash positions and zoom state after widgets are realized."""
        try:
            self.root.update_idletasks()
            sidebar_w = int(self._layout_store.get("sidebar_width", 320))
            self._pane.sashpos(0, sidebar_w)

            # Log panel: collapsed by default; only show if user persisted expanded.
            self._log_expanded = bool(self._layout_store.get("log_expanded", False))
            self._apply_log_state()

            if self._layout_store.get("zoomed", True):
                self.root.state("zoomed")

            # Restore last-selected sidebar tab. Tab order: 0=project, 1=resources.
            saved_tab = self._layout_store.get("sidebar_tab", "project")
            if saved_tab == "resources":
                try:
                    self._sidebar_nb.select(1)
                except Exception:
                    pass
        except Exception as e:
            from hub_logger import logger
            logger.error(f"应用保存的布局失败: {e}")

    def _on_close(self):
        """Persist layout then destroy the window."""
        import hub_layout
        try:
            zoomed = self.root.state() == "zoomed"
            if zoomed:
                # Take geometry from normal state so the next launch can restore it
                # accurately before re-zooming.
                self.root.state("normal")
                self.root.update_idletasks()
            try:
                idx = self._sidebar_nb.index(self._sidebar_nb.select())
                sidebar_tab = "resources" if idx == 1 else "project"
            except Exception:
                sidebar_tab = "project"
            payload = {
                "geometry":      self.root.geometry(),
                "zoomed":        zoomed,
                "sidebar_width": self._pane.sashpos(0),
                "log_expanded":  self._log_expanded,
                "sidebar_tab":   sidebar_tab,
            }
            hub_layout.save_layout(payload)
        except Exception as e:
            from hub_logger import logger
            logger.error(f"保存布局失败: {e}")
        self.root.destroy()

    def _set_app_icon(self):
        try:
            from PIL import Image
            _src = os.path.dirname(os.path.abspath(__file__))
            logo_path = os.path.join(_src, "..", "Logo", "logo.png")
            img = Image.open(logo_path).resize((64, 64), Image.Resampling.LANCZOS)
            import base64
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            self._app_icon = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))  # 持有引用防止 GC
            self.root.iconphoto(True, self._app_icon)
        except Exception:
            pass  # 图标加载失败不影响启动

    # ── 菜单 ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        from i18n import tr

        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File — Close Project returns to launcher; Open / new go through launcher.
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.file"), menu=file_menu)
        self._recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label=tr("menu.file.recent_projects"),
                              menu=self._recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label=tr("menu.file.close_project"),
                              command=self.close_project)
        file_menu.add_separator()
        file_menu.add_command(label=tr("menu.file.preferences"),
                              command=lambda: self.open_tool("preferences"))
        file_menu.add_separator()
        file_menu.add_command(label=tr("menu.file.exit"), command=self.root.quit)
        file_menu.configure(postcommand=self._rebuild_recent_menu)

        # The 「创作」 menu was removed in P4.6 — derivative creation lives
        # in the sidebar's Project tab (single entry point, less confusing).

        # Download
        dl_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.download"), menu=dl_menu)
        dl_menu.add_command(label=tr("menu.download.yt_dlp"),
                            command=lambda: self.open_tool(
                                "yt-dlp",
                                initial_file=self.project.folder))

        # Speech to text
        stt_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.speech"), menu=stt_menu)
        stt_menu.add_command(label=tr("menu.speech.lemonfox"),
                             command=lambda: self.open_tool("speech2text"))

        # Translate
        tr_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.translate"), menu=tr_menu)
        tr_menu.add_command(label=tr("menu.translate.srt"),
                            command=lambda: self.open_tool("translate"))

        # Video
        vid_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.video"), menu=vid_menu)
        vid_menu.add_command(label=tr("menu.video.subtitle_burn"),
                             command=lambda: self.open_tool("subtitle"))
        vid_menu.add_command(label=tr("menu.video.word_subtitle"),
                             command=lambda: self.open_tool("word-subtitle"))
        vid_menu.add_command(label=tr("menu.video.split_workbench"),
                             command=lambda: self.open_tool("split-workbench"))
        vid_menu.add_command(label=tr("menu.video.concat_workbench"),
                             command=lambda: self.open_tool("concat-workbench"))
        vid_menu.add_separator()
        vid_menu.add_command(label=tr("menu.video.extract_mp3"),
                             command=lambda: self.open_tool("extract-audio"))
        vid_menu.add_command(label=tr("menu.video.adjust_volume"),
                             command=lambda: self.open_tool("adjust-volume"))
        vid_menu.add_command(label=tr("menu.video.extract_clip"),
                             command=lambda: self.open_tool("extract-clip"))
        vid_menu.add_command(label=tr("menu.video.auto_split"),
                             command=lambda: self.open_tool("auto-split"))
        vid_menu.add_command(label=tr("menu.video.convert_bitrate"),
                             command=lambda: self.open_tool("convert-bitrate"))

        # Subtitle — pack (one-shot recommended) at top, single-step legacy
        # entries below as fallback for debugging or rerunning a single phase.
        sub_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.subtitle"), menu=sub_menu)
        sub_menu.add_command(label=tr("menu.subtitle.gen_pack"),
                             command=lambda: self.open_tool("srt-gen-pack"))
        sub_menu.add_separator()
        sub_menu.add_command(label=tr("menu.subtitle.extract_all"),
                             command=lambda: self.open_tool("srt-extract-subtitles"))
        sub_menu.add_command(label=tr("menu.subtitle.gen_segments"),
                             command=lambda: self.open_tool("srt-gen-segments"))
        sub_menu.add_command(label=tr("menu.subtitle.extract_paragraphs"),
                             command=lambda: self.open_tool("srt-extract-paragraphs"))
        sub_menu.add_command(label=tr("menu.subtitle.refine_segments"),
                             command=lambda: self.open_tool("srt-refine"))
        sub_menu.add_command(label=tr("menu.subtitle.gen_titles"),
                             command=lambda: self.open_tool("srt-gen-titles"))

        # Text to Video
        t2v_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.text2video"), menu=t2v_menu)
        t2v_menu.add_command(label=tr("menu.text2video.tts"),
                             command=lambda: self.open_tool("tts"))
        t2v_menu.add_command(label=tr("menu.text2video.srt_from_text"),
                             command=lambda: self.open_tool("tts-srt"))
        t2v_menu.add_command(label=tr("menu.text2video.audio_video"),
                             command=lambda: self.open_tool("tts-video"))
        t2v_menu.add_separator()
        t2v_menu.add_command(label=tr("menu.text2video.daily_news"),
                             command=lambda: self.open_tool("daily-news"))
        t2v_menu.add_command(label=tr("menu.text2video.composer"),
                             command=lambda: self.open_tool("media-composer"))

        # AI
        ai_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.ai"), menu=ai_menu)
        ai_menu.add_command(label=tr("menu.ai.console"),
                            command=lambda: self.open_tool("ai-console"))
        ai_menu.add_command(label=tr("menu.ai.prompt_console"),
                            command=lambda: self.open_tool("prompt-console"))
        ai_menu.add_command(label=tr("menu.ai.model_manager"),
                            command=lambda: self.open_tool("model-manager"))

        # Publish
        pub_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.publish"), menu=pub_menu)
        pub_menu.add_command(label=tr("menu.publish.tiktok"),
                             command=lambda: self.open_tool("tiktok-publish"))
        pub_menu.add_command(label=tr("menu.publish.youtube"),
                             command=lambda: self.open_tool("youtube-publish"))

        # Help
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=tr("menu.help"), menu=help_menu)
        help_menu.add_command(label=tr("menu.help.about"),
                              command=self._show_about)

    def _rebuild_recent_menu(self):
        assert self._recent_menu is not None
        from i18n import tr
        self._recent_menu.delete(0, "end")
        recents = get_recent_projects()
        if not recents:
            self._recent_menu.add_command(label=tr("menu.file.recent_empty"), state="disabled")
            return
        for path in recents:
            # Mark the current project but still allow clicking it (no-op switch).
            label = ("✓ " if path == self.project.folder else "  ") + path
            state = "disabled" if path == self.project.folder else "normal"
            self._recent_menu.add_command(
                label=label, state=state,
                command=lambda p=path: self.switch_to_project(p),
            )

    # ── 布局 ──────────────────────────────────────────────────────────────────

    def _build_layout(self):
        # Bottom strip = always-visible 1-line status bar (latest log + toggle).
        # Log panel sits above the strip, expanded only when toggled open.
        # Top container fills the rest. No PanedWindow on the vertical axis —
        # the log expansion is a binary state, not a drag-sized region.
        self._log_strip = tk.Frame(self.root, bg="#2d2d2d", height=24)
        self._log_strip.pack(side="bottom", fill="x")
        self._log_strip.pack_propagate(False)

        self._log_frame = tk.Frame(self.root, bd=1, relief="sunken", bg="#1e1e1e",
                                   height=160)
        self._log_frame.pack_propagate(False)
        # Not packed yet — _toggle_log() controls visibility.

        top_container = tk.Frame(self.root, bg="white")
        top_container.pack(side="top", fill="both", expand=True)

        # Horizontal PanedWindow inside the top container: left sidebar + right content.
        self._pane = ttk.PanedWindow(top_container, orient="horizontal")
        self._pane.pack(fill="both", expand=True)

        # ── 左：Sidebar (tabbed) ──
        sidebar_frame = tk.Frame(self._pane, width=320, bg="#f5f5f5")
        sidebar_frame.pack_propagate(False)
        self._pane.add(sidebar_frame, weight=0)

        from i18n import tr
        self._sidebar_nb = ttk.Notebook(sidebar_frame)
        self._sidebar_nb.pack(fill="both", expand=True)

        # ===== Project tab — Source / Subtitles / Derivatives dashboard (primary entry) =====
        prj_tab = tk.Frame(self._sidebar_nb, bg="#f5f5f5")
        self._sidebar_nb.add(prj_tab, text=tr("hub.sidebar.tab.project"))
        self._build_project_tab(prj_tab)

        # ===== Resources tab — file browser (index 1) =====
        res_tab = tk.Frame(self._sidebar_nb, bg="#f5f5f5")
        self._sidebar_nb.add(res_tab, text=tr("hub.sidebar.tab.resources"))

        sb_top = tk.Frame(res_tab, bg="#e8e8e8")
        sb_top.pack(fill="x")
        tk.Label(sb_top, text=tr("hub.sidebar.title"), font=("", 9, "bold"),
                 bg="#e8e8e8", fg="#555").pack(side="left", padx=8, pady=4)
        tk.Button(sb_top, text="⟳", width=3, relief="flat",
                  command=self.refresh_sidebar,
                  bg="#e8e8e8").pack(side="right", padx=4, pady=2)

        tree_frame = tk.Frame(res_tab)
        tree_frame.pack(fill="both", expand=True)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        self._tree = ttk.Treeview(tree_frame, show="tree",
                                  yscrollcommand=vsb.set, selectmode="browse")
        vsb.config(command=self._tree.yview)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._tree.bind("<Double-1>", self._on_tree_double_click)
        self._tree.bind("<Button-3>", self._on_tree_right_click)
        self._tree.bind("<<TreeviewOpen>>", self._on_tree_open)

        # ── 右：内容区 ──
        self._content = tk.Frame(self._pane, bg="white")
        self._pane.add(self._content, weight=1)

        # Tab bar is always packed — tab 0 (preview) is permanent.
        self._tab_bar = TabBar(self._content,
                               on_select=self._select_tab,
                               on_close=self._close_tab)
        self._tab_bar.pack(side="top", fill="x")
        # Tool/preview content switch area
        self._content_area = tk.Frame(self._content, bg="white")
        self._content_area.pack(fill="both", expand=True)

        # ── Permanent preview tab (key = PREVIEW_TAB_KEY, no close button) ──
        self._preview_tab = tk.Frame(self._content_area, bg="white")
        self._tab_frames[PREVIEW_TAB_KEY] = self._preview_tab
        self._tab_bar.add_tab(PREVIEW_TAB_KEY, "项目", closable=False)
        self._render_preview_placeholder()
        self._select_tab(PREVIEW_TAB_KEY)

        self._build_logpanel()

    # ── Preview tab content ──────────────────────────────────────────────────

    def _clear_preview_tab(self) -> None:
        """Destroy whatever's currently inside the preview tab frame."""
        for child in self._preview_tab.winfo_children():
            child.destroy()
        self._preview_key = None

    def _render_preview_placeholder(self) -> None:
        """Empty-state content for the preview tab (project name + hint)."""
        from i18n import tr
        self._clear_preview_tab()
        inner = tk.Frame(self._preview_tab, bg="white")
        inner.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(inner, text=self.project.name, font=("", 18, "bold"),
                 bg="white", fg="#333").pack(pady=(0, 8))
        tk.Label(inner, text=tr("hub.placeholder.hint"),
                 font=("", 10), bg="white", fg="#888",
                 wraplength=500, justify="center").pack()
        self._preview_key = "placeholder"

    def show_subtitle_preview(self, srt_path: str, lang_iso: str) -> None:
        """Sidebar click handler: show SRT contents + inline issues."""
        from ui.srt_preview_pane import build_srt_preview
        key = f"subtitle:{lang_iso}"
        if self._preview_key != key:
            self._clear_preview_tab()
            meta = self.project.meta.language
            source_lang = meta.source
            ref_path = None
            if source_lang and lang_iso != source_lang:
                cand = os.path.join(self.project.subtitles_dir,
                                     f"{source_lang}.srt")
                if os.path.isfile(cand):
                    ref_path = cand
            frame = build_srt_preview(
                self._preview_tab, srt_path,
                lang_iso=lang_iso,
                reference_srt_path=ref_path,
                on_fixed=self._refresh_subtitles_section,
            )
            frame.pack(fill="both", expand=True)
            self._preview_key = key
        self._select_tab(PREVIEW_TAB_KEY)

    def show_derivative_video_preview(self, video_path: str) -> None:
        """Sidebar click handler: preview a derivative output video."""
        if not os.path.isfile(video_path):
            return
        from ui.video_preview_pane import build_video_preview
        key = f"video:{os.path.abspath(video_path)}"
        if self._preview_key != key:
            self._clear_preview_tab()
            cache_dir = os.path.join(self.project.videocraft_dir, "cache")
            # Pick a derived title: "<type>/<inst>/<filename>"
            try:
                rel = os.path.relpath(video_path, self.project.derivatives_dir)
            except ValueError:
                rel = os.path.basename(video_path)
            frame = build_video_preview(
                self._preview_tab, video_path,
                cache_dir=cache_dir,
                title=rel,
            )
            frame.pack(fill="both", expand=True)
            self._preview_key = key
        self._select_tab(PREVIEW_TAB_KEY)

    def show_source_preview(self) -> None:
        """Sidebar click handler: show source/video.mp4 in the preview tab."""
        if self.project.source_status() != "ready":
            return
        from ui.source_preview_pane import build_source_preview
        key = "source"
        if self._preview_key != key:
            self._clear_preview_tab()
            frame = build_source_preview(self._preview_tab, self.project,
                                          on_modify=self._on_source_button)
            frame.pack(fill="both", expand=True)
            self._preview_key = key
        self._select_tab(PREVIEW_TAB_KEY)

    def _select_tab(self, key: str):
        assert self._tab_bar is not None
        for tf in self._tab_frames.values():
            tf.pack_forget()
        if key in self._tab_frames:
            self._tab_frames[key].pack(fill="both", expand=True)
        self._tab_bar.set_active(key)

    def _close_tab(self, key: str):
        """Close a tool tab; the permanent preview tab cannot be closed."""
        assert self._tab_bar is not None
        if key == PREVIEW_TAB_KEY:
            return
        if key in self._tab_frames:
            self._tab_frames[key].destroy()
            del self._tab_frames[key]
        self._tab_registry.pop(key, None)
        nxt = self._tab_bar.remove_tab(key)
        if nxt:
            self._select_tab(nxt)
        else:
            self._select_tab(PREVIEW_TAB_KEY)

    # ── Project 操作 ──────────────────────────────────────────────────────────

    def close_project(self):
        """File → 关闭项目: destroy Hub and signal main to reopen the launcher."""
        self.reopen_launcher = True
        self.requested_project_path = None
        # Run the normal close handler so layout is persisted, then destroy.
        self._on_close()

    def switch_to_project(self, path: str):
        """File → Recent → click another project: switch directly without
        bouncing through the launcher UI."""
        if not os.path.isdir(path):
            messagebox.showerror("VideoCraft", f"项目不存在:\n{path}")
            return
        self.reopen_launcher = True
        self.requested_project_path = path
        self._on_close()

    def refresh_sidebar(self):
        self._tree.delete(*self._tree.get_children())

        root_node = self._tree.insert(
            "", "end",
            text=f"  {self.project.name}",
            open=True,
            tags=("folder",)
        )
        for entry in self.project.get_files():
            icon = entry["icon"]
            label = f"  {icon}  {entry['name']}"
            node = self._tree.insert(root_node, "end", text=label,
                                     values=(entry["path"],),
                                     tags=("dir" if entry["is_dir"] else "file",))
            if entry["is_dir"]:
                self._tree.insert(node, "end", tags=("_placeholder",))

    # ── Sidebar: Project tab (Source / Subtitles / Derivatives) ────────────

    def _build_project_tab(self, parent: tk.Frame) -> None:
        """Build the sidebar 'Project' tab as a 3-section dashboard:

          [Source]      add / modify / status
          [Subtitles]   add / modify / regenerate / status (per-lang rows)
          [派生作品]    single [+ 添加] + dynamic type groups → instances

        Source and Subtitles drive the prerequisites; the 派生 [+ 添加]
        button is disabled until both are ready.
        """
        # Vertically-stacked sections inside a scrollable canvas would be
        # ideal but overkill for 3 fixed-height regions. Plain stacked frames
        # are fine — content fits and Tk handles overflow with the parent
        # PanedWindow's natural scrolling.

        # ── Section 1: Source ──
        self._source_section = tk.Frame(parent, bg="#f5f5f5")
        self._source_section.pack(fill="x", padx=4, pady=(4, 0))
        self._build_source_section(self._source_section)

        _sidebar_separator(parent)

        # ── Section 2: Subtitles ──
        self._subtitles_section = tk.Frame(parent, bg="#f5f5f5")
        self._subtitles_section.pack(fill="x", padx=4, pady=(0, 0))
        self._build_subtitles_section(self._subtitles_section)

        _sidebar_separator(parent)

        # ── Section 3: 派生作品 ──
        self._derivatives_section = tk.Frame(parent, bg="#f5f5f5")
        self._derivatives_section.pack(fill="both", expand=True,
                                       padx=4, pady=(0, 4))
        self._build_derivatives_section(self._derivatives_section)

    # ── Source section ────────────────────────────────────────────────────────

    def _build_source_section(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="Source", font=("", 9, "bold"),
                 bg="#f5f5f5", fg="#555", anchor="w"
                 ).pack(fill="x", padx=2, pady=(2, 2))

        self._source_status_var = tk.StringVar()
        self._source_status_lbl = tk.Label(
            parent, textvariable=self._source_status_var,
            bg="#f5f5f5", fg="#222", font=("", 9),
            anchor="w", justify="left", wraplength=280,
        )
        self._source_status_lbl.pack(fill="x", padx=4, pady=(0, 2))
        self._source_status_lbl.bind(
            "<Button-1>", lambda _e: self.show_source_preview())

        btn_row = tk.Frame(parent, bg="#f5f5f5")
        btn_row.pack(fill="x", padx=2, pady=(0, 4))
        self._source_primary_btn = tk.Button(
            btn_row, relief="flat", bg="#e8e8e8",
            command=self._on_source_button,
        )
        self._source_primary_btn.pack(side="left")

    def _on_source_button(self) -> None:
        """Add (when missing) or Modify (when present)."""
        from ui.source_add_dialog import show_source_add_dialog
        from ui.source_prepare_modal import SourcePrepareModal
        from ui.disclaimer_dialog import show_if_needed as show_disclaimer_if_needed
        from core.source_acquire import AcquireError, ERR_CANCELLED
        from core.project_schema import ORIGIN_LINK

        current_meta = self.project.meta
        preset = current_meta.source if self.project.source_status() == "ready" else None
        title = "修改源视频" if preset else "添加源视频"

        src = show_source_add_dialog(self.root, title=title, preset=preset)
        if src is None:
            return

        # First-time disclaimer for link mode.
        if src.origin == ORIGIN_LINK:
            if not show_disclaimer_if_needed(self.root):
                return

        # If we're modifying, nuke the existing source first so the modal's
        # rollback semantics work cleanly (cancel = "no source", not "old source").
        # We rebuild from current state on cancel by keeping a snapshot.
        modal = SourcePrepareModal(
            self.root, src,
            dest_video_path=self.project.source_video_path,
            dest_meta_path=self.project.source_meta_path,
        )
        try:
            result = modal.run()
        except AcquireError as e:
            if e.category == ERR_CANCELLED:
                return  # silent
            messagebox.showerror(
                "源视频准备失败",
                f"{e.message}\n\n{e.details[:400]}" if e.details else e.message,
                parent=self.root,
            )
            return
        except Exception as e:
            messagebox.showerror("源视频准备失败", str(e), parent=self.root)
            return

        # Back-fill metadata
        meta = self.project.meta
        meta.source = src  # capture origin/url/clip_range/imported_from
        if result.title:
            meta.source.title = result.title
        if result.duration_sec is not None:
            meta.source.duration_sec = result.duration_sec
        if result.width is not None:
            meta.source.width = result.width
        if result.height is not None:
            meta.source.height = result.height
        self.project.update_meta(meta)

        self._refresh_project_tab()

    # ── Subtitles section ─────────────────────────────────────────────────────

    def _build_subtitles_section(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="Subtitles", font=("", 9, "bold"),
                 bg="#f5f5f5", fg="#555", anchor="w"
                 ).pack(fill="x", padx=2, pady=(2, 2))

        # Container for per-language rows (rebuilt on every refresh).
        # When no SRTs exist, we show a single "✗ 无" label in here.
        self._subtitles_lang_box = tk.Frame(parent, bg="#f5f5f5")
        self._subtitles_lang_box.pack(fill="x", padx=4, pady=(0, 2))

        btn_row = tk.Frame(parent, bg="#f5f5f5")
        btn_row.pack(fill="x", padx=2, pady=(0, 4))
        self._subtitles_primary_btn = tk.Button(
            btn_row, relief="flat", bg="#e8e8e8",
            command=self._on_subtitles_primary,
        )
        self._subtitles_primary_btn.pack(side="left")

    def _on_subtitles_primary(self) -> None:
        """[+ 生成字幕] when no SRTs exist, else [+ 添加翻译]."""
        srt_files = _list_subtitle_srts(self.project.subtitles_dir)
        if not srt_files:
            self._invoke_asr()
        else:
            self._invoke_translate()

    # ── Subtitle pipeline drivers ─────────────────────────────────────────────

    def _invoke_asr(self, *, preset_lang_iso: str | None = "ASK") -> None:
        """Run ASR. When preset_lang_iso == "ASK" (default), show the dialog.
        Otherwise skip the dialog and use the provided ISO directly (used by
        the per-row regenerate action which already knows the language)."""
        from ui.subtitles_dialogs import show_asr_dialog
        from ui.subtitles_progress_modal import SubtitlesProgressModal
        from core.subtitle_pipeline import run_asr
        from core.ai.errors import AIError, Kind

        if preset_lang_iso == "ASK":
            choice = show_asr_dialog(self.root)
            if choice is None:
                return
            if choice["mode"] == "import":
                self._import_subtitle_file(choice["path"], choice["lang_iso"])
                return
            lang_iso = choice["lang_iso"]  # None = auto-detect
        else:
            lang_iso = preset_lang_iso

        def worker(progress_cb, cancel_token):
            return run_asr(
                self.project,
                source_lang_iso=lang_iso,
                progress_cb=progress_cb,
                cancel_token=cancel_token,
            )

        modal = SubtitlesProgressModal(self.root, worker, title="生成字幕")
        try:
            modal.run()
        except AIError as e:
            if e.kind == Kind.CANCELLED:
                return
            messagebox.showerror("ASR 失败", str(e), parent=self.root)
            return
        except FileNotFoundError as e:
            messagebox.showerror("源视频缺失", str(e), parent=self.root)
            return
        except Exception as e:
            messagebox.showerror("ASR 失败", repr(e), parent=self.root)
            return

        self._refresh_project_tab()

    def _invoke_translate(self, *, preset_target_iso: str | None = None) -> None:
        """Run translation. When preset_target_iso is None (default), show the
        target picker. Otherwise skip the dialog and re-translate the given
        ISO directly (used by per-row regenerate)."""
        from ui.subtitles_dialogs import show_translate_dialog
        from ui.subtitles_progress_modal import SubtitlesProgressModal
        from core.subtitle_pipeline import run_translate
        from core.ai.errors import AIError, Kind

        meta = self.project.meta
        src_iso = meta.language.source
        if not src_iso:
            messagebox.showerror(
                "VideoCraft", "项目未设置源语言,请先重新生成字幕。",
                parent=self.root)
            return

        if preset_target_iso is None:
            target_iso = show_translate_dialog(
                self.root, src_iso, meta.language.translated_to,
            )
            if target_iso is None:
                return
        else:
            target_iso = preset_target_iso

        def worker(progress_cb, cancel_token):
            return run_translate(
                self.project,
                target_lang_iso=target_iso,
                progress_cb=progress_cb,
                cancel_token=cancel_token,
            )

        modal = SubtitlesProgressModal(self.root, worker, title="添加翻译")
        try:
            modal.run()
        except AIError as e:
            if e.kind == Kind.CANCELLED:
                return
            messagebox.showerror("翻译失败", str(e), parent=self.root)
            return
        except (ValueError, FileNotFoundError) as e:
            messagebox.showerror("翻译失败", str(e), parent=self.root)
            return
        except Exception as e:
            messagebox.showerror("翻译失败", repr(e), parent=self.root)
            return

        self._refresh_project_tab()

    def _import_subtitle_file(self, src_path: str, lang_iso: str) -> None:
        """Copy an external SRT into subtitles/<lang>.srt and mark it as source."""
        import shutil, os
        dst = os.path.join(self.project.subtitles_dir, f"{lang_iso}.srt")
        os.makedirs(self.project.subtitles_dir, exist_ok=True)
        try:
            shutil.copy2(src_path, dst)
        except OSError as e:
            messagebox.showerror("导入失败", str(e), parent=self.root)
            return
        # Record as the source language (first imported SRT becomes the source).
        meta = self.project.meta
        if not meta.language.source:
            meta.language.source = lang_iso
        self.project.update_meta(meta)
        self._refresh_project_tab()

    # ── Derivatives section ───────────────────────────────────────────────────

    def _build_derivatives_section(self, parent: tk.Frame) -> None:
        head = tk.Frame(parent, bg="#f5f5f5")
        head.pack(fill="x", padx=2, pady=(2, 2))
        tk.Label(head, text="派生作品", font=("", 9, "bold"),
                 bg="#f5f5f5", fg="#555"
                 ).pack(side="left")
        self._derivative_add_btn = tk.Button(
            head, text="+ 添加", relief="flat", bg="#e8e8e8",
            command=self._on_new_derivative_hub,
        )
        self._derivative_add_btn.pack(side="right", padx=2)

        tree_frame = tk.Frame(parent, bg="#f5f5f5")
        tree_frame.pack(fill="both", expand=True)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        self._project_tree = ttk.Treeview(tree_frame, show="tree",
                                          yscrollcommand=vsb.set,
                                          selectmode="browse")
        vsb.config(command=self._project_tree.yview)
        self._project_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._project_tree.bind("<<TreeviewSelect>>",
                                self._on_derivative_tree_select)
        self._project_tree.bind("<Double-1>",
                                self._on_derivative_tree_double_click)
        # Right-click on instance → delete (compact UX, no separate button)
        self._project_tree.bind("<Button-3>",
                                self._on_derivative_tree_right_click)

        self._derivative_empty_lbl = tk.Label(
            parent, text="还没有派生作品。点 [+ 添加] 开始。",
            bg="#f5f5f5", fg="#888", font=("", 9),
            wraplength=280, justify="left",
        )

    # ── State refresh ─────────────────────────────────────────────────────────

    def _refresh_project_tab(self) -> None:
        if not hasattr(self, "_source_status_var"):
            return  # not built yet
        self._refresh_source_section()
        self._refresh_subtitles_section()
        self._refresh_derivatives_section()

    def _refresh_source_section(self) -> None:
        if self.project.source_status() == "ready":
            meta = self.project.meta.source
            label = "✓ " + (meta.title or "video.mp4")
            extras = []
            if meta.duration_sec:
                extras.append(_fmt_duration(meta.duration_sec))
            if meta.width and meta.height:
                extras.append(f"{meta.width}x{meta.height}")
            if extras:
                label += "\n   " + " · ".join(extras)
            self._source_status_var.set(label)
            self._source_primary_btn.config(text="修改")
            self._source_status_lbl.configure(cursor="hand2")
        else:
            self._source_status_var.set("✗ 无")
            self._source_primary_btn.config(text="+ 添加源视频")
            self._source_status_lbl.configure(cursor="")

    def _refresh_subtitles_section(self) -> None:
        from core import lang_names
        from core.subtitle_check import check_srt

        # Rebuild language rows from scratch each refresh — simplest and the
        # widget count is tiny (1~3 rows in practice).
        for child in self._subtitles_lang_box.winfo_children():
            child.destroy()

        srt_files = _list_subtitle_srts(self.project.subtitles_dir)
        meta = self.project.meta.language
        source_ready = self.project.source_status() == "ready"

        if not srt_files:
            tk.Label(self._subtitles_lang_box, text="✗ 无",
                     bg="#f5f5f5", fg="#222", font=("", 9),
                     anchor="w"
                     ).pack(fill="x")
            self._subtitles_primary_btn.config(
                text="+ 生成字幕",
                state="normal" if source_ready else "disabled",
            )
            return

        # Reference SRT for length-ratio checks on translations
        source_lang = meta.source
        ref_path = (os.path.join(self.project.subtitles_dir, f"{source_lang}.srt")
                    if source_lang else None)

        for lang in sorted(srt_files):
            try:
                lang_label = lang_names.friendly_name(lang, "zh")
            except Exception:
                lang_label = lang
            role = "源" if meta.source == lang else "翻译"
            srt_path = os.path.join(self.project.subtitles_dir, f"{lang}.srt")

            ref = ref_path if (lang != source_lang and ref_path
                              and os.path.isfile(ref_path)) else None
            check = check_srt(srt_path, expected_lang_iso=lang,
                              reference_srt_path=ref)

            # Worst-class drives the badge; advisory is silent in sidebar.
            if check.hard_count > 0:
                icon, color = "✗", "#c00"
                badge = f"  · {check.hard_count} 处错误"
            elif check.fixable_count > 0:
                icon, color = "⚠", "#a60"
                badge = ""  # fixable count appears on the action button
            else:
                icon, color = "✓", "#222"
                badge = ""

            row = tk.Frame(self._subtitles_lang_box, bg="#f5f5f5")
            row.pack(fill="x", pady=1)
            icon_lbl = tk.Label(row, text=icon, bg="#f5f5f5", fg=color,
                                font=("", 9), width=2)
            icon_lbl.pack(side="left")
            text_lbl = tk.Label(row, text=f"{role} ({lang_label}): {lang}.srt{badge}",
                                bg="#f5f5f5", fg=color, font=("", 9), anchor="w")
            text_lbl.pack(side="left", fill="x", expand=True)

            # Click anywhere on the row (label or icon) → SRT preview in right pane.
            for w in (row, icon_lbl, text_lbl):
                w.bind("<Button-1>",
                       lambda _e, p=srt_path, l=lang:
                           self.show_subtitle_preview(p, l))
                w.configure(cursor="hand2")

            # Right side (packed right→left so visual order is [↻] [🔧]):
            if check.hard_count == 0 and check.fixable_count > 0:
                tk.Button(row, text=f"🔧 修 {check.fixable_count}",
                          relief="flat", bg="#fff3cd", fg="#856404",
                          font=("", 8),
                          command=lambda p=srt_path:
                              self._on_quick_fix_subtitle(p),
                          ).pack(side="right", padx=2)
            is_source_row = (lang == source_lang)
            tk.Button(row, text="↻", relief="flat", bg="#e8e8e8",
                      font=("", 9), cursor="hand2",
                      command=lambda l=lang, s=is_source_row:
                          self._on_regenerate_subtitle(l, s),
                      ).pack(side="right", padx=2)

        self._subtitles_primary_btn.config(text="+ 添加翻译", state="normal")

    def _on_regenerate_subtitle(self, lang_iso: str, is_source: bool) -> None:
        """Per-row [↻]: re-run ASR for the source row or re-translate for a
        translated row. Confirms before overwriting since the operation can
        take minutes."""
        from core import lang_names
        try:
            display = lang_names.friendly_name(lang_iso, "zh")
        except Exception:
            display = lang_iso
        if is_source:
            prompt = (f"将重新运行 ASR 生成「{display}」字幕，"
                      f"现有 {lang_iso}.srt 会被覆盖。确定继续吗？")
        else:
            prompt = (f"将重新翻译生成「{display}」字幕，"
                      f"现有 {lang_iso}.srt 会被覆盖。确定继续吗？")
        if not messagebox.askyesno("重新生成字幕", prompt,
                                    default="no", parent=self.root):
            return
        if is_source:
            self._invoke_asr(preset_lang_iso=lang_iso)
        else:
            self._invoke_translate(preset_target_iso=lang_iso)

    def _on_quick_fix_subtitle(self, srt_path: str) -> None:
        """Sidebar one-click 🔧 修 N — apply auto-fixes silently and refresh."""
        from core.subtitle_check import apply_auto_fixes
        try:
            apply_auto_fixes(srt_path)
        except Exception as e:
            messagebox.showerror("清理失败", str(e), parent=self.root)
            return
        self._refresh_subtitles_section()
        # Refresh preview if it was showing this file.
        self._refresh_preview_if_match(srt_path)

    def _refresh_preview_if_match(self, srt_path: str) -> None:
        """Re-render SRT preview if it's currently showing srt_path."""
        if not self._preview_key or not self._preview_key.startswith("subtitle:"):
            return
        # Re-derive lang from path basename to avoid stale state mismatch.
        base = os.path.basename(srt_path)
        if base.endswith(".srt"):
            self.show_subtitle_preview(srt_path, base[:-4])

    def _refresh_derivatives_section(self) -> None:
        from core import derivative_types
        if not hasattr(self, "_project_tree"):
            return

        source_ready = self.project.source_status() == "ready"
        srt_files = _list_subtitle_srts(self.project.subtitles_dir)
        subs_ready = bool(srt_files)

        # Toggle the [+ 添加] button
        self._derivative_add_btn.config(
            state="normal" if (source_ready and subs_ready) else "disabled"
        )

        # Repopulate tree; suppress select callback so re-applying the prior
        # selection at the end doesn't auto-reopen a workbench the user just
        # closed.
        self._suppress_tree_select = True
        prev_sel = (self._project_tree.selection()[0]
                    if self._project_tree.selection() else None)
        self._project_tree.delete(*self._project_tree.get_children())
        self._derivative_empty_lbl.pack_forget()

        derivatives = self.project.list_derivatives()
        any_instance = False

        for t in derivative_types.all_types():
            instances = derivatives.get(t.type_name, [])
            if not instances:
                continue  # type group only shown when non-empty
            group_iid = f"type:{t.type_name}"
            self._project_tree.insert(
                "", "end", iid=group_iid, open=True,
                text=f"  {derivative_types.display_name(t.type_name)}",
                tags=("group",),
            )
            for inst in instances:
                inst_iid = f"{t.type_name}/{inst}"
                self._project_tree.insert(
                    group_iid, "end", iid=inst_iid,
                    text=f"  {inst}", tags=("instance",), open=True,
                )
                self._populate_instance_artifacts(inst_iid, t.type_name, inst)
                any_instance = True

        # Orphan types (forward-compat)
        for type_name, instances in derivatives.items():
            if derivative_types.get(type_name) is not None:
                continue
            group_iid = f"type:{type_name}"
            self._project_tree.insert(
                "", "end", iid=group_iid, open=True,
                text=f"  ({type_name})", tags=("group",),
            )
            for inst in instances:
                inst_iid = f"{type_name}/{inst}"
                self._project_tree.insert(
                    group_iid, "end", iid=inst_iid,
                    text=f"  {inst}", tags=("instance",), open=True,
                )
                self._populate_instance_artifacts(inst_iid, type_name, inst)
                any_instance = True

        if not any_instance:
            self._derivative_empty_lbl.pack(fill="x", padx=12, pady=12)

        if prev_sel and self._project_tree.exists(prev_sel):
            self._project_tree.selection_set(prev_sel)
            self._project_tree.see(prev_sel)
        # Re-arm select handler on next event-loop tick so the now-pending
        # <<TreeviewSelect>> from selection_set fires under suppression.
        self.root.after(0, lambda: setattr(self, "_suppress_tree_select", False))

    # ── Derivative tree interactions ──────────────────────────────────────────

    def _is_instance_selected(self) -> bool:
        sel = self._project_tree.selection()
        if not sel:
            return False
        return "instance" in self._project_tree.item(sel[0], "tags")

    def _selected_instance(self) -> tuple[str, str] | None:
        if not self._is_instance_selected():
            return None
        iid = self._project_tree.selection()[0]
        type_name, _, inst = iid.partition("/")
        return (type_name, inst) if type_name and inst else None

    def _populate_instance_artifacts(
        self, inst_iid: str, type_name: str, instance_name: str,
    ) -> None:
        """Insert child rows for shippable artifacts under a derivative
        instance: output video first, then any sibling SRT files. Skips
        silently if the instance hasn't produced anything yet."""
        inst_dir = self.project.derivative_dir(type_name, instance_name)
        if not os.path.isdir(inst_dir):
            return
        try:
            entries = sorted(os.listdir(inst_dir))
        except OSError:
            return
        # Output video first.
        video_name = "output.mp4"
        if video_name in entries:
            self._project_tree.insert(
                inst_iid, "end",
                iid=f"{inst_iid}::artifact::{video_name}",
                text=f"  ▶ {video_name}",
                tags=("artifact_video",),
            )
        # Adapted SRTs (subtitles_<iso>.srt).
        for name in entries:
            if name.startswith("subtitles_") and name.endswith(".srt"):
                self._project_tree.insert(
                    inst_iid, "end",
                    iid=f"{inst_iid}::artifact::{name}",
                    text=f"  📄 {name}",
                    tags=("artifact_srt",),
                )

    def _selected_artifact(self) -> tuple[str, str] | None:
        """Returns (kind, abs_path) for an artifact row, or None.
        kind ∈ {"video", "srt"}."""
        sel = self._project_tree.selection()
        if not sel:
            return None
        iid = sel[0]
        tags = self._project_tree.item(iid, "tags")
        if "artifact_video" not in tags and "artifact_srt" not in tags:
            return None
        # iid format: "<type>/<inst>::artifact::<filename>"
        if "::artifact::" not in iid:
            return None
        inst_part, _, filename = iid.partition("::artifact::")
        type_name, _, instance_name = inst_part.partition("/")
        if not (type_name and instance_name and filename):
            return None
        inst_dir = self.project.derivative_dir(type_name, instance_name)
        abs_path = os.path.join(inst_dir, filename)
        kind = "video" if "artifact_video" in tags else "srt"
        return (kind, abs_path)

    def _on_derivative_tree_select(self, _event=None):
        """Sidebar tree single-click:
          - instance row → open/focus its workbench tab
          - artifact row → preview in the project tab"""
        if self._suppress_tree_select:
            return
        # Artifact row?
        art = self._selected_artifact()
        if art is not None:
            kind, path = art
            if kind == "video":
                self.show_derivative_video_preview(path)
            elif kind == "srt":
                base = os.path.basename(path)
                # Strip "subtitles_" prefix to recover the language hint
                # for the preview pane header (best-effort).
                lang_hint = base.removeprefix("subtitles_").removesuffix(".srt")
                self.show_subtitle_preview(path, lang_hint)
            return
        # Instance row?
        info = self._selected_instance()
        if info is None:
            return
        type_name, instance_name = info
        self._open_workbench_for_type(type_name, instance_name)

    def _on_derivative_tree_double_click(self, _event=None):
        # Single-click already opens; keep this as a no-op alias.
        self._on_derivative_tree_select()

    def _on_derivative_tree_right_click(self, event):
        item = self._project_tree.identify_row(event.y)
        if not item:
            return
        self._project_tree.selection_set(item)
        info = self._selected_instance()
        if info is None:
            return
        type_name, instance_name = info
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(
            label="打开",
            command=lambda: self._open_workbench_for_type(type_name, instance_name),
        )
        menu.add_separator()
        menu.add_command(
            label="删除",
            command=lambda: self._delete_derivative(type_name, instance_name),
        )
        menu.tk_popup(event.x_root, event.y_root)

    def _on_new_derivative_hub(self):
        from core import derivative_types
        from ui.new_derivative_dialog import show_type_picker, show_instance_namer

        types = derivative_types.all_types()
        if not types:
            messagebox.showinfo("VideoCraft", "没有可用的派生类型。", parent=self.root)
            return

        # Single registered type → skip type-picker, go straight to naming.
        if len(types) == 1:
            type_name = types[0].type_name
            inst_name = show_instance_namer(self.root, self.project, type_name)
            if inst_name is None:
                return
        else:
            picked = show_type_picker(self.root, self.project)
            if picked is None:
                return
            type_name, inst_name = picked

        try:
            self.project.create_derivative_instance(type_name, inst_name)
        except FileExistsError as e:
            messagebox.showerror("VideoCraft", str(e))
            return
        except ValueError as e:
            messagebox.showerror("VideoCraft", f"Invalid name: {e}")
            return

        self._refresh_project_tab()
        new_iid = f"{type_name}/{inst_name}"
        if self._project_tree.exists(new_iid):
            self._project_tree.selection_set(new_iid)
            self._project_tree.see(new_iid)
        self._open_workbench_for_type(type_name, inst_name)

    def _delete_derivative(self, type_name: str, instance_name: str) -> None:
        if not messagebox.askyesno(
                "删除派生",
                f"确定删除派生 {type_name}/{instance_name}?\n"
                "对应目录及其内容将被删除,无法恢复。",
                default="no"):
            return
        import shutil
        inst_dir = self.project.derivative_dir(type_name, instance_name)
        try:
            shutil.rmtree(inst_dir)
        except OSError as e:
            messagebox.showerror("VideoCraft", f"删除失败: {e}")
            return
        self._refresh_project_tab()

    def _open_workbench_for_type(
        self, type_name: str, instance_name: str | None = None,
    ) -> None:
        from core import derivative_types
        t = derivative_types.get(type_name)
        if t is None:
            messagebox.showerror(
                "VideoCraft", f"未知派生类型: {type_name}")
            return
        # Compound tab key so each derivative instance has its own tab
        # (字幕视频/default vs 字幕视频/v2 are two different workspaces).
        tab_key = (f"{t.tool_key}:{instance_name}"
                   if instance_name else t.tool_key)
        self.open_tool(
            t.tool_key,
            initial_file=self.project.folder,
            project=self.project,
            instance_name=instance_name,
            tab_key=tab_key,
        )

    def _schedule_auto_refresh(self):
        """每 2 秒检查文件夹变化，有变化时自动刷新 Sidebar。"""
        if os.path.isdir(self.project.folder):
            snapshot = self._folder_snapshot(self.project.folder)
            if snapshot != self._last_snapshot:
                self._last_snapshot = snapshot
                self.refresh_sidebar()
            # Project tab refresh: cheap (a few dir listings + subtitle
            # checks are millisecond-level), and the project tab tree
            # needs to pick up derivative artifacts written by the
            # workbench tabs (output.mp4, subtitles_<iso>.srt) that
            # land 1-2 levels below project root — out of reach of the
            # top-level folder snapshot above.
            self._refresh_project_tab()
        self.root.after(2000, self._schedule_auto_refresh)

    def _folder_snapshot(self, folder: str) -> set:
        """返回文件夹内所有条目的 (名称, 大小, 修改时间) 集合。"""
        result = set()
        try:
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                try:
                    st = os.stat(path)
                    result.add((name, st.st_size, round(st.st_mtime)))
                except OSError:
                    result.add((name,))
        except OSError:
            pass
        return result

    def _on_tree_double_click(self, event):
        item = self._tree.focus()
        vals = self._tree.item(item, "values")
        if vals:
            path = vals[0]
            if os.path.isfile(path):
                os.startfile(path)
            elif os.path.isdir(path):
                is_open = self._tree.item(item, "open")
                self._tree.item(item, open=not is_open)

    def _on_tree_open(self, _event):
        item = self._tree.focus()
        children = self._tree.get_children(item)
        # 如果只有一个占位子节点，替换为真实内容
        if len(children) == 1 and "_placeholder" in self._tree.item(children[0], "tags"):
            self._tree.delete(children[0])
            vals = self._tree.item(item, "values")
            if not vals:
                return
            path = vals[0]
            try:
                names = sorted(os.listdir(path), key=lambda s: s.lower())
            except OSError:
                return
            for name in names:
                full = os.path.join(path, name)
                is_dir = os.path.isdir(full)
                icon = file_icon(name, is_dir)
                node = self._tree.insert(item, "end", text=f"  {icon}  {name}",
                                         values=(full,),
                                         tags=("dir" if is_dir else "file",))
                if is_dir:
                    self._tree.insert(node, "end", tags=("_placeholder",))

    def _on_tree_right_click(self, event):
        item = self._tree.identify_row(event.y)
        if not item:
            return
        self._tree.selection_set(item)
        self._tree.focus(item)

        vals = self._tree.item(item, "values")
        if not vals:
            return
        file_path = vals[0]

        menu = tk.Menu(self.root, tearoff=0)
        ops = get_operations(file_path)

        for op in ops:
            if op.separator_before and menu.index("end") is not None:
                menu.add_separator()
            menu.add_command(
                label=op.label,
                command=lambda o=op, fp=file_path: self._run_operation(o, fp)
            )

        menu.add_separator()
        menu.add_command(
            label="删除",
            command=lambda fp=file_path: self._delete_item(fp)
        )

        menu.tk_popup(event.x_root, event.y_root)

    def _delete_item(self, file_path: str):
        name = os.path.basename(file_path)
        kind = "文件夹" if os.path.isdir(file_path) else "文件"
        confirmed = messagebox.askyesno(
            "确认删除",
            f"将 {kind} 移至回收站：\n\n{name}\n\n确定吗？",
            default="no"
        )
        if not confirmed:
            return
        try:
            import send2trash  # noqa: PLC0415
            send2trash.send2trash(file_path)
        except ImportError:
            # send2trash 未安装，回退到 Windows Shell API
            import ctypes
            from ctypes import wintypes
            class SHFILEOPSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("hwnd",    wintypes.HWND),
                    ("wFunc",   ctypes.c_uint),
                    ("pFrom",   ctypes.c_wchar_p),
                    ("pTo",     ctypes.c_wchar_p),
                    ("fFlags",  ctypes.c_ushort),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", ctypes.c_wchar_p),
                ]
            FO_DELETE  = 0x0003
            FOF_ALLOWUNDO      = 0x0040
            FOF_NOCONFIRMATION = 0x0010
            FOF_SILENT         = 0x0004
            op = SHFILEOPSTRUCT()
            op.wFunc  = FO_DELETE
            op.pFrom  = file_path + "\0"
            op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
            ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        except Exception as e:
            messagebox.showerror("删除失败", str(e))
            return
        self.refresh_sidebar()

    def _run_operation(self, op, file_path: str):
        if op.handler in ("quick", "common"):
            self._run_quick(op, file_path)
        else:
            self.open_tool(op.tool_key, initial_file=file_path)

    def _run_quick(self, op, file_path: str):
        def task():
            try:
                result = op.func(file_path,
                                 progress_callback=self._update_status)
                if result:
                    self.root.after(0, lambda r=result: self._status_var.set(
                        f"完成: {os.path.basename(r)}"))
            except Exception as e:
                from hub_logger import logger
                self.root.after(0, lambda err=str(e): logger.error(err))
        threading.Thread(target=task, daemon=True).start()

    # ── 日志面板 ─────────────────────────────────────────────────────────────

    def _build_logpanel(self):
        """Collapsible log: always-visible 1-line status strip at the bottom,
        plus an expandable multi-line text area above it. Click the strip
        (or the ▲ button) to toggle expansion."""
        from hub_logger import logger
        from i18n import tr

        # ── Status strip (always visible, ~24px) ──
        assert self._log_strip is not None
        self._log_latest_var = tk.StringVar(value="")
        latest_lbl = tk.Label(
            self._log_strip, textvariable=self._log_latest_var,
            bg="#2d2d2d", fg="#aaa", font=("Consolas", 9),
            anchor="w", padx=8,
        )
        latest_lbl.pack(side="left", fill="x", expand=True)
        # Whole strip is clickable → toggle.
        for w in (self._log_strip, latest_lbl):
            w.bind("<Button-1>", lambda _e: self._toggle_log())
            w.configure(cursor="hand2")

        self._log_toggle_btn = tk.Button(
            self._log_strip, text="▲ 日志",
            bg="#2d2d2d", fg="#888", relief="flat",
            font=("", 9), cursor="hand2", padx=8,
            command=self._toggle_log,
        )
        self._log_toggle_btn.pack(side="right")

        # ── Expanded log panel (hidden by default) ──
        assert self._log_frame is not None
        title_bar = tk.Frame(self._log_frame, bg="#2d2d2d")
        title_bar.pack(fill="x")
        tk.Label(title_bar, text=tr("hub.log.title"), bg="#2d2d2d", fg="#aaa",
                 font=("", 9), padx=6).pack(side="left")
        tk.Button(title_bar, text="复制", bg="#2d2d2d", fg="#888",
                  relief="flat", font=("", 8), cursor="hand2",
                  command=self._copy_log).pack(side="right", padx=4, pady=1)
        tk.Button(title_bar, text=tr("hub.log.clear"), bg="#2d2d2d", fg="#888",
                  relief="flat", font=("", 8), cursor="hand2",
                  command=self._clear_log).pack(side="right", padx=4, pady=1)

        self._log_text = tk.Text(
            self._log_frame, bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 9), state="disabled",
            wrap="word", height=4, relief="flat",
            selectbackground="#264f78",
        )
        vsb = tk.Scrollbar(self._log_frame, command=self._log_text.yview,
                           bg="#2d2d2d")
        self._log_text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True, padx=2, pady=(0, 2))

        self._log_text.tag_configure("ts",      foreground="#555")
        self._log_text.tag_configure("info",    foreground="#d4d4d4")
        self._log_text.tag_configure("warning", foreground="#f0a500")
        self._log_text.tag_configure("error",   foreground="#f44747")

        logger.register_handler(self._on_log)

    def _toggle_log(self) -> None:
        """Expand or collapse the log panel."""
        self._log_expanded = not self._log_expanded
        self._apply_log_state()

    def _apply_log_state(self) -> None:
        assert self._log_frame is not None and self._log_toggle_btn is not None
        if self._log_expanded:
            # Insert above the status strip.
            self._log_frame.pack(side="bottom", fill="both", expand=False,
                                 before=self._log_strip)
            self._log_toggle_btn.config(text="▼ 收起")
        else:
            self._log_frame.pack_forget()
            self._log_toggle_btn.config(text="▲ 日志")

    def _copy_log(self) -> None:
        try:
            text = self._log_text.get("1.0", "end-1c")
        except tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _on_log(self, level: str, msg: str, ts: str):
        """logger 回调（可能来自任意线程），转到主线程追加。"""
        self.root.after(0, self._append_log, level, msg, ts)

    def _append_log(self, level: str, msg: str, ts: str):
        prefix = {"info": "✓", "warning": "⚠", "error": "✗"}.get(level, "·")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", f"{ts} ", "ts")
        self._log_text.insert("end", f"{prefix}  {msg}\n", level)
        self._log_text.configure(state="disabled")
        self._log_text.see("end")
        # Mirror the latest line into the always-visible status strip.
        if self._log_latest_var is not None:
            single = msg.replace("\n", " ").strip()
            if len(single) > 200:
                single = single[:200] + "…"
            self._log_latest_var.set(f"{prefix}  {single}")

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")
        if self._log_latest_var is not None:
            self._log_latest_var.set("")

    def _update_status(self, msg: str):
        """进度回调（线程安全），写入日志面板。"""
        from hub_logger import logger
        self.root.after(0, lambda m=msg: logger.info(m))

    # ── 工具启动 ──────────────────────────────────────────────────────────────

    def open_tool(
        self, key: str,
        initial_file: str | None = None,
        project: "Project | None" = None,
        instance_name: str | None = None,
        tab_key: str | None = None,
    ):
        cfg = TOOL_MAP.get(key)
        if cfg is None:
            messagebox.showerror("错误", f"未知工具：{key}")
            return

        file_path = os.path.join(_SRC, cfg["file"])
        if not os.path.exists(file_path):
            messagebox.showerror("错误", f"工具文件不存在：\n{file_path}")
            return

        if cfg["class"] is None:
            self._open_subprocess(file_path, initial_file=initial_file)
        else:
            self._open_in_tab(
                file_path, cfg["class"], key,
                initial_file=initial_file,
                project=project,
                instance_name=instance_name,
                tab_key=tab_key,
            )

    def _open_toplevel(self, file_path: str, class_name: str, initial_file: str | None = None):
        try:
            mod_name = os.path.splitext(os.path.basename(file_path))[0]
            spec = importlib.util.spec_from_file_location(mod_name, file_path)
            assert spec is not None and spec.loader is not None
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cls  = getattr(mod, class_name)
            win  = tk.Toplevel(self.root)
            win.transient(self.root)
            app  = cls(win, initial_file=initial_file) if initial_file else cls(win)
            self._tool_instances.append(app)
            win.bind("<Destroy>", lambda e, a=app: self._tool_instances.remove(a)
                     if a in self._tool_instances else None)
        except Exception as e:
            messagebox.showerror("启动失败", str(e))

    def _open_in_tab(
        self, file_path: str, class_name: str, tool_key: str,
        initial_file: str | None = None,
        project: "Project | None" = None,
        instance_name: str | None = None,
        tab_key: str | None = None,
    ):
        # tab_key lets one tool open as multiple tabs (one per derivative
        # instance). Falls back to tool_key for plain non-project tools.
        registry_key = tab_key or tool_key
        if registry_key in self._tab_registry:
            self._select_tab(registry_key)
            return
        try:
            mod_name = os.path.splitext(os.path.basename(file_path))[0]
            spec = importlib.util.spec_from_file_location(mod_name, file_path)
            assert spec is not None and spec.loader is not None
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cls  = getattr(mod, class_name)

            assert self._content_area is not None
            tf = ToolFrame(self._content_area)
            tab_bar = self._tab_bar
            assert tab_bar is not None
            tf._set_status_cb = lambda s, k=registry_key: tab_bar.set_status(k, s)

            # Tools take an optional initial_file (legacy plumbing). Project-
            # aware tools also take project / instance_name (see below).
            kwargs: dict = {}
            if initial_file is not None:
                kwargs["initial_file"] = initial_file
            # Project-aware tools: subtitle_tool is the first one wired here
            # (字幕视频 workbench). Others can opt in by accepting these kwargs.
            if tool_key == "subtitle" and project is not None:
                kwargs["project"] = project
                kwargs["instance_name"] = instance_name
            app = cls(tf, **kwargs) if kwargs else cls(tf)

            label = tf._tool_title or class_name
            tab_bar.add_tab(registry_key, label, status="idle")
            self._tab_frames[registry_key]   = tf
            self._tab_registry[registry_key] = registry_key
            self._tool_instances.append(app)

            self._select_tab(registry_key)
        except Exception as e:
            messagebox.showerror("启动失败", str(e))

    def _open_subprocess(self, file_path: str, initial_file: str | None = None):
        venv_python = os.path.join(_SRC, "..", "myenv", "Scripts", "python.exe")
        python = venv_python if os.path.exists(venv_python) else sys.executable
        try:
            cmd = [python, file_path]
            if initial_file:
                cmd.append(initial_file)
            subprocess.Popen(cmd)
        except Exception as e:
            messagebox.showerror("启动失败", str(e))

    # ── 关于 ──────────────────────────────────────────────────────────────────

    def _show_about(self):
        messagebox.showinfo(
            "关于 VideoCraft",
            "VideoCraft\n视频生产工具集\n\n"
            "核心流程：下载 → 语音转字幕 → 翻译 → 字幕烧录"
        )



# ── 入口 ──────────────────────────────────────────────────────────────────────

def _setup_dpi_and_scaling(root: tk.Tk) -> None:
    """Bump tk scaling to compensate for per-monitor DPI awareness so fonts
    and widgets keep their logical inch size."""
    try:
        import ctypes
        dpi = ctypes.windll.user32.GetDpiForSystem()
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass


def _run() -> None:
    """Application main loop: launcher → hub → (launcher | exit).

    The launcher returns a Project (or None to quit). Hub may signal
    reopen_launcher=True with optional requested_project_path to switch
    project directly (skipping the launcher UI for File → Recent clicks).
    """
    # Per-monitor DPI awareness MUST be enabled before any Tk window is
    # created. Required by ui.web_preview.WebPreviewFrame (clip-script
    # preview etc.) — SetParent across DPI-awareness boundaries breaks
    # WebView2 sizing.
    try:
        from ui.web_preview import setup_dpi_aware
        setup_dpi_aware()
    except Exception:
        pass

    from launcher import run_launcher

    next_project_path: str | None = None

    while True:
        # Acquire a Project, either by direct request (File → Recent
        # switching) or via the launcher window.
        if next_project_path is not None:
            try:
                project = Project.open(next_project_path)
            except Exception as e:
                messagebox.showerror("打开失败", f"{next_project_path}\n{e}")
                next_project_path = None
                continue
            next_project_path = None
        else:
            project = run_launcher()
            if project is None:
                return  # user closed launcher → quit app

        # Run the Hub for the chosen project.
        root = tk.Tk()
        _setup_dpi_and_scaling(root)
        hub = VideoCraftHub(root, project)
        root.mainloop()

        if not hub.reopen_launcher:
            return  # Hub closed via X or File→Exit → quit app
        next_project_path = hub.requested_project_path  # may be None → launcher


if __name__ == "__main__":
    _run()
