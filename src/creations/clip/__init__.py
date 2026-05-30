"""Clip creation plugin: AI-driven batch-cut short clips from
subtitle-derived hotclips.

Importing this package self-registers the CreationType.
"""

from __future__ import annotations

from creations import CreationType, register
from creations.clip.config import ClipInstanceConfig

register(CreationType(
    type_name="clip",
    display_name_key="creation.clip",        # renamed to creation.clip in slice I
    tool_key="clip",
    default_basename="default",
    single_instance=False,
    description_zh="基于字幕热点片段，批量切出短视频",
    description_en="Batch-cut short clips from subtitle hotclips",
    config_owner_cls=ClipInstanceConfig,
))
