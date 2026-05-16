"""News-video material plugin: a source video plus its AI-derived
context (15-field news schema), subtitles, chapters, and hot clips.

Importing this package self-registers the MaterialType. The plugin
exposes its sidebar through `materials.news_video.sidebar.render`,
which the Hub invokes when building the 素材 tab.
"""

from __future__ import annotations

from materials import MaterialType, register
from materials.news_video import sidebar as _sidebar_module


def _create_handler(hub) -> None:
    """Material-tab [+] menu handler. For single-source projects an
    instance is "created" by adding the source video; that flow lives
    on the news_video sidebar panel, but the panel doesn't exist yet
    when there's no instance — so we drive the source-add flow
    directly here through the same UI helpers the panel uses.
    """
    if _has_instance(hub.project):
        return  # already exists (single-source limit)

    from materials.news_video.ui.source_add_dialog import show_source_add_dialog
    from materials.news_video.ui.source_prepare_modal import SourcePrepareModal
    from ui.disclaimer_dialog import show_if_needed as show_disclaimer_if_needed
    from core.source_acquire import AcquireError, ERR_CANCELLED
    from core.project_schema import ORIGIN_LINK
    from tkinter import messagebox
    from i18n import tr

    src = show_source_add_dialog(hub.root, title=tr("hub.dialog.source.title_add"), preset=None)
    if src is None:
        return

    if src.origin == ORIGIN_LINK:
        if not show_disclaimer_if_needed(hub.root):
            return

    modal = SourcePrepareModal(
        hub.root, src,
        dest_video_path=hub.project.source_video_path,
        dest_meta_path=hub.project.source_meta_path,
    )
    try:
        result = modal.run()
    except AcquireError as e:
        if e.category == ERR_CANCELLED:
            return
        messagebox.showerror(
            tr("hub.error.source_prepare_failed"),
            f"{e.message}\n\n{e.details[:400]}" if e.details else e.message,
            parent=hub.root,
        )
        return
    except Exception as e:
        messagebox.showerror(tr("hub.error.source_prepare_failed"), str(e), parent=hub.root)
        return

    meta = hub.project.meta
    meta.source = src
    if result.title:
        meta.source.title = result.title
    if result.duration_sec is not None:
        meta.source.duration_sec = result.duration_sec
    if result.width is not None:
        meta.source.width = result.width
    if result.height is not None:
        meta.source.height = result.height
    hub.project.update_meta(meta)
    hub._refresh_project_tab()


def _has_instance(project) -> bool:
    """Single-source projects: a news_video instance "exists" once the
    source video is present. The 素材 tab paints the panel only after
    this returns True.
    """
    return project.source_status() == "ready"


register(MaterialType(
    type_name="news_video",
    display_name_key="material.news_video",
    description_zh="新闻/演讲/发布会素材：源视频 + 字幕 + 章节 + AI 新闻背景",
    description_en="News / speech / press-briefing material: source video + subtitles + chapters + AI context",
    icon="📺",
    sidebar_renderer=_sidebar_module.render,
    create_handler=_create_handler,
    has_instance=_has_instance,
    # artifact_resolver wired when a creation plugin first consumes it.
))
