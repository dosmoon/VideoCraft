"""SRT translation feature layer.

UI layer calls translate_srt_file() with progress callbacks; this module owns
all AI orchestration. Per architecture principle 1 (see
docs/design/04-ai-router.md), UI must not touch core.ai directly —
TranslateApp goes through this module.

Phase 1 preserves the batch-with-JSON-schema approach inherited from
tools/translate/translate_srt.py. Phase 7 will layer in proper error
classification via AIError.Kind so feature + UI can give targeted recovery
hints.
"""

import os
import re
import time
from typing import Callable

import srt

from core import ai
from core import prompts as _prompts
from core.ai.tiers import TIER_STANDARD
from core.lang_names import WHISPER_LANGUAGES
from core.subtitle_ops import read_srt


# Language data lives in core.lang_names.WHISPER_LANGUAGES (imported above).
# Removed on 2026-05-06: SUPPORTED_LANGUAGES / get_language_options() /
# get_lang_code(). Call sites now use WHISPER_LANG_CHOICES /
# WHISPER_DISPLAY_TO_ISO directly.


# ── JSON schema for batch translation ────────────────────────────────────────
# Models return {"translations": [{"index": int, "text": str}, ...]} where
# index matches the 【N】 marker in the prompt input (1-based).

_TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "text":  {"type": "string"},
                },
                "required": ["index", "text"],
            },
        },
    },
    "required": ["translations"],
}


# ── Public API ───────────────────────────────────────────────────────────────


