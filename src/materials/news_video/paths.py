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

No-arg callers resolve via `default_instance(project)` — first-on-disk
wins, or the literal "default" when no instance exists. Slice Q
replaces no-arg calls in creation plugins with explicit
bound_material lookups.
"""

from __future__ import annotations

import os

# ── Filename conventions (used to live in project.py) ────────────────

SOURCE_VIDEO_FILENAME = "video.mp4"
SOURCE_META_FILENAME = "meta.json"

# ── Default-instance resolution ───────────────────────────────────────
#
# Slice P transitional: callers that don't pass an instance_id resolve
# to the FIRST instance on disk (alphabetical via list_material_instances).
# Returns the literal "default" only as a fallback for empty-state
# path computation. Slice Q replaces these no-arg calls in creation
# plugins with explicit bound_material lookups.

_FALLBACK_NAME = "default"


def default_instance(project) -> str:
    """Pick a sensible no-arg instance. First-on-disk wins; literal
    'default' is returned only when zero instances exist (so paths
    still resolve to writable locations during empty-state UI builds)."""
    try:
        existing = project.list_material_instances("news_video")
    except Exception:
        existing = []
    return existing[0] if existing else _FALLBACK_NAME


def instance_dir(project, instance_id: str | None = None) -> str:
    """<project>/materials/news_video/<instance_id>/"""
    inst = instance_id or default_instance(project)
    return project.material_instance_dir("news_video", inst)


def source_dir(project, instance_id: str | None = None) -> str:
    return os.path.join(instance_dir(project, instance_id), "source")


def subtitles_dir(project, instance_id: str | None = None) -> str:
    return os.path.join(instance_dir(project, instance_id), "subtitles")


def source_video_path(project, instance_id: str | None = None) -> str:
    return os.path.join(source_dir(project, instance_id), SOURCE_VIDEO_FILENAME)


def source_meta_path(project, instance_id: str | None = None) -> str:
    return os.path.join(source_dir(project, instance_id), SOURCE_META_FILENAME)


def source_status(project, instance_id: str | None = None) -> str:
    """Returns 'ready' if source/video.mp4 is a non-empty file, else 'missing'."""
    path = source_video_path(project, instance_id)
    try:
        return "ready" if os.path.isfile(path) and os.path.getsize(path) > 0 else "missing"
    except OSError:
        return "missing"
