"""News-video material plugin: a source video plus its AI-derived
context (15-field news schema), subtitles, chapters, and hot clips.

Importing this package self-registers the MaterialType. Slice F
lands the schema (this package) and a skeletal registration;
slices G/H wire the sidebar renderer, create handler, and
artifact resolver.
"""

from __future__ import annotations

from materials import MaterialType, register

register(MaterialType(
    type_name="news_video",
    display_name_key="material.news_video",   # i18n key, may not exist yet — slice I/J
    description_zh="新闻视频素材：源视频 + 字幕 + 章节 + AI 新闻背景",
    description_en="News video material: source video + subtitles + chapters + AI context",
    # sidebar_renderer / create_handler / artifact_resolver wired in slice H
))
