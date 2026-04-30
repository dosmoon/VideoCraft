"""
tools/preferences/preferences.py - Settings panel as a Hub tab.

Sections:
  1. Interface Language
  2. Environment Health — table-driven dashboard fed by core.env registry
"""

import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, scrolledtext

import i18n
from i18n import tr
from tools.base import ToolBase
from core import env


# Color palette
_COLOR_OK     = "#2e8b57"
_COLOR_FAIL   = "#c0392b"
_COLOR_DIM    = "#888"
_COLOR_HINT   = "#c06000"
_COLOR_ACTION = "#0078d4"
_COLOR_ACTION_HOVER = "#1a8ae5"


class PreferencesApp(ToolBase):
    """Settings tab: language + environment dashboard."""

    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.preferences.title"))
        master.geometry("760x880")
        master.resizable(True, True)

        # Scrollable root
        canvas = tk.Canvas(master, highlightthickness=0)
        scrollbar = ttk.Scrollbar(master, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        root = tk.Frame(canvas, padx=24, pady=20)
        _win = canvas.create_window((0, 0), window=root, anchor="nw")

        root.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        # Per-component widgets keyed by component id, set up in _build_env_section
        self._row_widgets: dict[str, dict] = {}
        # Shared install/upgrade lock — only one component at a time
        self._installing: bool = False

        self._build_language_section(root)
        self._build_env_section(root)

        # Initial status refresh (background to avoid blocking UI)
        threading.Thread(target=self._refresh_all_in_bg, daemon=True).start()

    # ── Language ─────────────────────────────────────────────────────────────

    def _build_language_section(self, root):
        section = tk.LabelFrame(
            root, text=tr("tool.preferences.section_language"),
            padx=16, pady=12,
        )
        section.pack(fill="x")

        tk.Label(section, text=tr("tool.preferences.language_label")).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=6,
        )

        self._lang_labels = {
            "zh": tr("tool.preferences.language_zh"),
            "en": tr("tool.preferences.language_en"),
        }
        self._current_lang = i18n.get_current_lang()
        self._lang_var = tk.StringVar(
            value=self._lang_labels.get(self._current_lang, self._lang_labels["zh"])
        )
        ttk.Combobox(
            section, textvariable=self._lang_var, state="readonly", width=16,
            values=[self._lang_labels["zh"], self._lang_labels["en"]],
        ).grid(row=0, column=1, sticky="w", pady=6)

        tk.Button(
            section, text=tr("tool.preferences.save"),
            command=self._on_lang_save, width=14,
            bg=_COLOR_ACTION, fg="white", relief="flat",
            activebackground=_COLOR_ACTION_HOVER, cursor="hand2",
        ).grid(row=0, column=2, padx=(12, 0), pady=6)

        self._lang_status_lbl = tk.Label(section, text="", fg=_COLOR_OK, anchor="w")
        self._lang_status_lbl.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _on_lang_save(self):
        selected_label = self._lang_var.get()
        code = next(
            (k for k, v in self._lang_labels.items() if v == selected_label),
            i18n.DEFAULT_LANG,
        )
        try:
            i18n.set_current_lang(code)
        except Exception as e:
            self._lang_status_lbl.config(text=f"✗ {e}", fg=_COLOR_FAIL)
            return

        if code == self._current_lang:
            self._lang_status_lbl.config(
                text=tr("tool.preferences.saved_no_change"), fg=_COLOR_OK,
            )
        else:
            self._lang_status_lbl.config(
                text=tr("tool.preferences.saved_restart"), fg=_COLOR_HINT,
            )
        self.set_done()

    # ── Environment dashboard ────────────────────────────────────────────────

    def _build_env_section(self, root):
        section = tk.LabelFrame(
            root, text=tr("env.section.title"),
            padx=16, pady=12,
        )
        section.pack(fill="both", expand=True, pady=(16, 0))
        section.columnconfigure(0, weight=1)

        # Group components by category
        comps = env.list_components()
        categories: dict[str, list] = {}
        for c in comps:
            categories.setdefault(c.category, []).append(c)

        row_idx = 0
        for category in ("binary", "python"):
            if category not in categories:
                continue
            tk.Label(
                section, text=tr(f"env.category.{category}"),
                fg=_COLOR_DIM, font=("Segoe UI", 9, "bold"),
                anchor="w",
            ).grid(row=row_idx, column=0, sticky="ew", pady=(8, 4))
            row_idx += 1

            grid = tk.Frame(section)
            grid.grid(row=row_idx, column=0, sticky="ew")
            grid.columnconfigure(1, weight=1)
            row_idx += 1

            for sub_idx, comp in enumerate(categories[category]):
                self._build_component_row(grid, sub_idx, comp)

        # Refresh-all + shared log frame
        toolbar = tk.Frame(section)
        toolbar.grid(row=row_idx, column=0, sticky="ew", pady=(12, 4))
        tk.Button(
            toolbar, text=tr("env.action.refresh_all"),
            command=lambda: threading.Thread(target=self._refresh_all_in_bg, daemon=True).start(),
            width=14,
        ).pack(side="left")
        row_idx += 1

        self._env_log = scrolledtext.ScrolledText(
            section, height=8, state="disabled",
            font=("Consolas", 9), wrap="word",
        )
        self._env_log.grid(row=row_idx, column=0, sticky="ew", pady=(8, 0))

    def _build_component_row(self, parent, row: int, comp):
        """Build one row: [label] [status] [action button]."""
        label_lbl = tk.Label(parent, text=tr(comp.label_key), anchor="w", width=16)
        label_lbl.grid(row=row, column=0, sticky="w", padx=(8, 8), pady=2)

        status_lbl = tk.Label(parent, text="…", anchor="w", fg=_COLOR_DIM)
        status_lbl.grid(row=row, column=1, sticky="w", pady=2)

        action_btn = tk.Button(parent, text="", width=18, cursor="hand2")
        action_btn.grid(row=row, column=2, sticky="e", padx=(8, 8), pady=2)

        self._row_widgets[comp.id] = {
            "comp": comp,
            "status": status_lbl,
            "action": action_btn,
        }

    def _render_row(self, comp_id: str, result):
        """Update one row's status + action button based on detection result."""
        widgets = self._row_widgets[comp_id]
        comp = widgets["comp"]
        status_lbl = widgets["status"]
        action_btn = widgets["action"]

        # Status text
        if result.available:
            ver = result.version or "?"
            src = tr(f"env.status.{result.source}") if result.source else ""
            status_lbl.config(
                text=f"✓  {ver}  ({src})" if src else f"✓  {ver}",
                fg=_COLOR_OK,
            )
        else:
            status_lbl.config(text=f"✗  {tr('env.status.missing')}", fg=_COLOR_FAIL)

        # Action button: depends on (component-kind, source)
        if comp.id == "node":
            # Node is special: install always means "install managed", regardless
            # of whether system Node is present. Button label depends on whether
            # managed (specifically) is already installed.
            if result.source == "managed":
                label = tr("env.action.reinstall_node")
            else:
                label = tr("env.action.setup_node")
            action_btn.config(
                text=label,
                bg=_COLOR_ACTION, fg="white", relief="flat",
                activebackground=_COLOR_ACTION_HOVER,
                command=lambda cid=comp.id: self._do_install(cid),
            )
        elif comp.install is not None:
            if not result.available:
                # Pip package: not installed → install
                action_btn.config(
                    text=tr("env.action.install"),
                    bg=_COLOR_ACTION, fg="white", relief="flat",
                    activebackground=_COLOR_ACTION_HOVER,
                    command=lambda cid=comp.id: self._do_install(cid),
                )
            else:
                # Pip package: already installed → upgrade
                action_btn.config(
                    text=tr("env.action.upgrade"),
                    bg="SystemButtonFace", fg="black", relief="raised",
                    activebackground="SystemButtonFace",
                    command=lambda cid=comp.id: self._do_install(cid),
                )
        else:
            # No installer — link to install guide (when missing) or just refresh
            if not result.available and comp.info_url:
                action_btn.config(
                    text=tr("env.action.install_guide"),
                    bg="SystemButtonFace", fg=_COLOR_ACTION, relief="flat",
                    activebackground="SystemButtonFace",
                    command=lambda url=comp.info_url: self._open_url(url),
                )
            else:
                action_btn.config(
                    text=tr("env.action.refresh"),
                    bg="SystemButtonFace", fg="black", relief="raised",
                    activebackground="SystemButtonFace",
                    command=lambda cid=comp.id: self._refresh_one(cid),
                )

    def _refresh_one(self, comp_id: str):
        """Re-detect a single component (UI-thread safe)."""
        def run():
            result = env.detect_one(comp_id)
            self.master.after(0, self._render_row, comp_id, result)
        threading.Thread(target=run, daemon=True).start()

    def _refresh_all_in_bg(self):
        """Background refresh of all visible components."""
        for comp_id in self._row_widgets:
            try:
                result = env.detect_one(comp_id)
            except Exception as e:
                self.master.after(0, self._append_log, f"detect({comp_id}) failed: {e}")
                continue
            self.master.after(0, self._render_row, comp_id, result)

    def _do_install(self, comp_id: str):
        """Trigger install/upgrade for a component. Streams pip output to log."""
        if self._installing:
            self._append_log("Another install is in progress; please wait.")
            return
        self._installing = True
        # Disable all action buttons during install
        for w in self._row_widgets.values():
            w["action"].config(state="disabled")

        comp = self._row_widgets[comp_id]["comp"]
        action_label = "upgrade" if env.detect_one(comp_id).available else "install"
        self._append_log(tr("env.log.starting", action=action_label, component=comp_id))

        def on_log(line: str):
            self.master.after(0, self._append_log, line)

        def run():
            err = None
            try:
                env.install_one(comp_id, on_log)
            except Exception as e:
                err = str(e)
            self.master.after(0, self._on_install_done, comp_id, err)

        threading.Thread(target=run, daemon=True).start()

    def _on_install_done(self, comp_id: str, err: str | None):
        if err:
            self._append_log(tr("env.log.install_failed", err=err))
        else:
            self._append_log(tr("env.log.install_done"))
        self._installing = False
        # Re-enable buttons + refresh status
        for w in self._row_widgets.values():
            w["action"].config(state="normal")
        self._refresh_one(comp_id)

    def _open_url(self, url: str):
        try:
            webbrowser.open(url)
            self._append_log(tr("env.log.url_open", url=url))
        except Exception as e:
            self._append_log(f"failed to open {url}: {e}")

    def _append_log(self, line: str):
        self._env_log.config(state="normal")
        self._env_log.insert("end", line + "\n")
        self._env_log.see("end")
        self._env_log.config(state="disabled")
