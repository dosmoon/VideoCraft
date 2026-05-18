"""Per-clip detail editor for the clip workbench.

Embedded in the Clips tab's right pane: shows a CompositionPreview for
the currently selected candidate, plus editable time / hook / outro /
title / tags fields and an SRT cue list. Edits write into the host's
override dict; the host owns persistence, render-tv refresh, and
candidate data access.

Host contract — the panel calls these on its host (typically
ClipToolApp). Naming follows the workbench's existing methods so the
extraction is a near-mechanical move rather than an API redesign.

  Attributes:
    master                       Tk widget root for dialogs
    _candidate_meta              list[dict]  candidate hotclips entries
    _clips_overrides             dict[int, dict]  per-candidate edits
    _current_style               CompositionStyle  active style
    material_model               NewsVideoModel  for source_video_path

  Methods:
    _effective_start_end(idx) -> (float, float)
    _effective_hook(idx) -> str
    _effective_outro(idx) -> str
    _effective_title(idx) -> str
    _effective_tags(idx) -> list[str]
    _effective_crop(idx) -> dict | None
    _override(idx) -> dict
    _save_all() -> None
    _refresh_render_tv() -> None
    _cues_for_window(start, end) -> list[dict]
    _build_preview_timeline(start, end, *, hook="", outro="") -> Timeline
    _preview_aspect_short_edge() -> (str, int)
"""

from __future__ import annotations

import os
import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from core.composition.preview import CompositionPreview
from i18n import tr


# ── Local helpers (mirror clip_tool's module-level versions) ───────────────

_TS_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d+))?$")


def _parse_ts(s: str) -> float:
    m = _TS_RE.match((s or "").strip())
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mn = int(m.group(2))
    sec = int(m.group(3))
    frac = m.group(4)
    base = h * 3600 + mn * 60 + sec
    if frac:
        base += int(frac[:3].ljust(3, "0")) / 1000.0
    return base


def _format_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


# ── ClipDetailPanel ────────────────────────────────────────────────────────

