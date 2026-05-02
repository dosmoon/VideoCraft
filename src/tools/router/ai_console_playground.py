"""AI Console — Playground tab.

Closed-loop prompt debugging:
  pick task → fill placeholders (manual / fixture / pull from project)
  → run once or A/B → see rendered output + provider/model + latency
  → iterate B until satisfied → manually paste back into Prompts tab.

This module is consumed by ai_console.py via build_playground(parent).
It does NOT write prompts/*.md (Playground is read-only for prompts);
Fixtures live in prompts/_fixtures/<task>/<name>.json.
"""

from __future__ import annotations

import json
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from i18n import tr

from core import ai
from core import prompts as _prompts
from core import prompts_fixtures as _fixtures
from core import prompts_schemas as _schemas
from core.ai.cancellation import CancellationToken
from core.ai.errors import AIError, Kind
from core.ai.router import router
from core.ai.tiers import TIER_STANDARD
from core.ai import config as _ai_cfg


def build_playground(parent: tk.Widget) -> tk.Frame:
    """Factory: build and return the Playground frame."""
    frame = tk.Frame(parent)
    PlaygroundController(frame)
    return frame


# ── Helpers ────────────────────────────────────────────────────────────────

def _task_label(task_id: str) -> str:
    for tid, _cat, label in _ai_cfg.TASKS:
        if tid == task_id:
            return label
    return task_id


def _substitute(template: str, vars_: dict[str, str]) -> str:
    """{key} substitution without str.format (avoids brace clashes in JSON)."""
    out = template
    for k, v in vars_.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _planned_routing(task: str) -> tuple[str, str]:
    """Best-effort: ask router which (provider, model) is configured for task."""
    try:
        return router._resolve_task_tier(task, TIER_STANDARD, None)
    except Exception:
        return ("?", "?")


# ── Controller ─────────────────────────────────────────────────────────────

