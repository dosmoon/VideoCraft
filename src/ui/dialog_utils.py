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
    dlg.minsize(W, H)              # fallback floor; let content drive natural size

    # Pack the action row FIRST at the bottom so it's pinned and never
    # clipped when body content grows. This is the #1 dialog bug:
    # body.pack(expand=True) followed by btns.pack() pushes the buttons
    # outside the window when the body's natural height exceeds the
    # initial geometry.
    btns = ttk.Frame(dlg); btns.pack(side="bottom", fill="x", padx=12, pady=10)

    body = ttk.Frame(dlg); body.pack(fill="both", expand=True, padx=12, pady=10)
    # ... build body content into body, build buttons into btns

    center_dialog_on_parent(dlg, parent)   # AFTER widgets are packed

Prefer auto-sizing (no `dlg.geometry("WxH")`) for info / confirm
dialogs — text length is hard to predict across i18n. Use minsize for
a sensible floor. Reach for an explicit geometry only when the dialog
hosts widgets that need a specific size (canvas previews, large forms).

`center_dialog_on_parent` runs update_idletasks internally so calling
it after widgets are packed measures the real natural size.
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
