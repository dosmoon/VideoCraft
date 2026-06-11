"""Output-language threading for the subtitle analysis AI runners.

Regression guard for the bug where "Generate titles & chapters" /
"Generate hot clips" on a non-Chinese subtitle always came back in
Chinese: lang_iso reached the runners but the prompts (written in
Chinese) never told the model which language to answer in. The fix
threads lang_iso → prompt_language_name → the {output_language}
directive in subtitle.pack / subtitle.hotclips, with an append
fallback for stale prompt override files that predate the placeholder.
"""

from __future__ import annotations

import pytest

import core.prompts
from core.lang_names import prompt_language_name
from core.prompts import DEFAULTS, apply_output_language


SRT_EN = (
    "1\n00:00:00,000 --> 00:00:02,000\nHello world, this is a test.\n\n"
    "2\n00:00:02,000 --> 00:00:04,000\nAnother line of speech here.\n"
)

GENERIC_DIRECTIVE = "the same language as the input subtitles"


@pytest.fixture(autouse=True)
def isolated_prompts_dir(tmp_path, monkeypatch):
    """Point prompts_dir at an empty tmp dir so the repo's prompts/*.md
    override files can't shadow DEFAULTS during these tests."""
    d = tmp_path / "prompts_override"
    d.mkdir()
    monkeypatch.setattr(core.prompts, "prompts_dir", lambda: str(d))
    return d


@pytest.fixture
def en_srt(tmp_path):
    p = tmp_path / "en.srt"
    p.write_text(SRT_EN, encoding="utf-8")
    return str(p)


# ── prompt_language_name ─────────────────────────────────────────────────────

def test_prompt_language_name_known_iso():
    assert prompt_language_name("en") == "English（英语）"
    assert prompt_language_name("zh") == "Chinese（中文）"
    assert prompt_language_name("EN") == "English（英语）"


def test_prompt_language_name_bcp47_region_tag():
    # Not in the Whisper catalog; resolved via the BCP47 name table.
    assert prompt_language_name("pt-BR") == "Portuguese (Brazil)（葡萄牙语（巴西））"


def test_prompt_language_name_fallbacks():
    assert prompt_language_name("xx") == "xx"
    assert prompt_language_name("") == ""
    assert prompt_language_name(None) == ""


# ── Templates carry the directive ────────────────────────────────────────────

def test_templates_carry_output_language_placeholder():
    assert "{output_language}" in DEFAULTS["subtitle.pack"]
    assert "{output_language}" in DEFAULTS["subtitle.hotclips"]


def test_apply_output_language_appends_when_placeholder_missing():
    out = apply_output_language("旧模板正文", "English（英语）")
    assert "English（英语）" in out
    assert out.startswith("旧模板正文")


def test_apply_output_language_no_language_no_placeholder_is_noop():
    assert apply_output_language("旧模板正文", "") == "旧模板正文"


# ── End-to-end threading: lang_iso → prompt sent to the AI ──────────────────

def _capture_complete_json(monkeypatch, result):
    """Patch core.ai.complete_json; record every prompt it receives."""
    import core.ai

    captured: list[str] = []

    def fake(prompt, **kwargs):
        captured.append(prompt)
        return result

    monkeypatch.setattr(core.ai, "complete_json", fake)
    return captured


PACK_RESULT = {
    "titles": ["A title"],
    "segments": [{"time_str": "00:00:00", "title": "Seg",
                  "refined": "Refined.", "key_points": []}],
}


def test_pack_analysis_injects_subtitle_language(tmp_path, en_srt, monkeypatch):
    from core.subtitle_analysis_runners import run_pack_analysis

    captured = _capture_complete_json(monkeypatch, PACK_RESULT)
    run_pack_analysis(en_srt, str(tmp_path), "en", None, None)

    assert len(captured) == 1
    assert "English（英语）" in captured[0]
    assert "{output_language}" not in captured[0]


def test_pack_analysis_with_context_block_still_injects(tmp_path, en_srt, monkeypatch):
    # The news-context block is typically Chinese — the directive must
    # survive the context-prepended prompt path too.
    from core.subtitle_analysis_runners import run_pack_analysis

    captured = _capture_complete_json(monkeypatch, PACK_RESULT)
    run_pack_analysis(en_srt, str(tmp_path), "en", None, None,
                      context_block="# 事件背景\n中文背景资料。")

    assert "English（英语）" in captured[0]
    assert "{output_language}" not in captured[0]


def test_pack_analysis_stale_override_still_gets_directive(
        isolated_prompts_dir, tmp_path, en_srt, monkeypatch):
    # A prompts-dir override predating {output_language} (e.g. a user's
    # edited prompt) must still produce a language directive via the
    # append fallback.
    (isolated_prompts_dir / "subtitle.pack.md").write_text(
        "旧版自定义模板。\n\n{subtitle_content}\n", encoding="utf-8")
    from core.subtitle_analysis_runners import run_pack_analysis

    captured = _capture_complete_json(monkeypatch, PACK_RESULT)
    run_pack_analysis(en_srt, str(tmp_path), "en", None, None)

    assert "English（英语）" in captured[0]


def test_hotclips_injects_subtitle_language(tmp_path, en_srt, monkeypatch):
    from core.subtitle_analysis_runners import run_hotclips

    captured = _capture_complete_json(monkeypatch, {"clips": []})
    run_hotclips(en_srt, str(tmp_path), "en", None, None)

    assert len(captured) == 1
    assert "English（英语）" in captured[0]
    assert "{output_language}" not in captured[0]


def test_generate_subtitle_pack_empty_language_degrades_generic(en_srt, monkeypatch):
    # No language supplied → generic "same language as the subtitles"
    # instruction; the literal placeholder must never reach the model.
    from core.srt_ops import generate_subtitle_pack

    captured = _capture_complete_json(monkeypatch, PACK_RESULT)
    generate_subtitle_pack(en_srt)

    assert "{output_language}" not in captured[0]
    assert GENERIC_DIRECTIVE in captured[0]
