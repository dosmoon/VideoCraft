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
from core.subtitle_ops import read_srt


# ── Language catalog ─────────────────────────────────────────────────────────
# (ISO code -> (english_name, chinese_name)). UN-6 first, then alphabetical.
# This is the canonical source; speech2text.py has a sibling copy that will
# be unified in a later milestone.

SUPPORTED_LANGUAGES = {
    'auto': ('Auto Detect', '自动检测'),
    'ar': ('Arabic', '阿拉伯语'),
    'zh': ('Chinese', '中文'),
    'en': ('English', '英语'),
    'fr': ('French', '法语'),
    'ru': ('Russian', '俄语'),
    'es': ('Spanish', '西班牙语'),
    'af': ('Afrikaans', '南非荷兰语'),
    'am': ('Amharic', '阿姆哈拉语'),
    'as': ('Assamese', '阿萨姆语'),
    'az': ('Azerbaijani', '阿塞拜疆语'),
    'ba': ('Bashkir', '巴什基尔语'),
    'be': ('Belarusian', '白俄罗斯语'),
    'bg': ('Bulgarian', '保加利亚语'),
    'bn': ('Bengali', '孟加拉语'),
    'bo': ('Tibetan', '藏语'),
    'br': ('Breton', '布列塔尼语'),
    'bs': ('Bosnian', '波斯尼亚语'),
    'ca': ('Catalan', '加泰罗尼亚语'),
    'cs': ('Czech', '捷克语'),
    'cy': ('Welsh', '威尔士语'),
    'da': ('Danish', '丹麦语'),
    'de': ('German', '德语'),
    'el': ('Greek', '希腊语'),
    'et': ('Estonian', '爱沙尼亚语'),
    'eu': ('Basque', '巴斯克语'),
    'fa': ('Persian', '波斯语'),
    'fi': ('Finnish', '芬兰语'),
    'fo': ('Faroese', '法罗语'),
    'gl': ('Galician', '加利西亚语'),
    'gu': ('Gujarati', '古吉拉特语'),
    'ha': ('Hausa', '豪萨语'),
    'haw': ('Hawaiian', '夏威夷语'),
    'he': ('Hebrew', '希伯来语'),
    'hi': ('Hindi', '印地语'),
    'hr': ('Croatian', '克罗地亚语'),
    'ht': ('Haitian Creole', '海地克里奥尔语'),
    'hu': ('Hungarian', '匈牙利语'),
    'hy': ('Armenian', '亚美尼亚语'),
    'id': ('Indonesian', '印度尼西亚语'),
    'is': ('Icelandic', '冰岛语'),
    'it': ('Italian', '意大利语'),
    'ja': ('Japanese', '日语'),
    'jw': ('Javanese', '爪哇语'),
    'ka': ('Georgian', '格鲁吉亚语'),
    'kk': ('Kazakh', '哈萨克语'),
    'km': ('Khmer', '高棉语'),
    'kn': ('Kannada', '卡纳达语'),
    'ko': ('Korean', '韩语'),
    'la': ('Latin', '拉丁语'),
    'lb': ('Luxembourgish', '卢森堡语'),
    'ln': ('Lingala', '林加拉语'),
    'lo': ('Lao', '老挝语'),
    'lt': ('Lithuanian', '立陶宛语'),
    'lv': ('Latvian', '拉脱维亚语'),
    'mg': ('Malagasy', '马达加斯加语'),
    'mi': ('Maori', '毛利语'),
    'mk': ('Macedonian', '马其顿语'),
    'ml': ('Malayalam', '马拉雅拉姆语'),
    'mn': ('Mongolian', '蒙古语'),
    'mr': ('Marathi', '马拉地语'),
    'ms': ('Malay', '马来语'),
    'mt': ('Maltese', '马耳他语'),
    'my': ('Myanmar', '缅甸语'),
    'ne': ('Nepali', '尼泊尔语'),
    'nl': ('Dutch', '荷兰语'),
    'nn': ('Norwegian Nynorsk', '新挪威语'),
    'no': ('Norwegian', '挪威语'),
    'oc': ('Occitan', '奥克语'),
    'pa': ('Punjabi', '旁遮普语'),
    'pl': ('Polish', '波兰语'),
    'ps': ('Pashto', '普什图语'),
    'pt': ('Portuguese', '葡萄牙语'),
    'ro': ('Romanian', '罗马尼亚语'),
    'sa': ('Sanskrit', '梵语'),
    'sd': ('Sindhi', '信德语'),
    'si': ('Sinhala', '僧伽罗语'),
    'sk': ('Slovak', '斯洛伐克语'),
    'sl': ('Slovenian', '斯洛文尼亚语'),
    'sn': ('Shona', '绍纳语'),
    'so': ('Somali', '索马里语'),
    'sq': ('Albanian', '阿尔巴尼亚语'),
    'sr': ('Serbian', '塞尔维亚语'),
    'su': ('Sundanese', '巽他语'),
    'sv': ('Swedish', '瑞典语'),
    'sw': ('Swahili', '斯瓦希里语'),
    'ta': ('Tamil', '泰米尔语'),
    'te': ('Telugu', '泰卢固语'),
    'tg': ('Tajik', '塔吉克语'),
    'th': ('Thai', '泰语'),
    'tk': ('Turkmen', '土库曼语'),
    'tl': ('Tagalog', '他加禄语'),
    'tr': ('Turkish', '土耳其语'),
    'tt': ('Tatar', '鞑靼语'),
    'uk': ('Ukrainian', '乌克兰语'),
    'ur': ('Urdu', '乌尔都语'),
    'uz': ('Uzbek', '乌兹别克语'),
    'vi': ('Vietnamese', '越南语'),
    'yi': ('Yiddish', '意第绪语'),
    'yo': ('Yoruba', '约鲁巴语'),
    'yue': ('Cantonese', '粤语'),
    'ig': ('Igbo', '伊博语'),
    'jv': ('Javanese', '爪哇语'),
    'ceb': ('Cebuano', '宿务语'),
    'ilo': ('Iloko', '伊洛卡诺语'),
    'bi': ('Bislama', '比斯拉马语'),
    'to': ('Tonga', '汤加语'),
    'sm': ('Samoan', '萨摩亚语'),
    'fj': ('Fijian', '斐济语'),
    'mh': ('Marshallese', '马绍尔语'),
    'ty': ('Tahitian', '塔希提语'),
    'eo': ('Esperanto', '世界语'),
    'dz': ('Dzongkha', '宗喀语'),
    'pi': ('Pali', '巴利语'),
}


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

