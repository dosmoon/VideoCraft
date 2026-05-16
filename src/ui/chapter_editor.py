"""Chapter list verify + edit pane.

Embedded into the permanent preview tab 0 when the user clicks an
analysis.json sidebar artifact. Two columns:

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
    load_analysis,
    save_analysis_chapters_only,
    parse_time_str,
    fmt_time_str,
)
from core.subtitle_ops import srt_end_seconds
from i18n import tr
from ui.web_preview import WebPreviewFrame


# Cues are baked into the page as a JSON array, so the browser can
# render subtitles without a separate VTT fetch (file:// pages cannot
# load <track src=file://...> due to Chromium's local-file CORS rules).
_VIDEO_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin:0; padding:0; background:#000; height:100%;
                position:relative; overflow:hidden; }}
  body {{ display:flex; align-items:center; justify-content:center; }}
  video {{ width:100%; height:100%; object-fit:contain; }}
  #cap {{
    position: fixed; left: 0; right: 0; bottom: 60px;
    text-align: center; color: #fff;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 20px; font-weight: 600; line-height: 1.35;
    text-shadow: 1px 1px 0 #000, -1px -1px 0 #000,
                 1px -1px 0 #000, -1px 1px 0 #000,
                 0 0 6px rgba(0,0,0,0.85);
    padding: 0 24px; pointer-events: none;
    white-space: pre-wrap;
  }}
</style></head>
<body>
  <video id="v" controls preload="metadata" src="{video_url}"></video>
  <div id="cap"></div>
  <script>
    var cues = {cues_json};
    var v = document.getElementById('v');
    var cap = document.getElementById('cap');
    var last = -1;
    var lastIdx = -1;
    // Cues are sorted by start; advance an index pointer instead of
    // scanning the whole list every tick.
    function findCue(t) {{
      // Forward seek
      while (lastIdx + 1 < cues.length && cues[lastIdx + 1].s <= t) {{
        lastIdx++;
      }}
      // Backward seek (user scrubbed)
      while (lastIdx >= 0 && cues[lastIdx].s > t) {{
        lastIdx--;
      }}
      if (lastIdx >= 0 && cues[lastIdx].e > t) return cues[lastIdx].t;
      return "";
    }}
    v.addEventListener('timeupdate', function() {{
      var t = v.currentTime;
      cap.textContent = findCue(t);
      var sec = Math.floor(t);
      if (sec === last) return;
      last = sec;
      try {{ window.pywebview.api.notify({{type:'time', t:sec}}); }} catch(e) {{}}
    }});
    v.addEventListener('seeked', function() {{
      lastIdx = -1; // force re-search after a scrub
      cap.textContent = findCue(v.currentTime);
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
        self._analysis_path = chapters_path    # arg name kept for caller compat
        self._lang_iso = lang_iso
        self._source_video = source_video
        self._srt_path = srt_path
        self._on_saved = on_saved
        self._srt_end_sec = srt_end_seconds(srt_path)
        self._source_subtitle = f"{lang_iso}.srt"

        # State — loads the unified analysis envelope and edits its
        # chapters[] portion. Save preserves titles + other envelope keys.
        env = load_analysis(chapters_path)
        self._titles: list[str] = list(env.get("titles") or [])
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
        vsb = ttk.Scrollbar(left, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Delete>", lambda _e: self._on_delete_chapter())
        self._tree.bind("<Button-3>", self._on_right_click)

        self._tree_menu = tk.Menu(self._tree, tearoff=0)
        self._tree_menu.add_command(
            label=tr("chapter_editor.menu_delete"),
            command=self._on_delete_chapter)

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
        cues_json = self._build_cues_json()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(_VIDEO_HTML.format(video_url=video_url,
                                       cues_json=cues_json))
        initial_url = "file:///" + html_path.replace("\\", "/")
        self._web = WebPreviewFrame(video_box, initial_url=initial_url,
                                    on_message=self._on_web_message)
        self._web.pack(fill="both", expand=True)

        # Top button row — save / undo / add / delete only. The actual
        # field editors all live in the details panel below.
        btnbar = tk.Frame(right, bg="white")
        btnbar.pack(fill="x", pady=(8, 4), padx=8)

        self._save_btn = tk.Button(btnbar, text=tr("chapter_editor.btn_save"),
                                   relief="flat", bg="#0078d4", fg="white",
                                   state="disabled", padx=10,
                                   command=self._on_save)
        self._save_btn.pack(side="left", padx=(0, 6))

        self._undo_btn = tk.Button(btnbar, text=tr("chapter_editor.btn_undo"),
                                   relief="flat", bg="#e8e8e8",
                                   state="disabled", padx=10,
                                   command=self._on_undo)
        self._undo_btn.pack(side="left", padx=(0, 16))

        self._add_btn = tk.Button(
            btnbar, text=tr("chapter_editor.btn_add_at", t="0s"),
            relief="flat", bg="#e8e8e8", padx=10,
            command=self._on_add_chapter)
        self._add_btn.pack(side="left", padx=(0, 6))

        self._del_btn = tk.Button(
            btnbar, text=tr("chapter_editor.btn_delete"),
            relief="flat", bg="#e8e8e8", padx=10,
            state="disabled",
            command=self._on_delete_chapter)
        self._del_btn.pack(side="left")

        self._status = tk.Label(right, text="", bg="white", fg="#888",
                                font=("Microsoft YaHei UI", 9),
                                anchor="w")
        self._status.pack(fill="x", padx=8, pady=(0, 6))

        # Editable details — all per-chapter fields live here.
        # First row: start + title; below: refined; below: key_points.
        details = tk.LabelFrame(
            right, text=tr("chapter_editor.details_frame"),
            bg="white", fg="#444",
            font=("Microsoft YaHei UI", 9))
        details.pack(fill="both", expand=False, padx=8, pady=(0, 8))

        # — start + title row —
        top = tk.Frame(details, bg="white")
        top.pack(fill="x", padx=6, pady=(6, 6))

        tk.Label(top, text=tr("chapter_editor.field_start"),
                 bg="white", fg="#666",
                 font=("Microsoft YaHei UI", 9)
                 ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._start_var = tk.StringVar()
        self._start_entry = tk.Entry(top, textvariable=self._start_var,
                                     font=("Consolas", 10), width=12,
                                     state="disabled")
        self._start_entry.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self._start_var.trace_add("write", lambda *_: self._on_start_changed())
        self._start_entry.bind("<Return>", lambda _e: self._seek_to_entry())

        self._set_cur_btn = tk.Button(top, text="🎯 0s", relief="flat",
                                      bg="#e8e8e8", state="disabled",
                                      command=self._on_set_from_current)
        self._set_cur_btn.grid(row=0, column=2, sticky="w", padx=(0, 16))

        tk.Label(top, text=tr("chapter_editor.field_title"),
                 bg="white", fg="#666",
                 font=("Microsoft YaHei UI", 9)
                 ).grid(row=0, column=3, sticky="w", padx=(0, 6))
        self._title_var = tk.StringVar()
        self._title_entry = tk.Entry(top, textvariable=self._title_var,
                                     font=("Microsoft YaHei UI", 10),
                                     state="disabled")
        self._title_entry.grid(row=0, column=4, sticky="ew")
        top.columnconfigure(4, weight=1)
        self._title_var.trace_add("write", lambda *_: self._on_title_changed())

        # — refined —
        tk.Label(details, text=tr("chapter_editor.refined_label"),
                 bg="white", fg="#666",
                 font=("Microsoft YaHei UI", 9, "bold"), anchor="w"
                 ).pack(fill="x", padx=6, pady=(2, 0))
        self._refined_text = tk.Text(
            details, height=3, wrap="word",
            font=("Microsoft YaHei UI", 9),
            bg="white", fg="#222",
            relief="solid", borderwidth=1, state="disabled")
        self._refined_text.pack(fill="x", padx=6, pady=(2, 6))
        self._refined_text.bind("<<Modified>>", self._on_refined_modified)

        # — key_points —
        tk.Label(details, text=tr("chapter_editor.key_points_label"),
                 bg="white", fg="#666",
                 font=("Microsoft YaHei UI", 9, "bold"), anchor="w"
                 ).pack(fill="x", padx=6, pady=(0, 0))
        self._key_points_text = tk.Text(
            details, height=5, wrap="word",
            font=("Microsoft YaHei UI", 9),
            bg="white", fg="#222",
            relief="solid", borderwidth=1, state="disabled")
        self._key_points_text.pack(fill="x", padx=6, pady=(2, 6))
        self._key_points_text.bind("<<Modified>>",
                                    self._on_key_points_modified)

    # ── Tree ─────────────────────────────────────────────────────────────

    def _reload_tree(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for i, ch in enumerate(self._working):
            self._tree.insert("", "end", iid=str(i),
                              values=(ch.get("start", ""),
                                      ch.get("title", "")))
        self._selected = None
        self._suppress_trace = True
        self._start_var.set("")
        self._title_var.set("")
        self._suppress_trace = False
        self._start_entry.configure(state="disabled")
        self._title_entry.configure(state="disabled")
        # Clear the details panel — selecting a row will repopulate it.
        # _selected is None here so the <<Modified>> handler is a no-op.
        if hasattr(self, "_refined_text"):
            self._refined_text.configure(state="normal")
            self._refined_text.delete("1.0", "end")
            self._refined_text.edit_modified(False)
            self._refined_text.configure(state="disabled")
            self._key_points_text.configure(state="normal")
            self._key_points_text.delete("1.0", "end")
            self._key_points_text.edit_modified(False)
            self._key_points_text.configure(state="disabled")
        self._refresh_button_states()

    def _on_select(self, _e=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._selected = idx
        ch = self._working[idx]
        start_str = ch.get("start", "00:00:00")
        title_str = ch.get("title", "")
        # Suppress write-callbacks while we sync entries to the row.
        self._suppress_trace = True
        self._start_var.set(start_str)
        self._title_var.set(title_str)
        self._suppress_trace = False
        # First chapter is locked at 00:00:00 (intro or real first @0).
        # Title is editable on every row including the intro.
        is_first = idx == 0
        self._start_entry.configure(state="disabled" if is_first else "normal")
        self._title_entry.configure(state="normal")
        self._seek_to_str(start_str)
        self._refresh_button_states()
        self._refresh_details(ch)

    def _refresh_details(self, ch: dict) -> None:
        """Push the selected chapter's refined + key_points into the
        editable details panel. <<Modified>> fired by these inserts is
        harmless — the handler writes the same value back to _working
        (idempotent), and dirty is computed against _baseline anyway."""
        refined = (ch.get("refined") or "")
        self._refined_text.configure(state="normal")
        self._refined_text.delete("1.0", "end")
        self._refined_text.insert("1.0", refined)
        self._refined_text.edit_modified(False)

        kps = ch.get("key_points") or []
        self._key_points_text.configure(state="normal")
        self._key_points_text.delete("1.0", "end")
        self._key_points_text.insert("1.0", "\n".join(kps))
        self._key_points_text.edit_modified(False)

    # ── Subtitle overlay ─────────────────────────────────────────────────

    def _build_cues_json(self) -> str:
        """Parse the SRT once and emit a JSON literal of cues for the
        in-page subtitle overlay. Shape: [{s, e, t}] sorted by start."""
        try:
            import json as _json
            import srt as _srt
            from core.subtitle_ops import read_srt
            cues = list(_srt.parse(read_srt(self._srt_path)))
        except Exception:
            return "[]"
        out = []
        for cue in cues:
            text = cue.content.replace("\n", " ").strip()
            if not text:
                continue
            out.append({
                "s": cue.start.total_seconds(),
                "e": cue.end.total_seconds(),
                "t": text,
            })
        out.sort(key=lambda c: c["s"])
        return _json.dumps(out, ensure_ascii=False)

    # ── WebView messages ─────────────────────────────────────────────────

    def _on_web_message(self, data) -> None:
        if not isinstance(data, dict):
            return
        if data.get("type") == "time":
            t = int(data.get("t") or 0)
            self._current_video_sec = t
            self._set_cur_btn.configure(text=f"🎯 {t}s")
            self._add_btn.configure(
                text=tr("chapter_editor.btn_add_at", t=f"{t}s"))

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

    def _on_refined_modified(self, _e=None) -> None:
        if not self._refined_text.edit_modified():
            return
        self._refined_text.edit_modified(False)
        if self._selected is None:
            return
        val = self._refined_text.get("1.0", "end-1c")
        self._working[self._selected]["refined"] = val
        self._refresh_button_states()

    def _on_key_points_modified(self, _e=None) -> None:
        if not self._key_points_text.edit_modified():
            return
        self._key_points_text.edit_modified(False)
        if self._selected is None:
            return
        raw = self._key_points_text.get("1.0", "end-1c")
        # One bullet per non-empty line; strip any leading "• " markers
        # the user may have pasted in.
        kps = []
        for line in raw.splitlines():
            s = line.strip().lstrip("•·-*").strip()
            if s:
                kps.append(s)
        self._working[self._selected]["key_points"] = kps
        self._refresh_button_states()

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

    def _on_title_changed(self) -> None:
        if self._suppress_trace or self._selected is None:
            return
        val = self._title_var.get()
        self._working[self._selected]["title"] = val
        self._tree.set(str(self._selected), "title", val)
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
            if (a.get("refined") or "") != (b.get("refined") or ""):
                return True
            if list(a.get("key_points") or []) != list(b.get("key_points") or []):
                return True
        return False

    def _refresh_button_states(self) -> None:
        dirty = self._is_dirty()
        self._save_btn.configure(
            state="normal" if dirty else "disabled")
        self._undo_btn.configure(
            state="normal" if dirty else "disabled")
        # "Set from current" and "Delete" both require a non-first row
        # selected (first row is the locked 00:00 chapter).
        can_act = (self._selected is not None
                   and self._selected != 0)
        self._set_cur_btn.configure(
            state="normal" if can_act else "disabled")
        self._del_btn.configure(
            state="normal" if can_act else "disabled")

    # ── Add / delete ─────────────────────────────────────────────────────

    def _on_add_chapter(self) -> None:
        """Split the chapter containing the playback head at that point.

        We find the chapter whose start <= T < next_start, insert a new
        chapter right after it, and inherit its refined + key_points so
        the user can trim each half down to its actual content. We insert
        at the correct sorted position so the tree mirrors what save
        would produce — no surprise rows at the bottom.
        """
        sec = self._current_video_sec
        ts = fmt_time_str(sec)
        # Avoid creating an exact-duplicate row.
        for ch in self._working:
            if parse_time_str(str(ch.get("start", ""))) == sec:
                self._flash_status(tr("chapter_editor.add_duplicate"))
                return

        # Find the chapter being split: highest start_sec <= sec.
        insert_after = -1
        for i, ch in enumerate(self._working):
            ch_sec = parse_time_str(str(ch.get("start", "")))
            if ch_sec <= sec:
                insert_after = i
        if insert_after < 0:
            # Shouldn't happen — first chapter is always 00:00 — but be safe.
            insert_after = 0

        parent = self._working[insert_after]
        new_ch = {
            "start":      ts,
            "title":      tr("chapter_editor.new_default"),
            "refined":    parent.get("refined") or "",
            "key_points": list(parent.get("key_points") or []),
        }
        insert_idx = insert_after + 1
        self._working.insert(insert_idx, new_ch)
        new_iid = str(insert_idx)
        self._reload_tree()
        self._tree.selection_set(new_iid)
        self._tree.focus(new_iid)
        self._tree.see(new_iid)
        self._on_select()
        # Focus the title entry so the user can rename the new chapter
        # right away (was an in-tree inline editor before).
        self.after(50, self._focus_title_entry)

    def _focus_title_entry(self) -> None:
        try:
            self._title_entry.focus_force()
            self._title_entry.select_range(0, "end")
            self._title_entry.icursor("end")
        except Exception:
            pass

    def _on_delete_chapter(self) -> None:
        if self._selected is None:
            return
        if self._selected == 0:
            self._flash_status(tr("chapter_editor.cant_delete_first"))
            return
        del self._working[self._selected]
        self._reload_tree()

    def _on_right_click(self, event) -> None:
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return
        self._tree.selection_set(row_id)
        self._tree.focus(row_id)
        self._on_select()
        # Disable the menu item for the locked first chapter so right-
        # click affordance matches the toolbar's disabled state.
        state = "disabled" if int(row_id) == 0 else "normal"
        self._tree_menu.entryconfigure(0, state=state)
        self._tree_menu.post(event.x_root, event.y_root)

    def _flash_status(self, text: str, ms: int = 2000) -> None:
        self._status.configure(text=text)
        self.after(ms, lambda: self._status.configure(text=""))

    def _on_save(self) -> None:
        try:
            envelope = save_analysis_chapters_only(
                self._analysis_path, self._working,
                srt_end_sec=self._srt_end_sec,
                lang_iso=self._lang_iso,
                source_subtitle=self._source_subtitle,
            )
        except Exception as e:
            messagebox.showerror(tr("chapter_editor.save_failed_title"),
                                 str(e), parent=self)
            return
        normalized = envelope.get("chapters") or []
        self._baseline = copy.deepcopy(normalized)
        self._working = copy.deepcopy(normalized)
        self._reload_tree()
        self._flash_status(tr("chapter_editor.saved"))
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
