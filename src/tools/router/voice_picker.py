"""VoicePickerDialog — reusable TTS voice picker.

Consumers (text2video, dialogue tool, AI Console TTS tab) call:

    from tools.router.voice_picker import VoicePickerDialog
    voice = VoicePickerDialog.ask(parent,
                                  initial_voice_id="zh-CN-YunxiNeural")

Returns a TTSVoice instance or None if the user cancelled.

Layout:
    Filter row    — provider / language / gender / search + refresh
    Treeview      — voice list (provider | display | lang | gender | tags)
    Selection bar — currently-selected voice + Preview button
    Manual input  — collapsible row for power users to paste a voice ID
                    that isn't (or doesn't need to be) in any catalog
                    (e.g. fish.audio's 32-char hex IDs)
    OK / Cancel

Preview uses ffplay (ships with our ffmpeg toolchain). When ffplay isn't
on PATH the button is disabled with a tooltip explaining why.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import ttk

from i18n import tr
from core import ai
from core.ai.tts_voice import (
    TTSVoice, get_catalog, get_catalog_meta, find_voice,
)


# Providers the picker offers in its filter dropdown / manual-input
# combobox. Order matters — first one wins as default. Adding a new TTS
# provider means adding it here AND implementing fetch_voice_catalog()
# in its provider module.
KNOWN_TTS_PROVIDERS: tuple[str, ...] = ("edge_tts", "fish_audio", "aistack")

_HAS_FFPLAY = shutil.which("ffplay") is not None

# Sample text used by the Preview button. Picked by voice's BCP-47
# locale prefix — Chinese voices get the Chinese line, everything else
# the English line. Two locales is enough for now; expand when we hit
# Japanese / Korean voices in user reports.
_PREVIEW_SAMPLES: dict[str, str] = {
    "zh": "你好,这是一段试听样本,用来确认音色是否符合预期。",
    "en": "Hello, this is a preview sample so you can hear how the voice sounds.",
}


def _preview_text_for(language: str) -> str:
    if language.lower().startswith("zh"):
        return _PREVIEW_SAMPLES["zh"]
    return _PREVIEW_SAMPLES["en"]


# ── VoiceSlot ─────────────────────────────────────────────────────────────────

class VoiceSlot(tk.Frame):
    """Inline widget combining a [Pick voice…] button with a label that
    shows the current selection. Owns its TTSVoice state.

    Used at TTS use sites:
      - text2video single mode (one slot per synthesis)
      - text2video multi mode (one slot per dialog role)
      - composer toolbar (project-wide voice)

    Example:
        slot = VoiceSlot(parent, on_change=lambda v: project.save())
        slot.pack(side="left")
        slot.set_voice(TTSVoice(...))    # programmatic preselect
        v = slot.voice                   # current pick (or None)
    """

    def __init__(self, parent, *,
                 on_change=None,
                 label_width: int = 38,
                 ):
        super().__init__(parent)
        self.voice: TTSVoice | None = None
        self._on_change = on_change

        self._label_var = tk.StringVar(value=tr("tool.tts.no_voice_picked"))
        tk.Button(self, text=tr("tool.tts.btn_pick_voice"),
                  command=self._on_pick).pack(side="left", padx=(0, 6))
        self._label = tk.Label(self, textvariable=self._label_var,
                               anchor="w", width=label_width, fg="#888",
                               font=("", 9))
        self._label.pack(side="left", fill="x", expand=True)

    def _on_pick(self):
        v = VoicePickerDialog.ask(
            self,
            initial_voice_id=self.voice.voice_id if self.voice else "",
            initial_provider=self.voice.provider if self.voice else None,
        )
        if v is None:
            return
        self.set_voice(v)

    def set_voice(self, voice: TTSVoice | None):
        self.voice = voice
        if voice is None:
            self._label_var.set(tr("tool.tts.no_voice_picked"))
            self._label.configure(fg="#888")
        else:
            label_bits = []
            if voice.display_name:
                label_bits.append(voice.display_name)
            label_bits.append(voice.voice_id)
            label_bits.append(f"({voice.provider})")
            self._label_var.set(" · ".join(label_bits))
            self._label.configure(fg="#222")
        if self._on_change:
            self._on_change(voice)

    def set_from_ids(self, provider: str, voice_id: str):
        """Restore from persisted (provider, voice_id) pair. Looks up
        catalog metadata when available; falls back to a minimal
        TTSVoice when the cached catalog doesn't include this voice
        (cache stale, manual ID, etc.).
        """
        if not provider and not voice_id:
            self.set_voice(None)
            return
        from core.ai.tts_voice import find_voice
        v = find_voice(provider, voice_id) or TTSVoice(
            provider=provider, voice_id=voice_id,
            display_name=voice_id, language="", gender="", tags=(),
        )
        self.set_voice(v)


class VoicePickerDialog:
    @classmethod
    def ask(cls, parent: tk.Misc, *,
            initial_voice_id: str = "",
            initial_provider: str | None = None,
            lock_provider: bool = False,
            allowed_providers: tuple[str, ...] | None = None,
            title: str | None = None,
            ) -> TTSVoice | None:
        """Modal voice picker. Blocks until user selects or cancels.

        Args:
            initial_voice_id:   If set + present in any cached catalog,
                                that row is preselected.
            initial_provider:   Sets which provider's catalog the picker
                                opens to. The user can still switch via
                                the provider dropdown unless lock_provider
                                is True.
            lock_provider:      When True, disables the provider dropdown
                                and pins the manual-input dropdown to the
                                same provider. Used by the TTS tab's
                                "Browse <provider> voices" affordance.
            allowed_providers:  Restrict the provider dropdown to this
                                subset of KNOWN_TTS_PROVIDERS. Default =
                                all known.
        Returns:
            Selected TTSVoice or None on cancel.
        """
        dlg = cls(parent,
                  initial_voice_id=initial_voice_id,
                  initial_provider=initial_provider,
                  lock_provider=lock_provider,
                  allowed_providers=allowed_providers,
                  title=title)
        parent.wait_window(dlg.top)
        return dlg.result

    def __init__(self, parent, *,
                 initial_voice_id: str,
                 initial_provider: str | None,
                 lock_provider: bool,
                 allowed_providers: tuple[str, ...] | None,
                 title: str | None):
        self.parent = parent
        self.result: TTSVoice | None = None

        self._initial_voice_id = initial_voice_id or ""
        self._initial_provider = initial_provider
        self._provider_lock = initial_provider if lock_provider else None
        self._allowed_providers = tuple(allowed_providers
                                        or KNOWN_TTS_PROVIDERS)

        # Loaded voices for the currently-selected provider (or all
        # providers when filter == "all"). Filtered subset is what's
        # displayed in the Treeview.
        self._all_voices: list[TTSVoice] = []
        self._visible_voices: list[TTSVoice] = []

        # Preview state — ffplay subprocess + temp mp3 path. Cleaned up
        # on stop / dialog close.
        self._preview_proc: subprocess.Popen | None = None
        self._preview_temp_path: str | None = None
        self._preview_thread: threading.Thread | None = None

        self.top = tk.Toplevel(parent)
        self.top.title(title or tr("tool.voice_picker.title"))
        self.top.geometry("820x600")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._build()
        self._reload_catalog(preselect_id=self._initial_voice_id)

    # ── Layout ────────────────────────────────────────────────────────────

    def _build(self):
        outer = tk.Frame(self.top, padx=10, pady=10)
        outer.pack(fill="both", expand=True)

        # ── Filter row ──
        filt = tk.LabelFrame(outer, text=tr("tool.voice_picker.filter_section"),
                             padx=8, pady=6)
        filt.pack(fill="x")

        tk.Label(filt, text=tr("tool.voice_picker.filter_provider"),
                 ).grid(row=0, column=0, sticky="e", padx=(0, 4), pady=2)
        provider_options = list(self._allowed_providers)
        if len(self._allowed_providers) > 1 and self._provider_lock is None:
            provider_options = [tr("tool.voice_picker.filter_all"),
                                *self._allowed_providers]
        init_provider = (self._initial_provider
                         or self._allowed_providers[0])
        self._provider_var = tk.StringVar(value=init_provider)
        prov_cb = ttk.Combobox(filt, textvariable=self._provider_var,
                               values=provider_options, state="readonly",
                               width=14)
        prov_cb.grid(row=0, column=1, sticky="w", padx=(0, 12))
        prov_cb.bind("<<ComboboxSelected>>",
                     lambda _e: self._reload_catalog())
        if self._provider_lock is not None:
            prov_cb.configure(state="disabled")

        tk.Label(filt, text=tr("tool.voice_picker.filter_lang"),
                 ).grid(row=0, column=2, sticky="e", padx=(0, 4), pady=2)
        self._lang_var = tk.StringVar(value=tr("tool.voice_picker.filter_all"))
        self._lang_cb = ttk.Combobox(filt, textvariable=self._lang_var,
                                     values=[tr("tool.voice_picker.filter_all")],
                                     state="readonly", width=12)
        self._lang_cb.grid(row=0, column=3, sticky="w", padx=(0, 12))
        self._lang_cb.bind("<<ComboboxSelected>>",
                           lambda _e: self._apply_filters())

        tk.Label(filt, text=tr("tool.voice_picker.filter_gender"),
                 ).grid(row=0, column=4, sticky="e", padx=(0, 4), pady=2)
        self._gender_var = tk.StringVar(value=tr("tool.voice_picker.filter_all"))
        gender_options = [tr("tool.voice_picker.filter_all"),
                          tr("tool.voice_picker.gender_F"),
                          tr("tool.voice_picker.gender_M")]
        gen_cb = ttk.Combobox(filt, textvariable=self._gender_var,
                              values=gender_options, state="readonly", width=8)
        gen_cb.grid(row=0, column=5, sticky="w", padx=(0, 12))
        gen_cb.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())

        tk.Label(filt, text=tr("tool.voice_picker.search_label"),
                 ).grid(row=1, column=0, sticky="e", padx=(0, 4), pady=(6, 0))
        self._search_var = tk.StringVar(value="")
        search_entry = tk.Entry(filt, textvariable=self._search_var, width=32)
        search_entry.grid(row=1, column=1, columnspan=3, sticky="we",
                          padx=(0, 12), pady=(6, 0))
        self._search_var.trace_add("write", lambda *_: self._apply_filters())

        self._refresh_btn = tk.Button(
            filt, text=tr("tool.voice_picker.btn_refresh"),
            command=self._on_refresh, width=14,
        )
        self._refresh_btn.grid(row=1, column=4, columnspan=2, sticky="w",
                               padx=(0, 4), pady=(6, 0))

        # ── Voice table ──
        table_wrap = tk.Frame(outer)
        table_wrap.pack(fill="both", expand=True, pady=(8, 6))

        cols = ("display", "voice_id", "lang", "gender", "tags")
        self._tree = ttk.Treeview(
            table_wrap, columns=cols, show="headings", height=14,
            selectmode="browse",
        )
        for col, key, width, anchor in (
            ("display",  "tool.voice_picker.col_display",  240, "w"),
            ("voice_id", "tool.voice_picker.col_voice_id", 200, "w"),
            ("lang",     "tool.voice_picker.col_lang",      70, "w"),
            ("gender",   "tool.voice_picker.col_gender",    50, "center"),
            ("tags",     "tool.voice_picker.col_tags",     180, "w"),
        ):
            self._tree.heading(col, text=tr(key))
            self._tree.column(col, width=width, anchor=anchor)
        vsb = ttk.Scrollbar(table_wrap, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select_row())
        self._tree.bind("<Double-1>", lambda _e: self._on_ok())

        # Empty / status line under table
        self._status_var = tk.StringVar(value="")
        tk.Label(outer, textvariable=self._status_var, fg="#666",
                 anchor="w").pack(fill="x")

        # ── Selection bar ──
        sel = tk.Frame(outer)
        sel.pack(fill="x", pady=(8, 4))
        tk.Label(sel, text=tr("tool.voice_picker.selected_label"),
                 anchor="e", width=10).pack(side="left")
        self._selected_var = tk.StringVar(value="")
        tk.Label(sel, textvariable=self._selected_var,
                 fg="#222", anchor="w").pack(side="left", padx=(2, 8))

        preview_text = (tr("tool.voice_picker.btn_preview") if _HAS_FFPLAY
                        else tr("tool.voice_picker.btn_preview_unavailable"))
        self._preview_btn = tk.Button(
            sel, text=preview_text, command=self._on_preview, width=12,
        )
        self._preview_btn.pack(side="right", padx=4)
        if not _HAS_FFPLAY:
            self._preview_btn.configure(state="disabled")

        # ── Manual input (collapsible) ──
        manual_frame = tk.LabelFrame(
            outer, text=tr("tool.voice_picker.manual_section"),
            padx=8, pady=6,
        )
        manual_frame.pack(fill="x", pady=(8, 0))
        tk.Label(manual_frame, text=tr("tool.voice_picker.manual_hint"),
                 fg="#666", anchor="w", justify="left", wraplength=720,
                 ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))
        tk.Label(manual_frame, text=tr("tool.voice_picker.manual_provider"),
                 ).grid(row=1, column=0, sticky="e", padx=(0, 4))
        self._manual_provider_var = tk.StringVar(
            value=self._provider_lock or self._allowed_providers[0])
        manual_prov_cb = ttk.Combobox(
            manual_frame, textvariable=self._manual_provider_var,
            values=list(self._allowed_providers), state="readonly", width=14,
        )
        manual_prov_cb.grid(row=1, column=1, sticky="w", padx=(0, 12))
        if self._provider_lock is not None:
            manual_prov_cb.configure(state="disabled")
        tk.Label(manual_frame, text=tr("tool.voice_picker.manual_id"),
                 ).grid(row=1, column=2, sticky="e", padx=(0, 4))
        self._manual_id_var = tk.StringVar(value="")
        tk.Entry(manual_frame, textvariable=self._manual_id_var, width=36,
                 ).grid(row=1, column=3, sticky="we", padx=(0, 4))

        # ── OK / Cancel ──
        btns = tk.Frame(outer)
        btns.pack(fill="x", pady=(10, 0))
        tk.Button(btns, text=tr("tool.voice_picker.btn_cancel"),
                  command=self._on_cancel, width=10,
                  ).pack(side="right", padx=(6, 0))
        tk.Button(btns, text=tr("tool.voice_picker.btn_select"),
                  command=self._on_ok, width=10, default="active",
                  ).pack(side="right")

        self.top.bind("<Escape>", lambda _e: self._on_cancel())
        self.top.bind("<Return>", lambda _e: self._on_ok())

    # ── Catalog loading ───────────────────────────────────────────────────

    def _selected_provider_keys(self) -> list[str]:
        """Translate the provider filter Combobox value to provider IDs.
        '所有' / 'All' expands to every allowed provider."""
        v = self._provider_var.get()
        if v == tr("tool.voice_picker.filter_all"):
            return list(self._allowed_providers)
        return [v]

    def _reload_catalog(self, preselect_id: str = ""):
        """Pull voices from currently-selected providers (cached only —
        Refresh button is the explicit network call). Repopulate language
        filter options + table. preselect_id, when given, tries to land
        the cursor on that voice after rebuild.
        """
        self._all_voices = []
        for prov in self._selected_provider_keys():
            self._all_voices.extend(get_catalog(prov))

        # Refresh language options to reflect actually-present locales.
        # Sort by frequency so the top of the dropdown matches what users
        # see most.
        from collections import Counter
        lang_counts = Counter(v.language for v in self._all_voices if v.language)
        sorted_langs = [
            f"{lang}  ({cnt})" for lang, cnt in lang_counts.most_common()
        ]
        opts = [tr("tool.voice_picker.filter_all"), *sorted_langs]
        # Preserve previous selection if still present (user might be
        # mid-filter when refresh triggers).
        cur = self._lang_var.get()
        self._lang_cb.configure(values=opts)
        if cur not in opts:
            self._lang_var.set(opts[0])
        self._apply_filters(preselect_id=preselect_id)

    def _on_refresh(self):
        """Force a network refresh for each currently-visible provider.
        Runs in a thread to keep the UI responsive on slow Edge fetches.
        """
        self._refresh_btn.configure(state="disabled",
                                    text=tr("tool.voice_picker.fetching"))
        self._status_var.set(tr("tool.voice_picker.fetching_status"))
        providers = self._selected_provider_keys()

        def _do():
            for prov in providers:
                try:
                    get_catalog(prov, refresh=True)
                except Exception:
                    pass  # swallow; status line shows count after reload

            def _back():
                self._refresh_btn.configure(
                    state="normal", text=tr("tool.voice_picker.btn_refresh"))
                self._reload_catalog()
                # Status reflects the freshly-fetched counts
                meta_lines = []
                for prov in providers:
                    m = get_catalog_meta(prov)
                    meta_lines.append(
                        tr("tool.voice_picker.refresh_done_one",
                           provider=prov, count=m["count"]))
                self._status_var.set(" · ".join(meta_lines))
            self.top.after(0, _back)
        threading.Thread(target=_do, daemon=True).start()

    # ── Filtering ─────────────────────────────────────────────────────────

    def _apply_filters(self, preselect_id: str = ""):
        lang_pick = self._lang_var.get()
        if lang_pick.startswith(tr("tool.voice_picker.filter_all")):
            lang_filter = ""
        else:
            # Strip the "  (N)" count suffix
            lang_filter = lang_pick.split("  ")[0]

        gender_pick = self._gender_var.get()
        if gender_pick == tr("tool.voice_picker.gender_F"):
            gender_filter = "F"
        elif gender_pick == tr("tool.voice_picker.gender_M"):
            gender_filter = "M"
        else:
            gender_filter = ""

        needle = self._search_var.get().strip().lower()

        out: list[TTSVoice] = []
        for v in self._all_voices:
            if lang_filter and v.language != lang_filter:
                continue
            if gender_filter and v.gender != gender_filter:
                continue
            if needle:
                hay = " ".join((v.display_name, v.voice_id,
                                " ".join(v.tags))).lower()
                if needle not in hay:
                    continue
            out.append(v)

        self._visible_voices = out
        self._tree.delete(*self._tree.get_children())
        for v in out:
            self._tree.insert("", "end", iid=v.voice_id,
                              values=(v.display_name, v.voice_id,
                                      v.language, v.gender,
                                      ", ".join(v.tags[:3])))

        if not out:
            self._status_var.set(tr("tool.voice_picker.no_match"))
        else:
            providers = self._selected_provider_keys()
            metas = [get_catalog_meta(p) for p in providers]
            total = sum(m["count"] for m in metas)
            self._status_var.set(
                tr("tool.voice_picker.list_status",
                   visible=len(out), total=total))

        # Preselect by voice_id (matches Treeview iid since we set it above).
        if preselect_id and preselect_id in self._tree.get_children(""):
            self._tree.selection_set(preselect_id)
            self._tree.see(preselect_id)
            self._on_select_row()
        else:
            # Filter shrunk the list past the previously-selected row —
            # clear the "Selected: …" label so it doesn't lie about
            # what's currently active.
            self._selected_var.set("")

    # ── Selection + preview + final pick ──────────────────────────────────

    def _on_select_row(self):
        sel = self._tree.selection()
        if not sel:
            self._selected_var.set("")
            return
        v = self._voice_by_id(sel[0])
        if v is None:
            return
        self._selected_var.set(f"{v.display_name}  ·  {v.voice_id}")

    def _voice_by_id(self, voice_id: str) -> TTSVoice | None:
        for v in self._visible_voices:
            if v.voice_id == voice_id:
                return v
        return None

    def _current_selection(self) -> TTSVoice | None:
        sel = self._tree.selection()
        if not sel:
            return None
        return self._voice_by_id(sel[0])

    def _on_preview(self):
        """Synthesize a short sample with the selected voice and play
        via ffplay. Spawns the synth in a thread so the click feels
        responsive; the playback subprocess detaches and self-cleans."""
        voice = self._current_selection()
        if voice is None:
            self._status_var.set(tr("tool.voice_picker.preview_no_selection"))
            return
        if not _HAS_FFPLAY:
            return  # button is disabled; defensive

        # Stop any in-flight preview before starting a new one.
        self._stop_preview()

        text = _preview_text_for(voice.language)
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        self._preview_temp_path = tmp.name

        self._preview_btn.configure(state="disabled",
                                    text=tr("tool.voice_picker.btn_synthesizing"))
        self._status_var.set(tr("tool.voice_picker.preview_synth_status",
                                voice=voice.display_name))

        def _do():
            err: Exception | None = None
            try:
                ai.tts(text, self._preview_temp_path,
                       provider=voice.provider,
                       voice_id=voice.voice_id,
                       audio_format="mp3")
            except Exception as e:
                err = e

            def _back():
                if err is not None:
                    self._preview_btn.configure(
                        state="normal",
                        text=tr("tool.voice_picker.btn_preview"))
                    self._status_var.set(
                        tr("tool.voice_picker.preview_failed", err=str(err)[:200]))
                    self._cleanup_preview_temp()
                    return
                self._launch_ffplay(voice)
            self.top.after(0, _back)

        self._preview_thread = threading.Thread(target=_do, daemon=True)
        self._preview_thread.start()

    def _launch_ffplay(self, voice: TTSVoice):
        """ffplay -nodisp -autoexit -loglevel quiet <path>. Detached so
        Tk doesn't block; we poll exit and clean the temp file."""
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            self._preview_proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                 self._preview_temp_path],
                creationflags=creationflags,
            )
        except Exception as e:
            self._status_var.set(tr("tool.voice_picker.preview_failed",
                                    err=str(e)[:200]))
            self._cleanup_preview_temp()
            self._preview_btn.configure(state="normal",
                                        text=tr("tool.voice_picker.btn_preview"))
            return

        self._preview_btn.configure(state="normal",
                                    text=tr("tool.voice_picker.btn_stop"),
                                    command=self._stop_preview)
        self._status_var.set(tr("tool.voice_picker.previewing",
                                voice=voice.display_name))
        self.top.after(300, self._poll_preview)

    def _poll_preview(self):
        """Tk-thread polling — check if ffplay exited so we can reset
        the button and delete the temp file."""
        if self._preview_proc is None:
            return
        if self._preview_proc.poll() is None:
            self.top.after(300, self._poll_preview)
            return
        # Finished playing
        self._preview_proc = None
        self._cleanup_preview_temp()
        self._preview_btn.configure(state="normal",
                                    text=tr("tool.voice_picker.btn_preview"),
                                    command=self._on_preview)
        self._status_var.set("")

    def _stop_preview(self):
        if self._preview_proc is not None:
            try:
                self._preview_proc.terminate()
            except Exception:
                pass
            self._preview_proc = None
        self._cleanup_preview_temp()
        self._preview_btn.configure(state="normal",
                                    text=tr("tool.voice_picker.btn_preview"),
                                    command=self._on_preview)

    def _cleanup_preview_temp(self):
        if self._preview_temp_path and os.path.exists(self._preview_temp_path):
            try:
                os.unlink(self._preview_temp_path)
            except OSError:
                pass
        self._preview_temp_path = None

    def _on_ok(self):
        # Manual input wins when user typed something there. Surfaces a
        # synthetic TTSVoice with empty metadata — caller still gets the
        # provider+voice_id pair it needs to dispatch.
        manual_id = self._manual_id_var.get().strip()
        if manual_id:
            self.result = TTSVoice(
                provider=self._manual_provider_var.get(),
                voice_id=manual_id,
                display_name=manual_id,
                language="", gender="", tags=(),
                description=tr("tool.voice_picker.manual_description"),
            )
            self._close()
            return

        sel = self._current_selection()
        if sel is None:
            self._status_var.set(tr("tool.voice_picker.preview_no_selection"))
            return
        # Try to enrich via find_voice in case display row was a stale
        # snapshot — rare, but harmless.
        enriched = find_voice(sel.provider, sel.voice_id) or sel
        self.result = enriched
        self._close()

    def _on_cancel(self):
        self.result = None
        self._close()

    def _close(self):
        self._stop_preview()
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self.top.destroy()