def translate_srt_file(
    srt_path: str,
    *,
    source_lang: str,
    target_lang: str,
    custom_prompt: str | None = None,
    batch_size: int = 100,
    tier: str = TIER_STANDARD,
    progress_cb: Callable[[int, int, str], None] | None = None,
    log_cb: Callable[[str], None] | None = None,
    cancel_token=None,
) -> str:
    """Batch-translate an SRT file, writing output next to the source.

    Args:
        srt_path:      Path to input .srt file.
        source_lang:   ISO code of source language ("en", "auto", ...).
        target_lang:   ISO code of target language.
        custom_prompt: Optional prompt template override. When None (the
                       normal case), loads `prompts.get("translate")` from
                       the Prompt hub. Placeholders the template must
                       contain: {source_lang_name}, {target_lang_name},
                       {batch_size}, {numbered_input}.
        batch_size:    Subtitles per AI call. Defaults to 100.
        tier:          "premium" | "standard" | "economy".
        progress_cb:   Optional (done_batches, total_batches, status_msg)
                       callback fired between batches. Per architecture X5,
                       the semantics is "partial result ready" — Phase 1
                       fires per-batch, future streaming might fire more
                       granularly without callback shape change.
        log_cb:        Optional verbose line logger (printed to Hub log).

    Returns:
        Absolute path to the written output .srt (named
        <target_lang_english>.srt next to the input file).

    Raises:
        FileNotFoundError: source SRT missing or unreadable.
        RuntimeError:      SRT parse failed / no batches produced / output
                           could not be written. AI per-batch failures fall
                           back to original text so the overall task
                           completes with a partial translation.
    """
    subs = list(srt.parse(read_srt(srt_path)))

    template = custom_prompt if custom_prompt is not None else _prompts.get("translate")

    # ISO -> English name for the prompt template ("Translate from <X> to <Y>").
    # Unknown ISO codes degrade to "Unknown" so prompts still render; LLMs
    # tolerate this and the actual translation usually still works.
    source_lang_name = WHISPER_LANGUAGES.get(source_lang, ('Unknown', '未知'))[0]
    target_lang_name = WHISPER_LANGUAGES.get(target_lang, ('Unknown', '未知'))[0]

    if log_cb:
        log_cb(f"准备翻译 {len(subs)} 条字幕")

    # Number markers are batch-local (1..cur_batch_size) so the model's
    # returned `index` maps directly to a slot inside the current batch.
    # Using a global numbering here would break batches after the first,
    # because the matcher below treats `index` as batch-local.
    raw_contents = [sub.content for sub in subs]
    batches = []
    for i in range(0, len(raw_contents), batch_size):
        slice_ = raw_contents[i:i + batch_size]
        numbered = [f"【{j+1}】{text}" for j, text in enumerate(slice_)]
        batches.append({'start_idx': i, 'contents': numbered})
    total = len(batches)

    if log_cb:
        log_cb(f"分成 {total} 个批次进行翻译")

    translated_subs: dict[int, str] = {}

    for batch_idx, batch in enumerate(batches):
        # Cooperative cancel: between batches the user can bail and we stop
        # without writing the partial output. Re-raising the CANCELLED
        # AIError out of the loop so the UI's existing AIError handling
        # picks it up; per-batch fallback below intentionally skips it.
        if cancel_token is not None:
            cancel_token.throw_if_cancelled("Translate")

        if progress_cb:
            progress_cb(
                batch_idx, total,
                f"正在翻译 ({source_lang.upper()} → {target_lang.upper()}) "
                f"- 批次 {batch_idx+1}/{total}",
            )

        batch_start_idx = batch['start_idx']
        batch_contents  = batch['contents']
        cur_batch_size  = len(batch_contents)
        numbered_input  = '\n\n'.join(batch_contents)

        prompt = (template
                  .replace("{source_lang_name}", source_lang_name)
                  .replace("{target_lang_name}", target_lang_name)
                  .replace("{batch_size}", str(cur_batch_size))
                  .replace("{numbered_input}", numbered_input))

        try:
            parsed = ai.complete_json(
                prompt,
                schema=_TRANSLATE_SCHEMA,
                task="translate",
                tier=tier,
            )
        except Exception as e:
            # Cancellation must propagate, not fall back to original text.
            from core.ai.errors import AIError, Kind
            if isinstance(e, AIError) and e.kind == Kind.CANCELLED:
                raise
            if log_cb:
                log_cb(f"❌ 批次 {batch_idx+1} AI 调用失败: {e}")
            # Fall back to original text so the overall task keeps going.
            for i, line in enumerate(batch_contents):
                text_only = re.sub(r'^【\d+】\s*', '', line)
                translated_subs[batch_start_idx + i] = text_only
            if batch_idx < total - 1:
                time.sleep(0.5)
            continue

        items = parsed.get("translations", []) if isinstance(parsed, dict) else []
        if len(items) != cur_batch_size and log_cb:
            log_cb(f"⚠️ 批次 {batch_idx+1} 字幕数量不匹配: "
                   f"期望 {cur_batch_size}, 实际 {len(items)}")

        matched = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                local_idx = int(item.get("index", 0)) - 1
            except (TypeError, ValueError):
                continue
            text = item.get("text", "")
            if not isinstance(text, str):
                continue
            if 0 <= local_idx < cur_batch_size:
                translated_subs[batch_start_idx + local_idx] = text
                matched += 1

        # Fill any holes with originals so output stays dense.
        for i in range(cur_batch_size):
            global_idx = batch_start_idx + i
            if global_idx not in translated_subs:
                text_only = re.sub(r'^【\d+】\s*', '', batch_contents[i])
                translated_subs[global_idx] = text_only

        if log_cb:
            log_cb(f"📍 批次 {batch_idx+1} 完成 (匹配 {matched}/{cur_batch_size})")

        if batch_idx < total - 1:
            time.sleep(0.5)

    # Apply translated content (originals kept for any subtitle still missing).
    untranslated_count = 0
    for i, sub in enumerate(subs):
        if i in translated_subs:
            sub.content = translated_subs[i]
        else:
            untranslated_count += 1

    if log_cb:
        if untranslated_count:
            log_cb(f"共 {untranslated_count} 条字幕未翻译，保持原文")
        else:
            log_cb(f"成功: 所有 {len(subs)} 条字幕都已翻译")

    # Write output SRT named after the target language
    output_dir  = os.path.dirname(srt_path)
    output_file = os.path.join(output_dir, f"{target_lang_name}.srt")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(srt.compose(subs))

    if progress_cb:
        progress_cb(total, total, "翻译完成")

    return output_file
