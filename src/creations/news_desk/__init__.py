"""News-desk creation plugin: bilingual news/press-briefing video with
chapter strip, lower-third name plates, and AI-driven candidate titles.

Importing this package self-registers the CreationType.

ADR-0008: this plugin's logic lives entirely in TS (desktop/src/creations/news_desk/);
the sidecar only needs the type metadata for the framework directory lifecycle
(create/rename/delete instance, dir resolution). No Python config owner / preview
/ render / import / preset providers remain.
"""

from __future__ import annotations

from creations import CreationType, register

register(CreationType(
    type_name="news_desk",
    display_name_key="creation.news_desk",   # renamed to creation.news_desk in slice I
    tool_key="news-desk",
    default_basename="news",
    single_instance=False,
    description_zh="新闻/演讲/发布会成片：双语字幕 + 名牌 + 章节条",
    description_en="News / speech / press-briefing video with bilingual"
                   " subs, lower-third name plates, and topic strip",
))
