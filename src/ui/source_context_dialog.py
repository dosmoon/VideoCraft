"""Modal dialog for editing source/context.json.

Form layout:
  ┌─ Read-only platform metadata (top, condensed) ─┐
  │  uploader / description / tags from yt-dlp     │
  ├─ Editable fields ──────────────────────────────┤
  │  节目类型 / 主讲人 / 身份 / 嘉宾 / 观众 /       │
  │  整集主题 / 平台语气 / 备注                     │
  └─ [取消] [保存] ─────────────────────────────────┘

Returns True on save, False on cancel — caller refreshes preview.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core.source_context import (
    SourceContext, read_context, write_context, read_platform_metadata,
)
from i18n import tr


_SHOW_TYPES = ["", "访谈", "演讲", "直播切片", "课程", "评论", "解说", "纪录片", "其他"]
_PLATFORM_TONES = ["", "B 站", "抖音", "小红书", "YouTube", "TikTok", "Reels"]


def show_source_context_dialog(parent: tk.Misc, source_dir: str) -> bool:
    """Show the modal. Returns True if user saved, False if cancelled."""
    return _ContextDialog(parent, source_dir).run()


class _ContextDialog:
    def __init__(self, parent: tk.Misc, source_dir: str) -> None:
        self.source_dir = source_dir
        self._saved = False

        self.win = tk.Toplevel(parent)
        self.win.title(tr("dialog.source_context.title"))
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        ctx = read_context(source_dir)
        platform = read_platform_metadata(source_dir)

        # Vars
        self._vars: dict[str, tk.Variable] = {
            "show_type":     tk.StringVar(value=ctx.show_type),
            "host":          tk.StringVar(value=ctx.host),
            "host_bio":      tk.StringVar(value=ctx.host_bio),
            "guests":        tk.StringVar(value=ctx.guests),
            "audience":      tk.StringVar(value=ctx.audience),
            "episode_topic": tk.StringVar(value=ctx.episode_topic),
            "platform_tone": tk.StringVar(value=ctx.platform_tone),
        }
        # notes is multi-line, gets its own Text widget
        self._notes_initial = ctx.notes

        self._build_ui(platform)
        self._center_over(parent)

    def _build_ui(self, platform: dict) -> None:
        body = ttk.Frame(self.win, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=tr("dialog.source_context.heading"),
                  font=("Microsoft YaHei UI", 13, "bold")
                  ).pack(anchor="w", pady=(0, 12))

        # ── Read-only platform metadata ──
        if self._has_platform_info(platform):
            pf = ttk.LabelFrame(body, text=tr("dialog.source_context.platform_section"),
                                padding=10)
            pf.pack(fill="x", pady=(0, 12))
            self._render_platform_row(pf, tr("dialog.source_context.pf_uploader"),
                                      platform.get("uploader") or "—")
            self._render_platform_row(pf, tr("dialog.source_context.pf_description"),
                                      self._truncate(platform.get("description") or "—"))
            tags = platform.get("tags")
            if isinstance(tags, list) and tags:
                self._render_platform_row(pf, tr("dialog.source_context.pf_tags"),
                                          ", ".join(str(t) for t in tags[:12]))

        # ── Editable fields ──
        ef = ttk.LabelFrame(body, text=tr("dialog.source_context.edit_section"),
                            padding=10)
        ef.pack(fill="x", pady=(0, 8))

        self._build_field(ef, 0, tr("dialog.source_context.show_type"),
                          combobox_var=self._vars["show_type"], values=_SHOW_TYPES)
        self._build_field(ef, 1, tr("dialog.source_context.host"),
                          entry_var=self._vars["host"])
        self._build_field(ef, 2, tr("dialog.source_context.host_bio"),
                          entry_var=self._vars["host_bio"])
        self._build_field(ef, 3, tr("dialog.source_context.guests"),
                          entry_var=self._vars["guests"])
        self._build_field(ef, 4, tr("dialog.source_context.audience"),
                          entry_var=self._vars["audience"])
        self._build_field(ef, 5, tr("dialog.source_context.episode_topic"),
                          entry_var=self._vars["episode_topic"])
        self._build_field(ef, 6, tr("dialog.source_context.platform_tone"),
                          combobox_var=self._vars["platform_tone"], values=_PLATFORM_TONES)

        # Notes (multi-line)
        ttk.Label(ef, text=tr("dialog.source_context.notes"), anchor="ne", width=10
                  ).grid(row=7, column=0, sticky="ne", padx=(0, 8), pady=(4, 4))
        self._notes_text = tk.Text(ef, width=46, height=4,
                                    font=("Microsoft YaHei UI", 9), wrap="word")
        self._notes_text.grid(row=7, column=1, sticky="ew", pady=(4, 4))
        self._notes_text.insert("1.0", self._notes_initial)
        ef.columnconfigure(1, weight=1)

        # Hint
        ttk.Label(body, text=tr("dialog.source_context.hint"),
                  font=("Microsoft YaHei UI", 8), foreground="#888",
                  wraplength=520, justify="left"
                  ).pack(anchor="w", pady=(0, 10))

        # Buttons
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_cancel"), command=self._on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("dialog.source_context.btn_save"), command=self._on_save
                   ).pack(side="right")

        self.win.bind("<Escape>", lambda _e: self._on_cancel())

    @staticmethod
    def _has_platform_info(platform: dict) -> bool:
        return bool(platform.get("uploader") or platform.get("description") or platform.get("tags"))

    @staticmethod
    def _render_platform_row(parent, label: str, value: str) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=1)
        ttk.Label(row, text=label, font=("Microsoft YaHei UI", 9, "bold"),
                  foreground="#555", width=8, anchor="ne"
                  ).pack(side="left", padx=(0, 6))
        ttk.Label(row, text=value, font=("Microsoft YaHei UI", 9),
                  foreground="#666", wraplength=440, anchor="w", justify="left"
                  ).pack(side="left", fill="x", expand=True)

    @staticmethod
    def _truncate(s: str, max_len: int = 240) -> str:
        s = s.strip()
        return s if len(s) <= max_len else s[:max_len] + "…"

    @staticmethod
    def _build_field(parent, row_idx: int, label: str, *,
                     entry_var: tk.StringVar | None = None,
                     combobox_var: tk.StringVar | None = None,
                     values: list[str] | None = None) -> None:
        ttk.Label(parent, text=label, anchor="ne", width=10
                  ).grid(row=row_idx, column=0, sticky="ne", padx=(0, 8), pady=2)
        if combobox_var is not None:
            ttk.Combobox(parent, textvariable=combobox_var,
                         values=values or [], width=44
                         ).grid(row=row_idx, column=1, sticky="ew", pady=2)
        else:
            ttk.Entry(parent, textvariable=entry_var, width=46
                      ).grid(row=row_idx, column=1, sticky="ew", pady=2)

    def _on_save(self) -> None:
        notes = self._notes_text.get("1.0", "end-1c").strip()
        ctx = SourceContext(
            show_type=self._vars["show_type"].get().strip(),
            host=self._vars["host"].get().strip(),
            host_bio=self._vars["host_bio"].get().strip(),
            guests=self._vars["guests"].get().strip(),
            audience=self._vars["audience"].get().strip(),
            episode_topic=self._vars["episode_topic"].get().strip(),
            platform_tone=self._vars["platform_tone"].get().strip(),
            notes=notes,
        )
        write_context(self.source_dir, ctx)
        self._saved = True
        self.win.destroy()

    def _on_cancel(self) -> None:
        self._saved = False
        self.win.destroy()

    def _center_over(self, parent: tk.Misc) -> None:
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - w) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - h) // 2
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def run(self) -> bool:
        self.win.wait_window()
        return self._saved
