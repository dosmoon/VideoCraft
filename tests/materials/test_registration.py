"""materials registry + news_video MaterialType registration."""

from __future__ import annotations

import inspect

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
# Post-P2 (Tk app retired): sidebar_renderer / create_handler were the Tk-hub
# hooks; they are de-registered. The Electron shell creates instances via the
# project.create_material_instance RPC (covered by tests/core_rpc/test_material).

def test_news_video_has_required_fields():
    mt = materials.get("news_video")
    assert mt.type_name == "news_video"
    assert mt.display_name_key == "material.news_video"
    assert mt.icon == "📺"
    assert mt.description_zh
    assert mt.description_en
    assert callable(mt.instance_factory)


def test_has_instance_field_retired_from_dataclass():
    """ADR-0005 slice P retired has_instance in favor of
    project.list_material_instances. Regression guard."""
    assert "has_instance" not in MaterialType.__dataclass_fields__


# ── Signatures (what the sidecar expects to call) ────────────────────────────

def test_instance_factory_signature():
    mt = materials.get("news_video")
    params = list(inspect.signature(mt.instance_factory).parameters.keys())
    assert params == ["project", "instance_id"]


def test_instance_factory_returns_news_video_model(tmp_project):
    mt = materials.get("news_video")
    m = mt.instance_factory(tmp_project, "news-1")
    assert isinstance(m, NewsVideoModel)
    assert m.instance_id == "news-1"
