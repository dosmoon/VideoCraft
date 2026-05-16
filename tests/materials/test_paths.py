"""materials/news_video/paths.py — path resolution + default instance fallback."""

from __future__ import annotations

import os

from materials.news_video import paths as _nv_paths


# ── default_instance ─────────────────────────────────────────────────────────

def test_default_instance_returns_first_on_disk(tmp_project):
    """When instances exist, no-arg fallback picks the first (alphabetical)."""
    tmp_project.create_material_instance("news_video", "news-1")
    tmp_project.create_material_instance("news_video", "news-2")
    assert _nv_paths.default_instance(tmp_project) == "news-1"


def test_default_instance_fallback_literal(tmp_project):
    """Empty project returns the literal 'default' (for empty-state paths)."""
    assert _nv_paths.default_instance(tmp_project) == "default"


# ── source/subtitles dir resolution ──────────────────────────────────────────

def test_instance_dir_format(tmp_project):
    d = _nv_paths.instance_dir(tmp_project, "news-1")
    assert d.endswith(os.path.join("materials", "news_video", "news-1"))


def test_source_dir_under_instance(tmp_project):
    d = _nv_paths.source_dir(tmp_project, "news-1")
    assert d.endswith(os.path.join("news_video", "news-1", "source"))


def test_subtitles_dir_under_instance(tmp_project):
    d = _nv_paths.subtitles_dir(tmp_project, "news-1")
    assert d.endswith(os.path.join("news_video", "news-1", "subtitles"))


def test_source_video_path_format(tmp_project):
    p = _nv_paths.source_video_path(tmp_project, "news-1")
    assert p.endswith(os.path.join("news-1", "source", "video.mp4"))


def test_source_meta_path_format(tmp_project):
    p = _nv_paths.source_meta_path(tmp_project, "news-1")
    assert p.endswith(os.path.join("news-1", "source", "meta.json"))


# ── No-arg defaulting ───────────────────────────────────────────────────────

def test_no_arg_uses_default_instance(tmp_project):
    tmp_project.create_material_instance("news_video", "news-1")
    no_arg = _nv_paths.source_dir(tmp_project)
    explicit = _nv_paths.source_dir(tmp_project, "news-1")
    assert no_arg == explicit


def test_no_arg_on_empty_project_uses_default_literal(tmp_project):
    p = _nv_paths.source_dir(tmp_project)
    assert os.path.join("news_video", "default", "source") in p


# ── source_status ───────────────────────────────────────────────────────────

def test_source_status_missing_when_no_file(tmp_project):
    tmp_project.create_material_instance("news_video", "news-1")
    assert _nv_paths.source_status(tmp_project, "news-1") == "missing"


def test_source_status_ready_when_file_exists(tmp_project):
    tmp_project.create_material_instance("news_video", "news-1")
    sd = _nv_paths.source_dir(tmp_project, "news-1")
    os.makedirs(sd, exist_ok=True)
    video = _nv_paths.source_video_path(tmp_project, "news-1")
    with open(video, "wb") as f:
        f.write(b"\x00" * 16)
    assert _nv_paths.source_status(tmp_project, "news-1") == "ready"


def test_source_status_missing_for_empty_file(tmp_project):
    tmp_project.create_material_instance("news_video", "news-1")
    sd = _nv_paths.source_dir(tmp_project, "news-1")
    os.makedirs(sd, exist_ok=True)
    video = _nv_paths.source_video_path(tmp_project, "news-1")
    open(video, "w").close()  # zero-byte
    assert _nv_paths.source_status(tmp_project, "news-1") == "missing"
