"""materials registry + news_video MaterialType registration."""

from __future__ import annotations

import materials
import materials.news_video  # noqa: F401  triggers self-register
from materials import MaterialType


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
# hooks; they are de-registered. Post-ADR-0008 B5: the Python instance_factory /
# model were retired too — the material data model lives in TS and instances are
# created via the project.create_material_instance RPC. Only type metadata remains.

def test_news_video_has_required_fields():
    mt = materials.get("news_video")
    assert mt.type_name == "news_video"
    assert mt.display_name_key == "material.news_video"
    assert mt.icon == "📺"
    assert mt.description_zh
    assert mt.description_en
    assert mt.single_instance is True
    assert callable(mt.suggest_name)


def test_has_instance_field_retired_from_dataclass():
    """ADR-0005 slice P retired has_instance in favor of
    project.list_material_instances. Regression guard."""
    assert "has_instance" not in MaterialType.__dataclass_fields__


def test_instance_factory_retired_from_dataclass():
    """ADR-0008 B5 retired the Python instance_factory (model lives in TS)."""
    assert "instance_factory" not in MaterialType.__dataclass_fields__
