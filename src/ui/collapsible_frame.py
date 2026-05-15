"""CollapsibleFrame — a labeled frame with a clickable header that hides
or shows its body. Used to declutter long control panels.

Usage:
    cf = CollapsibleFrame(parent, text="Watermark", expanded=False)
    cf.pack(fill="x", padx=6, pady=4)
    ttk.Label(cf.body, text="...").pack(...)   # pack into .body
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


_GLYPH_EXPANDED = "▼"
_GLYPH_COLLAPSED = "▶"


class CollapsibleFrame(ttk.Frame):
    """A frame whose content can be hidden behind a clickable header.

    The header is a borderless ttk.Button styled to look like a label.
    Children should be added to `self.body`, not directly to the
    CollapsibleFrame, so the toggle can pack/unpack them as a group.
    """

    def __init__(self, parent, *, text: str = "", expanded: bool = True,
                 **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self._expanded = bool(expanded)
        self._label = text

        self._header = ttk.Button(
            self, text=self._header_text(),
            command=self.toggle, style="CollapsibleFrame.TButton")
        self._header.pack(side="top", fill="x")

        # Body holds caller-added widgets. We reach into it via .body.
        self.body = ttk.Frame(self)
        if self._expanded:
            self.body.pack(side="top", fill="x", padx=4, pady=(2, 4))

    def _header_text(self) -> str:
        glyph = _GLYPH_EXPANDED if self._expanded else _GLYPH_COLLAPSED
        return f"{glyph}  {self._label}" if self._label else glyph

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._header.config(text=self._header_text())
        if self._expanded:
            self.body.pack(side="top", fill="x", padx=4, pady=(2, 4))
        else:
            self.body.pack_forget()

    @property
    def expanded(self) -> bool:
        return self._expanded


def install_style(root: tk.Misc) -> None:
    """Register the borderless button style used by CollapsibleFrame
    headers. Call once per app (idempotent — ttk.Style.configure is safe
    to call repeatedly)."""
    style = ttk.Style(root)
    style.configure(
        "CollapsibleFrame.TButton",
        anchor="w",
        padding=(4, 2),
        relief="flat",
        font=("TkDefaultFont", 9, "bold"),
    )
