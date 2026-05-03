"""Reusable clip-script widgets used across the workbench tabs.

These widgets own pure UI; they don't touch persistence (cut file) directly.
The host workbench owns autosave + AI dispatch and wires the widgets via
callbacks. This keeps the widgets dumb-and-portable so Tab 1 (chapter
detail pane) and Tab 2 (export summary side panel) can both use them.

Provided widgets:
  PreviewPane         WebView2-backed video preview + crop overlay
  PackageForm         hook / outro / title / hashtags entries, bind_clip(clip)
  ClipCard            LabelFrame with PackageForm + actions, click-to-focus
  ClipSummaryTreeview cross-chapter Treeview with selection + status badges
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import ttk
from typing import Callable

from core.program.clip import ClipDraft
from core.segment_model import format_timestamp
from ui.web_preview import WebPreviewFrame

_CLIP_HTML = os.path.join(os.path.dirname(__file__), "web_preview_clip.html")


def _tr(key: str) -> str:
    from i18n import tr
    return tr(key)


def _seconds_to_str(s: float) -> str:
    return format_timestamp(s)


# ── PreviewPane ────────────────────────────────────────────────────────────

class PreviewPane(tk.Frame):
    """WebView2-backed clip preview: real video playback + crop overlay.

    bind_clip(clip, video_path, video_w, video_h) loads the source file (if
    different from the previous clip), constrains playback to clip.start_sec
    .. clip.end_sec, and pushes the crop rect (or null → center default) to
    the embedded HTML. on_change fires when the user drags the crop rect.

    set_aspect_ratio(w, h) updates the locked aspect; rect re-fits on the
    HTML side.
    """

    def __init__(self, master: tk.Misc, *,
                 on_change: Callable[[ClipDraft, dict], None] | None = None,
                 **kwargs):
        super().__init__(master, **kwargs)
        self._on_change = on_change
        self._clip: ClipDraft | None = None
        self._video_path: str = ""           # last-loaded source on the HTML side
        self._video_w: int = 0
        self._video_h: int = 0
        self._aspect: tuple[int, int] = (9, 16)
        self._page_loaded = False
        self._pending_aspect: tuple[int, int] | None = None
        self._pending_bind: tuple[ClipDraft, str] | None = None
        self._pending_style: dict | None = None

        # Top: WebView preview
        initial_url = "file:///" + _CLIP_HTML.replace("\\", "/")
        self._web = WebPreviewFrame(
            self, on_message=self._on_web_message,
            on_loaded=self._on_page_loaded, initial_url=initial_url)
        self._web.pack(fill="both", expand=True, padx=2, pady=2)

        # Action bar
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=2, pady=(2, 4))
        ttk.Button(bar, text=_tr("tool.clip.btn_reset_center"),
                   command=self.reset_to_center).pack(side="left", padx=2)
        self._info_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._info_var, fg="#666",
                 font=("", 9)).pack(side="left", padx=(10, 0))

    # ── public API ──

    def bind_clip(self, clip: ClipDraft | None, *,
                  video_path: str, video_w: int, video_h: int) -> None:
        self._clip = clip
        self._video_w = video_w
        self._video_h = video_h
        if clip is None:
            self._info_var.set("")
            self._video_path = ""
            self._send("vc.clear()")
            return
        self._info_var.set(
            f"#{clip.id}  [{_seconds_to_str(clip.start_sec)} – "
            f"{_seconds_to_str(clip.end_sec)}]  {int(clip.duration)}s")
        if not self._page_loaded:
            self._pending_bind = (clip, video_path)
            return
        self._push_clip(clip, video_path)

    def reset_to_center(self) -> None:
        if self._clip is None:
            return
        self._clip.crop_rect = None
        self._send("vc.setCrop(null)")
        if self._on_change:
            # Notify with whatever the JS side resolves to (centered fit at
            # current aspect). Worker can re-derive from None too.
            self._on_change(self._clip, {})

    def set_aspect_ratio(self, w_ratio: int, h_ratio: int) -> None:
        self._aspect = (int(w_ratio), int(h_ratio))
        if not self._page_loaded:
            self._pending_aspect = self._aspect
            return
        self._send(f"vc.setAspect({int(w_ratio)}, {int(h_ratio)})")

    def push_clip_meta(self, clip: ClipDraft) -> None:
        """Push the clip's hook/outro text to the HTML preview without
        re-loading the video. Called when the user types in PackageForm."""
        if not self._page_loaded or clip is None:
            return
        meta = json.dumps({"hook":  clip.hook  or "",
                            "outro": clip.outro or ""},
                           ensure_ascii=False)
        self._send(f"vc.setClipMeta({meta})")

    def push_style(self, style_dict: dict) -> None:
        """Push subtitle/watermark style to the HTML preview.

        style_dict mirrors the relevant subset of ClipProjectConfig:
          {"subtitle": {position, stroke_color, stroke_width,
                        sub1: {enabled, fontsize, color, bold, text},
                        sub2: {...}},
           "watermark": {enabled, type, text, text_fontsize,
                         text_color, text_opacity, image_scale,
                         image_opacity, position}}

        If the page hasn't loaded yet, the latest style is buffered and
        replayed on load.
        """
        self._pending_style = dict(style_dict or {})
        if not self._page_loaded:
            return
        try:
            payload = json.dumps(style_dict, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        self._send(f"vc.setStyle({payload})")

    def destroy(self) -> None:
        # WebPreviewFrame.destroy() shuts down the child process.
        try:
            self._web.destroy()
        except Exception:
            pass
        super().destroy()

    # ── internal ──

    def _on_page_loaded(self) -> None:
        self._page_loaded = True
        if self._pending_aspect is not None:
            w, h = self._pending_aspect
            self._send(f"vc.setAspect({w}, {h})")
            self._pending_aspect = None
        if self._pending_style is not None:
            self.push_style(self._pending_style)
        if self._pending_bind is not None:
            clip, video_path = self._pending_bind
            self._pending_bind = None
            self._push_clip(clip, video_path)

    def _push_clip(self, clip: ClipDraft, video_path: str) -> None:
        if not video_path:
            return
        # Only reload the source when the path changes; otherwise just adjust
        # the time range and crop.
        if video_path != self._video_path:
            self._video_path = video_path
            url = "file:///" + os.path.abspath(video_path).replace("\\", "/")
            url_json = json.dumps(url)
            self._send(
                f"vc.setSource({url_json}, {clip.start_sec}, {clip.end_sec})")
        else:
            self._send(
                f"vc.setClipRange({clip.start_sec}, {clip.end_sec})")
        # Crop rect: existing dict or null → JS centers
        crop_arg = "null" if not clip.crop_rect else json.dumps(clip.crop_rect)
        self._send(f"vc.setCrop({crop_arg})")
        # Hook / outro text — pushed per-clip; style stays project-level
        meta = json.dumps({"hook":  clip.hook  or "",
                            "outro": clip.outro or ""},
                           ensure_ascii=False)
        self._send(f"vc.setClipMeta({meta})")

    def _send(self, code: str) -> None:
        try:
            self._web.evaluate_js(code)
        except Exception:
            pass

    def _on_web_message(self, data) -> None:
        if not isinstance(data, dict):
            return
        if data.get("type") == "crop" and self._clip is not None:
            rect = data.get("rect") or {}
            try:
                rect = {k: float(rect[k]) for k in ("x", "y", "w", "h")}
            except (KeyError, ValueError, TypeError):
                return
            self._clip.crop_rect = rect
            if self._on_change:
                self._on_change(self._clip, dict(rect))

# ── PackageForm ────────────────────────────────────────────────────────────

class PackageForm(tk.Frame):
    """Hook / Outro / Title / Hashtags entries.

    bind_clip(clip) fills the entries from the clip; subsequent edits write
    back to clip via trace + fire on_change(clip).
    """

    def __init__(self, master: tk.Misc, *,
                 on_change: Callable[[ClipDraft], None] | None = None,
                 ai_button_factory: Callable | None = None,
                 ai_worker_for_clip: Callable | None = None,
                 **kwargs):
        super().__init__(master, **kwargs)
        self._on_change = on_change
        self._clip: ClipDraft | None = None
        self._suspend = False
        self._ai_button_factory = ai_button_factory
        self._ai_worker_for_clip = ai_worker_for_clip

        self._hook_var  = tk.StringVar()
        self._outro_var = tk.StringVar()
        self._title_var = tk.StringVar()
        self._tags_var  = tk.StringVar()

        # Hook
        ttk.Label(self, text=_tr("tool.clip.field_hook")).grid(
            row=0, column=0, sticky="e", padx=4, pady=2)
        ttk.Entry(self, textvariable=self._hook_var, width=70).grid(
            row=0, column=1, sticky="we", padx=4, pady=2)

        # Outro
        ttk.Label(self, text=_tr("tool.clip.field_outro")).grid(
            row=1, column=0, sticky="e", padx=4, pady=2)
        ttk.Entry(self, textvariable=self._outro_var, width=70).grid(
            row=1, column=1, sticky="we", padx=4, pady=2)

        # Title
        ttk.Label(self, text=_tr("tool.clip.field_clip_title")).grid(
            row=2, column=0, sticky="e", padx=4, pady=2)
        ttk.Entry(self, textvariable=self._title_var, width=70).grid(
            row=2, column=1, sticky="we", padx=4, pady=2)

        # Hashtags
        ttk.Label(self, text=_tr("tool.clip.field_hashtags")).grid(
            row=3, column=0, sticky="e", padx=4, pady=2)
        ttk.Entry(self, textvariable=self._tags_var, width=70).grid(
            row=3, column=1, sticky="we", padx=4, pady=2)

        self.columnconfigure(1, weight=1)

        # AI button row
        if ai_button_factory is not None and ai_worker_for_clip is not None:
            self._ai_holder = ttk.Frame(self)
            self._ai_holder.grid(row=4, column=1, sticky="w", padx=4,
                                  pady=(4, 2))
            self._ai_btn = None  # rebuilt on each bind_clip
        else:
            self._ai_holder = None
            self._ai_btn = None

        # Wire trace AFTER widgets are built
        self._hook_var .trace_add("write", self._on_hook_changed)
        self._outro_var.trace_add("write", self._on_outro_changed)
        self._title_var.trace_add("write", self._on_title_changed)
        self._tags_var .trace_add("write", self._on_tags_changed)

    # ── public API ──
    def bind_clip(self, clip: ClipDraft | None) -> None:
        self._clip = clip
        self._suspend = True
        try:
            if clip is None:
                self._hook_var.set("")
                self._outro_var.set("")
                self._title_var.set("")
                self._tags_var.set("")
            else:
                self._hook_var .set(clip.hook  or "")
                self._outro_var.set(clip.outro or "")
                self._title_var.set(clip.title or "")
                self._tags_var .set(" ".join(clip.hashtags or []))
        finally:
            self._suspend = False
        # Rebuild AI button so it captures this clip in its closure
        if self._ai_holder is not None:
            for w in self._ai_holder.winfo_children():
                w.destroy()
            if clip is None:
                return
            worker = self._ai_worker_for_clip(clip)
            self._ai_btn = self._ai_button_factory(
                self._ai_holder,
                idle_text=_tr("tool.clip.btn_ai_package"),
                worker=worker,
                on_success=lambda result, c=clip: self._apply_ai_result(c, result),
            )
            self._ai_btn.pack(side="left")

    def _apply_ai_result(self, clip: ClipDraft, result: dict) -> None:
        if self._clip is not clip:
            return    # user moved on; AI result lands on clip directly anyway
        self._suspend = True
        try:
            self._hook_var .set(result.get("hook",  "") or "")
            self._outro_var.set(result.get("outro", "") or "")
            self._title_var.set(result.get("title", "") or "")
            self._tags_var .set(" ".join(result.get("hashtags") or []))
        finally:
            self._suspend = False
        # Now apply to the clip itself (mirrors what trace would do)
        clip.hook  = self._hook_var.get()
        clip.outro = self._outro_var.get()
        clip.title = self._title_var.get()
        clip.hashtags = [t.strip() for t in self._tags_var.get().split()
                          if t.strip()]
        if self._on_change:
            self._on_change(clip)

    # ── internal ──
    def _on_hook_changed(self, *_a):
        if self._suspend or self._clip is None: return
        self._clip.hook = self._hook_var.get()
        if self._on_change: self._on_change(self._clip)

    def _on_outro_changed(self, *_a):
        if self._suspend or self._clip is None: return
        self._clip.outro = self._outro_var.get()
        if self._on_change: self._on_change(self._clip)

    def _on_title_changed(self, *_a):
        if self._suspend or self._clip is None: return
        self._clip.title = self._title_var.get()
        if self._on_change: self._on_change(self._clip)

    def _on_tags_changed(self, *_a):
        if self._suspend or self._clip is None: return
        self._clip.hashtags = [t.strip() for t in self._tags_var.get().split()
                                if t.strip()]
        if self._on_change: self._on_change(self._clip)


# ── ClipCard ───────────────────────────────────────────────────────────────

_STATUS_COLORS = {
    "draft":    ("◯", "#9aa0a6"),
    "reviewed": ("✓", "#1a7f37"),
    "exported": ("●", "#2563eb"),
    "skipped":  ("✗", "#9aa0a6"),
}


class ClipCard(tk.Frame):
    """One clip's inline editor — collapsible.

    Collapsed (default): single-line header showing
      [▶] glyph #id [time-range] dur · title · [skip] [×]
    Click the row → calls on_focus(clip); host expands this one and
    collapses siblings.

    Expanded: header + excerpt + PackageForm + AI / action buttons.
    Only the focused card is expanded; others stay one row tall.
    """

    def __init__(self, master: tk.Misc, clip: ClipDraft, *,
                 on_focus: Callable[[ClipDraft], None] | None = None,
                 on_remove: Callable[[ClipDraft], None] | None = None,
                 on_change: Callable[[ClipDraft], None] | None = None,
                 ai_button_factory: Callable | None = None,
                 ai_worker_for_clip: Callable | None = None,
                 **kwargs):
        super().__init__(master, highlightthickness=1,
                          highlightbackground="#d0d0d8", **kwargs)
        self._clip = clip
        self._on_focus = on_focus
        self._on_remove = on_remove
        self._on_change = on_change
        self._ai_button_factory = ai_button_factory
        self._ai_worker_for_clip = ai_worker_for_clip
        self._expanded = False

        # ── Header row (always visible, clickable) ──
        self._header = tk.Frame(self, background="#fafafa", cursor="hand2")
        self._header.pack(fill="x")

        self._chevron_var = tk.StringVar(value="▶")
        self._chevron_lbl = tk.Label(self._header,
                                       textvariable=self._chevron_var,
                                       background="#fafafa", fg="#666",
                                       width=2, font=("", 10))
        self._chevron_lbl.pack(side="left", padx=(4, 0))

        self._header_var = tk.StringVar()
        self._header_lbl = tk.Label(self._header, textvariable=self._header_var,
                                      background="#fafafa", anchor="w",
                                      font=("", 10), justify="left")
        self._header_lbl.pack(side="left", fill="x", expand=True, padx=4,
                                pady=4)

        # Inline action buttons in the header (always reachable)
        self._skip_btn = ttk.Button(
            self._header, text=self._skip_label(),
            command=self._on_skip_click, width=8)
        self._skip_btn.pack(side="right", padx=2, pady=2)
        ttk.Button(self._header, text="×",
                    command=self._on_remove_click, width=3).pack(
            side="right", padx=2, pady=2)

        # Click anywhere on header → focus + toggle
        for w in (self._header, self._header_lbl, self._chevron_lbl):
            w.bind("<Button-1>", self._on_header_click)

        # ── Body (built lazily on first expand) ──
        self._body: tk.Frame | None = None
        self._excerpt_lbl: tk.Label | None = None
        self._form: PackageForm | None = None

        self._refresh_header()

    # ── public API ──
    def update_clip(self, clip: ClipDraft) -> None:
        self._clip = clip
        self._refresh_header()
        self._skip_btn.config(text=self._skip_label())
        if self._body is not None:
            if self._excerpt_lbl is not None:
                self._excerpt_lbl.config(text=(clip.original_excerpt or "")[:300])
            if self._form is not None:
                self._form.bind_clip(clip)

    def set_focused(self, focused: bool) -> None:
        # Border accent + body expansion follow the focus state.
        try:
            self.config(highlightbackground=("#2563eb" if focused else "#d0d0d8"),
                        highlightthickness=(2 if focused else 1))
        except tk.TclError:
            pass
        bg = "#eef4ff" if focused else "#fafafa"
        try:
            self._header.config(background=bg)
            self._chevron_lbl.config(background=bg)
            self._header_lbl.config(background=bg)
        except tk.TclError:
            pass
        if focused and not self._expanded:
            self._expand()
        elif not focused and self._expanded:
            self._collapse()

    # ── internal ──
    def _refresh_header(self) -> None:
        c = self._clip
        glyph, _ = _STATUS_COLORS.get(c.status, ("◯", "#999"))
        title = (c.title or c.chapter_title or "").strip()[:60]
        self._header_var.set(
            f"{glyph}  #{c.id}   [{_seconds_to_str(c.start_sec)} – "
            f"{_seconds_to_str(c.end_sec)}]   {int(c.duration)}s   ·  {title}")

    def _skip_label(self) -> str:
        return (_tr("tool.clip.btn_unskip") if self._clip.status == "skipped"
                else _tr("tool.clip.btn_skip"))

    def _on_header_click(self, _event=None) -> None:
        if self._on_focus:
            self._on_focus(self._clip)

    def _build_body(self) -> None:
        if self._body is not None:
            return
        self._body = tk.Frame(self)
        # Excerpt
        self._excerpt_lbl = tk.Label(
            self._body,
            text=(self._clip.original_excerpt or "")[:300],
            fg="#666", wraplength=900, justify="left", anchor="w",
            font=("", 9))
        self._excerpt_lbl.pack(fill="x", padx=8, pady=(4, 4))
        # Package form
        self._form = PackageForm(
            self._body, on_change=self._on_change,
            ai_button_factory=self._ai_button_factory,
            ai_worker_for_clip=self._ai_worker_for_clip)
        self._form.pack(fill="x", padx=4, pady=(2, 6))
        self._form.bind_clip(self._clip)

    def _expand(self) -> None:
        self._build_body()
        self._body.pack(fill="x")
        self._chevron_var.set("▼")
        self._expanded = True

    def _collapse(self) -> None:
        if self._body is not None:
            self._body.pack_forget()
        self._chevron_var.set("▶")
        self._expanded = False

    def _on_skip_click(self) -> None:
        if self._clip.status == "skipped":
            self._clip.status = "draft"
        else:
            self._clip.status = "skipped"
        self._skip_btn.config(text=self._skip_label())
        self._refresh_header()
        if self._on_change:
            self._on_change(self._clip)

    def _on_remove_click(self) -> None:
        if self._on_remove:
            self._on_remove(self._clip)


# ── ClipSummaryTreeview ────────────────────────────────────────────────────

class ClipSummaryTreeview(ttk.Frame):
    """Cross-chapter clip list (Treeview) for the export summary tab.

    bind(clips) repopulates. on_select fires when the user clicks a row.
    get_selected_clips() returns the focused-then-multi-selected list.
    """

    def __init__(self, master: tk.Misc,
                 on_select: Callable[[ClipDraft | None], None] | None = None,
                 **kwargs):
        super().__init__(master, **kwargs)
        self._on_select = on_select
        self._clips: list[ClipDraft] = []

        cols = ("id", "chapter", "range", "duration", "status", "title")
        self._tree = ttk.Treeview(self, columns=cols, show="headings",
                                    selectmode="extended",
                                    style="Clip.Treeview")
        self._tree.heading("id",       text="#")
        self._tree.heading("chapter",  text=_tr("tool.clip.col_chapter"))
        self._tree.heading("range",    text=_tr("tool.clip.col_range"))
        self._tree.heading("duration", text=_tr("tool.clip.col_duration"))
        self._tree.heading("status",   text=_tr("tool.clip.col_status"))
        self._tree.heading("title",    text=_tr("tool.clip.col_clip_title"))
        self._tree.column("id",       width=50,  anchor="center", stretch=False)
        self._tree.column("chapter",  width=200, anchor="w",      stretch=True)
        self._tree.column("range",    width=160, anchor="center", stretch=False)
        self._tree.column("duration", width=70,  anchor="center", stretch=False)
        self._tree.column("status",   width=80,  anchor="center", stretch=False)
        self._tree.column("title",    width=300, anchor="w",      stretch=True)
        self._tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    # ── public API ──
    def bind(self, clips: list[ClipDraft]) -> None:
        # Preserve selection across rebinds when possible
        prior_sel = set(self._tree.selection())
        self._clips = list(clips)
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for c in clips:
            iid = str(c.id)
            dur = int(c.duration)
            mins, secs = divmod(dur, 60)
            glyph, _ = _STATUS_COLORS.get(c.status, ("◯", "#999"))
            self._tree.insert(
                "", "end", iid=iid,
                values=(c.id,
                        f"#{c.chapter_idx+1}  {c.chapter_title}"[:40],
                        f"{_seconds_to_str(c.start_sec)} – "
                        f"{_seconds_to_str(c.end_sec)}",
                        f"{mins}:{secs:02d}",
                        f"{glyph} {c.status}",
                        c.title or ""))
        # restore selection where iids still exist
        keep = [iid for iid in prior_sel if self._tree.exists(iid)]
        if keep:
            self._tree.selection_set(keep)

    def get_selected_clips(self) -> list[ClipDraft]:
        sel = self._tree.selection()
        out = []
        by_id = {str(c.id): c for c in self._clips}
        for iid in sel:
            c = by_id.get(iid)
            if c is not None:
                out.append(c)
        return out

    def get_focused_clip(self) -> ClipDraft | None:
        focus = self._tree.focus()
        if not focus:
            sel = self._tree.selection()
            focus = sel[0] if sel else ""
        if not focus:
            return None
        for c in self._clips:
            if str(c.id) == focus:
                return c
        return None

    def select_clip(self, clip_id: int) -> None:
        iid = str(clip_id)
        if self._tree.exists(iid):
            self._tree.selection_set(iid)
            self._tree.focus(iid)
            self._tree.see(iid)

    def _on_tree_select(self, _event=None) -> None:
        if self._on_select:
            self._on_select(self.get_focused_clip())
