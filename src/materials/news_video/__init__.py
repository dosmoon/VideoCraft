"""News-video material plugin: a source video plus its AI-derived
context (15-field news schema), subtitles, chapters, and hot clips.

Importing this package self-registers the MaterialType. The material is
driven by the Electron workbench via the core_rpc sidecar; the Tk sidebar
renderer / create-handler were retired with the Tk app (P2).
"""

from __future__ import annotations

from materials import MaterialType, register
from materials.news_video.model import NewsVideoModel


def _suggest_instance_name(existing: list[str]) -> str:
    """Auto-name pattern: news-1 / news-2 / ... — first unused index."""
    existing_set = set(existing)
    n = 1
    while True:
        name = f"news-{n}"
        if name not in existing_set:
            return name
        n += 1


def _instance_factory(project, instance_id: str) -> NewsVideoModel:
    return NewsVideoModel(project, instance_id)


register(MaterialType(
    type_name="news_video",
    display_name_key="material.news_video",
    description_zh="新闻/演讲/发布会素材：源视频 + 字幕 + 章节 + AI 新闻背景",
    description_en="News / speech / press-briefing material: source video + subtitles + chapters + AI context",
    # Single-instance: source acquisition + ASR are still project-level (one
    # source video per project), so a 2nd instance can't get its own source.
    # The [+] menu offers "open existing" instead of silently creating a broken
    # 2nd instance. See core/subtitle_pipeline.py TODO(ADR-0005).
    single_instance=True,
    icon="📺",
    instance_factory=_instance_factory,
    suggest_name=_suggest_instance_name,
))
