"""News-video material plugin: a source video plus its AI-derived
context (15-field news schema), subtitles, chapters, and hot clips.

Importing this package self-registers the MaterialType.

ADR-0008: the material's data model lives entirely in TS
(desktop/src/materials/news_video/); long-running capabilities (ASR / translate /
analysis / acquire) run via the plugin-agnostic capability.* gateway. The sidecar
only carries this type metadata for the framework directory lifecycle (create/
rename/delete instance + dir resolution). The Python model / schema / paths /
ai_fill + the instance_factory were retired.
"""

from __future__ import annotations

from materials import MaterialType, register


def _suggest_instance_name(existing: list[str]) -> str:
    """Auto-name pattern: news-1 / news-2 / ... — first unused index."""
    existing_set = set(existing)
    n = 1
    while True:
        name = f"news-{n}"
        if name not in existing_set:
            return name
        n += 1


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
    suggest_name=_suggest_instance_name,
))
