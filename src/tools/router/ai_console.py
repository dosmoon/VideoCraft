"""AI Console — provider management + task-routing dropdowns + prompts + stats.

UI layout:
  Tab 1 (Provider & Routing):
    - Top section "Task Routing": one row per task in TASKS, with a
      provider dropdown and a model dropdown. Picking either auto-saves
      via router.set_task_routing(). ASR/TTS rows render an em-dash in
      the model column (provider-only routing).
    - Bottom section "Providers": one compact row per configured
      provider — name, key status, Edit and Test buttons. Edit opens
      the existing per-type dialogs (LLM / claude_code / ASR-TTS).
  Tab 2 (Prompts): per-task prompt editor with override management.
  Tab 3 (Stats): per-provider call counters.

Per architecture principle 1, this tool is an "infrastructure console"
and is allowed to import core.ai directly.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from tools.base import ToolBase
from i18n import tr

from core import ai
from core import prompts as _prompts
from core.ai.router import router
from core.ai import config as _ai_cfg
from core.ai.config import keys_dir as _keys_dir
from core import paths as _paths


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _parse_int_range(value: str, *, minimum: int, maximum: int, field_label: str) -> int:
    try:
        parsed = int(value.strip())
    except Exception as e:
        raise ValueError(tr("tool.router.error_invalid_number", field=field_label)) from e
    if parsed < minimum or parsed > maximum:
        raise ValueError(tr("tool.router.error_out_of_range",
                            field=field_label, min=minimum, max=maximum))
    return parsed


# ── AI Console tool ─────────────────────────────────────────────────────────

class AIConsoleApp(ToolBase):
    def __init__(self, master, initial_file=None):
        self.master = master
        master.title(tr("tool.router.title"))
        master.geometry("1080x640")

        nb = ttk.Notebook(master)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_routing    = tk.Frame(nb, padx=8, pady=8)
        self.tab_prompts    = tk.Frame(nb, padx=8, pady=8)
        self.tab_playground = tk.Frame(nb, padx=8, pady=8)
        self.tab_stats      = tk.Frame(nb, padx=12, pady=10)

        nb.add(self.tab_routing,    text=tr("tool.router.tab_routing"))
        nb.add(self.tab_prompts,    text=tr("tool.router.tab_prompts"))
        nb.add(self.tab_playground, text=tr("tool.router.tab_playground"))
        nb.add(self.tab_stats,      text=tr("tool.router.tab_stats"))
        self._stats_tab_index = 3
        nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._build_routing_tab()
        self._build_prompts_tab()
        self._build_playground_tab()
        self._build_stats_tab()

    def _on_tab_change(self, event):
        nb = event.widget
        if nb.index(nb.select()) == self._stats_tab_index:
            self._refresh_stats()

    def _build_playground_tab(self):
        from tools.router.ai_console_playground import build_playground
        pg = build_playground(self.tab_playground)
        pg.pack(fill="both", expand=True)

    # ── Routing tab: top section + bottom section ──────────────────────────

    def _build_routing_tab(self):
        tab = self.tab_routing

        # Help line
        tk.Label(tab,
                 text=tr("tool.router.routing_prompt"),
                 font=("", 9), fg="#555", wraplength=1000, justify="left",
                 ).pack(anchor="w", pady=(0, 8))

        # Scrollable container — providers list can grow as users add
        # custom OpenAI-compat endpoints. Routing section is always 4 rows
        # so it doesn't need scrolling; both share one canvas for simplicity.
        outer = tk.Frame(tab)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        body = tk.Frame(canvas)
        canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Scope mousewheel to this canvas only: bind_all would also fire on
        # modal Edit dialogs, leaking scroll events through to the background.
        def _on_wheel(e):
            # Only scroll if content actually exceeds the viewport
            bbox = canvas.bbox("all")
            if not bbox:
                return
            if bbox[3] - bbox[1] <= canvas.winfo_height():
                return
            canvas.yview_scroll(int(-e.delta / 120), "units")

        def _bind_wheel(_e):
            canvas.bind_all("<MouseWheel>", _on_wheel)

        def _unbind_wheel(_e):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)
        # Also unbind when the tab/window is destroyed so wheel events don't
        # target a dead canvas after closing the console.
        canvas.bind("<Destroy>", _unbind_wheel)

        # Track widgets that need rebuilding/refresh after edits
        self._test_buttons: dict[str, tk.Button] = {}
        self._task_provider_vars: dict[str, tk.StringVar] = {}
        self._task_model_vars: dict[str, tk.StringVar] = {}
        self._task_model_combos: dict[str, ttk.Combobox] = {}

        # ── Top: local model cache ──
        cache_frame = tk.LabelFrame(
            body, text=tr("tool.router.section_cache_title"),
            padx=10, pady=8, font=("", 10, "bold"),
        )
        cache_frame.pack(fill="x", pady=(0, 12), anchor="w")
        self._build_cache_section(cache_frame)

        # ── Middle: task routing ──
        routing_frame = tk.LabelFrame(
            body, text=tr("tool.router.section_routing_title"),
            padx=10, pady=8, font=("", 10, "bold"),
        )
        routing_frame.pack(fill="x", pady=(0, 12), anchor="w")
        self._build_routing_section(routing_frame)

        # ── Bottom: providers ──
        providers_frame = tk.LabelFrame(
            body, text=tr("tool.router.section_providers_title"),
            padx=10, pady=8, font=("", 10, "bold"),
        )
        providers_frame.pack(fill="x", anchor="w")
        self._build_providers_section(providers_frame)

    # ── Cache section: models_dir + legacy banner + Ollama hint ────────────

    def _build_cache_section(self, parent):
        # Row 0: directory entry + buttons
        tk.Label(parent, text=tr("tool.router.cache_dir_label"),
                 anchor="w").grid(row=0, column=0, sticky="w", padx=4, pady=2)

        default_path = os.path.join(
            os.path.dirname(os.path.abspath(_paths.__file__)),
            "..", "..", "user_data", "models",
        )
        default_path = os.path.normpath(default_path)
        current = router.get_models_dir()

        self._cache_dir_var = tk.StringVar(
            value=current or default_path
        )
        self._cache_dir_is_default = not current
        entry = tk.Entry(parent, textvariable=self._cache_dir_var, width=68)
        entry.grid(row=0, column=1, sticky="ew", padx=4, pady=2, columnspan=4)
        if self._cache_dir_is_default:
            entry.configure(fg="#888")  # hint that it's the default

        tk.Button(parent, text=tr("tool.router.cache_dir_browse"),
                  command=self._on_cache_dir_browse,
                  ).grid(row=1, column=1, sticky="w", padx=4, pady=(2, 4))
        tk.Button(parent, text=tr("tool.router.cache_dir_reset"),
                  command=self._on_cache_dir_reset,
                  ).grid(row=1, column=2, sticky="w", padx=4, pady=(2, 4))
        tk.Button(parent, text=tr("tool.router.cache_dir_apply"),
                  command=self._on_cache_dir_apply,
                  ).grid(row=1, column=3, sticky="w", padx=4, pady=(2, 4))
        self._cache_dir_status = tk.Label(parent, text="", fg="#2a7", anchor="w")
        self._cache_dir_status.grid(row=1, column=4, sticky="w", padx=8)

        tk.Label(parent, text=tr("tool.router.cache_dir_help"),
                 fg="#777", anchor="w", wraplength=900, justify="left",
                 ).grid(row=2, column=0, columnspan=5, sticky="w",
                        padx=4, pady=(0, 6))

        parent.columnconfigure(1, weight=1)

        # Row 3: legacy cache banner (only if found)
        legacy = _paths.detect_legacy_hf_cache()
        if legacy is not None:
            legacy_path, legacy_size = legacy
            warn_text = tr(
                "tool.router.cache_legacy_warn",
                path=legacy_path, size=_human_bytes(legacy_size),
            )
            tk.Label(parent, text=warn_text, fg="#b85", anchor="w",
                     wraplength=820, justify="left",
                     ).grid(row=3, column=0, columnspan=4, sticky="w",
                            padx=4, pady=(2, 2))
            tk.Button(
                parent, text=tr("tool.router.cache_legacy_copy_cmd"),
                command=lambda p=legacy_path: self._copy_cleanup_cmd(p),
            ).grid(row=3, column=4, sticky="w", padx=8)

        # Row 4: Ollama guidance
        tk.Label(parent, text=tr("tool.router.cache_ollama_hint"),
                 fg="#557", anchor="w", wraplength=820, justify="left",
                 ).grid(row=4, column=0, columnspan=4, sticky="w",
                        padx=4, pady=(4, 2))
        tk.Button(parent, text=tr("tool.router.cache_ollama_open_envvars"),
                  command=self._open_env_vars_panel,
                  ).grid(row=4, column=4, sticky="w", padx=8)

    def _on_cache_dir_browse(self):
        from tkinter import filedialog
        initial = self._cache_dir_var.get() or os.path.expanduser("~")
        chosen = filedialog.askdirectory(
            initialdir=initial if os.path.isdir(initial) else os.path.expanduser("~"),
        )
        if chosen:
            self._cache_dir_var.set(os.path.normpath(chosen))

    def _on_cache_dir_reset(self):
        self._cache_dir_var.set("")
        router.set_models_dir("")
        self._cache_dir_status.configure(text=tr("tool.router.cache_dir_saved"))

    def _on_cache_dir_apply(self):
        path = self._cache_dir_var.get().strip()
        # Treat the auto-shown default path as "no override" when the user
        # hasn't actually changed it — keeps providers.json clean.
        router.set_models_dir(path)
        self._cache_dir_status.configure(text=tr("tool.router.cache_dir_saved"))

    def _copy_cleanup_cmd(self, legacy_path: str):
        # Cross-shell command — Windows users usually run cmd or PowerShell.
        cmd = f'rmdir /S /Q "{legacy_path}"'
        try:
            self.master.clipboard_clear()
            self.master.clipboard_append(cmd)
            self.master.update()  # required for clipboard to persist after window close
        except tk.TclError:
            pass
        self._cache_dir_status.configure(
            text=tr("tool.router.cache_legacy_cmd_copied"))

    def _open_env_vars_panel(self):
        # rundll32 sysdm.cpl,EditEnvironmentVariables — opens the Windows
        # "Environment Variables" dialog directly (Win 10+).
        import subprocess
        try:
            subprocess.Popen(
                ["rundll32.exe", "sysdm.cpl,EditEnvironmentVariables"],
                shell=False,
            )
        except OSError:
            pass

    # ── Top section: 4-row task routing table ──────────────────────────────

    def _build_routing_section(self, parent):
        current_routing = router.get_task_routing()

        # Header row
        tk.Label(parent, text=tr("tool.router.col_task"),
                 font=("", 9, "bold"), anchor="w", width=22,
                 ).grid(row=0, column=0, sticky="w", padx=4, pady=(0, 4))
        tk.Label(parent, text=tr("tool.router.col_provider"),
                 font=("", 9, "bold"), anchor="w", width=18,
                 ).grid(row=0, column=1, sticky="w", padx=4, pady=(0, 4))
        tk.Label(parent, text=tr("tool.router.col_model"),
                 font=("", 9, "bold"), anchor="w", width=28,
                 ).grid(row=0, column=2, sticky="w", padx=4, pady=(0, 4))

        for i, (tid, cat, label) in enumerate(_ai_cfg.TASKS, start=1):
            tk.Label(parent, text=label, anchor="w").grid(
                row=i, column=0, sticky="w", padx=4, pady=4)

            cell = current_routing.get(tid, {})
            prov_var = tk.StringVar(value=cell.get("provider", ""))
            model_var = tk.StringVar(value=cell.get("model", ""))
            self._task_provider_vars[tid] = prov_var
            self._task_model_vars[tid] = model_var

            prov_choices = self._provider_choices_for(cat)
            prov_cb = ttk.Combobox(
                parent, textvariable=prov_var, values=prov_choices,
                state="readonly", width=22,
            )
            prov_cb.grid(row=i, column=1, sticky="w", padx=4, pady=4)
            prov_cb.bind("<<ComboboxSelected>>",
                         lambda _e, t=tid: self._on_routing_provider_changed(t))

            if cat == "llm":
                model_choices = self._models_for(prov_var.get())
                model_cb = ttk.Combobox(
                    parent, textvariable=model_var, values=model_choices,
                    state="normal", width=30,
                )
                model_cb.grid(row=i, column=2, sticky="w", padx=4, pady=4)
                self._task_model_combos[tid] = model_cb
                model_cb.bind("<<ComboboxSelected>>",
                              lambda _e, t=tid: self._on_routing_model_changed(t))
                # Persist manually-typed model on focus-out / Return
                model_cb.bind("<FocusOut>",
                              lambda _e, t=tid: self._on_routing_model_changed(t))
                model_cb.bind("<Return>",
                              lambda _e, t=tid: self._on_routing_model_changed(t))
            elif cat == "asr":
                # Replace the empty model cell with a small frame holding
                # the master enable switch + the language-routing entry
                # button. Count in button reflects how many per-language
                # overrides are currently configured. The Enable switch
                # is the master gate — when off, lang_routing entries are
                # ignored at dispatch (so the user can swap default
                # provider freely without surprise hijacking).
                lr_frame = tk.Frame(parent)
                lr_frame.grid(row=i, column=2, sticky="w", padx=4, pady=4)

                lr_enabled = router.get_task_language_routing_enabled(tid)
                lr = router.get_task_language_routing(tid)

                self._task_lang_enable_vars = getattr(
                    self, "_task_lang_enable_vars", {})
                en_var = tk.BooleanVar(value=lr_enabled)
                self._task_lang_enable_vars[tid] = en_var

                btn_text = tr("tool.router.lang_routing_btn", n=len(lr))
                btn = tk.Button(
                    lr_frame, text=btn_text, anchor="w", width=18,
                    command=lambda t=tid: self._open_language_routing_dialog(t),
                )

                def _on_toggle_lr(t=tid, var=en_var, b=btn):
                    new_val = bool(var.get())
                    router.set_task_language_routing_enabled(t, new_val)
                    self._refresh_lang_button_state(t)

                ttk.Checkbutton(
                    lr_frame, text=tr("tool.router.btn_enable"),
                    variable=en_var, command=_on_toggle_lr,
                ).pack(side="left")
                btn.pack(side="left", padx=(4, 0))

                # Store references so the dialog refresh path can update
                # both the button label and its disabled state.
                self._task_lang_buttons = getattr(self, "_task_lang_buttons", {})
                self._task_lang_buttons[tid] = btn
                self._refresh_lang_button_state(tid)
            else:
                tk.Label(parent, text="—", fg="#999", anchor="w",
                         ).grid(row=i, column=2, sticky="w", padx=4, pady=4)

    def _provider_choices_for(self, category: str) -> list[str]:
        """Return a list of provider names available for this category.

        Includes providers that lack auth — the user can still pick them,
        but the call will fail until they configure a key (visible in the
        Providers section below).
        """
        src: dict
        if category == "llm":
            src = router._providers
        elif category == "asr":
            src = router._asr_providers
        elif category == "tts":
            src = router._tts_providers
        else:
            return []
        return list(src.keys())

    def _models_for(self, provider: str) -> list[str]:
        cfg = router._providers.get(provider, {})
        return list(cfg.get("models", []))

    def _on_routing_provider_changed(self, task_id: str):
        prov = self._task_provider_vars[task_id].get()
        cat = _ai_cfg.task_category(task_id)
        if cat == "llm":
            models = self._models_for(prov)
            cb = self._task_model_combos.get(task_id)
            if cb is not None:
                cb.configure(values=models)
            cur = self._task_model_vars[task_id].get()
            if cur not in models:
                self._task_model_vars[task_id].set(models[0] if models else "")
            router.set_task_routing(
                task_id, prov, self._task_model_vars[task_id].get())
        else:
            router.set_task_routing(task_id, prov, "")

    def _on_routing_model_changed(self, task_id: str):
        prov = self._task_provider_vars[task_id].get()
        model = self._task_model_vars[task_id].get().strip()
        router.set_task_routing(task_id, prov, model)

    # ── Language routing dialog (ASR per-language provider override) ───────

    def _refresh_lang_button_state(self, task_id: str) -> None:
        """Sync the 🌐 button's text + visual disabled state with the
        current enable flag and override count. Called after toggling the
        master switch and after the dialog persists changes."""
        btn = getattr(self, "_task_lang_buttons", {}).get(task_id)
        if btn is None:
            return
        lr = router.get_task_language_routing(task_id)
        enabled = router.get_task_language_routing_enabled(task_id)
        btn.configure(text=tr("tool.router.lang_routing_btn", n=len(lr)))
        # Keep button clickable either way — user may want to view/edit
        # overrides while the master switch is off. Visual cue only:
        # gray foreground when inactive so the row clearly shows the
        # current dispatch behavior.
        btn.configure(fg=("#000" if enabled else "#999"))

    def _open_language_routing_dialog(self, task_id: str):
        dlg = tk.Toplevel(self.master)
        dlg.title(tr("tool.router.lang_routing_title", task=task_id))
        dlg.transient(self.master)
        dlg.grab_set()

        default_prov = (router.get_task_routing()
                          .get(task_id, {})
                          .get("provider")
                          or tr("tool.router.lang_routing_no_default"))

        tk.Label(
            dlg,
            text=tr("tool.router.lang_routing_help", default=default_prov),
            wraplength=520, justify="left", fg="#555",
        ).pack(anchor="w", padx=12, pady=(10, 8))

        # Header row
        header = tk.Frame(dlg)
        header.pack(fill="x", padx=12)
        tk.Label(header, text=tr("tool.router.lang_routing_lang_col"),
                 font=("", 9, "bold"), width=20, anchor="w").pack(side="left")
        tk.Label(header, text=tr("tool.router.lang_routing_provider_col"),
                 font=("", 9, "bold"), width=22, anchor="w").pack(side="left")

        # Dynamic body — one row per (iso, provider) pair
        rows_frame = tk.Frame(dlg)
        rows_frame.pack(fill="both", expand=True, padx=12, pady=(4, 4))

        asr_provider_names = list(router._asr_providers.keys())
        lang_options = self._language_routing_options()

        # Each row: (iso_var, provider_var, frame_widget)
        row_widgets: list[dict] = []

        def persist():
            mapping = {}
            for r in row_widgets:
                iso = r["iso_var"].get().strip().lower()
                prov = r["prov_var"].get().strip()
                if iso and prov:
                    mapping[iso] = {"provider": prov}
            router.set_task_language_routing(task_id, mapping)
            self._refresh_lang_button_state(task_id)

        def add_row(iso: str = "", prov: str = ""):
            row = tk.Frame(rows_frame)
            row.pack(fill="x", pady=2)
            iso_var = tk.StringVar(value=iso)
            prov_var = tk.StringVar(value=prov)

            iso_cb = ttk.Combobox(
                row, textvariable=iso_var, values=lang_options,
                state="normal", width=18,
            )
            iso_cb.pack(side="left")
            iso_cb.bind("<<ComboboxSelected>>", lambda _e: persist())
            iso_cb.bind("<FocusOut>", lambda _e: persist())

            prov_cb = ttk.Combobox(
                row, textvariable=prov_var, values=asr_provider_names,
                state="readonly", width=20,
            )
            prov_cb.pack(side="left", padx=(4, 4))
            prov_cb.bind("<<ComboboxSelected>>", lambda _e: persist())

            entry = {"iso_var": iso_var, "prov_var": prov_var, "frame": row}

            def remove():
                row.destroy()
                row_widgets.remove(entry)
                persist()

            tk.Button(row, text="×", width=2, command=remove,
                      ).pack(side="left", padx=4)
            row_widgets.append(entry)

        # Seed with existing entries
        for iso, sub in router.get_task_language_routing(task_id).items():
            add_row(iso, sub.get("provider", ""))

        # Footer
        footer = tk.Frame(dlg)
        footer.pack(fill="x", padx=12, pady=(4, 12))
        tk.Button(footer, text=tr("tool.router.lang_routing_add"),
                  command=lambda: add_row()).pack(side="left")
        tk.Button(footer, text=tr("tool.router.lang_routing_close"),
                  command=dlg.destroy).pack(side="right")

    def _language_routing_options(self) -> list[str]:
        """ISO codes shown in the language column dropdown. Pulls the
        union of (1) Parakeet's supported European languages,
        (2) SenseVoice's supported Asian languages + English, and
        (3) a small extra set so users can target Whisper-only langs.
        """
        try:
            from core.ai.providers.parakeet_local import SUPPORTED_LANGUAGES as _PK_LANGS
        except Exception:
            _PK_LANGS = ()
        try:
            from core.ai.providers.sensevoice_local import SUPPORTED_LANGUAGES as _SV_LANGS
        except Exception:
            _SV_LANGS = ()
        # Whisper-only fallback targets for users who want to keep certain
        # languages on faster-whisper.
        extras = ("ar", "hi", "tr", "vi", "th", "id")
        seen: list[str] = []
        for code in tuple(_PK_LANGS) + tuple(_SV_LANGS) + extras:
            if code in ("auto",):
                continue
            if code not in seen:
                seen.append(code)
        return seen

    # ── Bottom section: provider management list ───────────────────────────

    def _build_providers_section(self, parent):
        # Header
        tk.Label(parent, text=tr("tool.router.col_provider_model"),
                 font=("", 9, "bold"), anchor="w", width=22,
                 ).grid(row=0, column=0, sticky="w", padx=4, pady=(0, 4))
        tk.Label(parent, text=tr("tool.router.col_key_status"),
                 font=("", 9, "bold"), anchor="w", width=22,
                 ).grid(row=0, column=1, sticky="w", padx=4, pady=(0, 4))

        ttk.Separator(parent, orient="horizontal").grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=2)

        row_idx = 2
        for category, src in (
            ("llm", router._providers),
            ("asr", router._asr_providers),
            ("tts", router._tts_providers),
        ):
            for name, cfg in src.items():
                row_idx = self._build_provider_row(
                    parent, row_idx, name, cfg, category)

    def _build_provider_row(self, parent, row: int, name: str,
                            cfg: dict, category: str) -> int:
        is_available = _ai_cfg.has_auth(cfg)
        key_text, key_color = self._key_status(cfg)
        display_name = cfg.get("name", name)

        # Name + LLM model count hint (e.g. "Gemini · 2 models")
        label_frame = tk.Frame(parent)
        label_frame.grid(row=row, column=0, sticky="w", padx=4, pady=2)
        tk.Label(label_frame, text=display_name,
                 font=("", 9, "bold"), anchor="w").pack(anchor="w")
        if category == "llm":
            n_models = len(cfg.get("models", []))
            if n_models:
                tk.Label(label_frame, text=f"  · {n_models} models",
                         font=("", 8), fg="#777").pack(anchor="w")

        tk.Label(parent, text=key_text, fg=key_color, anchor="w",
                 font=("", 9)).grid(row=row, column=1, sticky="w",
                                    padx=4, pady=2)

        # Enable toggle — `enabled` only affects auto-fallback candidate
        # pools (LLM tier dispatch); explicit task_routing picks bypass
        # it. Surface it here so users can hide unused providers from
        # the LLM auto-fallback flow without deleting their config.
        enabled_var = tk.BooleanVar(value=cfg.get("enabled", True))
        def _on_toggle_enabled(n=name, cat=category, var=enabled_var):
            new_val = bool(var.get())
            if cat == "llm":
                router.set_provider_enabled(n, new_val)
            elif cat == "asr":
                router.set_asr_provider_enabled(n, new_val)
            elif cat == "tts":
                router.set_tts_provider_enabled(n, new_val)
        ttk.Checkbutton(parent, text=tr("tool.router.btn_enable"),
                        variable=enabled_var,
                        command=_on_toggle_enabled).grid(
            row=row, column=2, padx=4, sticky="w")

        tk.Button(parent, text=tr("tool.router.btn_edit"), width=5,
                  command=lambda n=name, c=cfg, cat=category:
                          self._open_edit_dialog(n, c, cat)
                  ).grid(row=row, column=3, padx=2)

        test_btn = tk.Button(
            parent, text=tr("tool.router.btn_test"), width=5,
            command=lambda n=name, cat=category:
                    self._run_provider_test(n, cat),
        )
        if category != "llm" or not is_available:
            test_btn.configure(state="disabled")
        test_btn.grid(row=row, column=4, padx=2)
        self._test_buttons[name] = test_btn
        return row + 1

    def _rebuild_routing_tab(self):
        for w in self.tab_routing.winfo_children():
            w.destroy()
        self._build_routing_tab()

    # ── Edit dialog (provider key + base_url + models + refresh) ────────────

    def _open_edit_dialog(self, name: str, cfg: dict, category: str):
        if cfg.get("type") == "claude_code":
            self._open_claude_code_dialog(name, cfg)
            return
        if category == "llm":
            self._open_llm_edit_dialog(name, cfg)
            return
        # ASR / TTS dialog
        self._open_asr_tts_edit_dialog(name, cfg, category)

    def _open_llm_edit_dialog(self, name: str, cfg: dict):
        dlg = tk.Toplevel(self.master)
        dlg.title(tr("tool.router.edit_dialog_title", name=name))

        # Local providers (e.g. Ollama) use auth_required=False — they have no
        # API key, so we hide the key row entirely and seed key_var with a
        # placeholder so the model-picker's fetch path still works.
        is_local = cfg.get("auth_required") is False

        # Local mode adds a hint row that needs more horizontal room; widen
        # the dialog so the right-side button column (Pick / Remove / Health
        # Check) doesn't get clipped (especially under Windows DPI scaling).
        dlg.geometry("900x460" if is_local else "560x420")
        dlg.resizable(True, True)
        dlg.grab_set()
        # Ensure column 3 always reserves room for the action buttons even
        # when no widget in that column has a wide natural request.
        dlg.grid_columnconfigure(3, minsize=180)

        r = 0
        if is_local:
            tk.Label(dlg, text=tr("tool.router.local_provider_hint"),
                     fg="#666", anchor="w", justify="left",
                     wraplength=680).grid(
                row=r, column=0, columnspan=4, padx=12, pady=(12, 6), sticky="w")
            key_var = tk.StringVar(value="ollama")
            r += 1
        else:
            tk.Label(dlg, text=tr("tool.router.label_api_key"),
                     anchor="e", width=12).grid(
                row=r, column=0, padx=10, pady=10, sticky="e")
            key_var = tk.StringVar()
            key_entry = tk.Entry(dlg, textvariable=key_var, width=42, show="*")
            key_entry.grid(row=r, column=1, columnspan=2, pady=10, sticky="w")
            kp = os.path.join(_keys_dir(), cfg.get("key_file", ""))
            if kp and os.path.exists(kp) and os.path.isfile(kp):
                with open(kp, "r", encoding="utf-8") as f:
                    key_var.set(f.read().strip())
            show_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(dlg, text=tr("tool.router.label_show"), variable=show_var,
                            command=lambda: key_entry.config(show="" if show_var.get() else "*"),
                            ).grid(row=r, column=3, padx=6)
            r += 1

        url_var = None
        if cfg.get("type") == "openai_compatible":
            tk.Label(dlg, text="Base URL:", anchor="e", width=12).grid(
                row=r, column=0, padx=10, pady=8, sticky="e")
            url_var = tk.StringVar(value=cfg.get("base_url", ""))
            tk.Entry(dlg, textvariable=url_var, width=52).grid(
                row=r, column=1, columnspan=3, pady=8, sticky="w")
            r += 1

        # Selected-models list + "Refresh & Pick…" button. Replaces the
        # legacy Text-area-of-comma-separated-names where API refresh dumped
        # 20+ Gemini models flat. Picker dialog (below) handles the curation.
        tk.Label(dlg, text=tr("tool.router.label_active_models"),
                 anchor="ne", width=12).grid(
            row=r, column=0, padx=10, pady=8, sticky="ne")

        selected_models: list[str] = list(cfg.get("models", []))

        list_frame = tk.Frame(dlg)
        list_frame.grid(row=r, column=1, columnspan=2, pady=8, sticky="w")
        models_listbox = tk.Listbox(list_frame, height=6, width=44,
                                    exportselection=False, font=("", 9))
        models_listbox.pack(side="left", fill="both")
        lb_vsb = ttk.Scrollbar(list_frame, orient="vertical",
                               command=models_listbox.yview)
        models_listbox.configure(yscrollcommand=lb_vsb.set)
        lb_vsb.pack(side="right", fill="y")

        def _redraw_selected():
            models_listbox.delete(0, "end")
            for m in selected_models:
                models_listbox.insert("end", m)
        _redraw_selected()

        def _remove_selected():
            sel = models_listbox.curselection()
            if not sel:
                return
            del selected_models[sel[0]]
            _redraw_selected()

        def _on_picked(new_list: list[str]):
            # Mutate in place so the save() closure sees the new content.
            selected_models[:] = new_list
            _redraw_selected()

        btn_col = tk.Frame(dlg)
        btn_col.grid(row=r, column=3, padx=6, pady=8, sticky="n")
        tk.Button(btn_col, text=tr("tool.router.btn_pick_models"),
                  command=lambda: self._open_model_picker_dialog(
                      dlg, name, cfg, key_var, url_var,
                      list(selected_models), _on_picked),
                  width=18).pack(pady=2, fill="x")
        tk.Button(btn_col, text=tr("tool.router.btn_remove_model"),
                  command=_remove_selected, width=18).pack(pady=2, fill="x")
        if is_local:
            def _health_check():
                base = (url_var.get().strip() if url_var is not None
                        else cfg.get("base_url", ""))
                if not base:
                    messagebox.showerror(tr("dialog.common.error"),
                                         tr("tool.router.error_no_base_url"),
                                         parent=dlg)
                    return
                try:
                    from core.ai.providers import openai_compat as _oc
                    models = _oc.list_models("ollama", base)
                    messagebox.showinfo(
                        tr("tool.router.saved_title"),
                        tr("tool.router.health_ok", n=len(models)),
                        parent=dlg)
                except Exception as e:
                    messagebox.showerror(
                        tr("dialog.common.error"),
                        tr("tool.router.health_fail") + f"\n\n{e}",
                        parent=dlg)
            tk.Button(btn_col, text=tr("tool.router.btn_health_check"),
                      command=_health_check, width=18).pack(pady=2, fill="x")
        r += 1

        def save():
            if not is_local:
                key = key_var.get().strip()
                if not key:
                    messagebox.showerror(tr("dialog.common.error"),
                                         tr("tool.router.error_key_empty"), parent=dlg)
                    return
                key_file = cfg.get("key_file", "")
                if key_file:
                    kp_save = os.path.join(_keys_dir(), key_file)
                    os.makedirs(os.path.dirname(kp_save), exist_ok=True)
                    with open(kp_save, "w", encoding="utf-8") as f:
                        f.write(key)
            kwargs = {}
            if url_var is not None:
                kwargs["base_url"] = url_var.get().strip()
            kwargs["models"] = list(selected_models)
            router.update_provider(name, **kwargs)
            messagebox.showinfo(tr("tool.router.saved_title"),
                                tr("tool.router.saved_config_msg", name=name), parent=dlg)
            self._rebuild_routing_tab()
            dlg.destroy()

        btn_row = tk.Frame(dlg)
        btn_row.grid(row=r, column=0, columnspan=4, pady=14)
        tk.Button(btn_row, text=tr("tool.router.btn_save"), command=save,
                  width=10).pack(side="left", padx=10)
        tk.Button(btn_row, text=tr("tool.router.btn_cancel"), command=dlg.destroy,
                  width=10).pack(side="left")

    def _open_model_picker_dialog(self, parent_dlg, name: str, cfg: dict,
                                  key_var: tk.StringVar,
                                  url_var: tk.StringVar | None,
                                  current_selected: list[str],
                                  on_save):
        """Modal model-picker. Fetches the API list, lets the user toggle
        checkboxes, supports search, and a manual-add row at the bottom for
        models that aren't returned by list_models() (or when no API call is
        possible). on_save(new_list) is invoked when the user confirms.
        """
        dlg = tk.Toplevel(parent_dlg)
        dlg.title(tr("tool.router.picker_title", name=name))
        dlg.geometry("520x560")
        dlg.transient(parent_dlg)
        dlg.grab_set()

        # State: API-returned models (display order) + per-model BooleanVar.
        # Pre-seed checks for currently-selected models so they remain
        # checked even if list_models() doesn't return them.
        api_models: list[str] = []
        check_vars: dict[str, tk.BooleanVar] = {
            m: tk.BooleanVar(value=True) for m in current_selected
        }

        # Top row: search
        top = tk.Frame(dlg)
        top.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(top, text=tr("tool.router.picker_search")).pack(side="left")
        search_var = tk.StringVar()
        search_entry = tk.Entry(top, textvariable=search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))

        # Status line (loading / loaded / error)
        status_var = tk.StringVar(value=tr("tool.router.refresh_models_busy"))
        tk.Label(dlg, textvariable=status_var, fg="#555", font=("", 8),
                 anchor="w").pack(fill="x", padx=10, pady=(0, 4))

        # Middle: scrollable list of checkboxes
        list_outer = tk.Frame(dlg, bd=1, relief="sunken")
        list_outer.pack(fill="both", expand=True, padx=10, pady=4)
        list_canvas = tk.Canvas(list_outer, highlightthickness=0)
        list_vsb = ttk.Scrollbar(list_outer, orient="vertical",
                                 command=list_canvas.yview)
        list_canvas.configure(yscrollcommand=list_vsb.set)
        list_canvas.pack(side="left", fill="both", expand=True)
        list_vsb.pack(side="right", fill="y")
        list_inner = tk.Frame(list_canvas)
        list_canvas.create_window((0, 0), window=list_inner, anchor="nw")
        list_inner.bind(
            "<Configure>",
            lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")),
        )

        # Scoped wheel binding (don't leak through to background canvas).
        def _wheel(e):
            bbox = list_canvas.bbox("all")
            if not bbox:
                return
            if bbox[3] - bbox[1] <= list_canvas.winfo_height():
                return
            list_canvas.yview_scroll(int(-e.delta / 120), "units")
        list_canvas.bind("<Enter>",
                         lambda _e: list_canvas.bind_all("<MouseWheel>", _wheel))
        list_canvas.bind("<Leave>",
                         lambda _e: list_canvas.unbind_all("<MouseWheel>"))
        list_canvas.bind("<Destroy>",
                         lambda _e: list_canvas.unbind_all("<MouseWheel>"))

        def _redraw():
            for w in list_inner.winfo_children():
                w.destroy()
            q = search_var.get().lower().strip()
            # Stable order: API first, then preselected-not-in-API, then manual.
            seen: set[str] = set()
            order: list[str] = []
            for m in api_models:
                order.append(m)
                seen.add(m)
            for m in current_selected:
                if m not in seen:
                    order.append(m)
                    seen.add(m)
            for m in check_vars.keys():
                if m not in seen:
                    order.append(m)
                    seen.add(m)

            shown = 0
            for m in order:
                if q and q not in m.lower():
                    continue
                if m not in check_vars:
                    check_vars[m] = tk.BooleanVar(value=False)
                ttk.Checkbutton(list_inner, text=m,
                                variable=check_vars[m]).pack(
                    anchor="w", padx=4, pady=1, fill="x")
                shown += 1
            if shown == 0:
                tk.Label(list_inner, text=tr("tool.router.picker_no_match"),
                         fg="#888", font=("", 9, "italic")).pack(
                    anchor="w", padx=8, pady=8)

        search_var.trace_add("write", lambda *_: _redraw())

        # Bottom: manual add row
        add_row = tk.Frame(dlg)
        add_row.pack(fill="x", padx=10, pady=(4, 4))
        tk.Label(add_row, text=tr("tool.router.picker_manual_label")
                 ).pack(side="left")
        manual_var = tk.StringVar()
        manual_entry = tk.Entry(add_row, textvariable=manual_var)
        manual_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))

        def _manual_add():
            m = manual_var.get().strip()
            if not m:
                return
            if m not in check_vars:
                check_vars[m] = tk.BooleanVar(value=True)
            else:
                check_vars[m].set(True)
            manual_var.set("")
            _redraw()

        tk.Button(add_row, text=tr("tool.router.picker_btn_add"),
                  command=_manual_add, width=6).pack(side="left")
        manual_entry.bind("<Return>", lambda _e: _manual_add())

        # Save / Cancel
        btn_row = tk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=(8, 12))

        def _do_save():
            new_list = [m for m, v in check_vars.items() if v.get()]
            on_save(new_list)
            dlg.destroy()

        tk.Button(btn_row, text=tr("tool.router.picker_btn_save"),
                  command=_do_save, width=14).pack(side="right")
        tk.Button(btn_row, text=tr("tool.router.btn_cancel"),
                  command=dlg.destroy, width=10).pack(side="right", padx=6)

        # Initial render so preselected models show up immediately
        _redraw()

        # Background API fetch — best-effort. If key empty or fetch fails,
        # the picker still works for manual-add only.
        new_key = key_var.get().strip()
        new_url = (url_var.get().strip() if url_var is not None
                   else cfg.get("base_url", ""))
        if not new_key:
            status_var.set(tr("tool.router.error_key_empty"))
            return

        is_local_pick = cfg.get("auth_required") is False

        def _do_fetch():
            try:
                ptype = cfg.get("type")
                if ptype == "gemini":
                    from core.ai.providers import gemini as _g
                    models = _g.list_models(new_key)
                elif ptype == "openai_compatible":
                    if not new_url:
                        raise RuntimeError(tr("tool.router.error_no_base_url"))
                    from core.ai.providers import openai_compat as _oc
                    models = _oc.list_models(new_key, new_url)
                else:
                    raise RuntimeError(tr("tool.router.refresh_unsupported"))
                dlg.after(0, lambda m=models: _on_loaded(m))
            except Exception as e:
                err = str(e)
                if is_local_pick:
                    hint = tr("tool.router.health_fail")
                    dlg.after(0,
                        lambda em=err, h=hint: status_var.set(
                            f"{h}\n[{em[:160]}]"))
                else:
                    dlg.after(0,
                        lambda em=err: status_var.set(
                            tr("tool.router.refresh_models_fail", e=em[:100])))

        def _on_loaded(models):
            nonlocal api_models
            api_models = list(models)
            for m in api_models:
                if m not in check_vars:
                    check_vars[m] = tk.BooleanVar(value=False)
            sel_count = sum(1 for v in check_vars.values() if v.get())
            status_var.set(tr("tool.router.picker_status_loaded",
                              api_count=len(api_models),
                              sel_count=sel_count))
            _redraw()

        threading.Thread(target=_do_fetch, daemon=True).start()

    def _open_claude_code_dialog(self, name: str, cfg: dict):
        dlg = tk.Toplevel(self.master)
        dlg.title(tr("tool.router.edit_dialog_title", name=name))
        dlg.geometry("500x340")
        dlg.resizable(False, False)
        dlg.grab_set()

        r = 0
        tk.Label(dlg, text=tr("tool.router.label_executable"), anchor="e", width=14).grid(
            row=r, column=0, padx=10, pady=(14, 6), sticky="e")
        exec_var = tk.StringVar(value=cfg.get("executable", "claude"))
        tk.Entry(dlg, textvariable=exec_var, width=42).grid(
            row=r, column=1, columnspan=3, pady=(14, 6), sticky="w")
        r += 1

        tk.Label(dlg, text=tr("tool.router.label_timeout_sec"), anchor="e", width=14).grid(
            row=r, column=0, padx=10, pady=6, sticky="e")
        timeout_var = tk.StringVar(value=str(cfg.get("timeout_sec", 600)))
        tk.Entry(dlg, textvariable=timeout_var, width=14).grid(
            row=r, column=1, pady=6, sticky="w")
        r += 1

        tk.Label(dlg, text=tr("tool.router.label_models"), anchor="ne", width=14).grid(
            row=r, column=0, padx=10, pady=6, sticky="ne")
        models_text = tk.Text(dlg, height=4, width=42, wrap="word")
        models_text.grid(row=r, column=1, columnspan=3, pady=6, sticky="w")
        models_text.insert("1.0", ", ".join(cfg.get("models", [])))
        r += 1

        tk.Label(
            dlg, text=tr("tool.router.claudecode_hint"),
            font=("", 8), fg="gray", justify="left", wraplength=440,
        ).grid(row=r, column=0, columnspan=4, padx=12, pady=(8, 4), sticky="w")
        r += 1

        def save():
            executable = exec_var.get().strip() or "claude"
            try:
                timeout_sec = _parse_int_range(
                    timeout_var.get(), minimum=10, maximum=3600,
                    field_label=tr("tool.router.label_timeout_sec"),
                )
            except ValueError as e:
                messagebox.showerror(tr("dialog.common.error"), str(e), parent=dlg)
                return
            raw = models_text.get("1.0", "end")
            models = [m.strip() for m in raw.replace("\n", ",").split(",") if m.strip()]
            router.update_provider(
                name,
                executable=executable,
                timeout_sec=timeout_sec,
                models=models,
            )
            messagebox.showinfo(tr("tool.router.saved_title"),
                                tr("tool.router.saved_config_msg", name=name), parent=dlg)
            self._rebuild_routing_tab()
            dlg.destroy()

        btn_row = tk.Frame(dlg)
        btn_row.grid(row=r, column=0, columnspan=4, pady=14)
        tk.Button(btn_row, text=tr("tool.router.btn_save"), command=save, width=10).pack(side="left", padx=10)
        tk.Button(btn_row, text=tr("tool.router.btn_cancel"), command=dlg.destroy, width=10).pack(side="left")

    def _open_asr_tts_edit_dialog(self, name: str, cfg: dict, category: str):
        is_asr = (category == "asr")
        is_local = cfg.get("auth_required") is False
        if is_local and is_asr:
            self._open_local_asr_edit_dialog(name, cfg)
            return
        display_name = cfg.get("name", name)
        dlg = tk.Toplevel(self.master)
        dlg.title(tr("tool.router.edit_dialog_title", name=display_name))
        dlg.geometry("560x300" if is_asr else "560x180")
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text=tr("tool.router.label_api_key"),
                 anchor="e", width=12).grid(row=0, column=0, padx=10, pady=16, sticky="e")
        key_var = tk.StringVar()
        key_entry = tk.Entry(dlg, textvariable=key_var, width=38, show="*")
        key_entry.grid(row=0, column=1, columnspan=2, pady=16, sticky="w")
        kp = os.path.join(_keys_dir(), cfg.get("key_file", ""))
        if kp and os.path.exists(kp):
            with open(kp, "r", encoding="utf-8") as f:
                key_var.set(f.read().strip())
        show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dlg, text=tr("tool.router.label_show"), variable=show_var,
                        command=lambda: key_entry.config(show="" if show_var.get() else "*"),
                        ).grid(row=0, column=3, padx=6)

        connect_var = tk.StringVar(value=str(cfg.get("connect_timeout_sec", 60)))
        read_var    = tk.StringVar(value=str(cfg.get("read_timeout_sec", 120)))
        retries_var = tk.StringVar(value=str(cfg.get("max_retries", 1)))

        if is_asr:
            tk.Label(dlg, text=tr("tool.router.label_connect_timeout_sec"),
                     anchor="e", width=12).grid(row=1, column=0, padx=10, pady=6, sticky="e")
            tk.Entry(dlg, textvariable=connect_var, width=14).grid(row=1, column=1, pady=6, sticky="w")
            tk.Label(dlg, text=tr("tool.router.label_read_timeout_sec"),
                     anchor="e", width=12).grid(row=2, column=0, padx=10, pady=6, sticky="e")
            tk.Entry(dlg, textvariable=read_var, width=14).grid(row=2, column=1, pady=6, sticky="w")
            tk.Label(dlg, text=tr("tool.router.label_max_retries"),
                     anchor="e", width=12).grid(row=3, column=0, padx=10, pady=6, sticky="e")
            tk.Entry(dlg, textvariable=retries_var, width=14).grid(row=3, column=1, pady=6, sticky="w")
            tk.Label(dlg, text=tr("tool.router.asr_retry_hint"),
                     font=("", 8), fg="gray", justify="left", wraplength=430,
                     ).grid(row=4, column=0, columnspan=4, padx=12, pady=(8, 4), sticky="w")

        def save():
            key = key_var.get().strip()
            if not key:
                messagebox.showerror(tr("dialog.common.error"),
                                     tr("tool.router.error_key_empty"), parent=dlg)
                return
            if is_asr:
                try:
                    ct = _parse_int_range(connect_var.get(), minimum=5, maximum=300,
                                          field_label=tr("tool.router.label_connect_timeout_sec"))
                    rt = _parse_int_range(read_var.get(), minimum=30, maximum=600,
                                          field_label=tr("tool.router.label_read_timeout_sec"))
                    mr = _parse_int_range(retries_var.get(), minimum=1, maximum=10,
                                          field_label=tr("tool.router.label_max_retries"))
                except ValueError as e:
                    messagebox.showerror(tr("dialog.common.error"), str(e), parent=dlg)
                    return
            kp_save = os.path.join(_keys_dir(), cfg.get("key_file", ""))
            if kp_save:
                os.makedirs(os.path.dirname(kp_save), exist_ok=True)
                with open(kp_save, "w", encoding="utf-8") as f:
                    f.write(key)
            if is_asr:
                router.update_asr_provider(
                    name,
                    connect_timeout_sec=ct,
                    read_timeout_sec=rt,
                    max_retries=mr,
                )
            messagebox.showinfo(tr("tool.router.saved_title"),
                                tr("tool.router.saved_config_msg", name=display_name), parent=dlg)
            self._rebuild_routing_tab()
            dlg.destroy()

        btn_row = tk.Frame(dlg)
        btn_row.grid(row=5, column=0, columnspan=4, pady=14)
        tk.Button(btn_row, text=tr("tool.router.btn_save"), command=save,
                  width=10).pack(side="left", padx=10)
        tk.Button(btn_row, text=tr("tool.router.btn_cancel"), command=dlg.destroy,
                  width=10).pack(side="left")

    def _open_local_asr_edit_dialog(self, name: str, cfg: dict):
        """Edit dialog for a local ASR provider (faster-whisper).

        No API key row; instead exposes model size, device, compute type,
        and beam size. First-time use of a model triggers a HuggingFace
        download — emit that warning in the hint label.
        """
        display_name = cfg.get("name", name)
        dlg = tk.Toplevel(self.master)
        dlg.title(tr("tool.router.edit_dialog_title", name=display_name))
        dlg.geometry("620x360")
        dlg.resizable(True, True)
        dlg.grab_set()

        tk.Label(dlg, text=tr("tool.router.local_asr_hint"),
                 fg="#666", anchor="w", justify="left",
                 wraplength=580).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="w")

        # Model size dropdown — sorted from smallest to largest, with a
        # short capability hint per option.
        MODEL_OPTIONS = [
            "tiny",
            "base",
            "small",
            "medium",
            "large-v3-turbo",
            "large-v3",
        ]
        DEVICE_OPTIONS = ["auto", "cpu", "cuda"]
        COMPUTE_OPTIONS = ["auto", "int8", "int8_float16", "float16", "float32"]

        model_var   = tk.StringVar(value=cfg.get("model", "small"))
        device_var  = tk.StringVar(value=cfg.get("device", "auto"))
        compute_var = tk.StringVar(value=cfg.get("compute_type", "auto"))
        beam_var    = tk.StringVar(value=str(cfg.get("beam_size", 5)))

        def _row(r, label_key, var, values):
            tk.Label(dlg, text=tr(label_key), anchor="e", width=14).grid(
                row=r, column=0, padx=10, pady=6, sticky="e")
            ttk.Combobox(dlg, textvariable=var, values=values,
                         state="readonly", width=24).grid(
                row=r, column=1, padx=4, pady=6, sticky="w")

        _row(1, "tool.router.label_fw_model", model_var, MODEL_OPTIONS)
        _row(2, "tool.router.label_fw_device", device_var, DEVICE_OPTIONS)
        _row(3, "tool.router.label_fw_compute", compute_var, COMPUTE_OPTIONS)

        tk.Label(dlg, text=tr("tool.router.label_fw_beam_size"),
                 anchor="e", width=14).grid(
            row=4, column=0, padx=10, pady=6, sticky="e")
        tk.Entry(dlg, textvariable=beam_var, width=10).grid(
            row=4, column=1, padx=4, pady=6, sticky="w")

        def save():
            try:
                bs = _parse_int_range(beam_var.get(), minimum=1, maximum=10,
                                      field_label=tr("tool.router.label_fw_beam_size"))
            except ValueError as e:
                messagebox.showerror(tr("dialog.common.error"), str(e), parent=dlg)
                return
            router.update_asr_provider(
                name,
                model=model_var.get(),
                device=device_var.get(),
                compute_type=compute_var.get(),
                beam_size=bs,
            )
            messagebox.showinfo(tr("tool.router.saved_title"),
                                tr("tool.router.saved_config_msg", name=display_name),
                                parent=dlg)
            self._rebuild_routing_tab()
            dlg.destroy()

        btn_row = tk.Frame(dlg)
        btn_row.grid(row=5, column=0, columnspan=2, pady=18)
        tk.Button(btn_row, text=tr("tool.router.btn_save"), command=save,
                  width=10).pack(side="left", padx=10)
        tk.Button(btn_row, text=tr("tool.router.btn_cancel"), command=dlg.destroy,
                  width=10).pack(side="left")

    # ── Test button ─────────────────────────────────────────────────────────

    def _run_provider_test(self, name: str, category: str):
        if category != "llm":
            messagebox.showinfo(
                tr("tool.router.test_result_skipped_title", name=name),
                tr("tool.router.test_unsupported_for_category"),
                parent=self.master,
            )
            return

        btn = self._test_buttons.get(name)
        if btn is not None:
            btn.configure(state="disabled", text=tr("tool.router.btn_test_busy"))

        def _restore():
            if btn is not None:
                btn.configure(state="normal", text=tr("tool.router.btn_test"))

        def _run():
            try:
                # Local providers (Ollama) ship with empty tier defaults;
                # fall back to the first picked model so the smoke test
                # can resolve a model_id to call.
                cfg_now = router._providers.get(name, {})
                tiers = cfg_now.get("tiers", {}) or {}
                model_override = None
                if not any(tiers.values()):
                    picked = cfg_now.get("models") or []
                    if picked:
                        model_override = picked[0]
                txt = ai.complete(
                    "Please reply with the single word OK and nothing else.",
                    provider=name,
                    model=model_override,
                )
                self.master.after(0,
                    lambda t=(txt or "").strip(): self._show_test_result(name, "ok", t))
            except Exception as e:
                err = str(e)
                self.master.after(0,
                    lambda em=err: self._show_test_result(name, "fail", em))
            finally:
                self.master.after(0, _restore)

        threading.Thread(target=_run, daemon=True).start()

    def _show_test_result(self, name: str, kind: str, message: str):
        title_key = {
            "ok":      "tool.router.test_result_ok_title",
            "fail":    "tool.router.test_result_fail_title",
            "skipped": "tool.router.test_result_skipped_title",
        }[kind]
        title = tr(title_key, name=name)
        snippet = message if len(message) <= 800 else message[:800] + "\n…"
        messagebox.showinfo(title, snippet, parent=self.master)

    # ── Key status ──────────────────────────────────────────────────────────

    def _key_status(self, cfg: dict):
        """Return (display_text, color)."""
        if cfg.get("type") == "claude_code":
            return tr("tool.router.status_claude_cli"), "#228B22"
        key_file = cfg.get("key_file", "")
        if not key_file:
            return tr("tool.router.status_no_key_needed"), "#555555"
        key_path = os.path.join(_keys_dir(), key_file)
        if not os.path.exists(key_path):
            return tr("tool.router.status_not_configured"), "#CC0000"
        with open(key_path, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if not key:
            return tr("tool.router.status_key_empty"), "#CC0000"
        masked = key[:4] + "****" + key[-4:] if len(key) >= 8 else "****"
        return f"✅ {masked}", "#228B22"

    # ── Prompts tab (central prompt management) ─────────────────────────────

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

    # ── Stats tab (unchanged from M6) ───────────────────────────────────────

    def _build_stats_tab(self):
        tab = self.tab_stats

        cols   = ("provider", "calls", "errors", "error_rate", "last_used")
        labels = (tr("tool.router.col_provider"),
                  tr("tool.router.col_calls"),
                  tr("tool.router.col_errors"),
                  tr("tool.router.col_error_rate"),
                  tr("tool.router.col_last_used"))
        widths = (100, 80, 80, 70, 180)

        self.stats_tree = ttk.Treeview(tab, columns=cols,
                                       show="headings", height=10)
        for col, label, w in zip(cols, labels, widths):
            self.stats_tree.heading(col, text=label)
            self.stats_tree.column(col, width=w, anchor="center")

        vsb = ttk.Scrollbar(tab, orient="vertical",
                            command=self.stats_tree.yview)
        self.stats_tree.configure(yscrollcommand=vsb.set)
        self.stats_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        btn_col = tk.Frame(tab)
        btn_col.pack(side="left", padx=10, anchor="n")
        tk.Button(btn_col, text=tr("tool.router.btn_refresh"),
                  command=self._refresh_stats, width=8).pack(pady=4)

        self._refresh_stats()

    def _refresh_stats(self):
        if not hasattr(self, "stats_tree"):
            return
        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)
        for name, s in router.get_stats().items():
            calls  = s["calls"]
            errors = s["errors"]
            rate   = f"{errors / calls * 100:.0f}%" if calls > 0 else "—"
            last   = s["last_used"] or tr("tool.router.never_used")
            self.stats_tree.insert("", "end", values=(name, calls, errors, rate, last))
