"""materials/news_video/model.py — NewsVideoModel state + business surface.

These tests verify the model's contract WITHOUT Tk, AI, or pipeline
runs. ASR / translate / AI fill are covered separately when (and if)
they get mocked — they're integration-heavy.
"""

from __future__ import annotations

import os
import pytest

from materials.news_video.model import (
    NewsVideoModel, SlotState,
    SLOT_SOURCE, SLOT_NEWS_CONTEXT, SLOT_SUBTITLES,
)
from materials.news_video.schema import SourceContext, SourceBasicInfo


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def model(tmp_project):
    """A model bound to a fresh 'news-1' instance with skeleton dirs."""
    inst_dir = tmp_project.create_material_instance(
        "news_video", "news-1",
        initial_config={"type_name": "news_video", "instance_name": "news-1"},
        config_filename="instance.json",
    )
    os.makedirs(os.path.join(inst_dir, "source"), exist_ok=True)
    os.makedirs(os.path.join(inst_dir, "subtitles"), exist_ok=True)
    return NewsVideoModel(tmp_project, "news-1")


def _write_fake_source_video(model: NewsVideoModel) -> None:
    """Pretend the source video has been acquired."""
    os.makedirs(model.source_dir, exist_ok=True)
    with open(model.source_video_path, "wb") as f:
        f.write(b"\x00" * 16)


def _write_srt(model: NewsVideoModel, lang_iso: str, content: str = "") -> None:
    """Drop a minimal SRT for `lang_iso` into the subtitles dir."""
    os.makedirs(model.subtitles_dir, exist_ok=True)
    path = os.path.join(model.subtitles_dir, f"{lang_iso}.srt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content or
                "1\n00:00:00,000 --> 00:00:02,000\nhello\n\n")


# ── Identity / paths ─────────────────────────────────────────────────────────

def test_instance_id_matches_constructor(tmp_project):
    m = NewsVideoModel(tmp_project, "news-7")
    assert m.instance_id == "news-7"


def test_instance_id_defaults_via_paths_when_omitted(tmp_project):
    tmp_project.create_material_instance("news_video", "news-1")
    m = NewsVideoModel(tmp_project)
    assert m.instance_id == "news-1"


def test_paths_correctly_resolved(model):
    assert model.instance_dir.endswith(os.path.join("news_video", "news-1"))
    assert model.source_dir.endswith(os.path.join("news-1", "source"))
    assert model.subtitles_dir.endswith(os.path.join("news-1", "subtitles"))


# ── Source video slot ────────────────────────────────────────────────────────

def test_has_source_video_false_initially(model):
    assert not model.has_source_video()


def test_has_source_video_true_after_write(model):
    _write_fake_source_video(model)
    assert model.has_source_video()


# ── Subtitles slot ───────────────────────────────────────────────────────────

def test_list_subtitle_languages_empty(model):
    assert model.list_subtitle_languages() == []


def test_list_subtitle_languages_sorted(model):
    _write_srt(model, "en")
    _write_srt(model, "zh")
    _write_srt(model, "fr")
    assert model.list_subtitle_languages() == ["en", "fr", "zh"]


def test_has_subtitle(model):
    assert not model.has_subtitle("zh")
    _write_srt(model, "zh")
    assert model.has_subtitle("zh")


def test_subtitle_path_format(model):
    p = model.subtitle_path("zh")
    assert p.endswith(os.path.join("subtitles", "zh.srt"))


def test_import_subtitle_writes_file(tmp_path, model):
    """import_subtitle copies an external SRT into the instance."""
    external = tmp_path / "external.srt"
    external.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    model.import_subtitle(str(external), "zh")
    assert model.has_subtitle("zh")


def test_import_subtitle_sets_source_language(tmp_path, model):
    """First imported SRT becomes the project's source language."""
    assert model.source_language() is None
    external = tmp_path / "external.srt"
    external.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    model.import_subtitle(str(external), "en")
    assert model.source_language() == "en"


def test_import_subtitle_does_not_overwrite_existing_source_lang(tmp_path, model):
    """Once source language is set, importing another lang doesn't override it."""
    external = tmp_path / "external.srt"
    external.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    model.import_subtitle(str(external), "zh")
    model.import_subtitle(str(external), "en")
    assert model.source_language() == "zh"


# ── News context slot ────────────────────────────────────────────────────────

def test_context_completion_empty(model):
    filled, total = model.context_completion()
    assert filled == 0
    assert total == 15


def test_context_completion_partial(model):
    model.write_context(SourceContext(host="H", episode_topic="T"))
    filled, total = model.context_completion()
    assert filled == 2
    assert total == 15


# ── slot_readiness ───────────────────────────────────────────────────────────

def test_slot_readiness_returns_all_slots(model):
    states = model.slot_readiness()
    assert set(states.keys()) == {SLOT_SOURCE, SLOT_NEWS_CONTEXT, SLOT_SUBTITLES}
    assert all(isinstance(s, SlotState) for s in states.values())


def test_slot_readiness_empty(model):
    states = model.slot_readiness()
    assert not states[SLOT_SOURCE].is_filled
    assert states[SLOT_NEWS_CONTEXT].is_locked
    assert states[SLOT_SUBTITLES].is_locked


def test_slot_readiness_unlocks_after_source(model):
    _write_fake_source_video(model)
    states = model.slot_readiness()
    assert states[SLOT_SOURCE].is_filled
    assert not states[SLOT_NEWS_CONTEXT].is_locked
    assert not states[SLOT_SUBTITLES].is_locked


def test_slot_readiness_subtitles_filled_with_lang(model):
    _write_fake_source_video(model)
    _write_srt(model, "zh")
    states = model.slot_readiness()
    assert states[SLOT_SUBTITLES].is_filled


# ── get_artifact ─────────────────────────────────────────────────────────────

def test_get_artifact_source_present(model):
    _write_fake_source_video(model)
    art = model.get_artifact("source")
    assert art is not None
    assert art.name == "video.mp4"


def test_get_artifact_source_absent(model):
    assert model.get_artifact("source") is None


def test_get_artifact_subtitle(model):
    _write_srt(model, "zh")
    art = model.get_artifact("subtitle:zh")
    assert art is not None
    assert art.name == "zh.srt"


def test_get_artifact_subtitle_missing(model):
    assert model.get_artifact("subtitle:zh") is None


def test_get_artifact_basic_info(model):
    model.write_basic_info(SourceBasicInfo(host="H"))
    assert model.get_artifact("basic_info") is not None


def test_get_artifact_context(model):
    model.write_context(SourceContext(host="H"))
    assert model.get_artifact("context") is not None


def test_get_artifact_unknown_key_returns_none(model):
    assert model.get_artifact("nonsense_key") is None


# ── Change notification ──────────────────────────────────────────────────────

def test_subscribe_notify_roundtrip(model):
    calls: list[int] = []
    model.subscribe(lambda: calls.append(1))
    model._notify()
    assert calls == [1]


def test_subscribe_fires_on_write(model):
    calls: list[int] = []
    model.subscribe(lambda: calls.append(1))
    model.write_basic_info(SourceBasicInfo(host="H"))
    assert len(calls) == 1


def test_subscribe_multiple_subscribers(model):
    a, b = [], []
    model.subscribe(lambda: a.append(1))
    model.subscribe(lambda: b.append(1))
    model._notify()
    assert a == [1] and b == [1]


def test_subscribe_exception_does_not_break_others(model):
    a = []

    def bad():
        raise RuntimeError("boom")
    model.subscribe(bad)
    model.subscribe(lambda: a.append(1))
    model._notify()  # should NOT raise
    assert a == [1]
