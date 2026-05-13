"""Chapter list verify + edit pane.

Embedded into the permanent preview tab 0 when the user clicks a
chapters.json sidebar artifact. Two columns:

    +-----------------+----------------------------------------+
    |  chapter list   |  WebView <video>                       |
    |  (Treeview)     |  ----------------------------------    |
    |                 |  start [HH:MM:SS] [🎯 N秒]              |
    |                 |  title [           ]                    |
    |                 |  [💾 保存] [↺ 撤销]                     |
    +-----------------+----------------------------------------+

Click a chapter row → seek the video to that chapter's start.
Adjust the start (either by typing or by dragging the video and
pressing the "current second" button) → save → chapter list is
re-normalized via core.chapters_io and re-rendered.

All chapter invariants (sort, end recompute, auto-intro at 00:00,
drop-degenerate) live in chapters_io. This UI is a thin editor on
top — it never embeds the invariant logic itself.
"""

from __future__ import annotations

import copy
import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from core.chapters_io import (
    load_chapters,
    save_chapters,
    parse_time_str,
    fmt_time_str,
)
from core.subtitle_ops import srt_end_seconds
from i18n import tr
from ui.web_preview import WebPreviewFrame


_VIDEO_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin:0; padding:0; background:#000; height:100%; }}
  body {{ display:flex; align-items:center; justify-content:center; }}
  video {{ width:100%; height:100%; object-fit:contain; }}
</style></head>
<body>
  <video id="v" controls preload="metadata" src="{video_url}"></video>
  <script>
    var v = document.getElementById('v');
    var last = -1;
    v.addEventListener('timeupdate', function() {{
      var t = Math.floor(v.currentTime);
      if (t === last) return;
      last = t;
      try {{ window.pywebview.api.notify({{type:'time', t:t}}); }} catch(e) {{}}
    }});
  </script>
