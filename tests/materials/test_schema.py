"""materials/news_video/schema.py — dataclass + JSON IO + context prompt."""

from __future__ import annotations

import json
import os

from materials.news_video.schema import (
    SourceBasicInfo, SourceContext,
    basic_info_path, context_path,
    read_basic_info, write_basic_info,
    read_context, write_context,
    context_prompt_block,
)


# ── Dataclass shape ──────────────────────────────────────────────────────────

def test_source_basic_info_has_5_anchor_fields():
    assert set(SourceBasicInfo.__dataclass_fields__) == {
        "host", "host_bio", "event_date",
        "event_location", "episode_topic",
    }


def test_source_context_has_15_fields():
    assert len(SourceContext.__dataclass_fields__) == 15


def test_source_context_contains_anchor_fields():
    """Anchor fields appear in both basic_info AND context (AI's corrected version)."""
    ctx_fields = set(SourceContext.__dataclass_fields__)
    anchor = {"host", "host_bio", "event_date", "event_location", "episode_topic"}
    assert anchor.issubset(ctx_fields)


# ── Roundtrip ────────────────────────────────────────────────────────────────

def test_source_context_roundtrip():
    ctx = SourceContext(host="A", host_bio="B", episode_topic="T")
    d = ctx.to_dict()
    restored = SourceContext.from_dict(d)
    assert restored.host == "A"
    assert restored.host_bio == "B"
    assert restored.episode_topic == "T"


def test_source_context_from_dict_drops_unknown_keys():
    """Legacy JSON with extra keys still loads (forward compat)."""
    d = {"host": "A", "unknown_field": "x"}
    ctx = SourceContext.from_dict(d)
    assert ctx.host == "A"


def test_source_basic_info_is_empty():
    assert SourceBasicInfo().is_empty()
    assert not SourceBasicInfo(host="A").is_empty()


# ── File IO ──────────────────────────────────────────────────────────────────

def test_write_read_basic_info(tmp_path):
    src_dir = str(tmp_path / "source")
    info = SourceBasicInfo(host="HOST", episode_topic="TOPIC")
    write_basic_info(src_dir, info)
    assert os.path.isfile(basic_info_path(src_dir))
    restored = read_basic_info(src_dir)
    assert restored.host == "HOST"
    assert restored.episode_topic == "TOPIC"


def test_read_basic_info_missing_returns_empty(tmp_path):
    info = read_basic_info(str(tmp_path / "absent"))
    assert info.is_empty()


def test_write_read_context(tmp_path):
    src_dir = str(tmp_path / "source")
    ctx = SourceContext(host="X", background="ctx")
    write_context(src_dir, ctx)
    assert os.path.isfile(context_path(src_dir))
    restored = read_context(src_dir)
    assert restored.host == "X"
    assert restored.background == "ctx"


def test_read_context_missing_returns_empty(tmp_path):
    ctx = read_context(str(tmp_path / "absent"))
    assert ctx.is_empty()


# ── Context prompt block ────────────────────────────────────────────────────

def test_context_prompt_block_ignores_basic_info(tmp_path):
    """basic_info is AI input only — must never bleed into the prompt block."""
    src_dir = str(tmp_path / "source")
    write_basic_info(src_dir, SourceBasicInfo(host="USER_HINT"))
    # context.json empty → block is empty even though basic_info has data.
    assert context_prompt_block(src_dir) == ""


def test_context_prompt_block_empty_when_blank(tmp_path):
    src_dir = str(tmp_path / "source")
    assert context_prompt_block(src_dir) == ""


def test_context_prompt_block_renders_filled_fields(tmp_path):
    src_dir = str(tmp_path / "source")
    write_context(src_dir, SourceContext(
        host="H", episode_topic="T", background="B"))
    block = context_prompt_block(src_dir)
    assert "主讲人" in block
    assert "H" in block
    assert "整集主题" in block
    assert "T" in block
    assert "背景" in block
    assert "B" in block


def test_context_prompt_block_omits_empty_fields(tmp_path):
    """Empty fields don't render to avoid 'host:   ' style noise.
    Check at line level: each rendered field becomes a '- 标签: 值' line."""
    src_dir = str(tmp_path / "source")
    write_context(src_dir, SourceContext(host="ONLY_HOST"))
    block = context_prompt_block(src_dir)
    field_lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    # Only one field rendered → exactly one field line.
    assert len(field_lines) == 1
    assert "ONLY_HOST" in field_lines[0]
