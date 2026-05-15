"""Shared Toplevel dialog helpers.

Use these from any new modal dialog (`tk.Toplevel`) so:
- Position rules stay consistent (centered on the app window, not at the
  screen's top-left where Tk drops Toplevels by default).
- The dialog clamps inside the screen even if the host window straddles
  the edge or is partially off-screen.
- Future Claude / dev sees ONE canonical helper and doesn't need to
  copy-paste the math from another dialog file.

Convention for new dialogs:

    dlg = tk.Toplevel(parent)
    dlg.title(...)
    dlg.transient(parent.winfo_toplevel())
    dlg.grab_set()
    # ... pack widgets, optionally dlg.geometry("WxH") for a fixed size
    center_dialog_on_parent(dlg, parent)

Always call AFTER widgets are packed; the helper runs update_idletasks
internally so winfo_width/height return real values.
"""

from __future__ import annotations

import tkinter as tk


def center_dialog_on_parent(dlg: tk.Toplevel, parent: tk.Misc) -> None:
    """Place `dlg` centered over `parent`'s toplevel window.

    `parent` can be any widget — the helper walks up to its Toplevel so
    callers can pass the same `parent` they used in `tk.Toplevel(parent)`
    without thinking. Result is clamped inside the primary screen so a
    dialog never opens fully off-screen when the host window is dragged
    near an edge.

    Idempotent. Cheap. Safe to call multiple times (e.g. after resizing
    the dialog content), though once is enough for most cases.
    """
    dlg.update_idletasks()
    w = dlg.winfo_width()
    h = dlg.winfo_height()
    host = parent.winfo_toplevel()
    px = host.winfo_rootx()
    py = host.winfo_rooty()
    pw = host.winfo_width()
    ph = host.winfo_height()
    x = px + max(0, (pw - w) // 2)
    y = py + max(0, (ph - h) // 2)
    # Clamp inside screen.
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    x = max(0, min(x, sw - w))
    y = max(0, min(y, sh - h))
    dlg.geometry(f"+{x}+{y}")