class ClipDetailPanel:
    """Detail editor for one clip candidate.

    Lifecycle:
        panel = ClipDetailPanel(parent_frame, host)
        # parent_frame stays mounted; panel starts in the empty state
        panel.show(idx)         # load a clip
        panel.push_preview()    # re-push timeline after style change
        panel.refresh_crop()    # re-apply effective crop after a global crop change
        panel.destroy_preview() # on workbench teardown
    """

    def __init__(self, parent: ttk.Frame, host) -> None:
        self._host = host
        self._detail_idx: Optional[int] = None
        self._detail_vars: dict[str, tk.StringVar] = {}
        self._detail_widgets: dict = {}
        self._preview: Optional[CompositionPreview] = None
        self._build_ui(parent)

    # ── public API ────────────────────────────────────────────────────────

    @property
    def current_idx(self) -> Optional[int]:
        return self._detail_idx

    @property
    def preview(self) -> Optional[CompositionPreview]:
        return self._preview

    def show(self, idx: int) -> None:
        meta = self._host._candidate_meta
        if not (0 <= idx < len(meta)):
            return
        self._detail_idx = idx
        # Swap empty placeholder for the real container on first load
        self._detail_empty_label.pack_forget()
        self._detail_container.pack(fill="both", expand=True)
        # Preview push
        self.push_preview()
        # Populate fields
        host = self._host
        start, end = host._effective_start_end(idx)
        self._detail_vars["start"].set(_format_ts(start))
        self._detail_vars["end"].set(_format_ts(end))
        self._detail_vars["duration_score"].set(
            tr("clip_tool.detail_duration_score_fmt",
               duration=f"{end - start:.1f}",
               score=str(meta[idx].get("score", "-"))))
        self._detail_vars["hook"].set(host._effective_hook(idx))
        self._detail_vars["outro"].set(host._effective_outro(idx))
        self._detail_vars["title"].set(host._effective_title(idx))
        self._detail_vars["tags"].set(" ".join(host._effective_tags(idx)))
        self._populate_cues_widget(start, end)

    def push_preview(self) -> None:
        """Push timeline state for the current candidate (no-op if none
        loaded). Called whenever the host's style changes or the host
        wants a forced refresh."""
        idx = self._detail_idx
        if idx is None or self._preview is None:
            return
        host = self._host
        video_path = host.material_model.source_video_path
        if not os.path.isfile(video_path):
            return
        start, end = host._effective_start_end(idx)
        self._preview.set_source(video_path, start, end)
        self._preview.set_geometry(host._current_style.output)
        self._preview.set_crop(host._effective_crop(idx))
        self._preview.enable_crop_drag(True)
        aspect, short = host._preview_aspect_short_edge()
        tl = host._build_preview_timeline(
            start, end,
            hook=host._effective_hook(idx),
            outro=host._effective_outro(idx))
        self._preview.set_timeline(tl, aspect=aspect, short_edge=short)

    def refresh_crop(self) -> None:
        """Re-apply effective crop to the preview. Called after the
        global crop changes (e.g. apply-to-all)."""
        if self._detail_idx is None or self._preview is None:
            return
        self._preview.set_crop(self._host._effective_crop(self._detail_idx))

    def destroy_preview(self) -> None:
        if self._preview is not None:
            self._preview.destroy()
            self._preview = None

    # ── UI build ──────────────────────────────────────────────────────────

    def _build_ui(self, parent: ttk.Frame) -> None:
        # Empty-state label (visible when no detail loaded)
        self._detail_empty_var = tk.StringVar(
            value=tr("clip_tool.detail_no_selection"))
        self._detail_empty_label = tk.Label(
            parent, textvariable=self._detail_empty_var,
            bg="white", fg="#888", justify="center")
        self._detail_empty_label.pack(fill="both", expand=True)

        # Container (hidden until first detail load)
        self._detail_container = ttk.Frame(parent)

        # Preview
        self._preview = CompositionPreview(
            self._detail_container,
            on_crop_changed=self._on_crop_changed,
            width=420, height=360)
        self._preview.widget.pack(fill="both", expand=True,
                                   padx=4, pady=4)

        # Time row
        time_row = ttk.LabelFrame(self._detail_container,
                                    text=tr("clip_tool.detail_time"))
        time_row.pack(fill="x", padx=6, pady=4)

        self._detail_vars["start"] = tk.StringVar()
        self._detail_vars["end"] = tk.StringVar()
        for label_key, var_key, nudge_fn in (
                ("clip_tool.detail_start", "start", self._on_nudge_start),
                ("clip_tool.detail_end",   "end",   self._on_nudge_end)):
            row = ttk.Frame(time_row); row.pack(fill="x", padx=4, pady=2)
            ttk.Label(row, text=tr(label_key), width=8
                      ).pack(side="left")
            ent = ttk.Entry(row, textvariable=self._detail_vars[var_key],
                            width=14)
            ent.pack(side="left", padx=(4, 4))
            ent.bind("<FocusOut>",
                     lambda _e, k=var_key: self._on_time_entry_blur(k))
            ent.bind("<Return>",
                     lambda _e, k=var_key: self._on_time_entry_blur(k))
            ttk.Button(row, text=tr("clip_tool.nudge_minus"),
                       command=lambda fn=nudge_fn: fn(-0.5),
                       width=6).pack(side="left", padx=(2, 0))
            ttk.Button(row, text=tr("clip_tool.nudge_plus"),
                       command=lambda fn=nudge_fn: fn(0.5),
                       width=6).pack(side="left", padx=(2, 0))

        self._detail_vars["duration_score"] = tk.StringVar()
        tk.Label(time_row, textvariable=self._detail_vars["duration_score"],
                 fg="#666", anchor="w").pack(fill="x", padx=4, pady=(2, 4))

        # Text row
        text_row = ttk.LabelFrame(self._detail_container,
                                    text=tr("clip_tool.detail_text"))
        text_row.pack(fill="x", padx=6, pady=4)

        self._detail_vars["hook"] = tk.StringVar()
        self._detail_vars["outro"] = tk.StringVar()
        self._detail_vars["title"] = tk.StringVar()
        self._detail_vars["tags"] = tk.StringVar()
        for label_key, var_key in (
                ("clip_tool.detail_hook",  "hook"),
                ("clip_tool.detail_outro", "outro"),
                ("clip_tool.detail_title", "title"),
                ("clip_tool.detail_tags",  "tags")):
            row = ttk.Frame(text_row); row.pack(fill="x", padx=4, pady=2)
            ttk.Label(row, text=tr(label_key), width=8
                      ).pack(side="left")
            ent = ttk.Entry(row, textvariable=self._detail_vars[var_key])
            ent.pack(side="left", padx=(4, 0), fill="x", expand=True)
            ent.bind("<FocusOut>",
                     lambda _e, k=var_key: self._on_text_entry_blur(k))
            ent.bind("<Return>",
                     lambda _e, k=var_key: self._on_text_entry_blur(k))

        # SRT cues readonly
        cues_row = ttk.LabelFrame(self._detail_container,
                                    text=tr("clip_tool.detail_srt_cues"))
        cues_row.pack(fill="both", expand=False, padx=6, pady=4)
        self._detail_widgets["cues_text"] = tk.Text(
            cues_row, height=6, state="disabled", wrap="word",
            font=("Consolas", 9), bg="#f6f6f6")
        self._detail_widgets["cues_text"].pack(fill="x", padx=4, pady=4)

        # Buttons
        btn_row = ttk.Frame(self._detail_container)
        btn_row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btn_row, text=tr("clip_tool.btn_reset_clip_crop"),
                   command=self._on_reset_crop).pack(side="left")
        ttk.Button(btn_row, text=tr("clip_tool.btn_restore_ai_text"),
                   command=self._on_restore_ai_text).pack(
                       side="left", padx=(6, 0))

        # Without this, clicking any Entry/Text after the WebView2
        # preview has had focus leaves keystrokes stranded in the
        # WebView's input thread (see ui/web_preview attach_focus_grab_fix).
        from ui.web_preview import attach_focus_grab_fix
        attach_focus_grab_fix(parent)

    # ── handlers ──────────────────────────────────────────────────────────

    def _on_time_entry_blur(self, key: str) -> None:
        if self._detail_idx is None:
            return
        raw = self._detail_vars[key].get()
        secs = _parse_ts(raw)
        ov = self._host._override(self._detail_idx)
        ov[f"{key}_sec"] = secs
        self._detail_vars[key].set(_format_ts(secs))
        self._refresh_dependents()
        self._host._refresh_render_tv()
        self._host._save_all()

    def _on_text_entry_blur(self, key: str) -> None:
        if self._detail_idx is None:
            return
        raw = self._detail_vars[key].get()
        ov = self._host._override(self._detail_idx)
        if key == "tags":
            tags = [t.strip() for t in raw.split() if t.strip()]
            if tags:
                ov["hashtags"] = tags
            else:
                ov.pop("hashtags", None)
        else:
            field = {
                "hook":  "hook_text",
                "outro": "outro_text",
                "title": "title",
            }[key]
            if raw.strip():
                ov[field] = raw
            else:
                ov.pop(field, None)
        self._host._refresh_render_tv()
        self._host._save_all()
        # Re-push timeline so hook/outro overlay reflects edited text
        self.push_preview()

    def _on_nudge_start(self, delta: float) -> None:
        if self._detail_idx is None:
            return
        start, end = self._host._effective_start_end(self._detail_idx)
        new_start = max(0.0, min(end - 0.1, start + delta))
        ov = self._host._override(self._detail_idx)
        ov["start_sec"] = new_start
        self._detail_vars["start"].set(_format_ts(new_start))
        self._refresh_dependents()
        self._host._refresh_render_tv()
        self._host._save_all()
        if self._preview is not None:
            self._preview.set_clip_range(new_start, end)

    def _on_nudge_end(self, delta: float) -> None:
        if self._detail_idx is None:
            return
        start, end = self._host._effective_start_end(self._detail_idx)
        new_end = max(start + 0.1, end + delta)
        ov = self._host._override(self._detail_idx)
        ov["end_sec"] = new_end
        self._detail_vars["end"].set(_format_ts(new_end))
        self._refresh_dependents()
        self._host._refresh_render_tv()
        self._host._save_all()
        if self._preview is not None:
            self._preview.set_clip_range(start, new_end)

    def _on_crop_changed(self, rect: dict) -> None:
        """Called from JS when the user drags the crop rect."""
        if self._detail_idx is None:
            return
        if not rect or "x" not in rect:
            return
        self._host._override(self._detail_idx)["crop_rect"] = rect
        self._host._save_all()

    def _on_reset_crop(self) -> None:
        if self._detail_idx is None:
            return
        ov = self._host._clips_overrides.get(self._detail_idx)
        if ov and "crop_rect" in ov:
            ov.pop("crop_rect", None)
        self.refresh_crop()
        self._host._save_all()

    def _on_restore_ai_text(self) -> None:
        if self._detail_idx is None:
            return
        if not messagebox.askyesno(
                "VideoCraft",
                tr("clip_tool.confirm_restore_ai_text"),
                parent=self._host.master):
            return
        ov = self._host._clips_overrides.get(self._detail_idx)
        if ov:
            for k in ("hook_text", "outro_text", "title", "hashtags"):
                ov.pop(k, None)
        self.show(self._detail_idx)
        self._host._refresh_render_tv()
        self._host._save_all()

    # ── internals ─────────────────────────────────────────────────────────

    def _refresh_dependents(self) -> None:
        idx = self._detail_idx
        if idx is None:
            return
        host = self._host
        start, end = host._effective_start_end(idx)
        self._detail_vars["duration_score"].set(
            tr("clip_tool.detail_duration_score_fmt",
               duration=f"{end - start:.1f}",
               score=str(host._candidate_meta[idx].get("score", "-"))))
        self._populate_cues_widget(start, end)
        # Subtitle window changed → re-push timeline with the new range
        self.push_preview()

    def _populate_cues_widget(self, start: float, end: float) -> None:
        cues = self._host._cues_for_window(start, end)
        widget = self._detail_widgets["cues_text"]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for c in cues:
            widget.insert("end",
                           f"[{_format_ts(c['start'])}]  {c['text']}\n")
        widget.configure(state="disabled")
