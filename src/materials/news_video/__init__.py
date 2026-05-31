"""News-video material plugin: a source video plus its AI-derived
context (15-field news schema), subtitles, chapters, and hot clips.

Importing this package self-registers the MaterialType. The plugin
exposes its sidebar through `materials.news_video.sidebar.render`,
which the Hub invokes once per instance when building the 素材 tab.
"""

from __future__ import annotations

import os

from materials import MaterialType, register
from materials.news_video import sidebar as _sidebar_module
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


def _create_handler(hub) -> None:
    """素材 tab [+] menu handler. Creates a NEW empty news_video instance
    (no source video yet) and triggers the sidebar to refresh so the
    instance's tree appears with all slots in empty state. User then
    fills the source-video slot from inside the tree (per the user-
    confirmed design in ADR-0005 K.2 feedback)."""
    existing = hub.project.list_material_instances("news_video")
    name = _suggest_instance_name(existing)
    inst_dir = hub.project.create_material_instance(
        "news_video", name,
        initial_config={
            "schema_version": 1,
            "type_name": "news_video",
            "instance_name": name,
            "display_name": name,
        },
        config_filename="instance.json",
    )
    # Skeleton dirs so writes don't hit ENOENT later.
    os.makedirs(os.path.join(inst_dir, "source"), exist_ok=True)
    os.makedirs(os.path.join(inst_dir, "subtitles"), exist_ok=True)
    hub._refresh_project_tab()


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
    sidebar_renderer=_sidebar_module.render,
    create_handler=_create_handler,
    instance_factory=_instance_factory,
    suggest_name=_suggest_instance_name,
))