def get_language_options() -> list:
    """Return UI-friendly dropdown list: Auto first, then UN-6, then alphabetical.

    Format: ["English (英语)", ...]. UI uses get_lang_code() to extract the
    ISO code from a selected option.
    """
    options = ["Auto Detect (自动检测，用于混合或未知语言)"]
    un_langs = ["ar", "zh", "en", "fr", "ru", "es"]
    other = sorted([c for c in SUPPORTED_LANGUAGES
                    if c not in un_langs and c != 'auto'])
    for code in un_langs + other:
        eng, chn = SUPPORTED_LANGUAGES[code]
        options.append(f"{eng} ({chn})")
    return options


def get_lang_code(lang_str: str) -> str:
    """Extract ISO code from a dropdown display string like 'English (英语)'.

    Returns 'auto' for Auto Detect; 'en' as fallback for unrecognized input.
    """
    if lang_str.startswith("Auto Detect"):
        return 'auto'
    eng_name = lang_str.split(" (")[0]
    for code, (english, _chinese) in SUPPORTED_LANGUAGES.items():
        if english == eng_name:
            return code
    return 'en'


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

    source_lang_name = SUPPORTED_LANGUAGES.get(source_lang, ('Unknown', '未知'))[0]
    target_lang_name = SUPPORTED_LANGUAGES.get(target_lang, ('Unknown', '未知'))[0]

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
