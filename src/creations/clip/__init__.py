"""Clip creation plugin: AI-driven batch-cut short clips from
subtitle-derived hotclips.

Importing this package self-registers the CreationType.

ADR-0008: this plugin's logic lives entirely in TS (desktop/src/creations/clip/);
the sidecar only needs the type metadata for the framework directory lifecycle
(create/rename/delete instance, dir resolution). No Python config owner / preview
/ render / preset providers remain.
"""

from __future__ import annotations

from creations import CreationType, register

register(CreationType(
    type_name="clip",
    display_name_key="creation.clip",        # renamed to creation.clip in slice I
    tool_key="clip",
    default_basename="default",
    single_instance=False,
    description_zh="基于字幕热点片段，批量切出短视频",
    description_en="Batch-cut short clips from subtitle hotclips",
))
