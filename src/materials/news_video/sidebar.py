"""News-video material sidebar — slot-abstracted tree view (ADR-0005).

This panel is the rendering layer for ONE news_video instance. It
delegates ALL data access and business actions to NewsVideoModel and
listens for change notifications to refresh.

Visual shape (state-2 mockup the user signed off on):

    ▼  📺  <instance_id>  ·  新闻视频
       │
       ├─ ✗  源视频              [+ 添加源视频]
       │
       ├─ 🔒 新闻背景 (AI)        (待源视频就绪)
       │
       ├─ ✗  字幕                [+ 生成字幕]
       │   ├─ ✓ source (zh): zh.srt   [↻] [+ 分析]
       │   │   └─ 📑 标题与章节
       │   ...

Every slot row uses the same uniform layout (status icon + label +
summary + primary action button). Subtitles is the only slot that
adds an expanded body for per-language sub-rows.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

from i18n import tr
from materials.news_video.model import (
    NewsVideoModel,
    SLOT_SOURCE, SLOT_NEWS_CONTEXT, SLOT_SUBTITLES,
)

if TYPE_CHECKING:
    from VideoCraftHub import VideoCraftHub


# ── Visual tokens ────────────────────────────────────────────────────────────

BG = "#f5f5f5"
ROW_BG = BG
ICON_OK = "✓"
ICON_MISSING = "✗"
ICON_LOCKED = "🔒"
INDENT_PX = 12


# ── The panel ────────────────────────────────────────────────────────────────

class NewsVideoSidebar:
    """View for one NewsVideoModel instance. Builds an indented tree of
    slot rows; refresh is driven by model subscription."""

    def __init__(self, parent: tk.Frame, model: NewsVideoModel,
                 hub: "VideoCraftHub") -> None:
        self.parent = parent
        self.model = model
        self.hub = hub

        self._body: tk.Frame | None = None
        self._build()
        self.model.subscribe(self._on_model_change)

    # ── Build / refresh ───────────────────────────────────────────────────

    def _build(self) -> None:
        # Instance header — anchors the tree visually.
        header = tk.Frame(self.parent, bg=BG)
        header.pack(fill="x", padx=2, pady=(4, 2))
        tk.Label(
            header,
            text=f"▼  📺  {self.model.instance_id}  ·  {tr('material.news_video')}",
            font=("", 10, "bold"), bg=BG, fg="#333", anchor="w",
        ).pack(side="left", padx=2)

        # Body — indented container. Slots live here.
        self._body = tk.Frame(self.parent, bg=BG)
        self._body.pack(fill="both", expand=True, padx=(INDENT_PX, 2))
        self._render_slots()

    def _render_slots(self) -> None:
        if self._body is None:
            return
        # Wipe and rebuild — cheap and avoids stale state across refreshes.
        for child in self._body.winfo_children():
            child.destroy()

        states = self.model.slot_readiness()
        for slot_id in (SLOT_SOURCE, SLOT_NEWS_CONTEXT, SLOT_SUBTITLES):
            state = states[slot_id]
            self._render_slot(slot_id, state)

    def _on_model_change(self) -> None:
        # Tk widgets created off the main thread will crash; route through
        # `after(0, ...)` so workers can call model._notify() safely.
        try:
            self.parent.after(0, self._render_slots)
        except Exception:
            pass

    # ── Slot rendering ────────────────────────────────────────────────────

    def _render_slot(self, slot_id: str, state) -> None:
        """One uniform slot row. Layout:
          [icon] [name]  [summary text below name]  [primary action button on right]
        Subtitles adds an expanded body below the row.
        """
        row = tk.Frame(self._body, bg=ROW_BG)
        row.pack(fill="x", pady=(4, 2))

        # Status icon
        icon = self._icon_for_state(state)
        icon_color = self._icon_color_for_state(state)
        tk.Label(row, text=icon, bg=ROW_BG, fg=icon_color, font=("", 10),
                 width=2).pack(side="left")

        # Name + summary stacked vertically
        text_col = tk.Frame(row, bg=ROW_BG)
        text_col.pack(side="left", fill="x", expand=True)
        tk.Label(text_col, text=self._slot_label(slot_id),
                 bg=ROW_BG, fg="#333", font=("", 9, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(text_col, text=state.summary,
                 bg=ROW_BG, fg=self._summary_color(state),
                 font=("", 9), anchor="w", wraplength=240, justify="left",
                 ).pack(fill="x")

        # Primary action button on the right (skipped for locked slots)
        if not state.is_locked:
            btn = self._slot_primary_button(slot_id, state)
            if btn:
                btn.pack(in_=row, side="right", padx=2)

        # Preview-click binding on the name row (where applicable)
        if not state.is_locked and self._slot_has_preview(slot_id):
            for w in (text_col,) + tuple(text_col.winfo_children()):
                w.bind("<Button-1>", lambda _e, sid=slot_id:
                       self._preview_slot(sid))
                w.configure(cursor="hand2")

        # Subtitle slot adds expanded per-language rows below the header row
        if slot_id == SLOT_SUBTITLES and not state.is_locked:
            self._render_subtitles_expanded()

    def _icon_for_state(self, state) -> str:
        if state.is_locked:
            return ICON_LOCKED
        return ICON_OK if state.is_filled else ICON_MISSING

    def _icon_color_for_state(self, state) -> str:
        if state.is_locked:
            return "#999"
        return "#222" if state.is_filled else "#c00"

    def _summary_color(self, state) -> str:
        return "#999" if state.is_locked else "#666"

    def _slot_label(self, slot_id: str) -> str:
        return {
            SLOT_SOURCE: tr("hub.sidebar.source.title"),
            SLOT_NEWS_CONTEXT: tr("hub.sidebar.news_context.title"),
            SLOT_SUBTITLES: tr("hub.sidebar.subtitles.title"),
        }[slot_id]

    def _slot_has_preview(self, slot_id: str) -> bool:
        # Source / news_context support click-to-preview; subtitles uses
        # per-language sub-rows for preview.
        return slot_id in (SLOT_SOURCE, SLOT_NEWS_CONTEXT)

    def _preview_slot(self, slot_id: str) -> None:
        if slot_id == SLOT_SOURCE and self.model.has_source_video():
            self.hub.show_source_preview()
        elif slot_id == SLOT_NEWS_CONTEXT and self.model.has_source_video():
            self.hub.show_news_context_preview()

    def _slot_primary_button(self, slot_id: str, state) -> tk.Button | None:
        if slot_id == SLOT_SOURCE:
            label = tr("hub.button.modify") if state.is_filled \
                else tr("hub.button.add_source_video")
            return tk.Button(self._body, text=label, relief="flat",
                              bg="#e8e8e8", command=self._action_source_button)
        if slot_id == SLOT_NEWS_CONTEXT:
            # Preview opens the editable pane; no separate button.
            return None
        if slot_id == SLOT_SUBTITLES:
            label = (tr("hub.button.add_translation") if state.is_filled
                     else tr("hub.button.add_subtitles"))
            return tk.Button(self._body, text=label, relief="flat",
                              bg="#e8e8e8", command=self._action_subtitles_primary)
        return None

    # ── Subtitles expanded body (per-language rows) ───────────────────────

    def _render_subtitles_expanded(self) -> None:
        langs = self.model.list_subtitle_languages()
        if not langs:
            return
        from core import lang_names

        box = tk.Frame(self._body, bg=ROW_BG)
        box.pack(fill="x", padx=(INDENT_PX, 0))

        source_lang = self.model.source_language()
        for lang in langs:
            check = self.model.check_subtitle(lang, reference_lang_iso=source_lang)

            if check.hard_count > 0:
                row_icon, row_color = ICON_MISSING, "#c00"
                badge = tr("hub.subtitle.badge_hard_count", n=check.hard_count)
            elif check.fixable_count > 0:
                row_icon, row_color = "⚠", "#a60"
                badge = ""
            else:
                row_icon, row_color = ICON_OK, "#222"
                badge = ""

            try:
                lang_label = lang_names.friendly_name(lang, "zh")
            except Exception:
                lang_label = lang
            role = (tr("hub.subtitle.role_source") if lang == source_lang
                    else tr("hub.subtitle.role_translated"))

            row = tk.Frame(box, bg=ROW_BG)
            row.pack(fill="x", pady=1)
            icon_lbl = tk.Label(row, text=row_icon, bg=ROW_BG, fg=row_color,
                                 font=("", 9), width=2)
            icon_lbl.pack(side="left")
            text_lbl = tk.Label(
                row, text=f"{role} ({lang_label}): {lang}.srt{badge}",
                bg=ROW_BG, fg=row_color, font=("", 9), anchor="w")
            text_lbl.pack(side="left", fill="x", expand=True)
            for w in (row, icon_lbl, text_lbl):
                w.bind("<Button-1>", lambda _e, l=lang:
                       self.hub.show_subtitle_preview(self.model.subtitle_path(l), l))
                w.configure(cursor="hand2")

            # Right-aligned action buttons: [+ analysis] [↻ regen] [🔧 fix]
            if check.hard_count == 0 and check.fixable_count > 0:
                tk.Button(row, text=tr("hub.subtitle.quick_fix_btn",
                                        n=check.fixable_count),
                          relief="flat", bg="#fff3cd", fg="#856404",
                          font=("", 8),
                          command=lambda l=lang: self._action_quick_fix(l),
                          ).pack(side="right", padx=2)
            is_source_row = (lang == source_lang)
            tk.Button(row, text="↻", relief="flat", bg="#e8e8e8",
                      font=("", 9), cursor="hand2",
                      command=lambda l=lang, s=is_source_row:
                          self._action_regenerate_subtitle(l, s),
                      ).pack(side="right", padx=2)
            tk.Button(row, text="+", relief="flat", bg="#e8e8e8",
                      font=("", 9, "bold"), cursor="hand2",
                      command=lambda l=lang, w=row:
                          self._action_analysis_menu(l, w),
                      ).pack(side="right", padx=2)

            # Existing analysis artifacts as further-indented sub-rows
            for art in self.model.list_analysis_artifacts(lang):
                art_row = tk.Frame(box, bg=ROW_BG)
                art_row.pack(fill="x", pady=0)
                tk.Label(art_row, text="     " + art.type.icon, bg=ROW_BG,
                         fg="#555", font=("", 9), anchor="w", width=4,
                         ).pack(side="left")
                tk.Label(art_row, text=tr(f"analysis.kind.{art.type.kind}"),
                         bg=ROW_BG, fg="#333", font=("", 9), anchor="w",
                         ).pack(side="left", fill="x", expand=True)
                for w in (art_row,) + tuple(art_row.winfo_children()):
                    w.bind("<Button-1>",
                           lambda _e, a=art: self.hub.show_analysis_preview(a))
                    w.configure(cursor="hand2")

    # ── Action handlers (delegate to model) ───────────────────────────────

    def _action_source_button(self) -> None:
        """Add (when missing) or Modify (when present)."""
        from materials.news_video.ui.source_add_dialog import show_source_add_dialog
        from materials.news_video.ui.source_prepare_modal import SourcePrepareModal
        from ui.disclaimer_dialog import show_if_needed as show_disclaimer_if_needed
        from core.source_acquire import AcquireError, ERR_CANCELLED
        from core.project_schema import ORIGIN_LINK

        current_meta = self.model.get_source_meta()
        preset = current_meta if self.model.has_source_video() else None
        title = (tr("hub.dialog.source.title_modify") if preset
                 else tr("hub.dialog.source.title_add"))

        src = show_source_add_dialog(self.hub.root, title=title, preset=preset)
        if src is None:
            return

        if src.origin == ORIGIN_LINK:
            if not show_disclaimer_if_needed(self.hub.root):
                return

        modal = SourcePrepareModal(
            self.hub.root, src,
            dest_video_path=self.model.source_video_path,
            dest_meta_path=self.model.source_meta_path,
        )
        try:
            result = modal.run()
        except AcquireError as e:
            if e.category == ERR_CANCELLED:
                return
            messagebox.showerror(
                tr("hub.error.source_prepare_failed"),
                f"{e.message}\n\n{e.details[:400]}" if e.details else e.message,
                parent=self.hub.root,
            )
            return
        except Exception as e:
            messagebox.showerror(tr("hub.error.source_prepare_failed"),
                                  str(e), parent=self.hub.root)
            return

        self.model.commit_source(
            src,
            title=result.title,
            duration_sec=result.duration_sec,
            width=result.width,
            height=result.height,
        )

    def _action_subtitles_primary(self) -> None:
        if self.model.list_subtitle_languages():
            self._action_translate()
        else:
            self._action_asr()

    def _action_asr(self, *, preset_lang_iso: str | None = "ASK") -> None:
        from materials.news_video.ui.subtitles_dialogs import show_asr_dialog
        from materials.news_video.ui.subtitles_progress_modal import SubtitlesProgressModal
        from core.ai.errors import AIError, Kind

        if preset_lang_iso == "ASK":
            choice = show_asr_dialog(self.hub.root)
            if choice is None:
                return
            if choice["mode"] == "import":
                try:
                    self.model.import_subtitle(choice["path"], choice["lang_iso"])
                except OSError as e:
                    messagebox.showerror(tr("hub.error.import_failed"),
                                          str(e), parent=self.hub.root)
                return
            lang_iso = choice["lang_iso"]
        else:
            lang_iso = preset_lang_iso

        def worker(progress_cb, cancel_token):
            return self.model.run_asr(
                source_lang_iso=lang_iso,
                progress_cb=progress_cb, cancel_token=cancel_token)

        modal = SubtitlesProgressModal(
            self.hub.root, worker,
            title=tr("hub.dialog.subtitles_progress.title_asr"))
        try:
            modal.run()
        except AIError as e:
            if e.kind == Kind.CANCELLED:
                return
            messagebox.showerror(tr("hub.error.asr_failed"), str(e),
                                  parent=self.hub.root)
        except FileNotFoundError as e:
            messagebox.showerror(tr("hub.error.source_missing"), str(e),
                                  parent=self.hub.root)
        except Exception as e:
            messagebox.showerror(tr("hub.error.asr_failed"), repr(e),
                                  parent=self.hub.root)

    def _action_translate(self, *, preset_target_iso: str | None = None) -> None:
        from materials.news_video.ui.subtitles_dialogs import show_translate_dialog
        from materials.news_video.ui.subtitles_progress_modal import SubtitlesProgressModal
        from core.ai.errors import AIError, Kind

        src_iso = self.model.source_language()
        if not src_iso:
            messagebox.showerror("VideoCraft", tr("hub.error.no_source_lang"),
                                  parent=self.hub.root)
            return

        if preset_target_iso is None:
            target_iso = show_translate_dialog(
                self.hub.root, src_iso, self.model.translated_languages())
            if target_iso is None:
                return
        else:
            target_iso = preset_target_iso

        def worker(progress_cb, cancel_token):
            return self.model.run_translate(
                target_lang_iso=target_iso,
                progress_cb=progress_cb, cancel_token=cancel_token)

        modal = SubtitlesProgressModal(
            self.hub.root, worker,
            title=tr("hub.dialog.subtitles_progress.title_translate"))
        try:
            modal.run()
        except AIError as e:
            if e.kind == Kind.CANCELLED:
                return
            messagebox.showerror(tr("hub.error.translate_failed"), str(e),
                                  parent=self.hub.root)
        except (ValueError, FileNotFoundError) as e:
            messagebox.showerror(tr("hub.error.translate_failed"), str(e),
                                  parent=self.hub.root)
        except Exception as e:
            messagebox.showerror(tr("hub.error.translate_failed"), repr(e),
                                  parent=self.hub.root)

    def _action_regenerate_subtitle(self, lang_iso: str, is_source: bool) -> None:
        from core import lang_names
        try:
            display = lang_names.friendly_name(lang_iso, "zh")
        except Exception:
            display = lang_iso
        if is_source:
            prompt = tr("hub.subtitle.regenerate.confirm_asr",
                        lang=display, iso=lang_iso)
        else:
            prompt = tr("hub.subtitle.regenerate.confirm_translate",
                        lang=display, iso=lang_iso)
        if not messagebox.askyesno(tr("hub.subtitle.regenerate.title"),
                                     prompt, default="no", parent=self.hub.root):
            return
        if is_source:
            self._action_asr(preset_lang_iso=lang_iso)
        else:
            self._action_translate(preset_target_iso=lang_iso)

    def _action_quick_fix(self, lang_iso: str) -> None:
        srt_path = self.model.subtitle_path(lang_iso)
        try:
            self.model.quick_fix_subtitle(lang_iso)
        except Exception as e:
            messagebox.showerror(tr("hub.error.cleanup_failed"), str(e),
                                  parent=self.hub.root)
            return
        self.hub._refresh_preview_if_match(srt_path)

    def _action_analysis_menu(self, lang_iso: str, anchor: tk.Widget) -> None:
        from core.subtitle_analysis import all_types
        hidden = {"transcript", "chapter_transcript"}
        menu = tk.Menu(self.hub.root, tearoff=0)
        for t in all_types():
            if t.kind in hidden:
                continue
            menu.add_command(
                label="+ " + tr(f"analysis.kind.{t.kind}"),
                command=lambda k=t.kind, l=lang_iso:
                    self._action_invoke_analysis(l, k),
            )
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height()
        menu.tk_popup(x, y)

    def _action_invoke_analysis(self, lang_iso: str, kind: str) -> None:
        from core.ai.errors import AIError, Kind as AIKind
        from materials.news_video.ui.subtitles_progress_modal import SubtitlesProgressModal

        if not self.model.has_subtitle(lang_iso):
            messagebox.showerror("VideoCraft", tr("analysis.error.srt_missing"),
                                  parent=self.hub.root)
            return

        if self.model.has_analysis(lang_iso, kind):
            display = tr(f"analysis.kind.{kind}")
            if not messagebox.askyesno(
                    tr("analysis.confirm_overwrite.title"),
                    tr("analysis.confirm_overwrite.message",
                       kind=display, iso=lang_iso),
                    default="no", parent=self.hub.root):
                return

        def worker(progress_cb, cancel_token):
            return self.model.run_analysis(
                kind, lang_iso,
                progress_cb=progress_cb, cancel_token=cancel_token)

        modal = SubtitlesProgressModal(
            self.hub.root, worker,
            title=tr("analysis.modal.title", kind=tr(f"analysis.kind.{kind}")))
        try:
            modal.run()
        except AIError as e:
            if e.kind == AIKind.CANCELLED:
                return
            messagebox.showerror(tr("analysis.error.failed"), str(e),
                                  parent=self.hub.root)
        except Exception as e:
            messagebox.showerror(tr("analysis.error.failed"), repr(e),
                                  parent=self.hub.root)

    # ── Public hook for hub-side legacy callbacks (transitional) ──────────

    def refresh(self) -> None:
        """Called by hub as a fallback when the model hasn't propagated
        notifications yet (e.g. external file system changes).

        Forwards to _render_slots after letting Tk settle."""
        self._on_model_change()


def render(parent: tk.Frame, hub: "VideoCraftHub") -> NewsVideoSidebar:
    """MaterialType.sidebar_renderer entry point.

    Constructs a NewsVideoModel for the DEFAULT instance (slice M
    transitional). Slice P replaces this with a renderer that takes an
    explicit instance_id from the hub iteration over
    project.list_material_instances("news_video").
    """
    model = NewsVideoModel(hub.project)
    return NewsVideoSidebar(parent, model, hub)
