"""LowerThird (name plate) component spec."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from i18n import tr
from core import source_context
from core.composition.overlays import LowerThirdOverlay

from . import (
    ComponentSpec, DeriveContext, DeriveSource,
    DERIVE_BASIC_INFO, install_live_traces, register,
)


def _factory(duration: float) -> LowerThirdOverlay:
    return LowerThirdOverlay(
        title="", subtitle="",
        start_sec=0.0, end_sec=max(10.0, duration),
        position="bottom-left",
    )


def _format(ov: LowerThirdOverlay) -> str:
    return f"{ov.title} | {ov.subtitle}"


def _build_edit_fields(parent: ttk.Frame, ov: LowerThirdOverlay,
                         _time_vars, on_change=None):
    title_v = tk.StringVar(value=ov.title)
    sub_v = tk.StringVar(value=ov.subtitle)
    pos_v = tk.StringVar(value=ov.position)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.title"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=title_v, width=42
              ).pack(side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.subtitle"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=sub_v, width=42
              ).pack(side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.position"), width=10
              ).pack(side="left")
    ttk.Combobox(row, textvariable=pos_v, state="readonly",
                  values=["bottom-left", "bottom-right"], width=20
                  ).pack(side="left")

    def _commit() -> None:
        ov.title = title_v.get().strip()
        ov.subtitle = sub_v.get().strip()
        ov.position = pos_v.get() or "bottom-left"
    if on_change is not None:
        install_live_traces([title_v, sub_v, pos_v], _commit, on_change)
    return _commit


def _derive_from_basic(ctx: DeriveContext) -> list:
    info = source_context.read_basic_info(ctx.project.source_dir)
    sub_ctx = source_context.read_context(ctx.project.source_dir)
    if info.is_empty() and sub_ctx.is_empty():
        return []
    title = info.host or ""
    # Subtitle line: host_bio + host_affiliation + event_date. Embedding the
    # date here is the lightest way to put broadcast date on screen; combine
    # with a DateStampOverlay if you want a persistent corner stamp too.
    parts: list[str] = []
    if info.host_bio:
        parts.append(info.host_bio)
    if sub_ctx.host_affiliation:
        parts.append(sub_ctx.host_affiliation)
    if info.event_date:
        parts.append(info.event_date)
    sub = " · ".join(parts)
    return [LowerThirdOverlay(
        title=title, subtitle=sub,
        start_sec=2.0, end_sec=max(12.0, min(ctx.duration, 30.0)),
        position="bottom-left",
    )]


register(ComponentSpec(
    kind="lower_third",
    dataclass_type=LowerThirdOverlay,
    label_key="tool.news_desk.add.lower_third",
    name_key="tool.news_desk.kind.lower_third",
    default_factory=_factory,
    format_content=_format,
    build_edit_fields=_build_edit_fields,
    derive_sources=[
        DeriveSource(
            kind=DERIVE_BASIC_INFO,
            label_key="tool.news_desk.derive_lt",
            handler=_derive_from_basic,
        ),
    ],
))
