"""translate_srt_file error-surfacing contract.

A systematic AI failure (disabled / misconfigured provider, missing key) must
FAIL the translate loudly, not silently write an all-original "translation"
that then trips confusing downstream subtitle checks. A genuine partial
success still completes.
"""

from __future__ import annotations

import pytest

import core.translate as t

# A custom prompt avoids depending on the Prompt hub; it carries the four
# placeholders translate_srt_file fills.
_PROMPT = "to {target_lang_name} from {source_lang_name} ({batch_size}):\n{numbered_input}"


def _make_srt(path) -> str:
    path.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello world\n", encoding="utf-8"
    )
    return str(path)


def test_translate_raises_when_all_batches_fail(tmp_path, monkeypatch):
    src = _make_srt(tmp_path / "en.srt")

    def boom(*_a, **_k):
        raise RuntimeError("Provider 'claude_code' (picked for task 'translate') is disabled")

    monkeypatch.setattr("core.ai.complete_json", boom)
    with pytest.raises(RuntimeError, match="翻译失败"):
        t.translate_srt_file(src, source_lang="en", target_lang="zh", custom_prompt=_PROMPT)


def test_translate_success_writes_output(tmp_path, monkeypatch):
    src = _make_srt(tmp_path / "en.srt")
    monkeypatch.setattr(
        "core.ai.complete_json",
        lambda *_a, **_k: {"translations": [{"index": 1, "text": "你好世界"}]},
    )
    out = t.translate_srt_file(src, source_lang="en", target_lang="zh", custom_prompt=_PROMPT)
    assert out.endswith(".srt")
    with open(out, encoding="utf-8") as f:
        assert "你好世界" in f.read()
