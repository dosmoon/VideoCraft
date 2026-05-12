"""Generic preview pane for subtitle analysis artifacts.

Lands in the permanent preview tab 0 when the user clicks an analysis
sub-row in the sidebar Subtitles section. Dispatches by analysis kind
to a type-specific render (titles / chapters / hotclips for JSON,
transcript / chapter_transcript / chapter_refined for Markdown).

The renderers are intentionally minimal in P1: enough to verify the
file is on disk and visually correct. Richer interactions (click cue
to jump, score-coloured hotclips, etc.) come in later phases.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from core.subtitle_analysis import AnalysisArtifact, get_type
from i18n import tr


def build_analysis_preview(parent: tk.Frame, artifact: AnalysisArtifact) -> tk.Frame:
    """Build the analysis preview UI inside parent. Returns the outer Frame."""
    outer = tk.Frame(parent, bg="white")

    # Header
    header = tk.Frame(outer, bg="white")
    header.pack(fill="x", padx=12, pady=(10, 6))
    tk.Label(
        header,
        text=f"{artifact.type.icon}  {_display_name(artifact.type.kind)} ({artifact.lang_iso})",
        bg="white", fg="#222",
        font=("Microsoft YaHei UI", 12, "bold"),
        anchor="w",
    ).pack(side="left")

    meta = []
    if artifact.exists:
        meta.append(_fmt_size(artifact.size_bytes))
        meta.append(tr("subtitle.preview.meta_mtime", ts=_fmt_mtime(artifact.mtime)))
    tk.Label(
        header, text="  ·  " + "  ·  ".join(meta) if meta else "",
        bg="white", fg="#888", font=("Microsoft YaHei UI", 9),
    ).pack(side="left")

    # Body — dispatch by kind
    body = tk.Frame(outer, bg="white")
    body.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    if not artifact.exists:
        tk.Label(
            body, text=tr("analysis_preview.missing"),
            bg="white", fg="#888", font=("Microsoft YaHei UI", 11),
        ).pack(expand=True)
        return outer

    try:
        if artifact.type.format == "json":
            _render_json(body, artifact)
        else:
            _render_markdown(body, artifact)
    except Exception as e:
        tk.Label(
            body, text=tr("analysis_preview.read_failed", error=str(e)),
            bg="white", fg="#c00", font=("Microsoft YaHei UI", 9),
            wraplength=600, justify="left",
        ).pack(anchor="w")

    return outer


# ── Format-specific renderers ────────────────────────────────────────────────

def _render_json(parent: tk.Frame, artifact: AnalysisArtifact) -> None:
    with open(artifact.path, "r", encoding="utf-8") as f:
        data = json.load(f)

    kind = artifact.type.kind
    if kind == "titles":
        _render_titles(parent, data)
    elif kind == "chapters":
        _render_chapters(parent, data)
    elif kind == "hotclips":
        _render_hotclips(parent, data)
    else:
        _render_raw_json(parent, data)


def _render_markdown(parent: tk.Frame, artifact: AnalysisArtifact) -> None:
    with open(artifact.path, "r", encoding="utf-8") as f:
        text = f.read()
    _text_box(parent, text)


def _render_titles(parent: tk.Frame, data) -> None:
    # Accept either a bare list of strings/objects or a wrapped {"titles": [...]}.
    items = data.get("titles") if isinstance(data, dict) else data
    if not isinstance(items, list):
        _render_raw_json(parent, data)
        return
    box, frame = _scrollable(parent)
    for i, item in enumerate(items, 1):
        title = item if isinstance(item, str) else (item.get("title") or item.get("text") or repr(item))
        row = tk.Frame(frame, bg="white")
        row.pack(fill="x", padx=4, pady=2)
        tk.Label(row, text=f"{i:>2}.", bg="white", fg="#888",
                 font=("Microsoft YaHei UI", 10), width=4, anchor="ne"
                 ).pack(side="left", padx=(0, 6))
        tk.Label(row, text=title, bg="white", fg="#222",
                 font=("Microsoft YaHei UI", 10), anchor="w",
                 wraplength=520, justify="left",
                 ).pack(side="left", fill="x", expand=True)


def _render_chapters(parent: tk.Frame, data) -> None:
    items = data.get("chapters") if isinstance(data, dict) else data
    if not isinstance(items, list):
        _render_raw_json(parent, data)
        return
    box, frame = _scrollable(parent)
    for i, item in enumerate(items, 1):
        start = (item.get("start") or item.get("start_time") or "") if isinstance(item, dict) else ""
        end = (item.get("end") or item.get("end_time") or "") if isinstance(item, dict) else ""
        title = (item.get("title") or "") if isinstance(item, dict) else str(item)
        row = tk.Frame(frame, bg="white")
        row.pack(fill="x", padx=4, pady=2)
        tk.Label(row, text=f"{i:>2}.", bg="white", fg="#888",
                 font=("Microsoft YaHei UI", 10), width=4, anchor="ne",
                 ).pack(side="left", padx=(0, 6))
        ts = f"{start} → {end}" if start or end else ""
        if ts:
            tk.Label(row, text=ts, bg="white", fg="#0078d4",
                     font=("Consolas", 9), anchor="w", width=24,
                     ).pack(side="left", padx=(0, 8))
        tk.Label(row, text=title, bg="white", fg="#222",
                 font=("Microsoft YaHei UI", 10), anchor="w",
                 wraplength=480, justify="left",
                 ).pack(side="left", fill="x", expand=True)


def _render_hotclips(parent: tk.Frame, data) -> None:
    clips = data.get("clips") if isinstance(data, dict) else data
    if not isinstance(clips, list):
        _render_raw_json(parent, data)
        return
    box, frame = _scrollable(parent)
    for i, c in enumerate(clips, 1):
        if not isinstance(c, dict):
            continue
        card = tk.Frame(frame, bg="#fafafa", bd=1, relief="solid")
        card.pack(fill="x", padx=4, pady=4)
        head = tk.Frame(card, bg="#fafafa")
        head.pack(fill="x", padx=8, pady=(6, 2))
        score = c.get("score")
        score_color = _score_color(score)
        tk.Label(head, text=f"#{i}", bg="#fafafa", fg="#666",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 ).pack(side="left", padx=(0, 8))
        ts = f"{c.get('start', '')} → {c.get('end', '')}"
        tk.Label(head, text=ts, bg="#fafafa", fg="#0078d4",
                 font=("Consolas", 9),
                 ).pack(side="left", padx=(0, 8))
        dur = c.get("duration_sec")
        if dur is not None:
            tk.Label(head, text=f"{dur:.0f}s", bg="#fafafa", fg="#888",
                     font=("Microsoft YaHei UI", 9),
                     ).pack(side="left", padx=(0, 8))
        if score is not None:
            tk.Label(head, text=f"⭐ {score}", bg="#fafafa", fg=score_color,
                     font=("Microsoft YaHei UI", 10, "bold"),
                     ).pack(side="right")
        hook = c.get("hook") or ""
        if hook:
            tk.Label(card, text=hook, bg="#fafafa", fg="#222",
                     font=("Microsoft YaHei UI", 10, "bold"),
                     wraplength=560, justify="left", anchor="w",
                     ).pack(fill="x", padx=8, pady=(2, 2))
        why = c.get("why_viral") or ""
        if why:
            tk.Label(card, text=why, bg="#fafafa", fg="#666",
                     font=("Microsoft YaHei UI", 9),
                     wraplength=560, justify="left", anchor="w",
                     ).pack(fill="x", padx=8, pady=(0, 4))
        title = c.get("suggested_title") or ""
        if title:
            tk.Label(card, text="🏷 " + title, bg="#fafafa", fg="#222",
                     font=("Microsoft YaHei UI", 9, "italic"),
                     wraplength=560, justify="left", anchor="w",
                     ).pack(fill="x", padx=8, pady=(0, 6))


def _render_raw_json(parent: tk.Frame, data) -> None:
    _text_box(parent, json.dumps(data, ensure_ascii=False, indent=2))


# ── UI helpers ───────────────────────────────────────────────────────────────

def _text_box(parent: tk.Frame, text: str) -> None:
    """Read-only scrollable text area."""
    frame = tk.Frame(parent, bg="white")
    frame.pack(fill="both", expand=True)
    vsb = ttk.Scrollbar(frame, orient="vertical")
    txt = tk.Text(
        frame, wrap="word", bg="white", fg="#222",
        font=("Microsoft YaHei UI", 10), relief="flat", padx=8, pady=6,
        yscrollcommand=vsb.set,
    )
    vsb.config(command=txt.yview)
    vsb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    txt.insert("1.0", text)
    txt.configure(state="disabled")


def _scrollable(parent: tk.Frame) -> tuple[tk.Canvas, tk.Frame]:
    """Vertical-scrollable inner Frame. Returns (canvas, inner_frame)."""
    outer = tk.Frame(parent, bg="white")
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg="white", highlightthickness=0)
    vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(canvas, bg="white")
    canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_resize(_e):
        canvas.configure(scrollregion=canvas.bbox("all"))
    inner.bind("<Configure>", _on_inner_resize)

    def _on_canvas_resize(e):
        canvas.itemconfig(canvas.find_all()[0], width=e.width)
    canvas.bind("<Configure>", _on_canvas_resize)

    def _on_mousewheel(e):
        canvas.yview_scroll(int(-e.delta / 120), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

    return canvas, inner


def _score_color(score) -> str:
    if not isinstance(score, (int, float)):
        return "#888"
    if score >= 8:
        return "#c00"
    if score >= 6:
        return "#d97706"
    return "#888"


def _display_name(kind: str) -> str:
    """Resolve i18n display name for a kind."""
    return tr(f"analysis.kind.{kind}")


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def _fmt_mtime(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
