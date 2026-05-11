"""AI Prompt Console — per-task prompt editor + Playground for live A/B trial.

Split out from AI Console 2026-05-11. The original Console grew to four
tabs (Routing / Prompts / Playground / Stats); Prompts and Playground
both serve "prompt authoring" workflows, while Routing/Stats serve
"provider plumbing" — different audience and different time of day.
Two windows let users keep both open side-by-side without paying the
context-switch tax of constantly flipping tabs in one window.

Tabs:
  - Prompts    — central editor for `core.prompts` overrides
  - Playground — drive a (provider, model) with substituted variables
                 and compare two outputs side-by-side
"""

import tkinter as tk
from tkinter import ttk, messagebox

from tools.base import ToolBase
from i18n import tr

from core import prompts as _prompts
from core.ai import config as _ai_cfg


class PromptConsoleApp(ToolBase):
    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.prompts.title"))
        master.geometry("1080x640")

        nb = ttk.Notebook(master)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_prompts    = tk.Frame(nb, padx=8, pady=8)
        self.tab_playground = tk.Frame(nb, padx=8, pady=8)

        nb.add(self.tab_prompts,    text=tr("tool.router.tab_prompts"))
        nb.add(self.tab_playground, text=tr("tool.router.tab_playground"))

        self._build_prompts_tab()
        self._build_playground_tab()

    def _build_playground_tab(self):
        from tools.router.ai_console_playground import build_playground
        pg = build_playground(self.tab_playground)
        pg.pack(fill="both", expand=True)

    # ── Prompts tab ─────────────────────────────────────────────────────────

    def _build_prompts_tab(self):
        tab = self.tab_prompts

        tk.Label(
            tab,
            text=tr("tool.router.prompts_prompt"),
            font=("", 9), fg="#555", wraplength=1000, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # Two-pane: task list on the left, editor on the right
        body = tk.Frame(tab)
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, width=180)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        # Left: listbox of task ids with display labels
        tk.Label(left, text=tr("tool.router.col_task"), anchor="w",
                 font=("", 9, "bold")).pack(anchor="w", pady=(0, 2))
        self._prompt_task_listbox = tk.Listbox(
            left, exportselection=False, font=("", 9))
        self._prompt_task_listbox.pack(fill="both", expand=True)
        self._prompt_tasks_in_order: list[str] = list(_prompts.list_tasks())
        for tid in self._prompt_tasks_in_order:
            label = self._task_label(tid)
            tag = " ●" if _prompts.is_overridden(tid) else ""
            self._prompt_task_listbox.insert("end", f"{label}{tag}")
        self._prompt_task_listbox.bind("<<ListboxSelect>>",
                                       lambda e: self._on_prompt_task_selected())

        # Right: prompt editor + placeholders + buttons
        meta_row = tk.Frame(right)
        meta_row.pack(fill="x", pady=(0, 4))
        self._prompt_title_var = tk.StringVar(value="")
        tk.Label(meta_row, textvariable=self._prompt_title_var,
                 font=("", 10, "bold"), anchor="w").pack(side="left")

        ph_row = tk.Frame(right)
        ph_row.pack(fill="x", pady=(0, 4))
        tk.Label(ph_row, text=tr("tool.router.placeholders_label"),
                 font=("", 8), fg="#555").pack(side="left")
        self._prompt_ph_var = tk.StringVar(value="")
        tk.Label(ph_row, textvariable=self._prompt_ph_var,
                 font=("", 8), fg="#888").pack(side="left", padx=(6, 0))

        editor_frame = tk.Frame(right)
        editor_frame.pack(fill="both", expand=True)
        self._prompt_editor = tk.Text(editor_frame, wrap="word",
                                      font=("Consolas", 10), undo=True)
        ed_vsb = ttk.Scrollbar(editor_frame, orient="vertical",
                               command=self._prompt_editor.yview)
        self._prompt_editor.configure(yscrollcommand=ed_vsb.set)
        self._prompt_editor.pack(side="left", fill="both", expand=True)
        ed_vsb.pack(side="right", fill="y")

        actions = tk.Frame(right)
        actions.pack(fill="x", pady=(6, 0))
        self._prompt_save_btn = tk.Button(
            actions, text=tr("tool.router.btn_save_prompt"),
            command=self._save_current_prompt, width=10)
        self._prompt_save_btn.pack(side="left", padx=(0, 6))
        self._prompt_reset_btn = tk.Button(
            actions, text=tr("tool.router.btn_reset_prompt"),
            command=self._reset_current_prompt, width=10)
        self._prompt_reset_btn.pack(side="left")

        self._prompt_status_var = tk.StringVar(value="")
        tk.Label(actions, textvariable=self._prompt_status_var,
                 fg="#228B22", font=("", 9)).pack(side="left", padx=10)

        self._current_prompt_task: str | None = None

        # Auto-select first task so the editor isn't blank on open
        if self._prompt_tasks_in_order:
            self._prompt_task_listbox.selection_set(0)
            self._on_prompt_task_selected()

    @staticmethod
    def _task_label(task_id: str) -> str:
        """Use the canonical TASKS catalog for display labels."""
        for tid, _cat, label in _ai_cfg.TASKS:
            if tid == task_id:
                return label
        return task_id

    def _on_prompt_task_selected(self):
        sel = self._prompt_task_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._prompt_tasks_in_order):
            return
        task_id = self._prompt_tasks_in_order[idx]
        self._current_prompt_task = task_id
        self._prompt_title_var.set(self._task_label(task_id))
        ph = _prompts.placeholders(task_id)
        self._prompt_ph_var.set(", ".join(ph) if ph else tr("tool.router.no_placeholders"))
        self._prompt_editor.delete("1.0", "end")
        self._prompt_editor.insert("1.0", _prompts.get(task_id))
        self._prompt_status_var.set("")

    def _save_current_prompt(self):
        if not self._current_prompt_task:
            return
        content = self._prompt_editor.get("1.0", "end-1c")
        try:
            _prompts.set(self._current_prompt_task, content)
            self._prompt_status_var.set(tr("tool.router.prompt_saved"))
            self._refresh_prompt_listbox_marks()
        except Exception as e:
            messagebox.showerror(tr("dialog.common.error"), str(e), parent=self.master)
            return
        self.master.after(3000, lambda: self._prompt_status_var.set(""))

    def _reset_current_prompt(self):
        if not self._current_prompt_task:
            return
        if not messagebox.askyesno(
            tr("tool.router.reset_prompt_confirm_title"),
            tr("tool.router.reset_prompt_confirm_msg",
               name=self._task_label(self._current_prompt_task)),
            parent=self.master,
        ):
            return
        text = _prompts.reset(self._current_prompt_task)
        self._prompt_editor.delete("1.0", "end")
        self._prompt_editor.insert("1.0", text)
        self._prompt_status_var.set(tr("tool.router.prompt_reset_done"))
        self._refresh_prompt_listbox_marks()
        self.master.after(3000, lambda: self._prompt_status_var.set(""))

    def _refresh_prompt_listbox_marks(self):
        """Re-render listbox entries to show ● marker on overridden tasks."""
        sel = self._prompt_task_listbox.curselection()
        self._prompt_task_listbox.delete(0, "end")
        for tid in self._prompt_tasks_in_order:
            label = self._task_label(tid)
            tag = " ●" if _prompts.is_overridden(tid) else ""
            self._prompt_task_listbox.insert("end", f"{label}{tag}")
        if sel:
            self._prompt_task_listbox.selection_set(sel[0])
