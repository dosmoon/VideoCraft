"""TopicStrip (chapter banner) component spec."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from i18n import tr
from core import chapters_io
from core.composition.overlays import TopicStripOverlay

from . import (
    ComponentSpec, DeriveContext, DeriveSource,
    DERIVE_ANALYSIS, register,
)


def _factory(duration: float) -> TopicStripOverlay:
    return TopicStripOverlay(
        topic_text="",
        start_sec=0.0, end_sec=max(10.0, duration),
    )


def _format(ov: TopicStripOverlay) -> str:
    return ov.topic_text


def _build_edit_fields(parent: ttk.Frame, ov: TopicStripOverlay, _time_vars):
    topic_v = tk.StringVar(value=ov.topic_text)
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.topic"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=topic_v, width=42
              ).pack(side="left", fill="x", expand=True)

    def _commit() -> None:
        ov.topic_text = topic_v.get().strip()
    return _commit


def _derive_from_chapters(ctx: DeriveContext) -> list:
    chapters = ctx.chapters_loader()
    if not chapters:
        return []
    out: list = []
    for ch in chapters:
        start_s = chapters_io.parse_time_str(ch.get("start", ""))
        end_s = chapters_io.parse_time_str(ch.get("end", ""))
        title = (ch.get("title") or "").strip()
        if not title or end_s <= start_s:
            continue
        out.append(TopicStripOverlay(
            topic_text=title, start_sec=start_s, end_sec=end_s))
    return out


register(ComponentSpec(
    kind="topic_strip",
    dataclass_type=TopicStripOverlay,
    label_key="tool.news_desk.add.topic_strip",
    name_key="tool.news_desk.kind.topic_strip",
    default_factory=_factory,
    format_content=_format,
    build_edit_fields=_build_edit_fields,
    derive_sources=[
        DeriveSource(
            kind=DERIVE_ANALYSIS,
            label_key="tool.news_desk.derive_ts",
            handler=_derive_from_chapters,
        ),
    ],
))
