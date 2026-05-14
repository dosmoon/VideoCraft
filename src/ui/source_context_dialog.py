"""Modal dialog for editing source/context.json.

Layout (scrollable body, grouped sections):

  ┌─ Read-only platform metadata ─┐
  │  uploader / description / tags │
  ├─ 人物 (host / bio / affil. / guests)
  ├─ 时间地点 (event_date / event_time / event_location)
  ├─ 事件 (show_type / topic / summary / key_points)
  ├─ 背景 (background)
  ├─ 产出层 (audience / platform_tone / notes)
  └─ [✨ AI 填充]              [取消] [保存]

Returns True on save, False on cancel — caller refreshes preview.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from core.source_context import (
    SourceContext, read_context, write_context, read_platform_metadata,
)
from i18n import tr


_SHOW_TYPES = ["", "新闻发布会", "演讲", "访谈", "直播切片",
               "课程", "评论", "解说", "纪录片", "其他"]
_PLATFORM_TONES = ["", "YouTube", "B 站", "抖音", "小红书", "TikTok", "Reels"]

# Single-line StringVar fields (key). Reduced 2026-05-14: 5 anchor fields
# (host / host_bio / event_date / event_location / episode_topic) moved
# to source_basic_info_dialog.py; this dialog now edits the 10 AI-owned
# fields of SourceContext.
_ENTRY_FIELDS = (
    "host_affiliation", "guests", "event_time",
)
# Multi-line Text fields (key, line height in dialog).
_TEXT_FIELDS = (
    ("event_summary", 3),
    ("key_points",    4),
    ("background",    5),
    ("notes",         3),
)


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
        self.win.resizable(True, True)
        self.win.minsize(560, 600)
        self.win.geometry("680x780")
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        ctx = read_context(source_dir)
        platform = read_platform_metadata(source_dir)

        # StringVars for single-line fields.
        self._vars: dict[str, tk.StringVar] = {
            f: tk.StringVar(value=getattr(ctx, f, "")) for f in _ENTRY_FIELDS
        }
        self._vars["show_type"]     = tk.StringVar(value=ctx.show_type)
        self._vars["platform_tone"] = tk.StringVar(value=ctx.platform_tone)
        self._vars["audience"]      = tk.StringVar(value=ctx.audience)

        # Text widgets for multi-line fields, registered after build.
        self._text_widgets: dict[str, tk.Text] = {}
        self._text_initial = {name: getattr(ctx, name, "") for name, _ in _TEXT_FIELDS}

        self._build_ui(platform)
        self._center_over(parent)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self, platform: dict) -> None:
        # Root: heading, scrollable body, button bar.
        root = ttk.Frame(self.win)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text=tr("dialog.source_context.heading"),
                  font=("Microsoft YaHei UI", 13, "bold"),
                  ).pack(anchor="w", padx=20, pady=(16, 8))

        # Scrollable mid-section.
        mid = ttk.Frame(root)
        mid.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        canvas = tk.Canvas(mid, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(mid, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        body = ttk.Frame(canvas)
        body_win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(body_win, width=e.width))

        def _on_wheel(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")
        body.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_wheel))
        body.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        # Platform metadata (read-only, condensed).
        if self._has_platform_info(platform):
            pf = ttk.LabelFrame(body, text=tr("dialog.source_context.platform_section"),
                                padding=10)
            pf.pack(fill="x", pady=(0, 10))
            self._render_platform_row(pf, tr("dialog.source_context.pf_uploader"),
                                      platform.get("uploader") or "—")
            self._render_platform_row(pf, tr("dialog.source_context.pf_description"),
                                      self._truncate(platform.get("description") or "—"))
            tags = platform.get("tags")
            if isinstance(tags, list) and tags:
                self._render_platform_row(pf, tr("dialog.source_context.pf_tags"),
                                          ", ".join(str(t) for t in tags[:12]))

        # ── Section: People ──
        sec = self._section(body, tr("dialog.source_context.sec_people"))
        self._entry_row(sec, 0, "host_affiliation")
        self._entry_row(sec, 1, "guests")
        sec.columnconfigure(1, weight=1)

        # ── Section: Time ──
        sec = self._section(body, tr("dialog.source_context.sec_when_where"))
        self._entry_row(sec, 0, "event_time")
        sec.columnconfigure(1, weight=1)

        # ── Section: Event ──
        sec = self._section(body, tr("dialog.source_context.sec_event"))
        self._combo_row(sec, 0, "show_type", _SHOW_TYPES)
        self._text_row(sec, 1, "event_summary", height=3)
        self._text_row(sec, 2, "key_points", height=4,
                       hint=tr("dialog.source_context.hint_key_points"))
        sec.columnconfigure(1, weight=1)

        # ── Section: Background ──
        sec = self._section(body, tr("dialog.source_context.sec_why"))
        self._text_row(sec, 0, "background", height=5)
        sec.columnconfigure(1, weight=1)

        # ── Section: Production ──
        sec = self._section(body, tr("dialog.source_context.sec_production"))
        self._entry_row(sec, 0, "audience")
        self._combo_row(sec, 1, "platform_tone", _PLATFORM_TONES)
        self._text_row(sec, 2, "notes", height=3)
        sec.columnconfigure(1, weight=1)

        # Hint footer.
        ttk.Label(body, text=tr("dialog.source_context.hint"),
                  font=("Microsoft YaHei UI", 8), foreground="#888",
                  wraplength=600, justify="left",
                  ).pack(anchor="w", pady=(2, 10))

        # ── Button bar ──
        btns = ttk.Frame(root, padding=(20, 4, 20, 14))
        btns.pack(fill="x", side="bottom")

        self._ai_btn = ttk.Button(
            btns, text=tr("dialog.source_context.btn_ai_fill"),
            command=self._on_ai_fill,
        )
        self._ai_btn.pack(side="left")
        self._ai_status_lbl = ttk.Label(
            btns, text="", foreground="#666",
            font=("Microsoft YaHei UI", 8),
        )
        self._ai_status_lbl.pack(side="left", padx=(8, 0))

        ttk.Button(btns, text=tr("dialog.common.btn_cancel"), command=self._on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("dialog.source_context.btn_save"), command=self._on_save
                   ).pack(side="right")

        self.win.bind("<Escape>", lambda _e: self._on_cancel())

    @staticmethod
    def _section(parent, title: str) -> ttk.LabelFrame:
        """Create a labeled section box and return it for child packing."""
        sec = ttk.LabelFrame(parent, text=title, padding=10)
        sec.pack(fill="x", pady=(0, 10))
        return sec

    def _entry_row(self, parent, row: int, field: str, *,
                    hint: str | None = None) -> None:
        ttk.Label(parent, text=tr(f"dialog.source_context.{field}"),
                  anchor="ne", width=12,
                  ).grid(row=row, column=0, sticky="ne", padx=(0, 8), pady=3)
        ttk.Entry(parent, textvariable=self._vars[field],
                  ).grid(row=row, column=1, sticky="ew", pady=3)
        if hint:
            ttk.Label(parent, text=hint, foreground="#888",
                      font=("Microsoft YaHei UI", 8),
                      ).grid(row=row, column=2, sticky="w", padx=(6, 0))

    def _combo_row(self, parent, row: int, field: str,
                    values: list[str]) -> None:
        ttk.Label(parent, text=tr(f"dialog.source_context.{field}"),
                  anchor="ne", width=12,
                  ).grid(row=row, column=0, sticky="ne", padx=(0, 8), pady=3)
        ttk.Combobox(parent, textvariable=self._vars[field], values=values,
                     ).grid(row=row, column=1, sticky="ew", pady=3)

    def _text_row(self, parent, row: int, field: str, *,
                   height: int, hint: str | None = None) -> None:
        ttk.Label(parent, text=tr(f"dialog.source_context.{field}"),
                  anchor="ne", width=12,
                  ).grid(row=row, column=0, sticky="ne", padx=(0, 8), pady=3)
        txt = tk.Text(parent, height=height,
                      font=("Microsoft YaHei UI", 9), wrap="word",
                      relief="solid", borderwidth=1)
        txt.grid(row=row, column=1, sticky="ew", pady=3)
        txt.insert("1.0", self._text_initial.get(field, ""))
        self._text_widgets[field] = txt
        if hint:
            ttk.Label(parent, text=hint, foreground="#888",
                      font=("Microsoft YaHei UI", 8),
                      ).grid(row=row, column=2, sticky="nw", padx=(6, 0))

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
                  foreground="#666", wraplength=520, anchor="w", justify="left"
                  ).pack(side="left", fill="x", expand=True)

    @staticmethod
    def _truncate(s: str, max_len: int = 240) -> str:
        s = s.strip()
        return s if len(s) <= max_len else s[:max_len] + "…"

    # ── AI fill ────────────────────────────────────────────────────────────

    def _on_ai_fill(self) -> None:
        """Run AI extraction in a background thread; on success, repopulate
        form fields (keeping non-empty user input as priority)."""
        self._ai_btn.configure(state="disabled")
        self._ai_status_lbl.configure(
            text=tr("dialog.source_context.ai_running"), foreground="#666"
        )

        subtitles_dir = os.path.join(os.path.dirname(self.source_dir), "subtitles")

        def _worker():
            err: Exception | None = None
            ctx: SourceContext | None = None
            try:
                from core.source_context_ai import extract
                self._flush_form_to_disk()
                ctx = extract(self.source_dir, subtitles_dir)
            except Exception as e:
                err = e

            def _apply():
                self._ai_btn.configure(state="normal")
                if err is not None or ctx is None:
                    self._ai_status_lbl.configure(
                        text=tr("dialog.source_context.ai_error"),
                        foreground="#c44",
                    )
                    messagebox.showerror(
                        tr("dialog.source_context.ai_error_title"),
                        str(err) if err else "(unknown error)",
                        parent=self.win,
                    )
                    return
                self._populate_form(ctx)
                self._ai_status_lbl.configure(
                    text=tr("dialog.source_context.ai_done"),
                    foreground="#2a7",
                )
            self.win.after(0, _apply)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Form ⇄ context.json ────────────────────────────────────────────────

    def _read_form(self) -> SourceContext:
        """Snapshot the form widgets into a SourceContext."""
        kwargs = {f: self._vars[f].get().strip() for f in _ENTRY_FIELDS}
        kwargs["show_type"]     = self._vars["show_type"].get().strip()
        kwargs["platform_tone"] = self._vars["platform_tone"].get().strip()
        kwargs["audience"]      = self._vars["audience"].get().strip()
        for name, _ in _TEXT_FIELDS:
            w = self._text_widgets.get(name)
            kwargs[name] = w.get("1.0", "end-1c").strip() if w else ""
        return SourceContext(**kwargs)

    def _flush_form_to_disk(self) -> None:
        """Persist the current form state to context.json before AI runs.
        Lets the extractor see edits the user just typed as 'existing'."""
        write_context(self.source_dir, self._read_form())

    def _populate_form(self, ctx: SourceContext) -> None:
        """Replace form widget values with `ctx`."""
        for f in _ENTRY_FIELDS:
            self._vars[f].set(getattr(ctx, f, ""))
        self._vars["show_type"].set(ctx.show_type)
        self._vars["platform_tone"].set(ctx.platform_tone)
        self._vars["audience"].set(ctx.audience)
        for name, _ in _TEXT_FIELDS:
            w = self._text_widgets.get(name)
            if w is not None:
                w.delete("1.0", "end")
                w.insert("1.0", getattr(ctx, name, ""))

    # ── Save / cancel ──────────────────────────────────────────────────────

    def _on_save(self) -> None:
        write_context(self.source_dir, self._read_form())
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
