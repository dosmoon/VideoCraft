"""Modal subtitle-language picker — reusable across tools.

Originally lived in tools/download/yt_dlp_tool.py; promoted to ui/ so
the manifest workbench step1 card can reuse it without cross-tool
imports. Two construction modes:

  Sync mode (legacy yt-dlp tool path):
      Pass `available=[...]` — list of BCP47 codes already fetched by
      the caller (e.g. via Get Info). Modal opens populated.

  Async mode (manifest step1 path):
      Pass `loader=callable` returning list[str]. Modal opens in a
      "Loading..." state, runs loader in a worker thread, and
      populates when it returns. Errors get rendered as a red hint.
"""

from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable, Optional

from i18n import tr, get_current_lang
from core import lang_names


class SubsLangPicker(tk.Toplevel):
    """Modal language picker.

    Scrollable checkbox list of BCP47 codes with friendly names, a
    live search box that matches code/zh-name/en-name, and a hard
    cap on selections. Manual + auto-caption pickers can both use it.
    """

    def __init__(self, parent, *, title: str,
                 available: Optional[list[str]] = None,
                 current: list[str], max_pick: int,
                 on_ok: Callable[[list[str]], None],
                 loader: Optional[Callable[[], list[str]]] = None):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.geometry("420x520")

        self._max = max_pick
        self._on_ok = on_ok
        self._locale = get_current_lang()
        self._current = list(current)
        self._loader = loader
        self._available: list[str] = list(available or [])
        self._vars: dict[str, tk.BooleanVar] = {
            code: tk.BooleanVar(value=(code in self._current))
            for code in self._available
        }

        # Search box
        top = tk.Frame(self, padx=10, pady=8)
        top.pack(fill=tk.X)
        tk.Label(top, text=tr("tool.download.subs_modal_search"),
                 font=("Arial", 9)).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refilter())
        tk.Entry(top, textvariable=self._search_var,
                 font=("Arial", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        # Scrollable checkbox list
        mid = tk.Frame(self, padx=10)
        mid.pack(fill=tk.BOTH, expand=True)
        self._canvas = tk.Canvas(mid, highlightthickness=0)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(mid, command=self._canvas.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.configure(yscrollcommand=sb.set)
        self._inner = tk.Frame(self._canvas)
        self._win = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>",
                         lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._win, width=e.width))
        self._canvas.bind("<MouseWheel>",
                          lambda e: self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        # Status + buttons
        bottom = tk.Frame(self, padx=10, pady=8)
        bottom.pack(fill=tk.X)
        self._status_label = tk.Label(bottom, text="", font=("Arial", 9), fg="gray")
        self._status_label.pack(side=tk.LEFT)
        self._ok_btn = tk.Button(bottom, text=tr("tool.download.subs_modal_ok"),
                                  command=self._on_ok_click, width=8)
        self._ok_btn.pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(bottom, text=tr("tool.download.subs_modal_cancel"),
                  command=self.destroy, width=8).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(bottom, text=tr("tool.download.subs_modal_clear"),
                  command=self._clear_all, width=10).pack(side=tk.RIGHT, padx=(4, 0))

        # If a loader is set and we have nothing yet, kick off async fetch.
        if self._loader is not None and not self._available:
            self._show_loading()
            threading.Thread(target=self._run_loader, daemon=True).start()
        else:
            self._refilter()
            self._update_status()

        # Center over parent
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
            py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
            self.geometry(f"+{max(px, 0)}+{max(py, 0)}")
        except Exception:
            pass

    # ── Async loader path ────────────────────────────────────────────────────

    def _show_loading(self):
        for w in self._inner.winfo_children():
            w.destroy()
        tk.Label(self._inner, text=tr("tool.download.subs_modal_loading"),
                 font=("Arial", 9), fg="gray", pady=20).pack()
        self._ok_btn.config(state="disabled")

    def _run_loader(self):
        try:
            codes = self._loader() or []
            self.after(0, self._on_loader_done, list(codes), None)
        except Exception as e:
            self.after(0, self._on_loader_done, [], str(e))

    def _on_loader_done(self, codes: list[str], err: Optional[str]):
        if not self.winfo_exists():
            return
        if err:
            for w in self._inner.winfo_children():
                w.destroy()
            tk.Label(self._inner,
                     text=tr("tool.download.subs_modal_load_failed", e=err),
                     font=("Arial", 9), fg="red", pady=20,
                     wraplength=380, justify="left").pack()
            return
        self._available = codes
        self._vars = {
            code: tk.BooleanVar(value=(code in self._current))
            for code in self._available
        }
        self._ok_btn.config(state="normal")
        self._refilter()
        self._update_status()

    # ── Selection state ──────────────────────────────────────────────────────

    def _picked_codes(self) -> list[str]:
        return [c for c, v in self._vars.items() if v.get()]

    def _update_status(self):
        n = len(self._picked_codes())
        self._status_label.config(
            text=tr("tool.download.subs_modal_selected", n=n, max=self._max),
            fg="gray")

    def _on_check_toggle(self, code: str):
        # Enforce max cap: revert the new check if it would exceed.
        picked = self._picked_codes()
        if len(picked) > self._max:
            self._vars[code].set(False)
            self._status_label.config(
                text=tr("tool.download.subs_modal_max_warning", max=self._max),
                fg="red")
            self.after(1500, self._update_status)
        else:
            self._update_status()

    def _refilter(self):
        for w in self._inner.winfo_children():
            w.destroy()
        if not self._available:
            tk.Label(self._inner, text=tr("tool.download.subs_modal_empty_hint"),
                     font=("Arial", 9), fg="gray", pady=20).pack()
            return
        query = self._search_var.get()
        for code in self._available:
            if not lang_names.matches_search(code, query, self._locale):
                continue
            label = lang_names.display_label(code, self._locale)
            cb = tk.Checkbutton(self._inner, text=label,
                                variable=self._vars[code], anchor="w",
                                font=("Arial", 9),
                                command=lambda c=code: self._on_check_toggle(c))
            cb.pack(fill=tk.X, padx=4, pady=1, anchor="w")

    def _clear_all(self):
        for v in self._vars.values():
            v.set(False)
        self._update_status()

    def _on_ok_click(self):
        picked = self._picked_codes()
        if len(picked) > self._max:
            picked = picked[: self._max]
        self._on_ok(picked)
        self.destroy()
