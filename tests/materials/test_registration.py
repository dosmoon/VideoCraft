"""materials registry + news_video MaterialType registration."""

from __future__ import annotations

import inspect
import os

import materials
import materials.news_video  # noqa: F401  triggers self-register
from materials import MaterialType
from materials.news_video.model import NewsVideoModel


# ── Registry mechanism ───────────────────────────────────────────────────────

def test_news_video_self_registers():
    assert materials.get("news_video") is not None


def test_all_types_includes_news_video():
    type_names = [t.type_name for t in materials.all_types()]
    assert "news_video" in type_names


def test_register_is_idempotent():
    """Re-registering the same type doesn't duplicate it."""
    mt = materials.get("news_video")
    before = len(materials.all_types())
    materials.register(mt)
    assert len(materials.all_types()) == before


def test_get_unknown_returns_none():
    assert materials.get("definitely_not_a_type") is None


# ── MaterialType field contract ──────────────────────────────────────────────

def test_news_video_has_required_fields():
    mt = materials.get("news_video")
    assert mt.type_name == "news_video"
    assert mt.display_name_key == "material.news_video"
    assert mt.icon == "📺"
    assert mt.description_zh
    assert mt.description_en
    assert callable(mt.sidebar_renderer)
    assert callable(mt.create_handler)
    assert callable(mt.instance_factory)


def test_has_instance_field_retired_from_dataclass():
    """ADR-0005 slice P retired has_instance in favor of
    project.list_material_instances. Regression guard."""
    assert "has_instance" not in MaterialType.__dataclass_fields__


# ── Signatures (what the Hub expects to call) ────────────────────────────────

def test_sidebar_renderer_signature():
    mt = materials.get("news_video")
    params = list(inspect.signature(mt.sidebar_renderer).parameters.keys())
    assert params == ["parent", "hub", "instance_id"]


def test_create_handler_signature():
    mt = materials.get("news_video")
    params = list(inspect.signature(mt.create_handler).parameters.keys())
    assert params == ["hub"]


def test_instance_factory_signature():
    mt = materials.get("news_video")
    params = list(inspect.signature(mt.instance_factory).parameters.keys())
    assert params == ["project", "instance_id"]


def test_instance_factory_returns_news_video_model(tmp_project):
    mt = materials.get("news_video")
    m = mt.instance_factory(tmp_project, "news-1")
    assert isinstance(m, NewsVideoModel)
    assert m.instance_id == "news-1"


# ── create_handler behavior (drives [+] popup → new instance) ────────────────

class _HubStub:
    """Minimal hub stub: only the attributes create_handler reaches for."""
    def __init__(self, project, root=None):
        self.project = project
        self.root = root
        self.refresh_count = 0

    def _refresh_project_tab(self):
        self.refresh_count += 1


def test_create_handler_creates_instance_dir(tmp_project):
    mt = materials.get("news_video")
    hub = _HubStub(tmp_project)
    assert tmp_project.list_material_instances("news_video") == []
    mt.create_handler(hub)
    assert tmp_project.list_material_instances("news_video") == ["news-1"]


def test_create_handler_auto_increments_name(tmp_project):
    mt = materials.get("news_video")
    hub = _HubStub(tmp_project)
    mt.create_handler(hub)
    mt.create_handler(hub)
    mt.create_handler(hub)
    assert tmp_project.list_material_instances("news_video") == [
        "news-1", "news-2", "news-3",
    ]


def test_create_handler_writes_instance_json(tmp_project):
    mt = materials.get("news_video")
    hub = _HubStub(tmp_project)
    mt.create_handler(hub)
    inst_json = os.path.join(
        tmp_project.material_instance_dir("news_video", "news-1"),
        "instance.json",
    )
    assert os.path.isfile(inst_json)


def test_create_handler_writes_skeleton_subdirs(tmp_project):
    mt = materials.get("news_video")
    hub = _HubStub(tmp_project)
    mt.create_handler(hub)
    inst_dir = tmp_project.material_instance_dir("news_video", "news-1")
    assert os.path.isdir(os.path.join(inst_dir, "source"))
    assert os.path.isdir(os.path.join(inst_dir, "subtitles"))


def test_create_handler_triggers_refresh(tmp_project):
    mt = materials.get("news_video")
    hub = _HubStub(tmp_project)
    mt.create_handler(hub)
    assert hub.refresh_count == 1
