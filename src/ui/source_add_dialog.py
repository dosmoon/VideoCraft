"""Source video acquisition dialog — invoked from the sidebar Source row.

Asks the user how to fill <project>/source/video.mp4:
  - Source: 视频链接 (URL via yt-dlp) or 本地文件 (copy / ffmpeg-cut)
  - Optional time range (advanced, collapsed by default)
  - Permanent small-text copyright disclaimer

Validates in-dialog. On success returns a Source dataclass; caller then
runs SourcePrepareModal to actually fetch the video, applies the
disclaimer dialog on first link-mode use, and finally back-fills
project.meta.source with title / duration / dimensions.

Wording is neutral — never mentions specific sites.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Optional

from core.project_schema import Source, ClipRange, ORIGIN_LINK, ORIGIN_LOCAL
from core.source_acquire import fetch_link_info, parse_hms, AcquireError
from i18n import tr


# Video extension whitelist for the local-file picker.
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv")


def show_source_add_dialog(
    parent: tk.Misc,
    title: str | None = None,
    preset: Source | None = None,
) -> Optional[Source]:
    """Show the dialog. Returns Source or None if cancelled.

    `preset` pre-fills the form (used by the "modify source" path).
    """
    return _SourceAddDialog(parent, title=title or tr("hub.dialog.source.title_add"), preset=preset).run()


class _SourceAddDialog:
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        preset: Source | None,
    ) -> None:
        self._result: Optional[Source] = None

        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.transient(parent.winfo_toplevel())
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # State vars (pre-filled from preset when provided)
        origin = preset.origin if preset else ORIGIN_LINK
        self._origin_var = tk.StringVar(value=origin)
        self._url_var = tk.StringVar(value=(preset.url or "") if preset else "")
        self._local_path_var = tk.StringVar(
            value=(preset.imported_from or "") if preset else "")
        self._advanced_open = tk.BooleanVar(
            value=bool(preset and preset.clip_range))
        self._range_start_var = tk.StringVar(
            value=(preset.clip_range.start if preset and preset.clip_range else ""))
        self._range_end_var = tk.StringVar(
            value=(preset.clip_range.end if preset and preset.clip_range else ""))
        self._fetched_title: str | None = preset.title if preset else None

        self._build_ui()
        self._update_source_mode()
        if self._advanced_open.get():
            self._toggle_advanced()
        self._center_over(parent)

    def _build_ui(self) -> None:
        body = ttk.Frame(self.win, padding=20)
        body.pack(fill="both", expand=True)

        # ── Source type ──
        src_box = ttk.LabelFrame(body, text=tr("dialog.source_add.section_source"), padding=10)
        src_box.pack(fill="x", pady=(0, 8))

        radios = ttk.Frame(src_box)
        radios.pack(fill="x")
        ttk.Radiobutton(radios, text=tr("dialog.source_add.option_link"), value=ORIGIN_LINK,
                        variable=self._origin_var,
                        command=self._update_source_mode
                        ).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(radios, text=tr("dialog.source_add.option_local"), value=ORIGIN_LOCAL,
                        variable=self._origin_var,
                        command=self._update_source_mode
                        ).pack(side="left")

        self._link_row = ttk.Frame(src_box)
        ttk.Entry(self._link_row, textvariable=self._url_var, width=46
                  ).pack(side="left", fill="x", expand=True)
        ttk.Button(self._link_row, text=tr("dialog.source_add.btn_fetch_info"),
                   command=self._on_fetch_info
                   ).pack(side="left", padx=(8, 0))

        self._local_row = ttk.Frame(src_box)
        ttk.Entry(self._local_row, textvariable=self._local_path_var, width=46
                  ).pack(side="left", fill="x", expand=True)
        ttk.Button(self._local_row, text=tr("dialog.source_add.btn_select_file"),
                   command=self._on_pick_local
                   ).pack(side="left", padx=(8, 0))

        # ── Advanced (collapsed by default) ──
        ttk.Checkbutton(
            body, text=tr("dialog.source_add.advanced"),
            variable=self._advanced_open,
            command=self._toggle_advanced,
        ).pack(anchor="w", pady=(4, 0))

        self._adv_frame = ttk.Frame(body, padding=(20, 4, 0, 0))
        ttk.Label(self._adv_frame, text=tr("dialog.source_add.range_label"),
                  font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        rng_row = ttk.Frame(self._adv_frame)
        rng_row.pack(anchor="w", pady=(4, 4))
        ttk.Label(rng_row, text=tr("dialog.source_add.range_start")).pack(side="left")
        ttk.Entry(rng_row, textvariable=self._range_start_var, width=10
                  ).pack(side="left")
        ttk.Label(rng_row, text=tr("dialog.source_add.range_end")).pack(side="left")
        ttk.Entry(rng_row, textvariable=self._range_end_var, width=10
                  ).pack(side="left")

        ttk.Label(self._adv_frame,
                  text=tr("dialog.source_add.range_hint"),
                  font=("Microsoft YaHei UI", 8), foreground="#888",
                  justify="left"
                  ).pack(anchor="w", pady=(2, 0))

        # ── Permanent disclaimer ──
        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=(12, 6))
        ttk.Label(
            body,
            text=tr("dialog.source_add.disclaimer"),
            font=("Microsoft YaHei UI", 8), foreground="#666",
        ).pack(anchor="w")

        # ── Buttons ──
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_cancel"), command=self._on_cancel
                   ).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text=tr("dialog.common.btn_start"), command=self._on_submit
                   ).pack(side="right")

        # Inline error
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
            self._show_error(tr("dialog.source_add.err_fill_link"))
            return
        self._clear_error()
        self._error_var.set(tr("dialog.source_add.status_fetching"))
        self._error_label.config(foreground="#666")
        self.win.update_idletasks()
        try:
            info = fetch_link_info(url)
        except AcquireError as e:
            self._error_label.config(foreground="#c00")
            self._show_error(tr("dialog.source_add.err_fetch_failed", error=e.message))
            return
        except Exception as e:
            self._error_label.config(foreground="#c00")
            self._show_error(tr("dialog.source_add.err_fetch_failed", error=str(e)))
            return
        self._error_label.config(foreground="#c00")
        self._clear_error()
        title = info.get("title") if isinstance(info, dict) else None
        if title:
            self._fetched_title = title

    def _on_pick_local(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.win,
            title=tr("dialog.source_add.pick_local_title"),
            filetypes=[
                (tr("dialog.source_add.filter_video"), " ".join(f"*{e}" for e in VIDEO_EXTS)),
                (tr("dialog.source_add.filter_all"), "*.*"),
            ],
        )
        if path:
            self._local_path_var.set(path)

    # ── Validate + submit ─────────────────────────────────────────────────────

    def _on_submit(self) -> None:
        self._clear_error()
        mode = self._origin_var.get()

        url = ""
        local_path = ""
        if mode == ORIGIN_LINK:
            url = self._url_var.get().strip()
            if not url:
                return self._show_error(tr("dialog.source_add.err_fill_link"))
            if not _looks_like_url(url):
                return self._show_error(tr("dialog.source_add.err_invalid_url"))
        else:
            local_path = self._local_path_var.get().strip()
            if not local_path:
                return self._show_error(tr("dialog.source_add.err_select_local"))
            if not os.path.isfile(local_path):
                return self._show_error(tr("dialog.source_add.err_file_missing"))
            ext = os.path.splitext(local_path)[1].lower()
            if ext not in VIDEO_EXTS:
                return self._show_error(
                    tr("dialog.source_add.err_unsupported_ext", ext=ext or tr("dialog.source_add.no_extension"))
                )

        # Time range
        clip_range: ClipRange | None = None
        if self._advanced_open.get():
            rs = self._range_start_var.get().strip()
            re_ = self._range_end_var.get().strip()
            if rs or re_:
                if not (rs and re_):
                    return self._show_error(tr("dialog.source_add.err_range_pair"))
                try:
                    s_sec = parse_hms(rs)
                    e_sec = parse_hms(re_)
                except ValueError as e:
                    return self._show_error(tr("dialog.source_add.err_time_format", error=str(e)))
                if s_sec >= e_sec:
                    return self._show_error(tr("dialog.source_add.err_range_order"))
                clip_range = ClipRange(start=rs, end=re_)

        self._result = Source(
            origin=mode,
            url=url if mode == ORIGIN_LINK else None,
            imported_from=local_path if mode == ORIGIN_LOCAL else None,
            clip_range=clip_range,
            title=self._fetched_title if mode == ORIGIN_LINK else None,
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

    def _center_over(self, parent: tk.Misc) -> None:
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        pw = parent.winfo_toplevel()
        x = pw.winfo_rootx() + (pw.winfo_width() - w) // 2
        y = pw.winfo_rooty() + (pw.winfo_height() - h) // 2
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def run(self) -> Optional[Source]:
        self.win.wait_window()
        return self._result


def _looks_like_url(s: str) -> bool:
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")