class PlaygroundController:
    def __init__(self, root: tk.Frame):
        self.root = root

        # ── State ──
        self.tasks: list[str] = list(_prompts.list_tasks())
        self.current_task: str | None = None
        self.placeholder_widgets: dict[str, tk.Text] = {}
        self.mode_var = tk.StringVar(value="single")  # 'single' | 'ab'
        self.fixture_var = tk.StringVar(value="")

        # tri-state run state
        self._cancel_token: CancellationToken | None = None
        self._running = False

        # A/B B-side draft text (so it survives mode toggles)
        self._b_draft: str = ""

        # ── Layout: 3-pane PanedWindow ──
        pw = ttk.PanedWindow(root, orient="horizontal")
        pw.pack(fill="both", expand=True)

        left = tk.Frame(pw, width=180)
        mid  = tk.Frame(pw, width=380)
        right = tk.Frame(pw, width=520)
        pw.add(left, weight=0)
        pw.add(mid,  weight=2)
        pw.add(right, weight=3)

        self._build_task_pane(left)
        self._build_input_pane(mid)
        self._build_result_pane(right)

        if self.tasks:
            self._task_listbox.selection_set(0)
            self._on_task_selected()

    # ── Pane 1: task list ──────────────────────────────────────────────────

    def _build_task_pane(self, parent: tk.Frame):
        tk.Label(parent, text=tr("tool.router.col_task"), anchor="w",
                 font=("", 9, "bold")).pack(anchor="w", pady=(0, 2))
        self._task_listbox = tk.Listbox(parent, exportselection=False,
                                         font=("", 9))
        self._task_listbox.pack(fill="both", expand=True)
        for tid in self.tasks:
            tag_schema = " {J}" if _schemas.has_schema(tid) else ""
            self._task_listbox.insert("end", f"{_task_label(tid)}{tag_schema}")
        self._task_listbox.bind("<<ListboxSelect>>",
                                 lambda e: self._on_task_selected())

    # ── Pane 2: input form ─────────────────────────────────────────────────

    def _build_input_pane(self, parent: tk.Frame):
        # Title bar
        title_row = tk.Frame(parent)
        title_row.pack(fill="x", pady=(0, 4))
        self.task_title_var = tk.StringVar(value="")
        tk.Label(title_row, textvariable=self.task_title_var,
                 font=("", 10, "bold")).pack(side="left")
        self.schema_label_var = tk.StringVar(value="")
        tk.Label(title_row, textvariable=self.schema_label_var,
                 fg="#888", font=("", 8)).pack(side="left", padx=(8, 0))

        # Mode toggle
        mode_row = tk.Frame(parent)
        mode_row.pack(fill="x", pady=(0, 6))
        ttk.Radiobutton(mode_row, text=tr("tool.router.pg_mode_single"),
                         variable=self.mode_var, value="single",
                         command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(mode_row, text=tr("tool.router.pg_mode_ab"),
                         variable=self.mode_var, value="ab",
                         command=self._on_mode_change).pack(side="left", padx=(10, 0))

        # Routing display
        route_row = tk.Frame(parent)
        route_row.pack(fill="x", pady=(0, 4))
        self.route_var = tk.StringVar(value="")
        tk.Label(route_row, textvariable=self.route_var, fg="#666",
                 font=("", 8), anchor="w", justify="left",
                 wraplength=360).pack(side="left", fill="x", expand=True)

        # Fixtures row
        fix_row = tk.Frame(parent)
        fix_row.pack(fill="x", pady=(2, 4))
        tk.Label(fix_row, text=tr("tool.router.pg_fixture_label") + ":",
                 font=("", 9)).pack(side="left")
        self.fixture_combo = ttk.Combobox(fix_row, textvariable=self.fixture_var,
                                           state="readonly", width=18)
        self.fixture_combo.pack(side="left", padx=(4, 4))
        self.fixture_combo.bind("<<ComboboxSelected>>",
                                 lambda e: self._on_fixture_load())
        tk.Button(fix_row, text=tr("tool.router.pg_btn_save_fixture"),
                  command=self._on_fixture_save).pack(side="left", padx=(2, 2))
        tk.Button(fix_row, text=tr("tool.router.pg_btn_delete_fixture"),
                  command=self._on_fixture_delete).pack(side="left", padx=(2, 2))
        tk.Button(fix_row, text=tr("tool.router.pg_btn_load_project"),
                  command=self._on_pull_project).pack(side="left", padx=(8, 0))

        # Placeholder form (scrollable)
        ph_frame = tk.LabelFrame(parent, text=tr("tool.router.pg_input"))
        ph_frame.pack(fill="both", expand=True, pady=(4, 4))

        canvas = tk.Canvas(ph_frame, highlightthickness=0)
        vsb = ttk.Scrollbar(ph_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._ph_inner = tk.Frame(canvas)
        self._ph_window = canvas.create_window((0, 0), window=self._ph_inner,
                                                 anchor="nw")
        self._ph_canvas = canvas

        def _on_inner_config(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_config(e):
            canvas.itemconfig(self._ph_window, width=e.width)
        self._ph_inner.bind("<Configure>", _on_inner_config)
        canvas.bind("<Configure>", _on_canvas_config)

        # B-side draft (only visible in A/B mode)
        self.b_frame = tk.LabelFrame(parent, text=tr("tool.router.pg_ab_right"))
        self.b_text = tk.Text(self.b_frame, wrap="word", height=8,
                               font=("Consolas", 9), undo=True)
        b_vsb = ttk.Scrollbar(self.b_frame, orient="vertical",
                               command=self.b_text.yview)
        self.b_text.configure(yscrollcommand=b_vsb.set)
        self.b_text.pack(side="left", fill="both", expand=True)
        b_vsb.pack(side="right", fill="y")
        # Don't pack b_frame yet — appears only in A/B mode

        # Run button row
        run_row = tk.Frame(parent)
        run_row.pack(fill="x", pady=(4, 0))
        self.run_btn = tk.Button(run_row, text=tr("tool.router.pg_btn_run"),
                                  bg="#2563eb", fg="white",
                                  activebackground="#1d4ed8",
                                  command=self._on_run_click, width=14)
        self.run_btn.pack(side="left")

        self.status_var = tk.StringVar(value="")
        tk.Label(run_row, textvariable=self.status_var, fg="#555",
                 font=("", 9)).pack(side="left", padx=(10, 0))

    # ── Pane 3: result panels ─────────────────────────────────────────────

    def _build_result_pane(self, parent: tk.Frame):
        # Sub-notebook for single vs A/B output
        self.result_nb = ttk.Notebook(parent)
        self.result_nb.pack(fill="both", expand=True)

        # Single tab
        self.single_tab = tk.Frame(self.result_nb)
        self.result_nb.add(self.single_tab, text=tr("tool.router.pg_mode_single"))
        self._single_panel = self._build_result_panel(self.single_tab)

        # A/B tab
        self.ab_tab = tk.Frame(self.result_nb)
        self.result_nb.add(self.ab_tab, text=tr("tool.router.pg_mode_ab"))
        ab_pw = ttk.PanedWindow(self.ab_tab, orient="horizontal")
        ab_pw.pack(fill="both", expand=True)
        a_frame = tk.LabelFrame(ab_pw, text=tr("tool.router.pg_ab_left"))
        b_frame = tk.LabelFrame(ab_pw, text=tr("tool.router.pg_ab_right"))
        ab_pw.add(a_frame, weight=1)
        ab_pw.add(b_frame, weight=1)
        self._ab_a_panel = self._build_result_panel(a_frame)
        self._ab_b_panel = self._build_result_panel(b_frame)

    def _build_result_panel(self, parent: tk.Frame) -> dict:
        """Build one result panel; return dict of widgets/StringVars to update."""
        panel: dict = {}

        meta_row = tk.Frame(parent)
        meta_row.pack(fill="x", pady=(2, 2))
        panel["meta_var"] = tk.StringVar(value="—")
        tk.Label(meta_row, textvariable=panel["meta_var"],
                 fg="#444", font=("", 9), anchor="w",
                 justify="left", wraplength=520).pack(side="left",
                                                        fill="x", expand=True)

        # Result text
        out_frame = tk.LabelFrame(parent, text=tr("tool.router.pg_panel_result"))
        out_frame.pack(fill="both", expand=True, padx=2, pady=2)
        out_text = tk.Text(out_frame, wrap="word", font=("Consolas", 9),
                            height=14)
        out_vsb = ttk.Scrollbar(out_frame, orient="vertical",
                                 command=out_text.yview)
        out_text.configure(yscrollcommand=out_vsb.set)
        out_text.pack(side="left", fill="both", expand=True)
        out_vsb.pack(side="right", fill="y")
        out_text.tag_configure("err", foreground="#cc0000")
        panel["out_text"] = out_text

        # Sent prompt (collapsible)
        sent_frame = tk.LabelFrame(parent, text=tr("tool.router.pg_panel_sent"))
        sent_frame.pack(fill="both", expand=False, padx=2, pady=2)
        sent_text = tk.Text(sent_frame, wrap="word", font=("Consolas", 8),
                             height=6, fg="#444")
        sent_vsb = ttk.Scrollbar(sent_frame, orient="vertical",
                                  command=sent_text.yview)
        sent_text.configure(yscrollcommand=sent_vsb.set)
        sent_text.pack(side="left", fill="both", expand=True)
        sent_vsb.pack(side="right", fill="y")
        panel["sent_text"] = sent_text

        return panel

    # ── Selection / mode handlers ─────────────────────────────────────────

    def _on_task_selected(self):
        sel = self._task_listbox.curselection()
        if not sel:
            return
        task = self.tasks[sel[0]]
        self.current_task = task
        self.task_title_var.set(_task_label(task))
        self.schema_label_var.set(
            "[JSON]" if _schemas.has_schema(task) else "[text]"
        )
        # Routing
        prov, model = _planned_routing(task)
        if prov:
            self.route_var.set(
                tr("tool.router.pg_meta_provider") + f": {prov}   " +
                tr("tool.router.pg_meta_model") + f": {model or '—'}"
            )
        else:
            self.route_var.set(tr("tool.router.pg_default_routing"))

        # Reset placeholder form
        self._rebuild_placeholder_form(task)
        # Refresh fixtures
        self._refresh_fixture_combo()
        # Reset B draft to current saved prompt
        self._b_draft = _prompts.get(task)
        self.b_text.delete("1.0", "end")
        self.b_text.insert("1.0", self._b_draft)
        # Clear results
        self._clear_panel(self._single_panel)
        self._clear_panel(self._ab_a_panel)
        self._clear_panel(self._ab_b_panel)

    def _rebuild_placeholder_form(self, task: str):
        for child in list(self._ph_inner.winfo_children()):
            child.destroy()
        self.placeholder_widgets.clear()

        keys = _fixtures.task_placeholder_keys(task)
        if not keys:
            tk.Label(self._ph_inner, text=tr("tool.router.no_placeholders"),
                     fg="#888", font=("", 9), anchor="w").pack(fill="x", pady=4)
            return

        for k in keys:
            row = tk.Frame(self._ph_inner)
            row.pack(fill="x", pady=(4, 2))
            tk.Label(row, text="{" + k + "}", font=("Consolas", 9, "bold"),
                     fg="#1d4ed8", anchor="w").pack(fill="x")
            txt = tk.Text(row, height=3, wrap="word", font=("Consolas", 9),
                           undo=True)
            txt.pack(fill="x")
            self.placeholder_widgets[k] = txt

    def _on_mode_change(self):
        if self.mode_var.get() == "ab":
            self.b_frame.pack(fill="both", expand=False, pady=(4, 4))
            self.result_nb.select(self.ab_tab)
        else:
            self.b_frame.pack_forget()
            self.result_nb.select(self.single_tab)

    # ── Fixtures ──────────────────────────────────────────────────────────

    def _refresh_fixture_combo(self):
        if not self.current_task:
            return
        names = _fixtures.list_fixtures(self.current_task)
        self.fixture_combo["values"] = names
        self.fixture_var.set("")

    def _collect_vars(self) -> dict[str, str]:
        return {k: w.get("1.0", "end-1c")
                for k, w in self.placeholder_widgets.items()}

    def _on_fixture_load(self):
        if not self.current_task:
            return
        name = self.fixture_var.get()
        if not name:
            return
        try:
            payload = _fixtures.load_fixture(self.current_task, name)
        except Exception as e:
            messagebox.showerror("Fixture", str(e))
            return
        for k, v in (payload.get("vars") or {}).items():
            w = self.placeholder_widgets.get(k)
            if w is not None:
                w.delete("1.0", "end")
                w.insert("1.0", str(v))

    def _on_fixture_save(self):
        if not self.current_task:
            return
        name = simpledialog.askstring(
            tr("tool.router.pg_btn_save_fixture"),
            "Name:", parent=self.root,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return
        vars_ = self._collect_vars()
        try:
            _fixtures.save_fixture(self.current_task, name, vars_)
        except Exception as e:
            messagebox.showerror("Fixture", str(e))
            return
        self._refresh_fixture_combo()
        self.fixture_var.set(name)
        self.status_var.set(tr("tool.router.pg_fixture_saved"))

    def _on_fixture_delete(self):
        if not self.current_task:
            return
        name = self.fixture_var.get()
        if not name:
            return
        if not messagebox.askyesno("Fixture", f"Delete '{name}'?"):
            return
        try:
            _fixtures.delete_fixture(self.current_task, name)
        except Exception as e:
            messagebox.showerror("Fixture", str(e))
            return
        self._refresh_fixture_combo()

    # ── Pull from project ─────────────────────────────────────────────────

    def _on_pull_project(self):
        task = self.current_task
        if not task:
            return
        # File picker — pick types depend on task
        types: list[tuple[str, str]] = []
        if task in ("subtitle.pack", "subtitle.segments", "translate"):
            types = [("SRT", "*.srt"), ("All", "*.*")]
        elif task in ("clip.rank-chapters", "clip.find-peaks", "subtitle.refine"):
            types = [("Postprocess JSON", "*-postprocess.json"),
                     ("JSON", "*.json"), ("All", "*.*")]
        elif task == "clip.package":
            types = [("Cut JSON", "*.json"), ("All", "*.*")]
        else:
            types = [("All", "*.*")]

        path = filedialog.askopenfilename(title="Select project file",
                                            filetypes=types)
        if not path:
            return
        kwargs: dict = {}

        # Tasks needing a sub-pick
        try:
            if task == "clip.find-peaks":
                chs = _fixtures.list_chapters_for_picker(path)
                if not chs:
                    messagebox.showinfo("Pull", "No chapters in pack.")
                    return
                idx = self._pick_from_list(
                    "Pick chapter",
                    [f"#{c['idx']}  {c['title']}  [{c['time_str']}]" for c in chs],
                )
                if idx is None:
                    return
                kwargs["chapter_idx"] = idx
            elif task == "clip.package":
                clips = _fixtures.list_clips_for_picker(path)
                if not clips:
                    messagebox.showinfo("Pull", "No clips in cut file.")
                    return
                idx = self._pick_from_list(
                    "Pick clip", [c["label"] for c in clips])
                if idx is None:
                    return
                kwargs["clip_idx"] = idx
            elif task == "translate":
                kwargs["batch_size"] = 10

            vars_ = _fixtures.extract_from_project(task, path, **kwargs)
        except Exception as e:
            messagebox.showerror("Pull", str(e))
            return

        for k, v in vars_.items():
            w = self.placeholder_widgets.get(k)
            if w is not None:
                w.delete("1.0", "end")
                w.insert("1.0", str(v))

    def _pick_from_list(self, title: str, options: list[str]) -> int | None:
        """Modal listbox picker. Returns selected index or None."""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.geometry("520x420")
        dlg.transient(self.root.winfo_toplevel())
        dlg.grab_set()
        result = {"idx": None}
        lb = tk.Listbox(dlg, font=("", 9))
        for o in options:
            lb.insert("end", o)
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        if options:
            lb.selection_set(0)
        btns = tk.Frame(dlg)
        btns.pack(fill="x", pady=(0, 8))
        def _ok():
            sel = lb.curselection()
            if sel:
                result["idx"] = sel[0]
            dlg.destroy()
        def _cancel():
            dlg.destroy()
        tk.Button(btns, text="OK", width=10, command=_ok).pack(side="right",
                                                                 padx=(0, 8))
        tk.Button(btns, text="Cancel", width=10, command=_cancel).pack(
            side="right")
        lb.bind("<Double-Button-1>", lambda e: _ok())
        dlg.wait_window()
        return result["idx"]

    # ── Run (single + A/B) ────────────────────────────────────────────────

    def _on_run_click(self):
        if self._running and self._cancel_token is not None:
            # Cancel
            self._cancel_token.cancel()
            self.run_btn.config(state="disabled",
                                  text=tr("tool.router.pg_btn_cancelling"))
            return
        if not self.current_task:
            return
        if self.mode_var.get() == "ab":
            self._start_ab_run()
        else:
            self._start_single_run()

    def _set_running(self, running: bool):
        self._running = running
        if running:
            self._cancel_token = CancellationToken()
            self.run_btn.config(text=tr("tool.router.pg_btn_cancel"),
                                  bg="#dc2626", activebackground="#b91c1c",
                                  state="normal")
            self.status_var.set(tr("tool.router.pg_status_running"))
        else:
            self._cancel_token = None
            self.run_btn.config(text=tr("tool.router.pg_btn_run"),
                                  bg="#2563eb", activebackground="#1d4ed8",
                                  state="normal")

    def _clear_panel(self, panel: dict):
        panel["meta_var"].set("—")
        panel["out_text"].delete("1.0", "end")
        panel["sent_text"].delete("1.0", "end")

    def _fill_panel(self, panel: dict, payload: dict):
        sent = payload.get("sent", "")
        result = payload.get("result", "")
        meta = payload.get("meta", "—")
        error = payload.get("error", "")
        panel["sent_text"].delete("1.0", "end")
        panel["sent_text"].insert("1.0", sent)
        panel["out_text"].delete("1.0", "end")
        if error:
            panel["out_text"].insert("1.0", error, "err")
        else:
            if isinstance(result, (dict, list)):
                panel["out_text"].insert(
                    "1.0", json.dumps(result, ensure_ascii=False, indent=2))
            else:
                panel["out_text"].insert("1.0", str(result))
        panel["meta_var"].set(meta)

    def _start_single_run(self):
        task = self.current_task
        template = _prompts.get(task)
        vars_ = self._collect_vars()
        sent = _substitute(template, vars_)
        self._set_running(True)
        self.result_nb.select(self.single_tab)
        threading.Thread(target=self._run_one,
                         args=(task, sent, self._single_panel,
                                self._cancel_token),
                         daemon=True).start()

    def _start_ab_run(self):
        task = self.current_task
        template_a = _prompts.get(task)
        template_b = self.b_text.get("1.0", "end-1c")
        vars_ = self._collect_vars()
        sent_a = _substitute(template_a, vars_)
        sent_b = _substitute(template_b, vars_)
        self._set_running(True)
        self.result_nb.select(self.ab_tab)
        threading.Thread(target=self._run_ab,
                         args=(task, sent_a, sent_b, self._cancel_token),
                         daemon=True).start()

    def _run_one(self, task: str, prompt: str, panel: dict,
                 token: CancellationToken):
        sent_meta_prov, sent_meta_model = _planned_routing(task)
        t0 = time.perf_counter()
        try:
            if _schemas.has_schema(task):
                schema = _schemas.get_schema(task)
                result = ai.complete_json(prompt, schema=schema, task=task,
                                           cancel_token=token)
            else:
                result = ai.complete(prompt, task=task)
            elapsed = time.perf_counter() - t0
            meta = self._format_meta(sent_meta_prov, sent_meta_model, elapsed)
            self.root.after(0, self._fill_panel, panel,
                              {"sent": prompt, "result": result, "meta": meta})
            self.root.after(0, self.status_var.set,
                              tr("tool.router.pg_status_done",
                                  sec=f"{elapsed:.1f}"))
        except AIError as e:
            elapsed = time.perf_counter() - t0
            if e.kind == Kind.CANCELLED:
                self.root.after(0, self._fill_panel, panel,
                                  {"sent": prompt, "result": "(cancelled)",
                                   "meta": self._format_meta(
                                       sent_meta_prov, sent_meta_model, elapsed)})
                self.root.after(0, self.status_var.set,
                                  tr("tool.router.pg_btn_cancelling"))
            else:
                self.root.after(0, self._fill_panel, panel,
                                  {"sent": prompt, "result": "",
                                   "meta": self._format_meta(
                                       sent_meta_prov, sent_meta_model, elapsed),
                                   "error": f"{e.kind.name}: {e}"})
                self.root.after(0, self.status_var.set,
                                  tr("tool.router.pg_status_failed",
                                      err=str(e)[:60]))
        except Exception as e:
            elapsed = time.perf_counter() - t0
            self.root.after(0, self._fill_panel, panel,
                              {"sent": prompt, "result": "",
                               "meta": self._format_meta(
                                   sent_meta_prov, sent_meta_model, elapsed),
                               "error": f"{type(e).__name__}: {e}"})
            self.root.after(0, self.status_var.set,
                              tr("tool.router.pg_status_failed",
                                  err=str(e)[:60]))
        finally:
            self.root.after(0, self._set_running, False)

    def _run_ab(self, task: str, prompt_a: str, prompt_b: str,
                token: CancellationToken):
        # Serial: A then B (avoids provider rate limits)
        for label, prompt, panel in (("A", prompt_a, self._ab_a_panel),
                                       ("B", prompt_b, self._ab_b_panel)):
            if token.cancelled:
                self.root.after(0, self._fill_panel, panel,
                                  {"sent": prompt, "result": "(cancelled)",
                                   "meta": "—"})
                continue
            self._run_ab_one(task, prompt, panel, token, side_label=label)
        self.root.after(0, self._set_running, False)

    def _run_ab_one(self, task: str, prompt: str, panel: dict,
                    token: CancellationToken, *, side_label: str):
        prov, model = _planned_routing(task)
        t0 = time.perf_counter()
        try:
            if _schemas.has_schema(task):
                result = ai.complete_json(prompt, schema=_schemas.get_schema(task),
                                           task=task, cancel_token=token)
            else:
                result = ai.complete(prompt, task=task)
            elapsed = time.perf_counter() - t0
            self.root.after(0, self._fill_panel, panel,
                              {"sent": prompt, "result": result,
                               "meta": self._format_meta(prov, model, elapsed)})
        except AIError as e:
            elapsed = time.perf_counter() - t0
            err_text = "(cancelled)" if e.kind == Kind.CANCELLED else f"{e.kind.name}: {e}"
            self.root.after(0, self._fill_panel, panel,
                              {"sent": prompt, "result": "",
                               "meta": self._format_meta(prov, model, elapsed),
                               "error": err_text})
        except Exception as e:
            elapsed = time.perf_counter() - t0
            self.root.after(0, self._fill_panel, panel,
                              {"sent": prompt, "result": "",
                               "meta": self._format_meta(prov, model, elapsed),
                               "error": f"{type(e).__name__}: {e}"})

    @staticmethod
    def _format_meta(provider: str, model: str, elapsed: float) -> str:
        prov = provider or "?"
        m = model or "—"
        return (f"{tr('tool.router.pg_meta_provider')}: {prov}   "
                f"{tr('tool.router.pg_meta_model')}: {m}   "
                f"{tr('tool.router.pg_meta_latency')}: {elapsed:.2f}s   "
                f"{tr('tool.router.pg_meta_tokens')}: —")
