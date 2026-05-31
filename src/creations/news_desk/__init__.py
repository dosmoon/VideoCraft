"""News-desk creation plugin: bilingual news/press-briefing video with
chapter strip, lower-third name plates, and AI-driven candidate titles.

Importing this package self-registers the CreationType.
"""

from __future__ import annotations

from creations import CreationType, register
from creations.news_desk.config import NewsDeskInstanceConfig
from creations.news_desk.preview import preview_data as _preview_data

register(CreationType(
    type_name="news_desk",
    display_name_key="creation.news_desk",   # renamed to creation.news_desk in slice I
    tool_key="news-desk",
    default_basename="news",
    single_instance=False,
    description_zh="新闻/演讲/发布会成片：双语字幕 + 名牌 + 章节条",
    description_en="News / speech / press-briefing video with bilingual"
                   " subs, lower-third name plates, and topic strip",
    # New-arch sidecar: single-owner config drives the component/config RPC face
    # (ADR-0004 resolves it generically). render_provider is not wired yet —
    # per-chapter export is the next increment.
    config_owner_cls=NewsDeskInstanceConfig,
    preview_provider=_preview_data,
))
