"""News-video material sidebar — the structured tree this material type
exposes inside the 素材 tab.

Per ADR-0004, a material plugin owns its sidebar rendering. This module
defines `NewsVideoSidebar`, the panel that paints the news_video
material's slots (source video / news context / subtitles) as a tree
under an instance header.

Slice K.2: section builders, refresh logic, and event handlers all
live here. Hub provides preview routing (show_*_preview, project,
root) via the hub reference passed at construction.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING

from i18n import tr

if TYPE_CHECKING:
    from VideoCraftHub import VideoCraftHub


# ── Helpers (imported from hub for now; targets src/ui/ in a future
#    cleanup once a second material type forces shared-helper extraction)

def _sidebar_separator(parent: tk.Widget) -> None:
    sep = tk.Frame(parent, bg="#d0d0d0", height=1)
    sep.pack(fill="x", padx=4, pady=4)


def _list_subtitle_srts(subtitles_dir: str) -> dict[str, str]:
    if not os.path.isdir(subtitles_dir):
        return {}
    out: dict[str, str] = {}
    try:
        for name in os.listdir(subtitles_dir):
            if not name.lower().endswith(".srt"):
                continue
            stem = name[:-4]
            if 1 < len(stem) <= 8 and all(c.isalpha() or c == "-" for c in stem):
                out[stem] = name
    except OSError:
        pass
    return out


def _fmt_duration(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── The panel ──────────────────────────────────────────────────────────────

class NewsVideoSidebar:
    """One news_video material instance, rendered as a tree under the
    素材 tab. Single-source projects have an implicit instance; the
    panel is always painted regardless of how many slots are filled.
    """

    def __init__(self, parent: tk.Frame, hub: "VideoCraftHub") -> None:
        self.hub = hub
        self.parent = parent
        self._subtitles_snapshot: tuple | None = None
        self._build()

    # ── Accessors that shadow hub state for ergonomic code ────────────────
    @property
    def project(self):
        return self.hub.project

    @property
    def root(self):
        return self.hub.root

    # ── Build: instance header + indented slot body ───────────────────────
    def _build(self) -> None:
        # Instance header row — visually anchors the structural tree.
        header = tk.Frame(self.parent, bg="#f5f5f5")
        header.pack(fill="x", padx=2, pady=(4, 2))
        tk.Label(
            header,
            text=f"▼  📺  {tr('material.news_video')}",
            font=("", 10, "bold"), bg="#f5f5f5", fg="#333", anchor="w",
        ).pack(side="left", padx=2)

        # Indented body — every slot lives under the instance header.
        body = tk.Frame(self.parent, bg="#f5f5f5")
        body.pack(fill="both", expand=True, padx=(12, 2))

        self._source_section = tk.Frame(body, bg="#f5f5f5")
        self._source_section.pack(fill="x", pady=(2, 0))
        self._build_source_section(self._source_section)

        _sidebar_separator(body)

        self._news_context_section = tk.Frame(body, bg="#f5f5f5")
        self._news_context_section.pack(fill="x")
        self._build_news_context_section(self._news_context_section)

        _sidebar_separator(body)

        self._subtitles_section = tk.Frame(body, bg="#f5f5f5")
        self._subtitles_section.pack(fill="both", expand=True, pady=(0, 4))
        self._build_subtitles_section(self._subtitles_section)

        self.refresh()

    def refresh(self) -> None:
        if not hasattr(self, "_source_status_var"):
            return
        self._refresh_source_section()
        self._refresh_news_context_section()
        self._refresh_subtitles_section()

    # ── Source slot ───────────────────────────────────────────────────────

    def _build_source_section(self, parent: tk.Frame) -> None:
        tk.Label(parent, text=tr("hub.sidebar.source.title"),
                 font=("", 9, "bold"), bg="#f5f5f5", fg="#555", anchor="w"
                 ).pack(fill="x", padx=2, pady=(2, 2))

        self._source_status_var = tk.StringVar()
        self._source_status_lbl = tk.Label(
            parent, textvariable=self._source_status_var,
            bg="#f5f5f5", fg="#222", font=("", 9),
            anchor="w", justify="left", wraplength=260,
        )
        self._source_status_lbl.pack(fill="x", padx=4, pady=(0, 2))
        self._source_status_lbl.bind(
            "<Button-1>", lambda _e: self.hub.show_source_preview())

        btn_row = tk.Frame(parent, bg="#f5f5f5")
        btn_row.pack(fill="x", padx=2, pady=(0, 4))
        self._source_primary_btn = tk.Button(
            btn_row, relief="flat", bg="#e8e8e8",
            command=self._on_source_button,
        )
        self._source_primary_btn.pack(side="left")

    def _refresh_source_section(self) -> None:
        if self.project.source_status() == "ready":
            meta = self.project.meta.source
            label = "✓ " + (meta.title or "video.mp4")
            extras = []
            if meta.duration_sec:
                extras.append(_fmt_duration(meta.duration_sec))
            if meta.width and meta.height:
                extras.append(f"{meta.width}x{meta.height}")
            if extras:
                label += "\n   " + " · ".join(extras)
            self._source_status_var.set(label)
            self._source_primary_btn.config(text=tr("hub.button.modify"))
            self._source_status_lbl.configure(cursor="hand2")
        else:
            self._source_status_var.set(tr("hub.status.none"))
            self._source_primary_btn.config(text=tr("hub.button.add_source_video"))
            self._source_status_lbl.configure(cursor="")

    def _on_source_button(self) -> None:
        """Add (when missing) or Modify (when present)."""
        from materials.news_video.ui.source_add_dialog import show_source_add_dialog
        from materials.news_video.ui.source_prepare_modal import SourcePrepareModal
        from ui.disclaimer_dialog import show_if_needed as show_disclaimer_if_needed
        from core.source_acquire import AcquireError, ERR_CANCELLED
        from core.project_schema import ORIGIN_LINK

        current_meta = self.project.meta
        preset = current_meta.source if self.project.source_status() == "ready" else None
        title = tr("hub.dialog.source.title_modify") if preset else tr("hub.dialog.source.title_add")

        src = show_source_add_dialog(self.root, title=title, preset=preset)
        if src is None:
            return

        if src.origin == ORIGIN_LINK:
            if not show_disclaimer_if_needed(self.root):
                return

        modal = SourcePrepareModal(
            self.root, src,
            dest_video_path=self.project.source_video_path,
            dest_meta_path=self.project.source_meta_path,
        )
        try:
            result = modal.run()
        except AcquireError as e:
            if e.category == ERR_CANCELLED:
                return
            messagebox.showerror(
                tr("hub.error.source_prepare_failed"),
                f"{e.message}\n\n{e.details[:400]}" if e.details else e.message,
                parent=self.root,
            )
            return
        except Exception as e:
            messagebox.showerror(tr("hub.error.source_prepare_failed"), str(e), parent=self.root)
            return

        meta = self.project.meta
        meta.source = src
        if result.title:
            meta.source.title = result.title
        if result.duration_sec is not None:
            meta.source.duration_sec = result.duration_sec
        if result.width is not None:
            meta.source.width = result.width
        if result.height is not None:
            meta.source.height = result.height
        self.project.update_meta(meta)
        self.hub._refresh_project_tab()

    # ── News context slot ─────────────────────────────────────────────────

    def _build_news_context_section(self, parent: tk.Frame) -> None:
        tk.Label(parent, text=tr("hub.sidebar.news_context.title"),
                 font=("", 9, "bold"), bg="#f5f5f5", fg="#555",
                 anchor="w",
                 ).pack(fill="x", padx=2, pady=(2, 2))

        self._news_context_status_var = tk.StringVar()
        lbl = tk.Label(
            parent, textvariable=self._news_context_status_var,
            bg="#f5f5f5", fg="#222", font=("", 9),
            anchor="w", justify="left", wraplength=260, cursor="hand2",
        )
        lbl.pack(fill="x", padx=4, pady=(0, 4))
        lbl.bind("<Button-1>", lambda _e: self.hub.show_news_context_preview())
        self._news_context_status_lbl = lbl

    def _refresh_news_context_section(self) -> None:
        if not hasattr(self, "_news_context_status_var"):
            return
        if self.project.source_status() != "ready":
            self._news_context_status_var.set(
                tr("hub.sidebar.news_context.locked"))
            self._news_context_status_lbl.configure(fg="#999", cursor="")
            return
        try:
            from materials.news_video.schema import read_context, SourceContext
            ctx = read_context(self.project.source_dir).to_dict()
            total = len(SourceContext.__dataclass_fields__)
            filled = sum(1 for v in ctx.values()
                         if isinstance(v, str) and v.strip())
        except Exception:
            filled, total = 0, 15
        if filled == 0:
            self._news_context_status_var.set(
                tr("hub.sidebar.news_context.empty"))
        else:
            self._news_context_status_var.set(
                tr("hub.sidebar.news_context.filled",
                   filled=filled, total=total))
        self._news_context_status_lbl.configure(fg="#222", cursor="hand2")

    # ── Subtitles slot ────────────────────────────────────────────────────

    def _build_subtitles_section(self, parent: tk.Frame) -> None:
        tk.Label(parent, text=tr("hub.sidebar.subtitles.title"),
                 font=("", 9, "bold"), bg="#f5f5f5", fg="#555", anchor="w"
                 ).pack(fill="x", padx=2, pady=(2, 2))

        self._subtitles_lang_box = tk.Frame(parent, bg="#f5f5f5")
        self._subtitles_lang_box.pack(fill="x", padx=4, pady=(0, 2))

        btn_row = tk.Frame(parent, bg="#f5f5f5")
        btn_row.pack(fill="x", padx=2, pady=(0, 4))
        self._subtitles_primary_btn = tk.Button(
            btn_row, relief="flat", bg="#e8e8e8",
            command=self._on_subtitles_primary,
        )
        self._subtitles_primary_btn.pack(side="left")

    def _refresh_subtitles_section(self) -> None:
        from core import lang_names
        from core.subtitle_check import check_srt

        snapshot = self._subtitles_section_snapshot()
        if snapshot == self._subtitles_snapshot:
            return
        self._subtitles_snapshot = snapshot

        for child in self._subtitles_lang_box.winfo_children():
            child.destroy()

        srt_files = _list_subtitle_srts(self.project.subtitles_dir)
        meta = self.project.meta.language
        source_ready = self.project.source_status() == "ready"

        if not srt_files:
            tk.Label(self._subtitles_lang_box, text=tr("hub.status.none"),
                     bg="#f5f5f5", fg="#222", font=("", 9),
                     anchor="w"
                     ).pack(fill="x")
            self._subtitles_primary_btn.config(
                text=tr("hub.button.add_subtitles"),
                state="normal" if source_ready else "disabled",
            )
            return

        source_lang = meta.source
        ref_path = (os.path.join(self.project.subtitles_dir, f"{source_lang}.srt")
                    if source_lang else None)

        for lang in sorted(srt_files):
            try:
                lang_label = lang_names.friendly_name(lang, "zh")
            except Exception:
                lang_label = lang
            role = tr("hub.subtitle.role_source") if meta.source == lang else tr("hub.subtitle.role_translated")
            srt_path = os.path.join(self.project.subtitles_dir, f"{lang}.srt")

            ref = ref_path if (lang != source_lang and ref_path
                               and os.path.isfile(ref_path)) else None
            check = check_srt(srt_path, expected_lang_iso=lang,
                              reference_srt_path=ref)

            if check.hard_count > 0:
                icon, color = "✗", "#c00"
                badge = tr("hub.subtitle.badge_hard_count", n=check.hard_count)
            elif check.fixable_count > 0:
                icon, color = "⚠", "#a60"
                badge = ""
            else:
                icon, color = "✓", "#222"
                badge = ""

            row = tk.Frame(self._subtitles_lang_box, bg="#f5f5f5")
            row.pack(fill="x", pady=1)
            icon_lbl = tk.Label(row, text=icon, bg="#f5f5f5", fg=color,
                                font=("", 9), width=2)
            icon_lbl.pack(side="left")
            text_lbl = tk.Label(row, text=f"{role} ({lang_label}): {lang}.srt{badge}",
                                bg="#f5f5f5", fg=color, font=("", 9), anchor="w")
            text_lbl.pack(side="left", fill="x", expand=True)

            for w in (row, icon_lbl, text_lbl):
                w.bind("<Button-1>",
                       lambda _e, p=srt_path, l=lang:
                           self.hub.show_subtitle_preview(p, l))
                w.configure(cursor="hand2")

            if check.hard_count == 0 and check.fixable_count > 0:
                tk.Button(row, text=tr("hub.subtitle.quick_fix_btn", n=check.fixable_count),
                          relief="flat", bg="#fff3cd", fg="#856404",
                          font=("", 8),
                          command=lambda p=srt_path:
                              self._on_quick_fix_subtitle(p),
                          ).pack(side="right", padx=2)
            is_source_row = (lang == source_lang)
            tk.Button(row, text="↻", relief="flat", bg="#e8e8e8",
                      font=("", 9), cursor="hand2",
                      command=lambda l=lang, s=is_source_row:
                          self._on_regenerate_subtitle(l, s),
                      ).pack(side="right", padx=2)
            tk.Button(row, text="+", relief="flat", bg="#e8e8e8",
                      font=("", 9, "bold"), cursor="hand2",
                      command=lambda l=lang, w=row:
                          self._on_subtitle_analysis_menu(l, w),
                      ).pack(side="right", padx=2)

            self._populate_analysis_rows(lang)

        self._subtitles_primary_btn.config(text=tr("hub.button.add_translation"), state="normal")

    def _subtitles_section_snapshot(self) -> tuple:
        result: list = []
        subs_dir = self.project.subtitles_dir
        try:
            for name in os.listdir(subs_dir):
                p = os.path.join(subs_dir, name)
                try:
                    st = os.stat(p)
                    result.append((name, st.st_size, round(st.st_mtime, 1)))
                except OSError:
                    result.append((name, -1, 0))
        except OSError:
            pass
        result.sort()
        src_lang = self.project.meta.language.source or ""
        return (tuple(result), src_lang, self.project.source_status())

    def _populate_analysis_rows(self, lang_iso: str) -> None:
        from core.subtitle_analysis import existing_artifacts
        artifacts = existing_artifacts(self.project.subtitles_dir, lang_iso)
        for art in artifacts:
            row = tk.Frame(self._subtitles_lang_box, bg="#f5f5f5")
            row.pack(fill="x", pady=0)
            tk.Label(row, text="     " + art.type.icon, bg="#f5f5f5",
                     fg="#555", font=("", 9), anchor="w", width=4,
                     ).pack(side="left")
            display = tr(f"analysis.kind.{art.type.kind}")
            tk.Label(row, text=display, bg="#f5f5f5", fg="#333",
                     font=("", 9), anchor="w",
                     ).pack(side="left", fill="x", expand=True)
            for w in (row,) + tuple(row.winfo_children()):
                w.bind("<Button-1>", lambda _e, a=art: self.hub.show_analysis_preview(a))
                w.configure(cursor="hand2")

    def _on_subtitles_primary(self) -> None:
        srt_files = _list_subtitle_srts(self.project.subtitles_dir)
        if not srt_files:
            self._invoke_asr()
        else:
            self._invoke_translate()

    # ── Subtitle pipeline drivers ─────────────────────────────────────────

    def _invoke_asr(self, *, preset_lang_iso: str | None = "ASK") -> None:
        from materials.news_video.ui.subtitles_dialogs import show_asr_dialog
        from materials.news_video.ui.subtitles_progress_modal import SubtitlesProgressModal
        from core.subtitle_pipeline import run_asr
        from core.ai.errors import AIError, Kind

        if preset_lang_iso == "ASK":
            choice = show_asr_dialog(self.root)
            if choice is None:
                return
            if choice["mode"] == "import":
                self._import_subtitle_file(choice["path"], choice["lang_iso"])
                return
            lang_iso = choice["lang_iso"]
        else:
            lang_iso = preset_lang_iso

        def worker(progress_cb, cancel_token):
            return run_asr(
                self.project,
                source_lang_iso=lang_iso,
                progress_cb=progress_cb,
                cancel_token=cancel_token,
            )

        modal = SubtitlesProgressModal(self.root, worker,
                                       title=tr("hub.dialog.subtitles_progress.title_asr"))
        try:
            modal.run()
        except AIError as e:
            if e.kind == Kind.CANCELLED:
                return
            messagebox.showerror(tr("hub.error.asr_failed"), str(e), parent=self.root)
            return
        except FileNotFoundError as e:
            messagebox.showerror(tr("hub.error.source_missing"), str(e), parent=self.root)
            return
        except Exception as e:
            messagebox.showerror(tr("hub.error.asr_failed"), repr(e), parent=self.root)
            return

        self.hub._refresh_project_tab()

    def _invoke_translate(self, *, preset_target_iso: str | None = None) -> None:
        from materials.news_video.ui.subtitles_dialogs import show_translate_dialog
        from materials.news_video.ui.subtitles_progress_modal import SubtitlesProgressModal
        from core.subtitle_pipeline import run_translate
        from core.ai.errors import AIError, Kind

        meta = self.project.meta
        src_iso = meta.language.source
        if not src_iso:
            messagebox.showerror("VideoCraft", tr("hub.error.no_source_lang"), parent=self.root)
            return

        if preset_target_iso is None:
            target_iso = show_translate_dialog(self.root, src_iso, meta.language.translated_to)
            if target_iso is None:
                return
        else:
            target_iso = preset_target_iso

        def worker(progress_cb, cancel_token):
            return run_translate(
                self.project,
                target_lang_iso=target_iso,
                progress_cb=progress_cb,
                cancel_token=cancel_token,
            )

        modal = SubtitlesProgressModal(self.root, worker,
                                       title=tr("hub.dialog.subtitles_progress.title_translate"))
        try:
            modal.run()
        except AIError as e:
            if e.kind == Kind.CANCELLED:
                return
            messagebox.showerror(tr("hub.error.translate_failed"), str(e), parent=self.root)
            return
        except (ValueError, FileNotFoundError) as e:
            messagebox.showerror(tr("hub.error.translate_failed"), str(e), parent=self.root)
            return
        except Exception as e:
            messagebox.showerror(tr("hub.error.translate_failed"), repr(e), parent=self.root)
            return

        self.hub._refresh_project_tab()

    def _import_subtitle_file(self, src_path: str, lang_iso: str) -> None:
        import shutil
        dst = os.path.join(self.project.subtitles_dir, f"{lang_iso}.srt")
        os.makedirs(self.project.subtitles_dir, exist_ok=True)
        try:
            shutil.copy2(src_path, dst)
        except OSError as e:
            messagebox.showerror(tr("hub.error.import_failed"), str(e), parent=self.root)
            return
        meta = self.project.meta
        if not meta.language.source:
            meta.language.source = lang_iso
        self.project.update_meta(meta)
        self.hub._refresh_project_tab()

    # ── Subtitle row [+] menu + analysis invoker ─────────────────────────

    def _on_subtitle_analysis_menu(self, lang_iso: str, anchor: tk.Widget) -> None:
        from core.subtitle_analysis import all_types
        hidden = {"transcript", "chapter_transcript"}
        menu = tk.Menu(self.root, tearoff=0)
        for t in all_types():
            if t.kind in hidden:
                continue
            label = "+ " + tr(f"analysis.kind.{t.kind}")
            menu.add_command(
                label=label,
                command=lambda k=t.kind, l=lang_iso:
                    self._invoke_analysis(l, k),
            )
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height()
        menu.tk_popup(x, y)

    def _invoke_analysis(self, lang_iso: str, kind: str) -> None:
        from core.subtitle_analysis import analysis_path
        from core.subtitle_analysis_runners import run as run_analysis
        from core.ai.errors import AIError, Kind as AIKind
        from materials.news_video.ui.subtitles_progress_modal import SubtitlesProgressModal

        srt_path = os.path.join(self.project.subtitles_dir, f"{lang_iso}.srt")
        if not os.path.isfile(srt_path):
            messagebox.showerror("VideoCraft", tr("analysis.error.srt_missing"), parent=self.root)
            return

        out_path = analysis_path(self.project.subtitles_dir, lang_iso, kind)
        if os.path.isfile(out_path):
            display = tr(f"analysis.kind.{kind}")
            if not messagebox.askyesno(
                    tr("analysis.confirm_overwrite.title"),
                    tr("analysis.confirm_overwrite.message", kind=display, iso=lang_iso),
                    default="no", parent=self.root):
                return

        def worker(progress_cb, cancel_token):
            return run_analysis(kind, srt_path, self.project.subtitles_dir,
                                lang_iso, progress_cb, cancel_token)

        modal = SubtitlesProgressModal(
            self.root, worker,
            title=tr("analysis.modal.title", kind=tr(f"analysis.kind.{kind}")),
        )
        try:
            modal.run()
        except AIError as e:
            if e.kind == AIKind.CANCELLED:
                return
            messagebox.showerror(tr("analysis.error.failed"), str(e), parent=self.root)
            return
        except Exception as e:
            messagebox.showerror(tr("analysis.error.failed"), repr(e), parent=self.root)
            return

        # Force snapshot bust so the analysis row appears immediately.
        self._subtitles_snapshot = None
        self._refresh_subtitles_section()

    def _on_regenerate_subtitle(self, lang_iso: str, is_source: bool) -> None:
        from core import lang_names
        try:
            display = lang_names.friendly_name(lang_iso, "zh")
        except Exception:
            display = lang_iso
        if is_source:
            prompt = tr("hub.subtitle.regenerate.confirm_asr", lang=display, iso=lang_iso)
        else:
            prompt = tr("hub.subtitle.regenerate.confirm_translate", lang=display, iso=lang_iso)
        if not messagebox.askyesno(tr("hub.subtitle.regenerate.title"), prompt,
                                    default="no", parent=self.root):
            return
        if is_source:
            self._invoke_asr(preset_lang_iso=lang_iso)
        else:
            self._invoke_translate(preset_target_iso=lang_iso)

    def _on_quick_fix_subtitle(self, srt_path: str) -> None:
        from core.subtitle_check import apply_auto_fixes
        try:
            apply_auto_fixes(srt_path)
        except Exception as e:
            messagebox.showerror(tr("hub.error.cleanup_failed"), str(e), parent=self.root)
            return
        # Bust snapshot so the section actually rebuilds with new badge counts.
        self._subtitles_snapshot = None
        self._refresh_subtitles_section()
        self.hub._refresh_preview_if_match(srt_path)


def render(parent: tk.Frame, hub: "VideoCraftHub") -> NewsVideoSidebar:
    """MaterialType.sidebar_renderer entry point."""
    return NewsVideoSidebar(parent, hub)
