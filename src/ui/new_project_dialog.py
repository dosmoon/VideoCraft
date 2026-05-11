"""New Project dialog (P2).

Modal dialog gathering everything needed to create a project:
  - Source: link URL OR local file
  - Project name (auto-filled, editable)
  - Parent directory (default + remember last)
  - Optional time range (collapsed advanced section)
  - Permanent small-text copyright disclaimer

Validates in-dialog; failure highlights the offending field without
closing. On success returns a NewProjectRequest dataclass — caller
(launcher) then orchestrates: skeleton mkdir → disclaimer (first time
only) → source-prepare modal → final meta write.

Wording is neutral: never mentions specific sites (YouTube/B站/…).
"""

from __future__ import annotations

import os
import re
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, ttk
from typing import Optional

from core import settings
from core.project_schema import Source, ClipRange, ORIGIN_LINK, ORIGIN_LOCAL
from core.source_acquire import (
    fetch_link_info, parse_hms, AcquireError,
)


# Settings keys used by this dialog (also referenced by Preferences once added).
SETTINGS_KEY_LAST_PARENT = "last_parent_dir"
SETTINGS_KEY_DEFAULT_PARENT = "default_parent_dir"

# Video extension whitelist for the local-file picker.
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv")


@dataclass
class NewProjectRequest:
    """What the dialog returns on success."""
    parent_dir: str
    name: str
    source: Source


def show_new_project_dialog(parent: tk.Misc) -> Optional[NewProjectRequest]:
    """Show the dialog. Returns NewProjectRequest or None if cancelled."""
    return _NewProjectDialog(parent).run()


# ── Implementation ────────────────────────────────────────────────────────────

def _default_parent_dir() -> str:
    """Settings → last used → ~/Documents/VideoCraft (Windows) or ~/VideoCraft."""
    v = settings.get(SETTINGS_KEY_DEFAULT_PARENT)
    if isinstance(v, str) and v:
        return v
    v = settings.get(SETTINGS_KEY_LAST_PARENT)
    if isinstance(v, str) and v and os.path.isdir(v):
        return v
    if os.name == "nt":
        return os.path.join(os.path.expanduser("~"), "Documents", "VideoCraft")
    return os.path.join(os.path.expanduser("~"), "VideoCraft")


_NAME_BAD_RE = re.compile(r'[\\/:\*\?"<>\|]')


def _sanitize_name(s: str) -> str:
    """Strip filesystem-forbidden chars and surrounding whitespace."""
    return _NAME_BAD_RE.sub("", s).strip()