</body></html>
"""


def _is_valid_ts(text: str) -> bool:
    """Strict: only HH:MM:SS or MM:SS forms accepted by parse_time_str
    AND non-zero parse result for non-zero strings."""
    text = (text or "").strip()
    if not text:
        return False
    if text == "00:00:00" or text == "00:00" or text == "0:00":
        return True
    return parse_time_str(text) > 0


class ChapterEditor(tk.Frame):
    """Split-view editor; owns its own WebPreviewFrame lifecycle."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        chapters_path: str,
        lang_iso: str,
        source_video: str,
        srt_path: str,
        cache_dir: str,
        on_saved: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent, bg="white")
        self._chapters_path = chapters_path
        self._lang_iso = lang_iso
        self._source_video = source_video
        self._srt_path = srt_path
        self._on_saved = on_saved
        self._srt_end_sec = srt_end_seconds(srt_path)
        self._source_subtitle = f"{lang_iso}.srt"

        # State
        env = load_chapters(chapters_path)
        self._baseline: list[dict] = list(env.get("chapters") or [])
        self._working: list[dict] = copy.deepcopy(self._baseline)
        self._selected: Optional[int] = None
        self._current_video_sec: int = 0

        self._build_ui(cache_dir)
        self._reload_tree()
        self.bind("<Destroy>", self._on_destroy)

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self, cache_dir: str) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # Left: chapter list
        left = tk.Frame(paned, bg="white")
        paned.add(left, weight=2)

        cols = ("start", "title")
        self._tree = ttk.Treeview(left, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("start", text=tr("chapter_editor.col_start"))
        self._tree.heading("title", text=tr("chapter_editor.col_title"))
        self._tree.column("start", width=90, anchor="w", stretch=False)
        self._tree.column("title", width=200, anchor="w", stretch=True)
        vsb = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>", self._on_double_click)
        self._title_editor: Optional[tk.Entry] = None

        # Right: video + controls
        right = tk.Frame(paned, bg="white")
        paned.add(right, weight=3)

        video_box = tk.Frame(right, bg="black", height=320)
        video_box.pack(fill="both", expand=True)
        video_box.pack_propagate(False)

        os.makedirs(cache_dir, exist_ok=True)
        html_path = os.path.join(cache_dir, "chapter_editor_preview.html")
        video_url = "file:///" + os.path.abspath(
            self._source_video).replace("\\", "/")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(_VIDEO_HTML.format(video_url=video_url))
        initial_url = "file:///" + html_path.replace("\\", "/")
        self._web = WebPreviewFrame(video_box, initial_url=initial_url,
                                    on_message=self._on_web_message)
        self._web.pack(fill="both", expand=True)

        # Edit controls
        ctrl = tk.Frame(right, bg="white")
        ctrl.pack(fill="x", pady=(8, 4), padx=8)

        tk.Label(ctrl, text=tr("chapter_editor.field_start"),
                 bg="white", fg="#666",
                 font=("Microsoft YaHei UI", 9)
                 ).grid(row=0, column=0, sticky="w", padx=(0, 6))

        self._start_var = tk.StringVar()
        self._start_entry = tk.Entry(ctrl, textvariable=self._start_var,
                                     font=("Consolas", 10), width=12,
                                     state="disabled")
        self._start_entry.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self._start_var.trace_add("write", lambda *_: self._on_start_changed())
        self._start_entry.bind("<Return>", lambda _e: self._seek_to_entry())

        self._set_cur_btn = tk.Button(ctrl, text="🎯 0s", relief="flat",
                                      bg="#e8e8e8", state="disabled",
                                      command=self._on_set_from_current)
        self._set_cur_btn.grid(row=0, column=2, sticky="w", padx=(0, 12))

        self._save_btn = tk.Button(ctrl, text=tr("chapter_editor.btn_save"),
                                   relief="flat", bg="#0078d4", fg="white",
                                   state="disabled", padx=10,
                                   command=self._on_save)
        self._save_btn.grid(row=0, column=3, sticky="w", padx=(0, 6))

        self._undo_btn = tk.Button(ctrl, text=tr("chapter_editor.btn_undo"),
                                   relief="flat", bg="#e8e8e8",
                                   state="disabled", padx=10,
                                   command=self._on_undo)
        self._undo_btn.grid(row=0, column=4, sticky="w")

        self._status = tk.Label(right, text="", bg="white", fg="#888",
                                font=("Microsoft YaHei UI", 9),
                                anchor="w")
        self._status.pack(fill="x", padx=8, pady=(0, 6))

    # ── Tree ─────────────────────────────────────────────────────────────

    def _reload_tree(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for i, ch in enumerate(self._working):
            self._tree.insert("", "end", iid=str(i),
                              values=(ch.get("start", ""),
                                      ch.get("title", "")))
        self._selected = None
        self._start_var.set("")
        self._start_entry.configure(state="disabled")
        self._refresh_button_states()

    def _on_select(self, _e=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._selected = idx
        ch = self._working[idx]
        start_str = ch.get("start", "00:00:00")
        # Suppress write-callback while we sync the entry to the row.
        self._suppress_trace = True
        self._start_var.set(start_str)
        self._suppress_trace = False
        # First chapter is locked at 00:00:00 (intro or real first @0).
        is_first = idx == 0
        self._start_entry.configure(state="disabled" if is_first else "normal")
        self._seek_to_str(start_str)
        self._refresh_button_states()

    # ── Title inline edit ────────────────────────────────────────────────

    def _on_double_click(self, event) -> None:
        """Double-click on the title cell opens an overlay Entry."""
        region = self._tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self._tree.identify_column(event.x)
        if col != "#2":  # title column
            return
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return
        idx = int(row_id)
        bbox = self._tree.bbox(row_id, col)
        if not bbox:
            return
        x, y, w, h = bbox
        current_title = self._working[idx].get("title", "")
        self._close_title_editor()
        entry = tk.Entry(self._tree, font=("Microsoft YaHei UI", 10),
                         borderwidth=0, highlightthickness=1,
                         highlightcolor="#0078d4")
        entry.insert(0, current_title)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        self._title_editor = entry
        self._title_editor_idx = idx

        def commit(_e=None):
            new_val = entry.get().strip()
            self._close_title_editor()
            if new_val != current_title:
                self._working[idx]["title"] = new_val
                self._tree.set(row_id, "title", new_val)
                self._refresh_button_states()

        def cancel(_e=None):
            self._close_title_editor()

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", cancel)

    def _close_title_editor(self) -> None:
        if self._title_editor is not None:
            try:
                self._title_editor.destroy()
            except Exception:
                pass
            self._title_editor = None

    # ── WebView messages ─────────────────────────────────────────────────

    def _on_web_message(self, data) -> None:
        if not isinstance(data, dict):
            return
        if data.get("type") == "time":
            t = int(data.get("t") or 0)
            self._current_video_sec = t
            self._set_cur_btn.configure(text=f"🎯 {t}s")

    def _seek_to_str(self, ts: str) -> None:
        sec = parse_time_str(ts)
        self._seek_to_sec(sec)

    def _seek_to_sec(self, sec: float) -> None:
        # currentTime accepts float seconds. Pause then seek to avoid an
        # auto-play after each row click.
        js = (f"var v=document.getElementById('v');"
              f"if(v){{v.pause();v.currentTime={sec:.3f};}}")
        try:
            self._web.evaluate_js(js)
        except Exception:
            pass

    def _seek_to_entry(self) -> None:
        text = self._start_var.get().strip()
        if _is_valid_ts(text):
            self._seek_to_sec(parse_time_str(text))

    # ── Edit handlers ────────────────────────────────────────────────────

    _suppress_trace = False

    def _on_start_changed(self) -> None:
        if self._suppress_trace or self._selected is None:
            return
        text = self._start_var.get().strip()
        valid = _is_valid_ts(text) or text == ""
        self._start_entry.configure(
            bg="white" if valid else "#fdd")
        if valid and text:
            self._working[self._selected]["start"] = text
            # Reflect into the row immediately so the user sees the
            # ordering they're producing — final normalization happens
            # at save time.
            self._tree.set(str(self._selected), "start", text)
        self._refresh_button_states()

    def _on_set_from_current(self) -> None:
        if self._selected is None:
            return
        ts = fmt_time_str(self._current_video_sec)
        # Triggers _on_start_changed which writes through to _working.
        self._start_var.set(ts)

    # ── Save / Undo ──────────────────────────────────────────────────────

    def _is_dirty(self) -> bool:
        if len(self._working) != len(self._baseline):
            return True
        for a, b in zip(self._working, self._baseline):
            if a.get("start") != b.get("start"):
                return True
            if a.get("title") != b.get("title"):
                return True
        return False

    def _refresh_button_states(self) -> None:
        dirty = self._is_dirty()
        self._save_btn.configure(
            state="normal" if dirty else "disabled")
        self._undo_btn.configure(
            state="normal" if dirty else "disabled")
        # "Set from current" requires a row selected AND that row not
        # being the locked first chapter.
        can_set = (self._selected is not None
                   and self._selected != 0)
        self._set_cur_btn.configure(
            state="normal" if can_set else "disabled")

    def _on_save(self) -> None:
        try:
            normalized = save_chapters(
                self._chapters_path, self._working,
                srt_end_sec=self._srt_end_sec,
                lang_iso=self._lang_iso,
                source_subtitle=self._source_subtitle,
            )
        except Exception as e:
            messagebox.showerror(tr("chapter_editor.save_failed_title"),
                                 str(e), parent=self)
            return
        self._baseline = copy.deepcopy(normalized)
        self._working = copy.deepcopy(normalized)
        self._reload_tree()
        self._status.configure(text=tr("chapter_editor.saved"))
        self.after(2000, lambda: self._status.configure(text=""))
        if self._on_saved is not None:
            try:
                self._on_saved()
            except Exception:
                pass

    def _on_undo(self) -> None:
        self._working = copy.deepcopy(self._baseline)
        self._reload_tree()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def _on_destroy(self, _e=None) -> None:
        try:
            self._web.destroy()
        except Exception:
            pass
