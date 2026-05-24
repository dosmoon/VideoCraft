"""Unit tests to verify default components shapes and chapters_io envelope round-trips.

Guards Creations and Materials component structure schemas against silent breakages.
"""

from __future__ import annotations

import os
import json
import pytest

from core.chapters_io import (
    load_analysis,
    save_analysis,
    save_analysis_chapters_only,
    normalize_chapters,
    parse_time_str,
    fmt_time_str,
)

# Import registries to trigger side effects
from creations.clip.components import spec_for_kind as clip_spec, spec_for_instance as clip_inst_spec
from creations.news_desk.components import REGISTRY as news_desk_registry, ComponentDictAdapter


# ── 1. Creations default_instance and ComponentSpec validation ───────────

def test_clip_components_default_instances():
    """Verify that all clip components in the registry can generate valid
    default_instance dicts and hold required fields."""
    kinds = ["clip_subtitle", "clip_hook_card", "clip_outro_card", "clip_text_watermark", "clip_image_watermark"]
    
    for k in kinds:
        spec = clip_spec(k)
        assert spec is not None, f"Clip spec for kind {k} is missing"
        assert spec.kind == k
        
        # Factory test
        inst = spec.default_instance(60.0)
        assert isinstance(inst, dict)
        assert inst["kind"] == k
        assert "enabled" in inst


def test_news_desk_components_default_instances():
    """Verify that all news_desk components in the registry generate valid default_instances."""
    assert len(news_desk_registry) > 0
    
    for kind, spec in news_desk_registry.items():
        assert spec.kind == kind
        assert spec.compile is not None
        
        inst = spec.default_instance(120.0)
        assert isinstance(inst, dict)
        assert inst["kind"] == kind
        
        # Test dict adapter wrapping
        adapter = ComponentDictAdapter(inst)
        assert adapter.kind == kind
        assert adapter.id == inst.get("id", "")
        assert adapter.is_enabled() is True


# ── 2. chapters_io Subtitle Envelope Validation ──────────────────────────

def test_time_parsing_and_formatting():
    assert parse_time_str("00:00:15") == 15.0
    assert parse_time_str("01:30:00") == 5400.0
    assert parse_time_str("02:15") == 135.0  # mm:ss format
    
    assert fmt_time_str(15.0) == "00:00:15"
    assert fmt_time_str(5400.0) == "01:30:00"
    assert fmt_time_str(0.0) == "00:00:00"


def test_normalize_chapters_enforces_invariants():
    """Verify normalize_chapters sorts, fills missing starts, and removes degenerates."""
    chapters = [
        # Chapter 2 (out of order start)
        {"start": "00:00:10", "title": "Second Section", "refined": "Narrative 2", "key_points": ["KP 2"]},
        # Chapter 1 (starts after 0, triggers synthetic intro insertion)
        {"start": "00:00:03", "title": "First Real Chapter", "refined": "Narrative 1", "key_points": ["KP 1"]},
        # Degenerate chapter (end_sec <= start_sec after sort)
        {"start": "00:00:10", "title": "Duplicate / Degenerate", "refined": "Narrative 3"}
    ]
    
    normalized = normalize_chapters(chapters, srt_end_sec=30.0, lang_iso="zh-CN")
    
    # Invariants check:
    # 1. First chapter must start at 00:00:00 (synthetic intro inserted because first real start was 03s)
    # 2. Duplicate starts / degenerates removed (size should be 3: Intro, 3s, 10s)
    assert len(normalized) == 3
    
    # 1st chapter: Intro
    assert normalized[0]["start"] == "00:00:00"
    assert normalized[0]["end"] == "00:00:03"
    assert normalized[0]["title"] == "开始"  # zh localized intro title
    assert normalized[0]["refined"] == ""
    assert normalized[0]["key_points"] == []
    
    # 2nd chapter: First Real
    assert normalized[1]["start"] == "00:00:03"
    assert normalized[1]["end"] == "00:00:10"
    assert normalized[1]["title"] == "First Real Chapter"
    
    # 3rd chapter: Duplicate / Degenerate (survives over "Second Section" at t=10s)
    assert normalized[2]["start"] == "00:00:10"
    assert normalized[2]["end"] == "00:00:30"  # clamped to srt_end_sec
    assert normalized[2]["title"] == "Duplicate / Degenerate"


def test_chapters_io_envelope_roundtrip(tmp_path):
    """Test full load/save cycle of subtitle analysis envelope json."""
    path = str(tmp_path / "analysis.json")
    titles = ["Sample Video Title 1", "Alternative Title"]
    chapters = [
        {"start": "00:00:05", "title": "Act I", "refined": "First movement", "key_points": ["Point A"]}
    ]
    
    # Save envelope
    envelope = save_analysis(
        path,
        titles=titles,
        chapters=chapters,
        srt_end_sec=40.0,
        lang_iso="en",
        source_subtitle="zh.srt"
    )
    
    assert envelope["schema_version"] == 2
    assert envelope["source_subtitle"] == "zh.srt"
    assert len(envelope["titles"]) == 2
    assert len(envelope["chapters"]) == 2  # Intro (0-5s) + Act I (5-40s)
    
    # Load back
    loaded = load_analysis(path)
    assert loaded["schema_version"] == 2
    assert loaded["titles"] == titles
    assert loaded["chapters"][0]["title"] == "Intro"  # en localized intro title
    assert loaded["chapters"][1]["title"] == "Act I"
    
    # Chapters-only update: change chapters, keep existing titles
    updated_chapters = [
        {"start": "00:00:00", "title": "Act I Redux", "refined": "Re-refined", "key_points": ["New Point"]}
    ]
    save_analysis_chapters_only(
        path,
        chapters=updated_chapters,
        srt_end_sec=50.0,
        lang_iso="en",
        source_subtitle="zh.srt"
    )
    
    loaded_redux = load_analysis(path)
    # Verify titles are preserved from disk, while chapters are updated
    assert loaded_redux["titles"] == titles
    assert len(loaded_redux["chapters"]) == 1
    assert loaded_redux["chapters"][0]["title"] == "Act I Redux"
    assert loaded_redux["chapters"][0]["end"] == "00:00:50"
