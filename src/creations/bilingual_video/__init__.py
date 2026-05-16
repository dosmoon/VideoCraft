"""Bilingual-video creation plugin: render source video with burned-in
bilingual subtitles.

Importing this package self-registers the CreationType.
"""

from __future__ import annotations

from creations import CreationType, register

register(CreationType(
    type_name="bilingual_video",
    display_name_key="derivative.subtitle_video",  # renamed to creation.bilingual_video in slice I
    tool_key="subtitle",
    default_basename="default",
    single_instance=True,
    description_zh="把源视频和字幕烧录成成片(单语或双语)",
    description_en="Render the source video with burned-in subtitles",
))
