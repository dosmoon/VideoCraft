"""News-video tree-node detail panes (ADR-0005 slice R).

Sidebar is pure navigation (ttk.Treeview). Selecting a node calls
`show_node(hub, model, iid)` which dispatches to the right builder
here and paints the result into hub's preview tab.

Node iid scheme:
  inst:<instance>
  slot:<instance>:source
  slot:<instance>:news_context
  slot:<instance>:subtitles
  subtitle:<instance>:<lang>
  analysis:<instance>:<lang>:<kind>
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from i18n import tr
from materials.news_video.model import NewsVideoModel

if TYPE_CHECKING:
    from VideoCraftHub import VideoCraftHub


# ── Entry point ──────────────────────────────────────────────────────────────

def show_node(hub: "VideoCraftHub", model: NewsVideoModel, iid: str) -> None:
    """Parse iid and paint the matching pane into hub.preview_tab."""
    parts = iid.split(":")
    kind = parts[0]
    parent = hub._preview_tab
    # Wipe whatever's there.
    hub._clear_preview_tab()

    if kind == "inst":
        frame = _instance_overview(parent, model, hub)
    elif kind == "slot":
        _, _, slot_id = parts
        frame = _slot_pane(parent, model, hub, slot_id)
    elif kind == "subtitle":
        _, _, lang = parts
        frame = _subtitle_node(parent, model, hub, lang)
    elif kind == "analysis":
        _, _, lang, art_kind = parts
        frame = _analysis_node(parent, model, hub, lang, art_kind)
    else:
        frame = _placeholder(parent, f"未知节点: {iid}")

    frame.pack(fill="both", expand=True)
    hub._preview_key = f"news_video_node:{iid}"
    from VideoCraftHub import PREVIEW_TAB_KEY
    hub._select_tab(PREVIEW_TAB_KEY)


# ── Generic placeholder (locked / unknown) ───────────────────────────────────

def _placeholder(parent: tk.Frame, text: str, *, hint: str = "") -> tk.Frame:
    f = tk.Frame(parent, bg="white")
    inner = tk.Frame(f, bg="white")
    inner.place(relx=0.5, rely=0.4, anchor="center")
    tk.Label(inner, text=text, bg="white", fg="#888",
             font=("Microsoft YaHei UI", 16)).pack()
    if hint:
        tk.Label(inner, text=hint, bg="white", fg="#aaa",
                 font=("Microsoft YaHei UI", 10)).pack(pady=(8, 0))
    return f


# ── Instance overview ────────────────────────────────────────────────────────

def _instance_overview(parent: tk.Frame, model: NewsVideoModel,
                        hub: "VideoCraftHub") -> tk.Frame:
    outer = tk.Frame(parent, bg="white")

    header = tk.Frame(outer, bg="white", padx=20, pady=14)
    header.pack(fill="x")
    tk.Label(header, text=f"📺  {model.instance_id}",
             bg="white", fg="#222",
             font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
    tk.Label(header,
             text="  ·  " + tr("material.news_video"),
             bg="white", fg="#888",
             font=("Microsoft YaHei UI", 11)).pack(side="left")

    actions = tk.Frame(header, bg="white")
    actions.pack(side="right")
    tk.Button(actions, text=tr("material.action.rename"),
              relief="flat", bg="#e8e8e8", padx=10,
              command=lambda: _rename_instance(hub, model)
              ).pack(side="right", padx=(8, 0))
    tk.Button(actions, text=tr("material.action.delete"),
              relief="flat", bg="#fbe9e7", fg="#c00", padx=10,
              command=lambda: _delete_instance(hub, model)
              ).pack(side="right")

    ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=20)

    body = tk.Frame(outer, bg="white", padx=24, pady=18)
    body.pack(fill="both", expand=True)

    tk.Label(body, text=tr("material.overview.heading"),
             bg="white", fg="#555",
             font=("Microsoft YaHei UI", 11, "bold"),
             anchor="w").pack(fill="x", pady=(0, 8))

    # Render each slot as a horizontal status row
    for slot_id, state in model.slot_readiness().items():
        row = tk.Frame(body, bg="white")
        row.pack(fill="x", pady=2)
        icon = "🔒" if state.is_locked else ("✓" if state.is_filled else "✗")
        color = "#999" if state.is_locked else ("#222" if state.is_filled else "#c00")
        tk.Label(row, text=icon, bg="white", fg=color,
                 font=("Microsoft YaHei UI", 11), width=3).pack(side="left")
        label = {
            "source": tr("hub.sidebar.source.title"),
            "news_context": tr("hub.sidebar.news_context.title"),
            "subtitles": tr("hub.sidebar.subtitles.title"),
        }.get(slot_id, slot_id)
        tk.Label(row, text=label, bg="white", fg="#222",
                 font=("Microsoft YaHei UI", 11),
                 width=14, anchor="w").pack(side="left")
        tk.Label(row, text=state.summary, bg="white",
                 fg="#666" if not state.is_locked else "#999",
                 font=("Microsoft YaHei UI", 10),
                 anchor="w").pack(side="left", fill="x", expand=True)

    return outer


def _rename_instance(hub, model: NewsVideoModel) -> None:
    from tkinter import simpledialog
    new_name = simpledialog.askstring(
        tr("material.action.rename"),
        tr("material.dialog.rename_prompt", current=model.instance_id),
        parent=hub.root,
        initialvalue=model.instance_id,
    )
    if not new_name or new_name == model.instance_id:
        return
    new_name = new_name.strip()
    if not new_name:
        return
    try:
        new_dir = hub.project.material_instance_dir("news_video", new_name)
        if os.path.exists(new_dir):
            messagebox.showerror("VideoCraft",
                                  tr("material.dialog.rename_exists", name=new_name),
                                  parent=hub.root)
            return
        os.rename(model.instance_dir, new_dir)
    except OSError as e:
        messagebox.showerror("VideoCraft", str(e), parent=hub.root)
        return
    hub._refresh_project_tab()


def _delete_instance(hub, model: NewsVideoModel) -> None:
    if not messagebox.askyesno(
            tr("material.dialog.delete_title"),
            tr("material.dialog.delete_confirm", instance=model.instance_id),
            default="no", parent=hub.root):
        return
    import shutil
    try:
        shutil.rmtree(model.instance_dir)
    except OSError as e:
        messagebox.showerror("VideoCraft", str(e), parent=hub.root)
        return
    hub._refresh_project_tab()


# ── Slot panes ───────────────────────────────────────────────────────────────

def _slot_pane(parent: tk.Frame, model: NewsVideoModel, hub: "VideoCraftHub",
                slot_id: str) -> tk.Frame:
    states = model.slot_readiness()
    state = states.get(slot_id)
    if state is None:
        return _placeholder(parent, f"未知槽位: {slot_id}")
    if state.is_locked:
        return _placeholder(parent,
                             {"news_context": tr("hub.sidebar.news_context.title"),
                              "subtitles": tr("hub.sidebar.subtitles.title")}.get(
                                  slot_id, slot_id),
                             hint=state.summary)

    if slot_id == "source":
        return _source_pane(parent, model, hub, state)
    if slot_id == "news_context":
        return _news_context_pane(parent, model, hub)
    if slot_id == "subtitles":
        return _subtitles_overview(parent, model, hub)
    return _placeholder(parent, slot_id)


def _source_pane(parent, model, hub, state) -> tk.Frame:
    """Source slot: empty-state when missing, full preview when present.
    All add/modify actions live here, NOT on the sidebar."""
    if state.is_filled:
        from materials.news_video.ui.source_preview_pane import build_source_preview
        frame = build_source_preview(
            parent, model,
            on_modify=lambda: _trigger_source_action(hub, model),
        )
        return frame
    # Empty state: big add CTA in the center.
    outer = tk.Frame(parent, bg="white")
    inner = tk.Frame(outer, bg="white")
    inner.place(relx=0.5, rely=0.4, anchor="center")
    tk.Label(inner, text="✗  " + tr("hub.sidebar.source.title"),
             bg="white", fg="#888",
             font=("Microsoft YaHei UI", 16)).pack(pady=(0, 8))
    tk.Label(inner, text=tr("material.source.empty_hint"),
             bg="white", fg="#aaa",
             font=("Microsoft YaHei UI", 10)).pack(pady=(0, 16))
    tk.Button(inner, text=tr("hub.button.add_source_video"),
              relief="flat", bg="#1976d2", fg="white",
              font=("Microsoft YaHei UI", 11), padx=20, pady=6,
              command=lambda: _trigger_source_action(hub, model)
              ).pack()
    return outer


def _trigger_source_action(hub, model: NewsVideoModel) -> None:
    """Open the source add/modify dialog (acquisition modal etc.)."""
    from materials.news_video.ui.source_add_dialog import show_source_add_dialog
    from materials.news_video.ui.source_prepare_modal import SourcePrepareModal
    from ui.disclaimer_dialog import show_if_needed as show_disclaimer_if_needed
    from core.source_acquire import AcquireError, ERR_CANCELLED
    from core.project_schema import ORIGIN_LINK

    current_meta = model.get_source_meta()
    preset = current_meta if model.has_source_video() else None
    title = (tr("hub.dialog.source.title_modify") if preset
             else tr("hub.dialog.source.title_add"))

    src = show_source_add_dialog(hub.root, title=title, preset=preset)
    if src is None:
        return
    if src.origin == ORIGIN_LINK:
        if not show_disclaimer_if_needed(hub.root):
            return
    modal = SourcePrepareModal(
        hub.root, src,
        dest_video_path=model.source_video_path,
        dest_meta_path=model.source_meta_path,
    )
    try:
        result = modal.run()
    except AcquireError as e:
        if e.category == ERR_CANCELLED:
            return
        messagebox.showerror(
            tr("hub.error.source_prepare_failed"),
            f"{e.message}\n\n{e.details[:400]}" if e.details else e.message,
            parent=hub.root)
        return
    except Exception as e:
        messagebox.showerror(tr("hub.error.source_prepare_failed"),
                              str(e), parent=hub.root)
        return

    model.commit_source(
        src,
        title=result.title,
        duration_sec=result.duration_sec,
        width=result.width,
        height=result.height,
    )


def _news_context_pane(parent, model, hub) -> tk.Frame:
    from materials.news_video.ui.news_context_pane import build_news_context_preview
    return build_news_context_preview(parent, model)


def _subtitles_overview(parent, model: NewsVideoModel, hub) -> tk.Frame:
    """Subtitles slot: full list of languages + global actions."""
    outer = tk.Frame(parent, bg="white")
    header = tk.Frame(outer, bg="white", padx=20, pady=14)
    header.pack(fill="x")
    tk.Label(header, text=tr("hub.sidebar.subtitles.title"),
             bg="white", fg="#222",
             font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
    actions = tk.Frame(header, bg="white")
    actions.pack(side="right")
    has_subs = bool(model.list_subtitle_languages())
    tk.Button(actions, text=tr("hub.button.add_subtitles") if not has_subs
              else tr("hub.button.add_translation"),
              relief="flat", bg="#1976d2", fg="white", padx=14, pady=4,
              command=lambda: _trigger_subtitle_action(hub, model, has_subs)
              ).pack(side="right")

    ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=20)

    body = tk.Frame(outer, bg="white", padx=24, pady=18)
    body.pack(fill="both", expand=True)

    langs = model.list_subtitle_languages()
    if not langs:
        tk.Label(body, text=tr("material.subtitles.empty_hint"),
                 bg="white", fg="#888",
                 font=("Microsoft YaHei UI", 10)).pack(pady=20)
        return outer

    from core import lang_names
    source_lang = model.source_language()
    for lang in langs:
        row = tk.Frame(body, bg="white")
        row.pack(fill="x", pady=4)
        try:
            label = lang_names.friendly_name(lang, "zh")
        except Exception:
            label = lang
        role = (tr("hub.subtitle.role_source") if lang == source_lang
                else tr("hub.subtitle.role_translated"))
        tk.Label(row, text="✓", bg="white", fg="#222",
                 width=3, font=("Microsoft YaHei UI", 11)).pack(side="left")
        tk.Label(row, text=f"{role} ({label}): {lang}.srt",
                 bg="white", fg="#222",
                 font=("Microsoft YaHei UI", 10),
                 anchor="w").pack(side="left", fill="x", expand=True)
    return outer


def _trigger_subtitle_action(hub, model: NewsVideoModel,
                              already_has_subs: bool) -> None:
    if already_has_subs:
        _invoke_translate(hub, model)
    else:
        _invoke_asr(hub, model)


# ── Subtitle (per-language) node ─────────────────────────────────────────────

def _subtitle_node(parent, model: NewsVideoModel, hub,
                    lang: str) -> tk.Frame:
    """One language's SRT: preview + actions (regenerate / quick-fix / analysis)."""
    outer = tk.Frame(parent, bg="white")

    header = tk.Frame(outer, bg="white", padx=20, pady=10)
    header.pack(fill="x")
    from core import lang_names
    try:
        label = lang_names.friendly_name(lang, "zh")
    except Exception:
        label = lang
    tk.Label(header, text=f"📄  {lang}.srt  ·  {label}",
             bg="white", fg="#222",
             font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")

    actions = tk.Frame(header, bg="white")
    actions.pack(side="right")
    is_source_row = (lang == model.source_language())
    tk.Button(actions, text=tr("hub.button.analyze"),
              relief="flat", bg="#e8e8e8", padx=10,
              command=lambda w=actions: _show_analysis_menu(hub, model, lang, w)
              ).pack(side="right", padx=(8, 0))
    tk.Button(actions, text=tr("hub.button.regenerate"),
              relief="flat", bg="#e8e8e8", padx=10,
              command=lambda: _confirm_regenerate(hub, model, lang, is_source_row)
              ).pack(side="right", padx=(8, 0))
    check = model.check_subtitle(lang, reference_lang_iso=model.source_language())
    if check.fixable_count > 0 and check.hard_count == 0:
        tk.Button(actions, text=tr("hub.subtitle.quick_fix_btn", n=check.fixable_count),
                  relief="flat", bg="#fff3cd", fg="#856404", padx=10,
                  command=lambda: _quick_fix(hub, model, lang)
                  ).pack(side="right", padx=(8, 0))

    ttk.Separator(outer, orient="horizontal").pack(fill="x", padx=20)

    # Reuse existing srt preview pane
    from materials.news_video.ui.srt_preview_pane import build_srt_preview
    preview = build_srt_preview(
        outer, model.subtitle_path(lang),
        lang_iso=lang,
        reference_srt_path=(model.subtitle_path(model.source_language())
                             if model.source_language() and model.source_language() != lang
                             else None),
        on_fixed=hub._refresh_project_tab,
    )
    preview.pack(fill="both", expand=True)
    return outer


def _show_analysis_menu(hub, model, lang, anchor) -> None:
    from core.subtitle_analysis import all_types
    hidden = {"transcript", "chapter_transcript"}
    menu = tk.Menu(hub.root, tearoff=0)
    for t in all_types():
        if t.kind in hidden:
            continue
        menu.add_command(
            label="+ " + tr(f"analysis.kind.{t.kind}"),
            command=lambda k=t.kind: _invoke_analysis(hub, model, lang, k),
        )
    x = anchor.winfo_rootx()
    y = anchor.winfo_rooty() + anchor.winfo_height()
    menu.tk_popup(x, y)


def _confirm_regenerate(hub, model, lang, is_source: bool) -> None:
    from core import lang_names
    try:
        display = lang_names.friendly_name(lang, "zh")
    except Exception:
        display = lang
    if is_source:
        prompt = tr("hub.subtitle.regenerate.confirm_asr", lang=display, iso=lang)
    else:
        prompt = tr("hub.subtitle.regenerate.confirm_translate", lang=display, iso=lang)
    if not messagebox.askyesno(tr("hub.subtitle.regenerate.title"), prompt,
                                default="no", parent=hub.root):
        return
    if is_source:
        _invoke_asr(hub, model, preset_lang_iso=lang)
    else:
        _invoke_translate(hub, model, preset_target_iso=lang)


def _quick_fix(hub, model, lang) -> None:
    try:
        model.quick_fix_subtitle(lang)
    except Exception as e:
        messagebox.showerror(tr("hub.error.cleanup_failed"), str(e),
                              parent=hub.root)
        return
    hub._refresh_preview_if_match(model.subtitle_path(lang))


# ── Analysis artifact node ───────────────────────────────────────────────────

def _analysis_node(parent, model: NewsVideoModel, hub,
                    lang: str, art_kind: str) -> tk.Frame:
    from core.subtitle_analysis import all_types, get_type
    t = get_type(art_kind)
    if t is None:
        return _placeholder(parent, f"未知分析类型: {art_kind}")

    # Find the artifact (existing_artifacts returns only those on disk)
    artifacts = model.list_analysis_artifacts(lang)
    art = next((a for a in artifacts if a.type.kind == art_kind), None)
    if art is None:
        return _placeholder(parent, tr(f"analysis.kind.{art_kind}"),
                             hint=tr("material.analysis.missing_hint"))

    from materials.news_video.ui.subtitle_analysis_preview import build_analysis_preview
    return build_analysis_preview(parent, art, on_saved=hub._refresh_project_tab)


# ── ASR / translate / analysis invocation (shared by overview + sub-row) ─────

def _invoke_asr(hub, model: NewsVideoModel, *, preset_lang_iso="ASK") -> None:
    from materials.news_video.ui.subtitles_dialogs import show_asr_dialog
    from materials.news_video.ui.subtitles_progress_modal import SubtitlesProgressModal
    from core.ai.errors import AIError, Kind

    if preset_lang_iso == "ASK":
        choice = show_asr_dialog(hub.root)
        if choice is None:
            return
        if choice["mode"] == "import":
            try:
                model.import_subtitle(choice["path"], choice["lang_iso"])
            except OSError as e:
                messagebox.showerror(tr("hub.error.import_failed"),
                                      str(e), parent=hub.root)
            return
        lang_iso = choice["lang_iso"]
    else:
        lang_iso = preset_lang_iso

    def worker(progress_cb, cancel_token):
        return model.run_asr(source_lang_iso=lang_iso,
                              progress_cb=progress_cb,
                              cancel_token=cancel_token)

    modal = SubtitlesProgressModal(
        hub.root, worker, title=tr("hub.dialog.subtitles_progress.title_asr"))
    try:
        modal.run()
    except AIError as e:
        if e.kind == Kind.CANCELLED:
            return
        messagebox.showerror(tr("hub.error.asr_failed"), str(e), parent=hub.root)
    except FileNotFoundError as e:
        messagebox.showerror(tr("hub.error.source_missing"), str(e), parent=hub.root)
    except Exception as e:
        messagebox.showerror(tr("hub.error.asr_failed"), repr(e), parent=hub.root)


def _invoke_translate(hub, model, *, preset_target_iso=None) -> None:
    from materials.news_video.ui.subtitles_dialogs import show_translate_dialog
    from materials.news_video.ui.subtitles_progress_modal import SubtitlesProgressModal
    from core.ai.errors import AIError, Kind

    src_iso = model.source_language()
    if not src_iso:
        messagebox.showerror("VideoCraft", tr("hub.error.no_source_lang"),
                              parent=hub.root)
        return

    if preset_target_iso is None:
        target_iso = show_translate_dialog(
            hub.root, src_iso, model.translated_languages())
        if target_iso is None:
            return
    else:
        target_iso = preset_target_iso

    def worker(progress_cb, cancel_token):
        return model.run_translate(target_lang_iso=target_iso,
                                    progress_cb=progress_cb,
                                    cancel_token=cancel_token)

    modal = SubtitlesProgressModal(
        hub.root, worker, title=tr("hub.dialog.subtitles_progress.title_translate"))
    try:
        modal.run()
    except AIError as e:
        if e.kind == Kind.CANCELLED:
            return
        messagebox.showerror(tr("hub.error.translate_failed"), str(e), parent=hub.root)
    except (ValueError, FileNotFoundError) as e:
        messagebox.showerror(tr("hub.error.translate_failed"), str(e), parent=hub.root)
    except Exception as e:
        messagebox.showerror(tr("hub.error.translate_failed"), repr(e), parent=hub.root)


def _invoke_analysis(hub, model, lang: str, kind: str) -> None:
    from core.ai.errors import AIError, Kind as AIKind
    from materials.news_video.ui.subtitles_progress_modal import SubtitlesProgressModal

    if not model.has_subtitle(lang):
        messagebox.showerror("VideoCraft", tr("analysis.error.srt_missing"),
                              parent=hub.root)
        return
    if model.has_analysis(lang, kind):
        display = tr(f"analysis.kind.{kind}")
        if not messagebox.askyesno(
                tr("analysis.confirm_overwrite.title"),
                tr("analysis.confirm_overwrite.message", kind=display, iso=lang),
                default="no", parent=hub.root):
            return

    def worker(progress_cb, cancel_token):
        return model.run_analysis(kind, lang,
                                    progress_cb=progress_cb,
                                    cancel_token=cancel_token)

    modal = SubtitlesProgressModal(
        hub.root, worker,
        title=tr("analysis.modal.title", kind=tr(f"analysis.kind.{kind}")))
    try:
        modal.run()
    except AIError as e:
        if e.kind == AIKind.CANCELLED:
            return
        messagebox.showerror(tr("analysis.error.failed"), str(e), parent=hub.root)
    except Exception as e:
        messagebox.showerror(tr("analysis.error.failed"), repr(e), parent=hub.root)
