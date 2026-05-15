"""DateStamp (persistent corner date) component spec."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from i18n import tr
from core import source_context
from core.composition.overlays import DateStampOverlay

from . import (
    ComponentSpec, DeriveContext, DeriveSource,
    DERIVE_BASIC_INFO, install_live_traces, register,
)


def _factory(duration: float) -> DateStampOverlay:
    return DateStampOverlay(
        text="",
        start_sec=0.0,
        end_sec=max(60.0, duration),
        position="bottom-left",
    )


def _format(ov: DateStampOverlay) -> str:
    return ov.text


def _build_edit_fields(parent: ttk.Frame, ov: DateStampOverlay,
                         _time_vars, on_change=None):
    text_v = tk.StringVar(value=ov.text)
    pos_v = tk.StringVar(value=ov.position)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.date_text"), width=10
              ).pack(side="left")
    ttk.Entry(row, textvariable=text_v, width=42
              ).pack(side="left", fill="x", expand=True)

    row = ttk.Frame(parent); row.pack(fill="x", pady=2)
    ttk.Label(row, text=tr("tool.news_desk.field.position"), width=10
              ).pack(side="left")
    ttk.Combobox(row, textvariable=pos_v, state="readonly",
                  values=["bottom-left", "bottom-right",
                          "top-left", "top-right"], width=20
                  ).pack(side="left")

    def _commit() -> None:
        ov.text = text_v.get().strip()
        ov.position = pos_v.get() or "bottom-left"
    if on_change is not None:
        install_live_traces([text_v, pos_v], _commit, on_change)
    return _commit


def _derive_from_basic(ctx: DeriveContext) -> list:
    """One persistent corner date stamp pulled from basic_info.event_date.
    Spans the full video. Default bottom-left to stay clear of the
    top-right watermark zone. `replace_existing=True` on the DeriveSource
    makes re-derive idempotent."""
    info = source_context.read_basic_info(ctx.project.source_dir)
    date = (info.event_date or "").strip()
    if not date:
        return []
    return [DateStampOverlay(
        text=date,
        start_sec=0.0, end_sec=max(60.0, ctx.duration),
        position="bottom-left",
    )]


register(ComponentSpec(
    kind="date_stamp",
    dataclass_type=DateStampOverlay,
    label_key="tool.news_desk.add.date_stamp",
    name_key="tool.news_desk.kind.date_stamp",
    default_factory=_factory,
    format_content=_format,
    build_edit_fields=_build_edit_fields,
    derive_sources=[
        DeriveSource(
            kind=DERIVE_BASIC_INFO,
            label_key="tool.news_desk.derive_ds",
            handler=_derive_from_basic,
            replace_existing=True,
        ),
    ],
))
