"""ChapterPointCard (Hero callout per chapter) component spec."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from i18n import tr
from core import chapters_io
from core.composition.overlays import ChapterPointCardOverlay

from . import (
    ComponentSpec, DeriveContext, DeriveSource,
    DERIVE_ANALYSIS, install_live_traces, register,
)


def _factory(duration: float) -> ChapterPointCardOverlay:
    return ChapterPointCardOverlay(
        text="",
        start_sec=0.0, end_sec=max(6.0, min(duration, 6.0)),
    )


def _format(ov: ChapterPointCardOverlay) -> str:
    return ov.text


def _build_edit_fields(parent: ttk.Frame, ov: ChapterPointCardOverlay,
                         _time_vars, on_change=None):
    text_v = tk.StringVar(value=ov.text)
    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.card_text"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=text_v, width=42
              ).pack(side="left", fill="x", expand=True)

    def _commit() -> None:
        ov.text = text_v.get().strip()
    if on_change is not None:
        install_live_traces([text_v], _commit, on_change)
    return _commit


def _derive_from_chapters(ctx: DeriveContext) -> list:
    """One Hero callout per chapter, using `key_points[0]` if present
    else a truncated `refined`. Each callout lives ~6 s starting at the
    chapter boundary; the Hero zone (upper third) does not clash with
    LowerThird (lower) or subtitles (bottom)."""
    chapters = ctx.chapters_loader()
    if not chapters:
        return []
    out: list = []
    for ch in chapters:
        start_s = chapters_io.parse_time_str(ch.get("start", ""))
        end_s = chapters_io.parse_time_str(ch.get("end", ""))
        if end_s <= start_s:
            continue
        text = ""
        kps = ch.get("key_points")
        if isinstance(kps, list) and kps:
            cand = str(kps[0]).strip()
            if cand:
                text = cand
        if not text:
            refined = str(ch.get("refined", "")).strip()
            if refined:
                text = refined[:40]
        if not text:
            continue
        card_dur = 6.0
        card_end = min(end_s, start_s + card_dur)
        out.append(ChapterPointCardOverlay(
            text=text, start_sec=start_s, end_sec=card_end,
        ))
    return out


register(ComponentSpec(
    kind="chapter_point_card",
    dataclass_type=ChapterPointCardOverlay,
    label_key="tool.news_desk.add.chapter_point_card",
    name_key="tool.news_desk.kind.chapter_point_card",
    default_factory=_factory,
    format_content=_format,
    build_edit_fields=_build_edit_fields,
    derive_sources=[
        DeriveSource(
            kind=DERIVE_ANALYSIS,
            label_key="tool.news_desk.derive_cpc",
            handler=_derive_from_chapters,
        ),
    ],
))