class _NewProjectDialog:
    def __init__(self, parent: tk.Misc) -> None:
        self._result: Optional[NewProjectRequest] = None

        self.win = tk.Toplevel(parent)
        self.win.title("新建项目")
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # State vars
        self._origin_var = tk.StringVar(value=ORIGIN_LINK)
        self._url_var = tk.StringVar()
        self._local_path_var = tk.StringVar()
        self._name_var = tk.StringVar()
        self._parent_var = tk.StringVar(value=_default_parent_dir())
        self._advanced_open = tk.BooleanVar(value=False)
        self._range_start_var = tk.StringVar()
        self._range_end_var = tk.StringVar()
        # Holds the title we got from fetch_link_info() to keep across edits.
        self._fetched_title: str | None = None

        self._build_ui()

        # Center over parent.
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - w) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - h) // 2
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

        self._update_source_mode()

    def _build_ui(self) -> None:
        body = ttk.Frame(self.win, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="新建项目",
                  font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")

        # ── Source type ──
        src_box = ttk.LabelFrame(body, text="源视频", padding=10)
        src_box.pack(fill="x", pady=(12, 8))

        radios = ttk.Frame(src_box)
        radios.pack(fill="x")
        ttk.Radiobutton(radios, text="视频链接", value=ORIGIN_LINK,
                        variable=self._origin_var,
                        command=self._update_source_mode
                        ).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(radios, text="本地文件", value=ORIGIN_LOCAL,
                        variable=self._origin_var,
                        command=self._update_source_mode
                        ).pack(side="left")

        # Per-mode body (swapped via grid_remove)
        self._link_row = ttk.Frame(src_box)
        self._link_row.pack(fill="x", pady=(8, 0))
        self._url_entry = ttk.Entry(self._link_row, textvariable=self._url_var,
                                    width=46)
        self._url_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self._link_row, text="获取视频信息",
                   command=self._on_fetch_info
                   ).pack(side="left", padx=(8, 0))

        self._local_row = ttk.Frame(src_box)
        # Pack only when local mode active; we'll handle in _update_source_mode.
        self._local_path_entry = ttk.Entry(
            self._local_row, textvariable=self._local_path_var, width=46
        )
        self._local_path_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self._local_row, text="选择文件...",
                   command=self._on_pick_local
                   ).pack(side="left", padx=(8, 0))

        # ── Name + parent dir ──
        meta_box = ttk.Frame(body)
        meta_box.pack(fill="x", pady=(8, 8))

        ttk.Label(meta_box, text="项目名:", width=8, anchor="e"
                  ).grid(row=0, column=0, sticky="e", padx=(0, 6), pady=4)
        ttk.Entry(meta_box, textvariable=self._name_var, width=40
                  ).grid(row=0, column=1, sticky="we", pady=4)

        ttk.Label(meta_box, text="保存到:", width=8, anchor="e"
                  ).grid(row=1, column=0, sticky="e", padx=(0, 6), pady=4)
        parent_row = ttk.Frame(meta_box)
        parent_row.grid(row=1, column=1, sticky="we", pady=4)
        ttk.Entry(parent_row, textvariable=self._parent_var
                  ).pack(side="left", fill="x", expand=True)
        ttk.Button(parent_row, text="浏览...", command=self._on_pick_parent
                   ).pack(side="left", padx=(6, 0))

        meta_box.columnconfigure(1, weight=1)

        # ── Advanced (collapsed by default) ──
        adv_toggle = ttk.Checkbutton(
            body, text="高级选项",
            variable=self._advanced_open,
            command=self._toggle_advanced,
        )
        adv_toggle.pack(anchor="w", pady=(8, 0))

        self._adv_frame = ttk.Frame(body, padding=(20, 4, 0, 0))
        # don't pack yet — toggled

        ttk.Label(self._adv_frame, text="源视频范围(可选):",
                  font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        rng_row = ttk.Frame(self._adv_frame)
        rng_row.pack(anchor="w", pady=(4, 4))
        ttk.Label(rng_row, text="起 ").pack(side="left")
        ttk.Entry(rng_row, textvariable=self._range_start_var, width=10
                  ).pack(side="left")
        ttk.Label(rng_row, text="  止 ").pack(side="left")
        ttk.Entry(rng_row, textvariable=self._range_end_var, width=10
                  ).pack(side="left")

        ttk.Label(self._adv_frame,
                  text=("留空 = 完整下载/拷贝;\n"
                        "已知精彩段时填入可节省下载和磁盘占用。\n"
                        "格式: HH:MM:SS 或 MM:SS"),
                  font=("Microsoft YaHei UI", 8), foreground="#888",
                  justify="left"
                  ).pack(anchor="w", pady=(2, 0))

        # ── Permanent disclaimer ──
        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=(14, 6))
        ttk.Label(
            body,
            text="ⓘ  由你确认对所提供内容的合法使用权,版权责任自负。",
            font=("Microsoft YaHei UI", 8), foreground="#666",
        ).pack(anchor="w")

        # ── Buttons ──
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="取消", command=self._on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="创建项目", command=self._on_create
                   ).pack(side="right")

        # Inline error label below buttons — appears on validation fail.
        self._error_var = tk.StringVar()
        self._error_label = ttk.Label(
            body, textvariable=self._error_var,
            foreground="#c00", font=("Microsoft YaHei UI", 9),
            wraplength=480,
        )
        self._error_label.pack(anchor="w", pady=(8, 0))

    # ── Visibility toggles ────────────────────────────────────────────────────

    def _update_source_mode(self) -> None:
        mode = self._origin_var.get()
        if mode == ORIGIN_LINK:
            self._local_row.pack_forget()
            self._link_row.pack(fill="x", pady=(8, 0))
        else:
            self._link_row.pack_forget()
            self._local_row.pack(fill="x", pady=(8, 0))

    def _toggle_advanced(self) -> None:
        if self._advanced_open.get():
            self._adv_frame.pack(fill="x", pady=(2, 4))
        else:
            self._adv_frame.pack_forget()
        self.win.update_idletasks()

    # ── Source-specific helpers ───────────────────────────────────────────────

    def _on_fetch_info(self) -> None:
        url = self._url_var.get().strip()
        if not url:
            self._show_error("请先填入视频链接")
            return
        self._clear_error()
        self._set_busy("正在解析链接...")
        # Quick foreground call — extract_info typically returns in <1s for
        # warm sites, a few seconds otherwise. Acceptable to block here;
        # the heavy download happens in the modal later.
        try:
            info = fetch_link_info(url)
        except AcquireError as e:
            self._set_idle()
            self._show_error(f"无法获取视频信息: {e.message}")
            return
        except Exception as e:
            self._set_idle()
            self._show_error(f"无法获取视频信息: {e}")
            return
        self._set_idle()

        title = info.get("title") if isinstance(info, dict) else None
        if title:
            self._fetched_title = title
            if not self._name_var.get().strip():
                self._name_var.set(_sanitize_name(title))

    def _on_pick_local(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.win,
            title="选择本地视频文件",
            filetypes=[
                ("视频文件", " ".join(f"*{e}" for e in VIDEO_EXTS)),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        self._local_path_var.set(path)
        # Auto-fill project name if empty
        if not self._name_var.get().strip():
            base = os.path.splitext(os.path.basename(path))[0]
            self._name_var.set(_sanitize_name(base))

    def _on_pick_parent(self) -> None:
        cur = self._parent_var.get()
        initial = cur if cur and os.path.isdir(cur) else _default_parent_dir()
        path = filedialog.askdirectory(
            parent=self.win,
            title="选择项目存放位置",
            initialdir=initial,
        )
        if path:
            self._parent_var.set(path)

    # ── Validate + create ─────────────────────────────────────────────────────

    def _on_create(self) -> None:
        self._clear_error()
        mode = self._origin_var.get()

        # Source-specific validation
        url = ""
        local_path = ""
        if mode == ORIGIN_LINK:
            url = self._url_var.get().strip()
            if not url:
                return self._show_error("请填入视频链接")
            if not _looks_like_url(url):
                return self._show_error("视频链接格式无效")
        else:
            local_path = self._local_path_var.get().strip()
            if not local_path:
                return self._show_error("请选择本地视频文件")
            if not os.path.isfile(local_path):
                return self._show_error("文件不存在")
            ext = os.path.splitext(local_path)[1].lower()
            if ext not in VIDEO_EXTS:
                return self._show_error(
                    f"不支持的文件格式: {ext or '(无扩展名)'}"
                )

        # Project name
        name = self._name_var.get().strip()
        if not name:
            return self._show_error("请填入项目名")
        sanitized = _sanitize_name(name)
        if sanitized != name:
            return self._show_error(
                "项目名包含非法字符 (\\ / : * ? \" < > |),请修改"
            )
        if not sanitized:
            return self._show_error("项目名不能为空")
        if len(sanitized) > 64:
            return self._show_error("项目名过长(超过 64 字符)")

        # Parent dir
        parent_dir = self._parent_var.get().strip()
        if not parent_dir:
            return self._show_error("请选择保存位置")
        if not os.path.isdir(parent_dir):
            # Try to auto-create — common case is the user typed a new path.
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except OSError as e:
                return self._show_error(f"无法创建保存目录: {e}")
        if not os.access(parent_dir, os.W_OK):
            return self._show_error("保存目录不可写")

        # Final project folder must not already exist.
        if os.path.exists(os.path.join(parent_dir, sanitized)):
            return self._show_error(f"项目目录已存在: {sanitized}")

        # Time range (optional)
        clip_range: ClipRange | None = None
        if self._advanced_open.get():
            rs = self._range_start_var.get().strip()
            re_ = self._range_end_var.get().strip()
            if rs or re_:
                # Both must be supplied if either is.
                if not (rs and re_):
                    return self._show_error(
                        "源视频范围需要同时填写起和止时间"
                    )
                try:
                    s_sec = parse_hms(rs)
                    e_sec = parse_hms(re_)
                except ValueError as e:
                    return self._show_error(f"时间格式无效: {e}")
                if s_sec >= e_sec:
                    return self._show_error("起始时间必须小于结束时间")
                clip_range = ClipRange(start=rs, end=re_)

        # Build the Source object
        source = Source(
            origin=mode,
            url=url if mode == ORIGIN_LINK else None,
            imported_from=local_path if mode == ORIGIN_LOCAL else None,
            clip_range=clip_range,
            title=self._fetched_title if mode == ORIGIN_LINK else None,
        )

        # Persist parent_dir for next run.
        settings.set_(SETTINGS_KEY_LAST_PARENT, parent_dir)

        self._result = NewProjectRequest(
            parent_dir=parent_dir, name=sanitized, source=source,
        )
        self.win.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.win.destroy()

    # ── Inline status ─────────────────────────────────────────────────────────

    def _show_error(self, msg: str) -> None:
        self._error_var.set(msg)

    def _clear_error(self) -> None:
        self._error_var.set("")

    def _set_busy(self, msg: str) -> None:
        self._error_var.set(msg)
        self._error_label.config(foreground="#666")
        self.win.update_idletasks()

    def _set_idle(self) -> None:
        self._error_var.set("")
        self._error_label.config(foreground="#c00")

    # ── Public entry ──────────────────────────────────────────────────────────

    def run(self) -> Optional[NewProjectRequest]:
        self.win.wait_window()
        return self._result


def _looks_like_url(s: str) -> bool:
    """Lightweight URL sanity check — not a full validation, just guards
    obvious typos before handing off to yt-dlp."""
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")
