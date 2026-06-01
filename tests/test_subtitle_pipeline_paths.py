"""Unit tests for the plugin-free path-based subtitle pipeline (ADR-0008 B2).

run_asr_paths / run_translate_paths take resolved paths (no Project, no
materials.news_video import) and leave project.meta to the caller. The legacy
run_asr(project) / run_translate(project) shims keep working (covered indirectly
by tests/core_rpc/test_material.py, which monkeypatches at the run_asr level).
"""

from __future__ import annotations

import os

import pytest

from core import subtitle_pipeline as sp


def _write(path: str, text: str = "1\n00:00:00,000 --> 00:00:01,000\nhi\n") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def test_run_asr_paths_writes_canonical_srt(tmp_path, monkeypatch):
    src_video = str(tmp_path / "source" / "video.mp4")
    _write(src_video, "fakevideobytes")
    subs = str(tmp_path / "subtitles")

    def fake_transcribe(audio_path, output_srt_path, **kw):
        # Provider writes an ugly suffixed name; the pipeline renames it.
        raw = os.path.join(os.path.dirname(output_srt_path), "auto_en.srt")
        _write(raw)
        return {"srt_path": raw, "detected_lang_iso": "en", "segment_count": 3, "json_path": None}

    monkeypatch.setattr("core.asr.transcribe_audio", fake_transcribe)

    result = sp.run_asr_paths(source_video_path=src_video, subtitles_dir=subs, source_lang_iso=None)
    assert result["lang_iso"] == "en"
    assert result["segment_count"] == 3
    assert result["srt_path"] == os.path.join(subs, "en.srt")
    assert os.path.isfile(os.path.join(subs, "en.srt"))
    assert not os.path.exists(os.path.join(subs, "auto_en.srt"))  # renamed away


def test_run_asr_paths_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        sp.run_asr_paths(
            source_video_path=str(tmp_path / "nope.mp4"),
            subtitles_dir=str(tmp_path / "subtitles"),
        )


def test_run_translate_paths_writes_canonical_srt(tmp_path, monkeypatch):
    subs = str(tmp_path / "subtitles")
    _write(os.path.join(subs, "en.srt"))

    def fake_translate(src_path, *, source_lang, target_lang, progress_cb=None, cancel_token=None):
        out = os.path.join(os.path.dirname(src_path), "Chinese.srt")
        _write(out)
        return out

    monkeypatch.setattr("core.translate.translate_srt_file", fake_translate)

    result = sp.run_translate_paths(subtitles_dir=subs, source_lang_iso="en", target_lang_iso="zh")
    assert result["lang_iso"] == "zh"
    assert result["srt_path"] == os.path.join(subs, "zh.srt")
    assert os.path.isfile(os.path.join(subs, "zh.srt"))
    assert not os.path.exists(os.path.join(subs, "Chinese.srt"))  # renamed to canonical


def test_run_translate_paths_validates(tmp_path):
    subs = str(tmp_path / "subtitles")
    with pytest.raises(ValueError):  # empty source lang
        sp.run_translate_paths(subtitles_dir=subs, source_lang_iso="", target_lang_iso="zh")
    _write(os.path.join(subs, "en.srt"))
    with pytest.raises(ValueError):  # same language
        sp.run_translate_paths(subtitles_dir=subs, source_lang_iso="en", target_lang_iso="en")
    with pytest.raises(FileNotFoundError):  # source srt absent
        sp.run_translate_paths(subtitles_dir=subs, source_lang_iso="fr", target_lang_iso="zh")


def test_path_functions_take_no_project():
    """Guard the plugin-free contract: neither path function accepts a project."""
    import inspect

    for fn in (sp.run_asr_paths, sp.run_translate_paths):
        assert "project" not in inspect.signature(fn).parameters
