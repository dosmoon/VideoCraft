"""News-video material sidebar — pure ttk.Treeview navigation (ADR-0005 slice R).

Sidebar shows structure + state only. Selecting any node tells the
hub to paint the matching detail pane into the 主窗口 (preview tab).
All actions (add source / generate subs / regen / analysis menu /
rename / delete) live in the main-window panes — `materials/news_video/ui/node_panes.py`.

Tree iid scheme:
  inst:<instance>
  slot:<instance>:source | news_context | subtitles
  subtitle:<instance>:<lang>
  analysis:<instance>:<lang>:<kind>
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from i18n import tr
from materials.news_video.model import NewsVideoModel

if TYPE_CHECKING:
    from VideoCraftHub import VideoCraftHub


# ── Visual tokens ────────────────────────────────────────────────────────────

ICON_INSTANCE = "📺"
ICON_OK = "✓"
ICON_MISSING = "✗"
ICON_LOCKED = "🔒"
ICON_SUBTITLE = "📄"


class NewsVideoSidebar:
    """One news_video instance, rendered as a Treeview subtree under the
    parent sidebar tab. Selection events route to hub's main-window
    dispatcher (node_panes.show_node)."""

    def __init__(self, parent: tk.Frame, model: NewsVideoModel,
                  hub: "VideoCraftHub") -> None:
        self.parent = parent
        self.model = model
        self.hub = hub

        # State fingerprint to gate redundant tree rebuilds (auto-refresh
        # tick fires every 2s; we no-op when nothing changed).
        self._fingerprint: tuple = ()

        self._build()
        self.model.subscribe(self._on_model_change)

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        tree_frame = tk.Frame(self.parent, bg="#f5f5f5")
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            tree_frame, show="tree", selectmode="browse",
            height=12,
        )
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._on_right_click)

        # Compute and render
        self._fingerprint = self._compute_fingerprint()
        self._render()

    def _render(self) -> None:
        """Wipe + repopulate. Treeview is C-backed; rebuild is cheap."""
        self.tree.delete(*self.tree.get_children())

        inst_iid = f"inst:{self.model.instance_id}"
        self.tree.insert(
            "", "end", iid=inst_iid, open=True,
            text=f"  {ICON_INSTANCE}  {self.model.instance_id}  ·  {tr('material.news_video')}",
        )

        states = self.model.slot_readiness()
        for slot_id in ("source", "news_context", "subtitles"):
            state = states[slot_id]
            icon = (ICON_LOCKED if state.is_locked
                    else (ICON_OK if state.is_filled else ICON_MISSING))
            label = self._slot_label(slot_id)
            slot_iid = f"slot:{self.model.instance_id}:{slot_id}"
            text = f"  {icon}  {label}"
            if state.summary:
                text += f"  ·  {state.summary}"
            self.tree.insert(inst_iid, "end", iid=slot_iid, open=True,
                              text=text)

            # Subtitles slot expands into per-language children
            if slot_id == "subtitles" and not state.is_locked:
                self._render_subtitles_children(slot_iid)

    def _render_subtitles_children(self, parent_iid: str) -> None:
        from core import lang_names
        source_lang = self.model.source_language()
        for lang in self.model.list_subtitle_languages():
            try:
                lang_label = lang_names.friendly_name(lang, "zh")
            except Exception:
                lang_label = lang
            check = self.model.check_subtitle(
                lang, reference_lang_iso=source_lang)
            if check.hard_count > 0:
                row_icon = ICON_MISSING
            elif check.fixable_count > 0:
                row_icon = "⚠"
            else:
                row_icon = ICON_OK
            role = (tr("hub.subtitle.role_source") if lang == source_lang
                    else tr("hub.subtitle.role_translated"))
            sub_iid = f"subtitle:{self.model.instance_id}:{lang}"
            self.tree.insert(
                parent_iid, "end", iid=sub_iid, open=True,
                text=f"  {row_icon}  {ICON_SUBTITLE}  {role} ({lang_label}): {lang}.srt",
            )
            # Analysis children under each subtitle
            for art in self.model.list_analysis_artifacts(lang):
                art_iid = f"analysis:{self.model.instance_id}:{lang}:{art.type.kind}"
                self.tree.insert(
                    sub_iid, "end", iid=art_iid, open=False,
                    text=f"     {art.type.icon}  {tr(f'analysis.kind.{art.type.kind}')}",
                )

    def _slot_label(self, slot_id: str) -> str:
        return {
            "source": tr("hub.sidebar.source.title"),
            "news_context": tr("hub.sidebar.news_context.title"),
            "subtitles": tr("hub.sidebar.subtitles.title"),
        }[slot_id]

    # ── Refresh (model change / auto-tick) ────────────────────────────────

    def _on_model_change(self) -> None:
        try:
            self.parent.after(0, self._refresh_if_changed)
        except Exception:
            pass

    def refresh(self) -> None:
        """Public refresh entry (called by hub auto-tick + after writes).
        No-ops when state hasn't changed — fixes the 2s flicker."""
        self._refresh_if_changed()

    def _refresh_if_changed(self) -> None:
        fp = self._compute_fingerprint()
        if fp == self._fingerprint:
            return  # no actual change → skip rebuild → no flicker
        self._fingerprint = fp
        # Preserve selection through rebuild
        sel = self.tree.selection()
        prev_iid = sel[0] if sel else None
        self._render()
        if prev_iid and self.tree.exists(prev_iid):
            self.tree.selection_set(prev_iid)

    def _compute_fingerprint(self) -> tuple:
        """Cheap state hash — enough to decide whether to rebuild."""
        out = [self.model.instance_id]
        # Slot states
        for slot_id, st in self.model.slot_readiness().items():
            out.append((slot_id, st.is_locked, st.is_filled, st.summary))
        # Subtitle list + analysis presence per language
        for lang in self.model.list_subtitle_languages():
            out.append(("lang", lang))
            for art in self.model.list_analysis_artifacts(lang):
                out.append(("art", lang, art.type.kind))
        return tuple(out)

    # ── Selection routing ─────────────────────────────────────────────────

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        from materials.news_video.ui import node_panes
        try:
            node_panes.show_node(self.hub, self.model, iid)
        except Exception as e:
            # Defensive: don't let a pane build error wedge the sidebar
            from hub_logger import logger
            logger.error(f"news_video node pane error: {e}")

    def _on_right_click(self, event) -> None:
        """Right-click on the instance root → rename / delete menu."""
        row_iid = self.tree.identify_row(event.y)
        if not row_iid:
            return
        if row_iid != f"inst:{self.model.instance_id}":
            return
        from tkinter import Menu
        from materials.news_video.ui.node_panes import (
            _rename_instance, _delete_instance,
        )
        menu = Menu(self.hub.root, tearoff=0)
        menu.add_command(
            label=tr("material.action.rename"),
            command=lambda: _rename_instance(self.hub, self.model))
        menu.add_command(
            label=tr("material.action.delete"),
            command=lambda: _delete_instance(self.hub, self.model))
        menu.tk_popup(event.x_root, event.y_root)


def render(parent: tk.Frame, hub: "VideoCraftHub",
            instance_id: str) -> NewsVideoSidebar:
    """MaterialType.sidebar_renderer entry point."""
    model = NewsVideoModel(hub.project, instance_id)
    return NewsVideoSidebar(parent, model, hub)
