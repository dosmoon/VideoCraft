"""AI Console — provider management + task-routing dropdowns + stats.

UI layout (5 tabs):
  Provider — task routing matrix: one row per TASKS entry, with
             provider + model dropdowns. Picks auto-save via
             router.set_task_routing().
  内置模型 — 🏠 Local Embedded (LlamaCpp / faster-whisper) +
             🌐 Free Online (Microsoft Edge TTS) — bundled providers
             that need zero API key.
  云服务   — ☁️ Cloud providers requiring an API key (Gemini /
             DeepSeek / Custom / ClaudeCode / LemonFox / Fish Audio).
  aistack  — Self-hosted gateway pane: URL + Test/Refresh + Enable.
  Stats    — Per-provider call counters.

Editing a provider in any of the 4 provider-related tabs rebuilds
all 4 (the routing matrix dropdowns may have new choices).

Prompt editing + Playground live in the Prompt Console tool
(tools/router/prompt_console.py) — split out 2026-05-11.

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
from core.ai.router import router
from core.ai import config as _ai_cfg
from core.ai.config import keys_dir as _keys_dir
from core import paths as _paths


# ── Routing tier model ───────────────────────────────────────────────────────
# Each task box in the Routing tab presents 3-4 fixed tier rows (radio
# buttons), one of which is the active routing for that task. The set of
# tiers and per-(category, tier) defaults are declared here so adding a
# new tier (say a future OpenRouter gateway) means editing this block,
# not the rendering code.
_ROUTING_TIERS_LLM     = ("embedded", "cloud", "aistack", "auto")
_ROUTING_TIERS_NON_LLM = ("embedded", "cloud", "aistack")

_TIER_META: dict[str, tuple[str, str]] = {
    # tier_id -> (emoji, i18n label key)
    "embedded": ("🏠", "tool.router.tier_embedded"),
    "cloud":    ("☁️", "tool.router.tier_cloud"),
    "aistack":  ("🚀", "tool.router.tier_aistack"),
    "auto":     ("⚡", "tool.router.tier_auto"),
}

# The provider that owns each (tier, category) cell. None entries mean
# "the user picks among multiple providers" (cloud LLM is the only such
# case today — Gemini / DeepSeek / Custom / ClaudeCode all coexist).
_PROVIDER_FOR_TIER: dict[tuple[str, str], str | None] = {
    ("embedded", "llm"): "LlamaCpp",
    ("embedded", "asr"): "faster_whisper",
    ("embedded", "tts"): "edge_tts",
    ("cloud",    "llm"): None,             # multi-vendor pick
    ("cloud",    "asr"): "lemonfox",
    ("cloud",    "tts"): "fish_audio",
    ("aistack",  "llm"): "aistack",
    ("aistack",  "asr"): "aistack",
    ("aistack",  "tts"): "aistack",
}

# Names of providers that belong to the "embedded" routing tier (covers
# in-process providers + Microsoft Edge TTS — user requested they share
# one tier). Anything not in here / aistack / Auto = cloud.
_EMBEDDED_PROVIDER_NAMES = frozenset({"LlamaCpp", "faster_whisper", "edge_tts"})


def _routing_tier_of(stored_provider: str) -> str:
    """Reverse-map a stored routing provider string to its tier id."""
    if not stored_provider:
        return "auto"
    if stored_provider == "aistack":
        return "aistack"
    if stored_provider in _EMBEDDED_PROVIDER_NAMES:
        return "embedded"
    return "cloud"


# Sentinel shown in ASR/TTS model dropdowns when no specific model is picked.
# For aistack: "auto" tells the gateway to pick a backend internally (by
# language hint for ASR, only model for TTS today). Stored value is the
# literal string "auto" so dispatch can pass it straight through.
_AUTO_MODEL_LABEL = "auto"


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

        self.tab_routing  = tk.Frame(nb, padx=8, pady=8)
        self.tab_embedded = tk.Frame(nb, padx=8, pady=8)
        self.tab_cloud    = tk.Frame(nb, padx=8, pady=8)
        self.tab_aistack  = tk.Frame(nb, padx=8, pady=8)
        self.tab_tts      = tk.Frame(nb, padx=8, pady=8)
        self.tab_stats    = tk.Frame(nb, padx=12, pady=10)

        nb.add(self.tab_routing,  text=tr("tool.router.tab_routing"))
        nb.add(self.tab_embedded, text=tr("tool.router.tab_embedded"))
        nb.add(self.tab_cloud,    text=tr("tool.router.tab_cloud"))
        nb.add(self.tab_aistack,  text=tr("tool.router.tab_aistack"))
        nb.add(self.tab_tts,      text=tr("tool.router.tab_tts"))
        nb.add(self.tab_stats,    text=tr("tool.router.tab_stats"))
        self._routing_tab_index = 0
        self._stats_tab_index   = 5
        self._notebook = nb
        nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._build_routing_tab()
        self._build_embedded_tab()
        self._build_cloud_tab()
        self._build_aistack_tab()
        self._build_tts_tab()
        self._build_stats_tab()

        # Pick up newly-installed local models / fresh aistack model
        # caches when the user alt-tabs back from the Local Model Manager
        # window. FocusIn fires on every internal focus change too, so
        # filter to the toplevel-level event (when Tk reports the master
        # itself receiving focus = window activation by the OS).
        master.bind("<FocusIn>", self._on_window_focus)

    def _on_tab_change(self, event):
        nb = event.widget
        idx = nb.index(nb.select())
        if idx == self._stats_tab_index:
            self._refresh_stats()
        elif idx == self._routing_tab_index:
            # Switching back to routing also refreshes — covers the case
            # where the user installed a model in another tab (Embedded
            # tab's [Edit] dialog) and wants to see it appear here.
            self._rebuild_routing_tab()

    def _on_window_focus(self, event):
        if event.widget is not self.master:
            return
        # Only spend the rebuild if routing is the visible tab — no
        # point recreating its widgets when the user is staring at
        # Stats or aistack.
        if self._notebook.index(self._notebook.select()) == self._routing_tab_index:
            self._rebuild_routing_tab()

    # ── Routing tab: task-first per-task tier picker ──────────────────────

    def _build_routing_tab(self):
        tab = self.tab_routing
        body = self._scrollable_body(tab)

        tk.Label(body,
                 text=tr("tool.router.routing_prompt"),
                 font=("", 9), fg="#555", wraplength=1000, justify="left",
                 ).pack(anchor="w", pady=(0, 8))

        # Reset widget refs that survive across rebuild — used by Edit
        # buttons in other tabs (which still need this list to find the
        # per-provider Test button to re-enable).
        self._test_buttons: dict[str, tk.Button] = {}

        # Per-(task_id, tier) widget state. Keyed: [task_id][tier_id] = dict
        # of var/combo refs. Used by event handlers to read/write current
        # routing without re-walking the widget tree.
        self._task_radio_vars: dict[str, tk.StringVar] = {}
        self._task_tier_state: dict[str, dict[str, dict]] = {}

        self._build_routing_section(body)

    # ── Embedded tab: 🏠 in-process + 🌐 free online ───────────────────────

    def _build_embedded_tab(self):
        tab = self.tab_embedded
        body = self._scrollable_body(tab)

        tk.Label(body, text=tr("tool.router.embedded_intro"),
                 font=("", 9), fg="#555", wraplength=900, justify="left",
                 ).pack(anchor="w", padx=2, pady=(0, 8))

        buckets = self._bucket_providers_by_tier()

        local_frame = tk.LabelFrame(
            body, text=tr("tool.router.section_local_title"),
            padx=10, pady=8, font=("", 10, "bold"),
        )
        local_frame.pack(fill="x", pady=(0, 8), anchor="w")
        self._build_tier_block(
            local_frame, 0, buckets["local"],
            "tool.router.section_local_help",
            empty_key="tool.router.section_local_empty",
            extra_button=("tool.router.btn_open_model_manager",
                          self._open_local_model_manager),
        )

        free_frame = tk.LabelFrame(
            body, text=tr("tool.router.section_free_online_title"),
            padx=10, pady=8, font=("", 10, "bold"),
        )
        free_frame.pack(fill="x", anchor="w")
        self._build_tier_block(
            free_frame, 0, buckets["free_online"],
            "tool.router.section_free_online_help",
        )

    # ── Cloud tab: ☁️ providers requiring an API key ──────────────────────

    def _build_cloud_tab(self):
        tab = self.tab_cloud
        body = self._scrollable_body(tab)

        tk.Label(body, text=tr("tool.router.cloud_intro"),
                 font=("", 9), fg="#555", wraplength=900, justify="left",
                 ).pack(anchor="w", padx=2, pady=(0, 8))

        buckets = self._bucket_providers_by_tier()
        cloud_frame = tk.LabelFrame(
            body, text=tr("tool.router.section_cloud_title"),
            padx=10, pady=8, font=("", 10, "bold"),
        )
        cloud_frame.pack(fill="x", anchor="w")
        self._build_tier_block(
            cloud_frame, 0, buckets["cloud"],
            "tool.router.section_cloud_help",
        )

    # ── aistack tab: 🚀 self-hosted gateway ───────────────────────────────

    def _build_aistack_tab(self):
        tab = self.tab_aistack

        tk.Label(tab, text=tr("tool.router.aistack_intro"),
                 font=("", 9), fg="#555", wraplength=900, justify="left",
                 ).pack(anchor="w", pady=(0, 8))

        gateway_frame = tk.LabelFrame(
            tab, text=tr("tool.router.section_gateway_title"),
            padx=10, pady=8, font=("", 10, "bold"),
        )
        gateway_frame.pack(fill="x", anchor="w")
        self._build_aistack_gateway_section(gateway_frame)

    # ── TTS tab: unified provider cards ───────────────────────────────────
    # All TTS providers (edge_tts / fish_audio / aistack-as-TTS) live here
    # rather than scattered across the tier tabs. TTS doesn't route the
    # same way LLM/ASR do — voice picks happen at use time via
    # VoicePickerDialog — so this tab focuses on connection state,
    # voice catalog freshness, and the "browse voices" entry point.

    _TTS_PROVIDER_EMOJI: dict[str, str] = {
        "edge_tts":   "🌐",     # free online
        "fish_audio": "☁️",     # cloud
        "aistack":    "🚀",     # gateway
    }

    def _build_tts_tab(self):
        tab = self.tab_tts
        body = self._scrollable_body(tab)

        tk.Label(body, text=tr("tool.router.tts_intro"),
                 font=("", 9), fg="#555", wraplength=900, justify="left",
                 ).pack(anchor="w", padx=2, pady=(0, 8))

        # Render in a fixed order so the layout doesn't shuffle when
        # providers are added/removed (e.g. user disables fish_audio).
        for provider_name in ("edge_tts", "fish_audio", "aistack"):
            cfg = router._tts_providers.get(provider_name)
            if cfg is None:
                continue
            self._render_tts_card(body, provider_name, cfg)

    def _render_tts_card(self, parent, provider_name: str, cfg: dict):
        from core.ai.tts_voice import get_catalog_meta

        emoji = self._TTS_PROVIDER_EMOJI.get(provider_name, "·")
        display_name = cfg.get("name", provider_name)
        card = tk.LabelFrame(
            parent, text=f"  {emoji}  {display_name}  ",
            padx=10, pady=8, font=("", 10, "bold"),
        )
        card.pack(fill="x", pady=(0, 8), anchor="w")

        # Status line: connection state + catalog freshness
        status_text = self._tts_status_text(provider_name, cfg)
        tk.Label(card, text=status_text, fg="#555", anchor="w",
                 font=("", 9), wraplength=820, justify="left",
                 ).pack(fill="x", pady=(0, 4))

        meta = get_catalog_meta(provider_name)
        catalog_text = self._tts_catalog_text(meta)
        tk.Label(card, text=catalog_text, fg="#666", anchor="w",
                 font=("", 9),
                 ).pack(fill="x", pady=(0, 6))

        # Buttons
        btn_row = tk.Frame(card)
        btn_row.pack(fill="x")
        tk.Button(
            btn_row, text=tr("tool.router.tts_btn_refresh"), width=14,
            command=lambda p=provider_name: self._on_tts_refresh(p),
        ).pack(side="left", padx=(0, 4))
        tk.Button(
            btn_row, text=tr("tool.router.tts_btn_browse"), width=14,
            command=lambda p=provider_name: self._on_tts_browse(p),
        ).pack(side="left", padx=4)
        tk.Button(
            btn_row, text=tr("tool.router.tts_btn_edit"), width=10,
            command=lambda n=provider_name, c=cfg: self._open_edit_dialog(n, c, "tts"),
        ).pack(side="left", padx=4)

        # aistack gets a hint pointing at the gateway tab (connection
        # state isn't editable here — it's owned by the aistack tab).
        if provider_name == "aistack":
            tk.Label(card, text=tr("tool.router.tts_aistack_hint"),
                     fg="#888", font=("", 8, "italic"), anchor="w",
                     ).pack(fill="x", pady=(6, 0))

    def _tts_status_text(self, provider_name: str, cfg: dict) -> str:
        """One-line connection status for the TTS card."""
        if provider_name == "edge_tts":
            # Free online — only signal is whether the SDK is importable.
            try:
                import edge_tts  # noqa: F401
                return tr("tool.router.tts_status_ready")
            except ImportError:
                return tr("tool.router.tts_status_no_sdk", pkg="edge-tts")
        if provider_name == "fish_audio":
            key = _ai_cfg.read_key(cfg)
            if not key:
                return tr("tool.router.tts_status_no_key")
            masked = f"{key[:4]}****{key[-4:]}" if len(key) >= 8 else "****"
            return tr("tool.router.tts_status_keyed", masked=masked)
        if provider_name == "aistack":
            gw = router.get_aistack_gateway()
            if not gw["enabled"]:
                return tr("tool.router.tts_status_aistack_off")
            return tr("tool.router.tts_status_aistack_url", url=gw["base_url"])
        return ""

    def _tts_catalog_text(self, meta: dict) -> str:
        """One-line catalog freshness for the TTS card."""
        if not meta["has_cache"]:
            return tr("tool.router.tts_catalog_empty")
        return tr("tool.router.tts_catalog_meta",
                  count=meta["count"],
                  age=self._format_age(meta["last_refresh_ts"]))

    @staticmethod
    def _format_age(ts: float) -> str:
        """Human-readable elapsed time since `ts` (UNIX seconds).
        Localized via tr() so the wording matches the active language."""
        import time
        if ts <= 0:
            return tr("tool.router.age_never")
        elapsed = time.time() - ts
        if elapsed < 60:
            return tr("tool.router.age_just_now")
        if elapsed < 3600:
            return tr("tool.router.age_minutes", n=int(elapsed // 60))
        if elapsed < 86400:
            return tr("tool.router.age_hours", n=int(elapsed // 3600))
        return tr("tool.router.age_days", n=int(elapsed // 86400))

    def _on_tts_refresh(self, provider_name: str):
        """Force a network refresh of the provider's voice catalog,
        then rebuild the TTS tab so the catalog meta updates."""
        from core.ai.tts_voice import get_catalog
        # Run synchronously — Edge takes ~1s; UI freeze is acceptable
        # for an explicit user click. Worth threading later if other
        # providers (fish_audio with N voices) get slow.
        try:
            get_catalog(provider_name, refresh=True)
        except Exception as e:
            messagebox.showerror(tr("dialog.common.error"),
                                 tr("tool.router.tts_refresh_failed",
                                    provider=provider_name, err=str(e)[:200]),
                                 parent=self.master)
            return
        self._rebuild_tts_tab()

    def _on_tts_browse(self, provider_name: str):
        """Open the VoicePickerDialog scoped to one provider, in browse
        mode (the user just hits Cancel when done — discarding any
        selection). This is the "let me see what voices exist" affordance.
        """
        from tools.router.voice_picker import VoicePickerDialog
        VoicePickerDialog.ask(
            self.master,
            initial_provider=provider_name,
            allowed_providers=(provider_name,),
            title=tr("tool.router.tts_browse_title", provider=provider_name),
        )

    def _rebuild_tts_tab(self):
        for w in self.tab_tts.winfo_children():
            w.destroy()
        self._build_tts_tab()

    # ── Helpers ────────────────────────────────────────────────────────────

    def _scrollable_body(self, parent: tk.Frame) -> tk.Frame:
        """Wrap parent in a vertically scrollable Canvas + Frame and return
        the inner frame. Mousewheel is scoped to the canvas only so modal
        Edit dialogs don't leak scroll events through to the background.
        """
        outer = tk.Frame(parent)
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

        def _on_wheel(e):
            bbox = canvas.bbox("all")
            if not bbox:
                return
            if bbox[3] - bbox[1] <= canvas.winfo_height():
                return
            canvas.yview_scroll(int(-e.delta / 120), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        canvas.bind("<Destroy>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return body

    # ── aistack gateway pane: URL + enable + test/refresh ──────────────────

    def _build_aistack_gateway_section(self, parent):
        gw = router.get_aistack_gateway()

        # Row 0: URL entry + Test/Refresh button
        tk.Label(parent, text=tr("tool.router.gateway_url_label"),
                 anchor="w").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self._gateway_url_var = tk.StringVar(value=gw["base_url"])
        tk.Entry(parent, textvariable=self._gateway_url_var, width=42).grid(
            row=0, column=1, sticky="w", padx=4, pady=4)
        # When the URL diverges from what the gateway was last tested at,
        # the cached model list no longer corresponds to a known-good URL.
        # Drop it eagerly so the routing dropdowns can't expose stale models
        # belonging to the previous URL.
        self._gateway_url_var.trace_add(
            "write", lambda *_: self._on_gateway_url_changed())
        tk.Button(parent, text=tr("tool.router.gateway_test_btn"),
                  command=self._on_gateway_test,
                  ).grid(row=0, column=2, sticky="w", padx=8, pady=4)
        self._gateway_status = tk.Label(parent, text="", anchor="w",
                                        wraplength=560, justify="left")
        self._gateway_status.grid(row=0, column=3, sticky="w", padx=8)

        # Row 1: Enable checkbox
        self._gateway_enabled_var = tk.BooleanVar(value=gw["enabled"])
        ttk.Checkbutton(
            parent, text=tr("tool.router.gateway_enable_label"),
            variable=self._gateway_enabled_var,
            command=self._on_gateway_enable_toggle,
        ).grid(row=1, column=1, columnspan=3, sticky="w", padx=4, pady=(0, 4))

        # Row 2: help text
        tk.Label(parent, text=tr("tool.router.gateway_help"),
                 fg="#777", anchor="w", wraplength=900, justify="left",
                 ).grid(row=2, column=0, columnspan=4, sticky="w",
                        padx=4, pady=(2, 0))

    def _on_gateway_test(self):
        url = self._gateway_url_var.get().strip()
        if not url:
            self._gateway_status.configure(
                text=tr("tool.router.gateway_url_empty"), fg="#a32")
            return

        # Strip any /v1 suffix the user typed; the helper appends it.
        bare = url.rstrip("/")
        if bare.endswith("/v1"):
            bare = bare[:-3]

        self._gateway_status.configure(
            text=tr("tool.router.gateway_status_busy"), fg="#666")

        def _do_fetch():
            try:
                from core.ai.providers import aistack as _aistack
                pairs = _aistack.list_models_with_capabilities(bare)
            except Exception as e:
                # Reachability failed — do NOT persist the URL or touch the
                # cache. A typo here used to silently overwrite the prior
                # known-good URL and leave the user pointing at nothing.
                msg = str(e)
                self.master.after(
                    0, lambda m=msg: self._gateway_status.configure(
                        text=tr("tool.router.gateway_status_offline", err=m[:140]),
                        fg="#a32"))
                return
            buckets = {"llm": [], "asr": [], "tts": []}
            for mid, caps in pairs:
                for cap in caps:
                    if cap in buckets:
                        buckets[cap].append(mid)

            def _ok():
                # Persist URL + enabled and the freshly-fetched model cache
                # only on success — keeps router state and UI in lockstep.
                router.set_aistack_gateway(url, self._gateway_enabled_var.get())
                router.set_aistack_models_cache(buckets)
                self._gateway_status.configure(
                    text=tr(
                        "tool.router.gateway_status_online",
                        total=sum(len(v) for v in buckets.values()),
                        llm=len(buckets["llm"]),
                        asr=len(buckets["asr"]),
                        tts=len(buckets["tts"]),
                    ),
                    fg="#2a7a3a",
                )
                self._rebuild_routing_tab()
            self.master.after(0, _ok)

        threading.Thread(target=_do_fetch, daemon=True).start()

    def _on_gateway_enable_toggle(self):
        url = self._gateway_url_var.get().strip()
        router.set_aistack_gateway(url, self._gateway_enabled_var.get())
        # Toggling enable flips the aistack rows in the routing tab between
        # active model dropdowns and "(disabled)" hints — rebuild that tab
        # only so the URL Entry on this aistack tab keeps its focus.
        self._rebuild_routing_tab()

    def _on_gateway_url_changed(self):
        """Drop the model cache when the typed URL diverges from the one
        the gateway was last tested against. Aistack rows in the routing
        tab lose their model dropdowns until the user clicks Test & Refresh
        again — better an empty dropdown than one full of models that don't
        exist on the new URL.
        """
        typed = self._gateway_url_var.get().strip().rstrip("/")
        if typed.endswith("/v1"):
            typed = typed[:-3]
        stored = router.get_aistack_gateway()["base_url"].rstrip("/")
        if stored.endswith("/v1"):
            stored = stored[:-3]
        if typed == stored:
            return
        cache = router.get_aistack_models_cache()
        if not any(cache.get(k) for k in ("llm", "asr", "tts")):
            return
        router.set_aistack_models_cache({"llm": [], "asr": [], "tts": []})
        self._rebuild_routing_tab()
        if hasattr(self, "_gateway_status"):
            self._gateway_status.configure(text="", fg="#666")

    def _aistack_model_choices(self, category: str) -> list[str]:
        """Cached aistack models filtered by capability, with 'auto' first
        for ASR/TTS rows (LLM rows have no inherent fallback model)."""
        cache = router.get_aistack_models_cache()
        models = cache.get(category, [])
        if category in ("asr", "tts"):
            return [_AUTO_MODEL_LABEL, *models]
        return list(models)

    # ── Top section: 4-row task routing table ──────────────────────────────

    # Capability pill label rendered before each task name. Mirrors the
    # color treatment in the HTML mockup so users instantly see which
    # ability owns each row.
    _PILL_STYLE = {
        "llm": {"bg": "#e9eaf6", "fg": "#445", "text": "LLM"},
        "asr": {"bg": "#e8f3ec", "fg": "#2c5e3a", "text": "ASR"},
        "tts": {"bg": "#fbeede", "fg": "#7a4b1c", "text": "TTS"},
    }

    def _build_routing_section(self, parent):
        """Task-first routing — one LabelFrame per task, each containing
        radio rows for the available tiers (Embedded / Cloud / aistack /
        Auto-for-LLM). The radio that's checked = current routing for
        that task; the row's provider+model widgets show what that tier
        would dispatch to.
        """
        current_routing = router.get_task_routing()
        for tid, cat, label in _ai_cfg.TASKS:
            cell = current_routing.get(tid, {}) or {}
            self._build_task_box(parent, tid, cat, label, cell)

    def _build_task_box(self, parent, task_id: str, category: str,
                        label: str, current_cell: dict) -> None:
        pill = self._PILL_STYLE.get(category, {})
        title = f"  {pill.get('text', '?')}  ·  {label}  "

        box = tk.LabelFrame(parent, text=title, padx=10, pady=6,
                            font=("", 10, "bold"))
        box.pack(fill="x", pady=(0, 8), anchor="w")

        active_tier = _routing_tier_of(current_cell.get("provider", ""))
        # Drop tasks pinned to a tier that's gone (e.g. aistack disabled
        # but routing still points there) back to whatever tier the
        # stored provider says — handler will re-persist on next radio
        # interaction. Don't auto-fix here to avoid surprise writes.
        radio_var = tk.StringVar(value=active_tier)
        self._task_radio_vars[task_id] = radio_var
        self._task_tier_state[task_id] = {}

        tiers = _ROUTING_TIERS_LLM if category == "llm" else _ROUTING_TIERS_NON_LLM
        for r, tier in enumerate(tiers):
            self._build_tier_row(box, r, task_id, category, tier,
                                 radio_var, active_tier, current_cell)

    def _build_tier_row(self, parent, r: int, task_id: str, category: str,
                        tier: str, radio_var: tk.StringVar,
                        active_tier: str, current_cell: dict) -> None:
        """Render one (radio, tier label, provider widget, model widget)
        row inside a task box.
        """
        is_active = (active_tier == tier)
        emoji, label_key = _TIER_META[tier]

        ttk.Radiobutton(
            parent, variable=radio_var, value=tier,
            command=lambda: self._on_tier_radio_picked(task_id, category, tier),
        ).grid(row=r, column=0, padx=(0, 4), pady=2, sticky="w")

        tk.Label(parent, text=f"{emoji} {tr(label_key)}", anchor="w",
                 width=12, font=("", 9),
                 ).grid(row=r, column=1, padx=(0, 8), pady=2, sticky="w")

        # ── Auto row: no provider/model widgets, just a hint ──
        if tier == "auto":
            tk.Label(parent, text=tr("tool.router.tier_auto_hint"),
                     fg="#777", anchor="w", font=("", 9, "italic"),
                     ).grid(row=r, column=2, columnspan=2, padx=4, pady=2,
                            sticky="w")
            self._task_tier_state[task_id][tier] = {"provider": "", "model": ""}
            return

        # ── aistack: implicit provider, model dropdown from gateway cache ──
        if tier == "aistack":
            self._render_aistack_row(parent, r, task_id, category, tier,
                                     is_active, current_cell)
            return

        # ── embedded LLM: provider label + model dropdown from cfg.models ──
        if tier == "embedded" and category == "llm":
            self._render_embedded_llm_row(parent, r, task_id, tier,
                                          is_active, current_cell)
            return

        # ── cloud LLM: provider dropdown + model dropdown ──
        if tier == "cloud" and category == "llm":
            self._render_cloud_llm_row(parent, r, task_id, tier,
                                       is_active, current_cell)
            return

        # ── embedded ASR: provider label + model dropdown from disk ──
        if tier == "embedded" and category == "asr":
            self._render_embedded_asr_row(parent, r, task_id, tier)
            return

        # ── all other ASR/TTS: provider label + static model label ──
        self._render_simple_asr_tts_row(parent, r, task_id, category, tier)

    # ── Per-tier-shape renderers ───────────────────────────────────────────
    # All renderers read their initial (provider, model) pick from the
    # task_tier_prefs sidecar via _initial_pick (so per-tier configs survive
    # tier switches and Console reopens). Defaults kick in lazily — first
    # time a row is rendered with no pref, we fall back to a sensible
    # default and write nothing; the user's first dropdown change will
    # populate the pref.

    def _initial_pick(self, task_id: str, tier: str,
                      default_provider: str, valid_models: list[str],
                      ) -> tuple[str, str]:
        """Read pref → validate against current options → fall back if stale.
        Returns (provider, model)."""
        pref = router.get_task_tier_pref(task_id, tier)
        if pref:
            prov = pref.get("provider", "")
            model = pref.get("model", "")
            # Embedded/aistack tiers have a fixed provider; cloud LLM is
            # the only multi-provider tier (validated by caller). Validate
            # the model belongs to whatever provider the pref names.
            if prov and (not valid_models or model in valid_models):
                return (prov, model)
        if not valid_models:
            return (default_provider, "")
        return (default_provider, valid_models[0])

    def _render_embedded_llm_row(self, parent, r, task_id, tier,
                                 is_active, current_cell):
        provider = "LlamaCpp"
        models = list(router._providers.get(provider, {}).get("models", []))
        _prov, init_model = self._initial_pick(task_id, tier, provider, models)

        tk.Label(parent, text=provider, anchor="w", width=18, fg="#222",
                 ).grid(row=r, column=2, padx=4, pady=2, sticky="w")

        if models:
            model_var = tk.StringVar(value=init_model)
            cb = ttk.Combobox(parent, textvariable=model_var, values=models,
                              state="readonly", width=28)
            cb.grid(row=r, column=3, padx=4, pady=2, sticky="w")
            cb.bind("<<ComboboxSelected>>",
                    lambda _e: self._on_tier_model_picked(task_id, tier))
            self._task_tier_state[task_id][tier] = {
                "provider": provider, "model_var": model_var,
            }
        else:
            tk.Label(parent, text=tr("tool.router.tier_no_model_installed"),
                     fg="#a32", anchor="w",
                     ).grid(row=r, column=3, padx=4, pady=2, sticky="w")
            self._task_tier_state[task_id][tier] = {
                "provider": provider, "model": "",
            }

    def _render_cloud_llm_row(self, parent, r, task_id, tier,
                              is_active, current_cell):
        providers = [n for n in router._providers.keys()
                     if n != "aistack" and n != "LlamaCpp"]

        # Initial provider: prev pref's provider if still listed; else
        # first provider with a configured key; else first listed.
        pref = router.get_task_tier_pref(task_id, tier) or {}
        pref_prov = pref.get("provider", "")
        if pref_prov and pref_prov in providers:
            init_prov = pref_prov
        else:
            init_prov = next(
                (p for p in providers
                 if _ai_cfg.has_auth(router._providers.get(p, {}))),
                providers[0] if providers else "",
            )

        prov_var = tk.StringVar(value=init_prov)
        prov_cb = ttk.Combobox(parent, textvariable=prov_var, values=providers,
                               state="readonly", width=16)
        prov_cb.grid(row=r, column=2, padx=4, pady=2, sticky="w")
        prov_cb.bind("<<ComboboxSelected>>",
                     lambda _e: self._on_cloud_llm_provider_picked(task_id, tier))

        models = list(router._providers.get(init_prov, {}).get("models", []))
        # Initial model: pref's model if it belongs to the picked provider
        # (and pref's provider == init_prov); else first model.
        if pref_prov == init_prov and pref.get("model") in models:
            init_model = pref["model"]
        else:
            init_model = models[0] if models else ""
        model_var = tk.StringVar(value=init_model)
        model_cb = ttk.Combobox(parent, textvariable=model_var, values=models,
                                state="readonly", width=26)
        model_cb.grid(row=r, column=3, padx=4, pady=2, sticky="w")
        model_cb.bind("<<ComboboxSelected>>",
                      lambda _e: self._on_tier_model_picked(task_id, tier))

        self._task_tier_state[task_id][tier] = {
            "provider_var": prov_var, "provider_cb": prov_cb,
            "model_var": model_var, "model_cb": model_cb,
        }

    def _render_aistack_row(self, parent, r, task_id, category, tier,
                            is_active, current_cell):
        gw_enabled = router.get_aistack_gateway()["enabled"]
        provider = "aistack"

        prov_color = "#222" if gw_enabled else "#a32"
        prov_text = provider if gw_enabled else (
            f"{provider}  ·  {tr('tool.router.tier_aistack_disabled')}")
        tk.Label(parent, text=prov_text, anchor="w", width=22, fg=prov_color,
                 ).grid(row=r, column=2, padx=4, pady=2, sticky="w")

        choices = self._aistack_model_choices(category) if gw_enabled else []
        _prov, init_model = self._initial_pick(task_id, tier, provider, choices)

        if choices:
            model_var = tk.StringVar(value=init_model)
            cb = ttk.Combobox(parent, textvariable=model_var, values=choices,
                              state="readonly", width=28)
            cb.grid(row=r, column=3, padx=4, pady=2, sticky="w")
            cb.bind("<<ComboboxSelected>>",
                    lambda _e: self._on_tier_model_picked(task_id, tier))
            self._task_tier_state[task_id][tier] = {
                "provider": provider, "model_var": model_var,
            }
        else:
            hint_key = ("tool.router.tier_aistack_no_model" if gw_enabled
                        else "tool.router.tier_aistack_disabled_hint")
            tk.Label(parent, text=tr(hint_key), fg="#888",
                     font=("", 9, "italic"), anchor="w",
                     ).grid(row=r, column=3, padx=4, pady=2, sticky="w")
            # No choices: persist with empty model. The dispatch will 503
            # at runtime (better than silently using a meaningless "auto"
            # for LLM, which the gateway can't auto-pick).
            self._task_tier_state[task_id][tier] = {
                "provider": provider, "model": "",
            }

    def _render_embedded_asr_row(self, parent, r, task_id, tier):
        """faster-whisper: model dropdown enumerates installed CT2 model
        directories under <models>/faster-whisper/. User can pick small
        vs large-v3-turbo inline without going through Edit dialog.
        """
        from core.ai.providers import faster_whisper as _fw
        provider = "faster_whisper"
        models = _fw.list_models()
        _prov, init_model = self._initial_pick(task_id, tier, provider, models)

        tk.Label(parent, text=provider, anchor="w", width=18, fg="#222",
                 ).grid(row=r, column=2, padx=4, pady=2, sticky="w")

        if models:
            model_var = tk.StringVar(value=init_model)
            cb = ttk.Combobox(parent, textvariable=model_var, values=models,
                              state="readonly", width=28)
            cb.grid(row=r, column=3, padx=4, pady=2, sticky="w")
            cb.bind("<<ComboboxSelected>>",
                    lambda _e: self._on_tier_model_picked(task_id, tier))
            self._task_tier_state[task_id][tier] = {
                "provider": provider, "model_var": model_var,
            }
        else:
            tk.Label(parent, text=tr("tool.router.tier_no_model_installed"),
                     fg="#a32", anchor="w",
                     ).grid(row=r, column=3, padx=4, pady=2, sticky="w")
            self._task_tier_state[task_id][tier] = {
                "provider": provider, "model": "",
            }

    def _render_simple_asr_tts_row(self, parent, r, task_id, category, tier):
        """embedded/cloud ASR/TTS: implicit provider + cfg-driven model
        (shown as static text — edit it via the [Edit] button in the
        Embedded / Cloud tab)."""
        provider = _PROVIDER_FOR_TIER[(tier, category)]
        cfg_src = (router._asr_providers if category == "asr"
                   else router._tts_providers)
        cfg = cfg_src.get(provider, {}) or {}
        # Use the most "model-like" field available per provider.
        model_text = (cfg.get("model")
                      or cfg.get("voice")
                      or "—")
        prov_color = "#222"

        tk.Label(parent, text=provider, anchor="w", width=18, fg=prov_color,
                 ).grid(row=r, column=2, padx=4, pady=2, sticky="w")
        tk.Label(parent, text=model_text, anchor="w", fg="#222",
                 ).grid(row=r, column=3, padx=4, pady=2, sticky="w")
        self._task_tier_state[task_id][tier] = {
            "provider": provider, "model": cfg.get("model", ""),
        }

    # ── Event handlers ────────────────────────────────────────────────────
    # Two write surfaces:
    #   - Radio click  → set_task_routing (this row becomes active)
    #   - Dropdown change → set_task_tier_pref (saved as that tier's pick;
    #     does NOT touch the radio — user's "exploring" the cloud row's
    #     options shouldn't yank the active routing)
    # When the radio happens to already be on the row whose dropdown
    # changed, we additionally update task_routing so dispatch sees the
    # fresh pick immediately (no stale-routing window between the pref
    # write and the next radio click).

    def _on_tier_radio_picked(self, task_id: str, category: str, tier: str):
        """Activate this tier: copy its current (provider, model) pick into
        task_routing so dispatch uses it.
        """
        provider, model = self._effective_pick(task_id, tier)
        router.set_task_routing(task_id, provider, model)

    def _on_cloud_llm_provider_picked(self, task_id: str, tier: str):
        """Cloud LLM only: vendor changed. Reset the model dropdown to
        the new vendor's first model, persist the pref. If this row is
        already active, keep task_routing in sync.
        """
        state = self._task_tier_state[task_id][tier]
        new_prov = state["provider_var"].get()
        models = list(router._providers.get(new_prov, {}).get("models", []))
        state["model_cb"].configure(values=models)
        new_model = models[0] if models else ""
        state["model_var"].set(new_model)
        router.set_task_tier_pref(task_id, tier, new_prov, new_model)
        if self._task_radio_vars[task_id].get() == tier:
            router.set_task_routing(task_id, new_prov, new_model)

    def _on_tier_model_picked(self, task_id: str, tier: str):
        """Model dropdown changed in any tier row. Always persist as that
        tier's pref (per-tier configs survive tier switches). Only touch
        task_routing if this row is the currently active tier.
        """
        provider, model = self._effective_pick(task_id, tier)
        router.set_task_tier_pref(task_id, tier, provider, model)
        if self._task_radio_vars[task_id].get() == tier:
            router.set_task_routing(task_id, provider, model)

    def _effective_pick(self, task_id: str, tier: str) -> tuple[str, str]:
        """Compute (provider, model) currently shown by a tier row."""
        state = self._task_tier_state.get(task_id, {}).get(tier, {})
        if tier == "auto":
            return ("", "")
        # Cloud LLM rows carry both provider_var and model_var
        if "provider_var" in state:
            return (state["provider_var"].get(),
                    state.get("model_var").get() if "model_var" in state else "")
        provider = state.get("provider", "")
        if "model_var" in state:
            return (provider, state["model_var"].get())
        return (provider, state.get("model", ""))

    # ── Bottom section: cloud providers, grouped by capability ─────────────

    # Provider-name → tier classification. Tiers drive the visual bucket a
    # provider lands in inside the Routing tab. Kept as a hard-coded map
    # rather than a cfg field so users can't accidentally mis-classify
    # their own provider into the "free online" bucket. New providers must
    # be added here (default = cloud).
    _LOCAL_PROVIDER_NAMES = frozenset({
        "LlamaCpp",            # in-process llama-cpp-python
        "faster_whisper",      # in-process CTranslate2 Whisper
    })
    _FREE_ONLINE_PROVIDER_NAMES = frozenset({
        "edge_tts",            # Microsoft Read-Aloud, no key
    })

    def _classify_provider_tier(self, name: str) -> str:
        """Return one of: 'local' | 'free_online' | 'aistack' | 'cloud'."""
        if name == "aistack":
            return "aistack"
        if name in self._LOCAL_PROVIDER_NAMES:
            return "local"
        if name in self._FREE_ONLINE_PROVIDER_NAMES:
            return "free_online"
        return "cloud"

    def _bucket_providers_by_tier(self) -> dict[str, dict[str, list]]:
        """Walk LLM/ASR provider dicts and bucket each entry by tier.

        TTS is excluded entirely — TTS providers all live in the dedicated
        TTS tab (introduced 2026-05-11) instead of being scattered across
        the Embedded / Cloud sections by tier. aistack is also excluded
        here — it owns the aistack tab.

        Returns {tier: {category: [(name, cfg), ...]}}.
        """
        buckets: dict[str, dict[str, list]] = {
            "local":       {"llm": [], "asr": []},
            "free_online": {"llm": [], "asr": []},
            "cloud":       {"llm": [], "asr": []},
        }
        for category, src in (("llm", router._providers),
                              ("asr", router._asr_providers)):
            for name, cfg in src.items():
                tier = self._classify_provider_tier(name)
                if tier == "aistack":
                    continue
                buckets[tier][category].append((name, cfg))
        return buckets

    def _build_tier_block(self, parent, row_idx: int,
                          tier_buckets: dict[str, list],
                          help_key: str,
                          *,
                          empty_key: str | None = None,
                          extra_button: tuple[str, callable] | None = None,
                          ) -> int:
        """Render the inside of one tier LabelFrame:
            [help line]   [optional button at top-right]
            ── pill: LLM ── (if any)
              <provider rows>
            ── pill: ASR ── (if any)
              <provider rows>
            ── pill: TTS ── (if any)
              <provider rows>
        Caller owns the LabelFrame title. Returns next free row index.
        """
        # Help line + optional action button on the same row
        help_row = tk.Frame(parent)
        help_row.grid(row=row_idx, column=0, columnspan=5,
                      sticky="ew", padx=0, pady=(0, 4))
        help_row.columnconfigure(0, weight=1)
        tk.Label(help_row, text=tr(help_key), fg="#777", anchor="w",
                 font=("", 8), wraplength=820, justify="left",
                 ).grid(row=0, column=0, sticky="w")
        if extra_button is not None:
            btn_key, btn_cmd = extra_button
            tk.Button(help_row, text=tr(btn_key), command=btn_cmd,
                      font=("", 8), padx=4, pady=0,
                      ).grid(row=0, column=1, sticky="e", padx=4)
        row_idx += 1

        # Empty-state line if no providers in this tier
        if (empty_key is not None
                and not any(tier_buckets.get(c) for c in ("llm", "asr"))):
            tk.Label(parent, text=tr(empty_key), fg="#999",
                     font=("", 9, "italic"), anchor="w",
                     ).grid(row=row_idx, column=0, columnspan=5,
                            sticky="w", padx=4, pady=(0, 4))
            row_idx += 1
            return row_idx

        # Capability sub-blocks within the tier. TTS is intentionally
        # absent — TTS providers live in the dedicated TTS tab.
        for category, header_key in (("llm", "tool.router.subhead_llm"),
                                     ("asr", "tool.router.subhead_asr")):
            entries = tier_buckets.get(category, [])
            if not entries:
                continue
            pill_style = self._PILL_STYLE.get(category, {})
            sub_head = tk.Frame(parent, bg="#f6f7fa")
            sub_head.grid(row=row_idx, column=0, columnspan=5,
                          sticky="ew", padx=2, pady=(4, 2))
            tk.Label(sub_head, text=" " + pill_style.get("text", "?") + " ",
                     bg=pill_style.get("bg", "#eee"),
                     fg=pill_style.get("fg", "#333"),
                     font=("", 8, "bold"), padx=4, pady=1,
                     ).pack(side="left", padx=(2, 6))
            tk.Label(sub_head, text=tr(header_key),
                     font=("", 9, "bold"), bg="#f6f7fa", fg="#334",
                     ).pack(side="left", pady=2)
            row_idx += 1
            for name, cfg in entries:
                row_idx = self._build_provider_row(
                    parent, row_idx, name, cfg, category)
        return row_idx

    def _open_local_model_manager(self):
        """Spawn a Toplevel hosting the Local Model Manager. Opens fresh
        each click (no singleton tracking) — matches the rest of the
        Console's modal-style buttons.
        """
        from tools.models.manager_window import ModelManagerApp
        win = tk.Toplevel(self.master)
        ModelManagerApp(win)

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
        """Rebuild only the Routing tab. Used by aistack-pane handlers so
        their URL Entry / Test button / status label keep their state and
        focus while the routing rows pick up the new aistack model cache.
        """
        for w in self.tab_routing.winfo_children():
            w.destroy()
        self._build_routing_tab()

    def _rebuild_provider_tabs(self):
        """Rebuild Routing + Embedded + Cloud + aistack + TTS tabs in
        place. Used after edit dialogs save (provider's models / key /
        enable state may all have changed and ripple into the routing
        matrix's options or the TTS card status lines).
        """
        for tab, builder in (
            (self.tab_routing,  self._build_routing_tab),
            (self.tab_embedded, self._build_embedded_tab),
            (self.tab_cloud,    self._build_cloud_tab),
            (self.tab_aistack,  self._build_aistack_tab),
            (self.tab_tts,      self._build_tts_tab),
        ):
            for w in tab.winfo_children():
                w.destroy()
            builder()

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

        # Local gateways (e.g. aistack) use auth_required=False — they have no
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
            # Hint text varies per local provider type: aistack runs as a
            # local HTTP gateway, llama_cpp runs in-process from local GGUF
            # files. The legacy single-Ollama hint was misleading once we
            # had two flavors.
            if cfg.get("type") == "llama_cpp":
                hint_key = "tool.router.local_provider_hint_llama_cpp"
            else:
                hint_key = "tool.router.local_provider_hint"
            tk.Label(dlg, text=tr(hint_key),
                     fg="#666", anchor="w", justify="left",
                     wraplength=680).grid(
                row=r, column=0, columnspan=4, padx=12, pady=(12, 6), sticky="w")
            key_var = tk.StringVar(value="local")
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
        if is_local and cfg.get("type") == "llama_cpp":
            # In-process provider — there's no HTTP service to health-check.
            # The useful action here is "open the dir where I should drop
            # GGUFs" since that's the entire setup flow.
            def _open_models_dir():
                from core.models.registry import reveal_in_explorer
                from core.paths import cache_subdir
                reveal_in_explorer(cache_subdir("llama"))
            tk.Button(btn_col, text=tr("tool.router.btn_open_llama_dir"),
                      command=_open_models_dir, width=18).pack(pady=2, fill="x")
        elif is_local:
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
                    models = _oc.list_models("local", base)
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
            self._rebuild_provider_tabs()
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
                elif ptype == "llama_cpp":
                    # Embedded LLM — "models" are *.gguf files in
                    # <models>/llama/. No network call; the model manager
                    # window is responsible for downloads.
                    from core.ai.providers import llama_cpp as _lc
                    models = _lc.list_models()
                elif ptype == "openai_compatible":
                    if not new_url:
                        raise RuntimeError(tr("tool.router.error_no_base_url"))
                    if is_local_pick:
                        # Local gateway (aistack) publishes per-entry
                        # `capabilities` so the LLM picker can filter out
                        # asr/tts entries that would otherwise pollute the list.
                        from core.ai.providers import aistack as _aistack
                        # Strip the OpenAI-style "/v1" suffix from base_url so
                        # the helper can issue GET {base}/v1/models cleanly.
                        gateway_base = new_url.rstrip("/")
                        if gateway_base.endswith("/v1"):
                            gateway_base = gateway_base[:-3]
                        models = [
                            mid for mid, caps in
                            _aistack.list_models_with_capabilities(gateway_base)
                            if "llm" in caps
                        ]
                    else:
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
            self._rebuild_provider_tabs()
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
        if is_local and not is_asr and name == "edge_tts":
            # Microsoft Edge online TTS — no key, curated voice picker.
            self._open_edge_tts_edit_dialog(name, cfg)
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
            self._rebuild_provider_tabs()
            dlg.destroy()

        btn_row = tk.Frame(dlg)
        btn_row.grid(row=5, column=0, columnspan=4, pady=14)
        tk.Button(btn_row, text=tr("tool.router.btn_save"), command=save,
                  width=10).pack(side="left", padx=10)
        tk.Button(btn_row, text=tr("tool.router.btn_cancel"), command=dlg.destroy,
                  width=10).pack(side="left")

    def _open_local_asr_edit_dialog(self, name: str, cfg: dict):
        """Edit dialog for the embedded faster-whisper provider.

        Model selection lives in the Provider Routing tab (per-task pick
        from installed model directories) — this dialog only exposes the
        runtime knobs that apply globally to every dispatch: device,
        compute precision, word-timestamp emission.
        """
        display_name = cfg.get("name", name)
        dlg = tk.Toplevel(self.master)
        dlg.title(tr("tool.router.edit_dialog_title", name=display_name))
        dlg.geometry("620x300")
        dlg.resizable(True, True)
        dlg.grab_set()

        tk.Label(dlg, text=tr("tool.router.local_asr_hint"),
                 fg="#666", anchor="w", justify="left",
                 wraplength=580).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="w")

        DEVICE_OPTIONS  = ["auto", "cpu", "cuda"]
        COMPUTE_OPTIONS = ["auto", "int8", "int8_float16", "float16", "float32"]

        # cfg keys mirror config._DEFAULT_ASR_PROVIDERS["faster_whisper"]:
        #   provider = device hint, compute_type = quant, word_timestamps.
        device_var   = tk.StringVar(value=cfg.get("provider", "auto"))
        compute_var  = tk.StringVar(value=cfg.get("compute_type", "auto"))
        words_var    = tk.BooleanVar(value=bool(cfg.get("word_timestamps", False)))

        def _combo_row(r, label_key, var, values):
            tk.Label(dlg, text=tr(label_key), anchor="e", width=18).grid(
                row=r, column=0, padx=10, pady=6, sticky="e")
            ttk.Combobox(dlg, textvariable=var, values=values,
                         state="readonly", width=24).grid(
                row=r, column=1, padx=4, pady=6, sticky="w")

        _combo_row(1, "tool.router.label_fw_device",  device_var,  DEVICE_OPTIONS)
        _combo_row(2, "tool.router.label_fw_compute", compute_var, COMPUTE_OPTIONS)

        ttk.Checkbutton(
            dlg, text=tr("tool.router.label_fw_word_timestamps"),
            variable=words_var,
        ).grid(row=3, column=1, padx=4, pady=8, sticky="w")

        def save():
            router.update_asr_provider(
                name,
                provider=device_var.get(),
                compute_type=compute_var.get(),
                word_timestamps=bool(words_var.get()),
            )
            messagebox.showinfo(tr("tool.router.saved_title"),
                                tr("tool.router.saved_config_msg", name=display_name),
                                parent=dlg)
            self._rebuild_provider_tabs()
            dlg.destroy()

        btn_row = tk.Frame(dlg)
        btn_row.grid(row=4, column=0, columnspan=2, pady=18)
        tk.Button(btn_row, text=tr("tool.router.btn_save"), command=save,
                  width=10).pack(side="left", padx=10)
        tk.Button(btn_row, text=tr("tool.router.btn_cancel"), command=dlg.destroy,
                  width=10).pack(side="left")

    def _open_edge_tts_edit_dialog(self, name: str, cfg: dict):
        """Edit dialog for Microsoft Edge Read-Aloud TTS.

        No API key. Voice combobox lists curated POPULAR_VOICES (CN + EN
        common ones); users can also type any other Edge voice ID by
        editing the field directly. Speed via slider (mapped to edge-tts
        rate '+N%' string), pitch and volume as advanced text fields.
        """
        from core.ai.providers import edge_tts as _edge

        display_name = cfg.get("name", name)
        dlg = tk.Toplevel(self.master)
        dlg.title(tr("tool.router.edit_dialog_title", name=display_name))
        dlg.geometry("640x340")
        dlg.resizable(True, True)
        dlg.grab_set()

        tk.Label(dlg, text=tr("tool.router.edge_tts_hint"),
                 fg="#666", anchor="w", justify="left",
                 wraplength=600).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="w")

        voices = _edge.list_popular_voices()
        voice_var  = tk.StringVar(value=cfg.get("voice", _edge.DEFAULT_VOICE))
        speed_var  = tk.StringVar(value=str(cfg.get("speed", 1.0)))
        pitch_var  = tk.StringVar(value=str(cfg.get("pitch", "+0Hz")))
        volume_var = tk.StringVar(value=str(cfg.get("volume", "+0%")))

        def _row(r, label_key, var, values=None, width=32):
            tk.Label(dlg, text=tr(label_key), anchor="e", width=14).grid(
                row=r, column=0, padx=10, pady=6, sticky="e")
            if values:
                cb = ttk.Combobox(dlg, textvariable=var, values=values,
                                  width=width)
                cb.grid(row=r, column=1, padx=4, pady=6, sticky="w")
            else:
                tk.Entry(dlg, textvariable=var, width=width).grid(
                    row=r, column=1, padx=4, pady=6, sticky="w")

        _row(1, "tool.router.label_edge_voice",  voice_var, voices)
        _row(2, "tool.router.label_tts_speed",   speed_var)
        _row(3, "tool.router.label_edge_pitch",  pitch_var)
        _row(4, "tool.router.label_edge_volume", volume_var)

        def save():
            try:
                speed = float(speed_var.get().strip())
                if not (0.3 <= speed <= 3.0):
                    raise ValueError(tr("tool.router.tts_speed_range_hint"))
            except ValueError as e:
                messagebox.showerror(tr("dialog.common.error"), str(e), parent=dlg)
                return
            v = voice_var.get().strip()
            if not v:
                messagebox.showerror(tr("dialog.common.error"),
                                      tr("tool.router.error_edge_voice_empty"),
                                      parent=dlg)
                return
            router.update_tts_provider(
                name,
                voice=v,
                speed=speed,
                pitch=pitch_var.get().strip() or "+0Hz",
                volume=volume_var.get().strip() or "+0%",
            )
            messagebox.showinfo(
                tr("tool.router.saved_title"),
                tr("tool.router.saved_config_msg", name=display_name),
                parent=dlg)
            self._rebuild_provider_tabs()
            dlg.destroy()

        btn_row = tk.Frame(dlg)
        btn_row.grid(row=5, column=0, columnspan=2, pady=14)
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
