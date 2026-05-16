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
    """Material-tab [+] menu handler. Currently single-source projects
    have an implicit news_video instance; this triggers the same
    add-source-video flow the source-section button uses.
    """
    if hub.project.source_status() == "ready":
        # Already an instance — for single-source projects only one
        # news_video material exists. No-op until multi-source lands.
        return
    hub._on_source_button()


register(MaterialType(
    type_name="news_video",
    display_name_key="material.news_video",
    description_zh="新闻/演讲/发布会素材：源视频 + 字幕 + 章节 + AI 新闻背景",
    description_en="News / speech / press-briefing material: source video + subtitles + chapters + AI context",
    icon="📺",
    sidebar_renderer=_sidebar_module.render,
    create_handler=_create_handler,
    # artifact_resolver wired when a creation plugin first consumes it.
))
