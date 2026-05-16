"""News-video material on-disk path resolution.

Slice M (ADR-0005) moves all source / subtitles / analysis data from
project-direct children (`<project>/source/`, `<project>/subtitles/`)
to per-instance directories (`<project>/materials/news_video/<inst>/source/`,
`.../subtitles/`).

This module is the ONE place that knows the on-disk layout of a
news_video instance. Callers pass (project, instance_id) and get back
absolute paths. NewsVideoModel (slice N) will wrap these and become
the canonical access surface; callers that still pass strings can stay
on these helpers until they migrate.

DEFAULT_INSTANCE is a transitional convenience. The single-instance
assumption is hard-coded only inside the slice M migration period;
slice P kills DEFAULT_INSTANCE and forces callers to name their
instance explicitly.
"""

from __future__ import annotations

import os

# ── Filename conventions (used to live in project.py) ────────────────

SOURCE_VIDEO_FILENAME = "video.mp4"
SOURCE_META_FILENAME = "meta.json"

# ── Slice M transitional default instance name ───────────────────────

DEFAULT_INSTANCE = "default"


def instance_dir(project, instance_id: str = DEFAULT_INSTANCE) -> str:
    """<project>/materials/news_video/<instance_id>/"""
    return project.material_instance_dir("news_video", instance_id)


def source_dir(project, instance_id: str = DEFAULT_INSTANCE) -> str:
    return os.path.join(instance_dir(project, instance_id), "source")


def subtitles_dir(project, instance_id: str = DEFAULT_INSTANCE) -> str:
    return os.path.join(instance_dir(project, instance_id), "subtitles")


def source_video_path(project, instance_id: str = DEFAULT_INSTANCE) -> str:
    return os.path.join(source_dir(project, instance_id), SOURCE_VIDEO_FILENAME)


def source_meta_path(project, instance_id: str = DEFAULT_INSTANCE) -> str:
    return os.path.join(source_dir(project, instance_id), SOURCE_META_FILENAME)


def source_status(project, instance_id: str = DEFAULT_INSTANCE) -> str:
    """Returns 'ready' if source/video.mp4 is a non-empty file, else 'missing'."""
    path = source_video_path(project, instance_id)
    try:
        return "ready" if os.path.isfile(path) and os.path.getsize(path) > 0 else "missing"
    except OSError:
        return "missing"


def ensure_default_instance(project) -> None:
    """Create materials/news_video/default/source + subtitles dirs if missing.

    Slice M auto-bootstraps a default instance so existing code paths
    (which assume single-source semantics) keep functioning. Slice P
    removes this auto-bootstrap and forces user-driven [+] creation.
    """
    inst = instance_dir(project, DEFAULT_INSTANCE)
    if not os.path.isdir(inst):
        os.makedirs(os.path.join(inst, "source"), exist_ok=True)
        os.makedirs(os.path.join(inst, "subtitles"), exist_ok=True)
