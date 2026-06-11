"""BCP47 language code → human-friendly name mapping.

Hardcoded ~50 entries covering the languages users actually pick when
downloading YouTube subtitles. Keeps us free of the `langcodes`
dependency. Unknown codes degrade gracefully — `friendly_name` returns
the code itself so the UI stays usable.

Each entry is `(zh_name, en_name)`. `friendly_name(code, locale)` picks
the right one based on the active i18n locale.
"""

from __future__ import annotations

# (zh_name, en_name)
_NAMES: dict[str, tuple[str, str]] = {
    # Chinese variants
    "zh":         ("中文",            "Chinese"),
    "zh-Hans":    ("中文（简体）",    "Chinese (Simplified)"),
    "zh-Hant":    ("中文（繁体）",    "Chinese (Traditional)"),
    "zh-CN":      ("中文（中国大陆）", "Chinese (China)"),
    "zh-TW":      ("中文（台湾）",    "Chinese (Taiwan)"),
    "zh-HK":      ("中文（香港）",    "Chinese (Hong Kong)"),
    # Asian
    "ja":         ("日语",            "Japanese"),
    "ko":         ("韩语",            "Korean"),
    "vi":         ("越南语",          "Vietnamese"),
    "th":         ("泰语",            "Thai"),
    "id":         ("印尼语",          "Indonesian"),
    "ms":         ("马来语",          "Malay"),
    "fil":        ("菲律宾语",        "Filipino"),
    "tl":         ("他加禄语",        "Tagalog"),
    "hi":         ("印地语",          "Hindi"),
    "bn":         ("孟加拉语",        "Bengali"),
    "ta":         ("泰米尔语",        "Tamil"),
    "te":         ("泰卢固语",        "Telugu"),
    "ur":         ("乌尔都语",        "Urdu"),
    "fa":         ("波斯语",          "Persian"),
    # Arabic + Hebrew
    "ar":         ("阿拉伯语",        "Arabic"),
    "he":         ("希伯来语",        "Hebrew"),
    "iw":         ("希伯来语",        "Hebrew"),
    # English variants
    "en":         ("英语",            "English"),
    "en-US":      ("英语（美国）",    "English (US)"),
    "en-GB":      ("英语（英国）",    "English (UK)"),
    "en-AU":      ("英语（澳大利亚）", "English (Australia)"),
    "en-CA":      ("英语（加拿大）",  "English (Canada)"),
    "en-IN":      ("英语（印度）",    "English (India)"),
    # European — Romance
    "es":         ("西班牙语",        "Spanish"),
    "es-419":     ("西班牙语（拉美）", "Spanish (Latin America)"),
    "es-ES":      ("西班牙语（西班牙）", "Spanish (Spain)"),
    "es-MX":      ("西班牙语（墨西哥）", "Spanish (Mexico)"),
    "fr":         ("法语",            "French"),
    "fr-CA":      ("法语（加拿大）",  "French (Canada)"),
    "it":         ("意大利语",        "Italian"),
    "pt":         ("葡萄牙语",        "Portuguese"),
    "pt-BR":      ("葡萄牙语（巴西）", "Portuguese (Brazil)"),
    "pt-PT":      ("葡萄牙语（葡萄牙）", "Portuguese (Portugal)"),
    "ro":         ("罗马尼亚语",      "Romanian"),
    "ca":         ("加泰罗尼亚语",    "Catalan"),
    # European — Germanic
    "de":         ("德语",            "German"),
    "nl":         ("荷兰语",          "Dutch"),
    "sv":         ("瑞典语",          "Swedish"),
    "da":         ("丹麦语",          "Danish"),
    "no":         ("挪威语",          "Norwegian"),
    "fi":         ("芬兰语",          "Finnish"),
    "is":         ("冰岛语",          "Icelandic"),
    # European — Slavic
    "ru":         ("俄语",            "Russian"),
    "uk":         ("乌克兰语",        "Ukrainian"),
    "pl":         ("波兰语",          "Polish"),
    "cs":         ("捷克语",          "Czech"),
    "sk":         ("斯洛伐克语",      "Slovak"),
    "bg":         ("保加利亚语",      "Bulgarian"),
    "sr":         ("塞尔维亚语",      "Serbian"),
    "hr":         ("克罗地亚语",      "Croatian"),
    "sl":         ("斯洛文尼亚语",    "Slovenian"),
    # European — other
    "el":         ("希腊语",          "Greek"),
    "hu":         ("匈牙利语",        "Hungarian"),
    "tr":         ("土耳其语",        "Turkish"),
    "et":         ("爱沙尼亚语",      "Estonian"),
    "lv":         ("拉脱维亚语",      "Latvian"),
    "lt":         ("立陶宛语",        "Lithuanian"),
}


def bcp47_to_iso(code: str) -> str:
    """Reduce a BCP47 tag to its bare ISO 639-1 (or 639-3) language part.

    'en-US' -> 'en', 'zh-Hans' -> 'zh', 'pt-BR' -> 'pt', 'yue' -> 'yue'.
    Used when storing downloaded YouTube subtitles under the project's
    ISO-suffixed naming convention (`<basename>_<iso>.srt`). Region/script
    info is intentionally dropped — downstream steps consume by language,
    not locale variant. Multi-variant collisions (e.g. zh-Hans + zh-Hant)
    are not handled here; the caller decides how to disambiguate.
    """
    return code.split("-")[0].lower()


def friendly_name(code: str, locale: str = "zh") -> str:
    """Return a human-friendly name for a BCP47 code.

    Falls back to the code itself for unknown languages. `locale` is the
    active i18n locale ("zh" or "en"); anything else is treated as English.
    """
    entry = _NAMES.get(code)
    if entry is None:
        # Try the bare language part for region-tagged codes we don't list.
        bare = code.split("-")[0]
        entry = _NAMES.get(bare)
    if entry is None:
        return code
    zh, en = entry
    return zh if locale == "zh" else en


def display_label(code: str, locale: str = "zh") -> str:
    """Render a row label like 'en-US — English (US)' for the picker list."""
    name = friendly_name(code, locale)
    if name == code:
        return code
    return f"{code} — {name}"


def matches_search(code: str, query: str, locale: str = "zh") -> bool:
    """Case-insensitive match against code AND friendly names (zh+en).

    Used by the modal's live search box so typing 'zh', '中', or
    'chinese' all surface zh-* entries.
    """
    if not query:
        return True
    q = query.casefold()
    if q in code.casefold():
        return True
    entry = _NAMES.get(code) or _NAMES.get(code.split("-")[0])
    if entry is None:
        return False
    zh, en = entry
    return q in zh.casefold() or q in en.casefold()


# ── Whisper/faster-whisper language catalog ─────────────────────────────────
# Migrated 2026-05-06 from tools/speech/speech2text.py so multiple tools
# (Speech2Text, Project Workbench) share the same picker data and the
# same display-name -> ISO conversion. The shape is `(english_name,
# chinese_name)` to match core.translate.SUPPORTED_LANGUAGES, even though
# this file's older _NAMES dict above uses the opposite order — the two
# coexist because they cover different code domains (BCP47 for YouTube
# subs vs. ISO 639 for Whisper) and have different consumers.

WHISPER_LANGUAGES: dict[str, tuple[str, str]] = {
    "ar":  ("Arabic",         "阿拉伯语"),
    "zh":  ("Chinese",        "中文"),
    "en":  ("English",        "英语"),
    "fr":  ("French",         "法语"),
    "ru":  ("Russian",        "俄语"),
    "es":  ("Spanish",        "西班牙语"),
    "af":  ("Afrikaans",      "南非荷兰语"),
    "am":  ("Amharic",        "阿姆哈拉语"),
    "as":  ("Assamese",       "阿萨姆语"),
    "az":  ("Azerbaijani",    "阿塞拜疆语"),
    "ba":  ("Bashkir",        "巴什基尔语"),
    "be":  ("Belarusian",     "白俄罗斯语"),
    "bg":  ("Bulgarian",      "保加利亚语"),
    "bn":  ("Bengali",        "孟加拉语"),
    "bo":  ("Tibetan",        "藏语"),
    "br":  ("Breton",         "布列塔尼语"),
    "bs":  ("Bosnian",        "波斯尼亚语"),
    "ca":  ("Catalan",        "加泰罗尼亚语"),
    "cs":  ("Czech",          "捷克语"),
    "cy":  ("Welsh",          "威尔士语"),
    "da":  ("Danish",         "丹麦语"),
    "de":  ("German",         "德语"),
    "el":  ("Greek",          "希腊语"),
    "et":  ("Estonian",       "爱沙尼亚语"),
    "eu":  ("Basque",         "巴斯克语"),
    "fa":  ("Persian",        "波斯语"),
    "fi":  ("Finnish",        "芬兰语"),
    "fo":  ("Faroese",        "法罗语"),
    "gl":  ("Galician",       "加利西亚语"),
    "gu":  ("Gujarati",       "古吉拉特语"),
    "ha":  ("Hausa",          "豪萨语"),
    "haw": ("Hawaiian",       "夏威夷语"),
    "he":  ("Hebrew",         "希伯来语"),
    "hi":  ("Hindi",          "印地语"),
    "hr":  ("Croatian",       "克罗地亚语"),
    "ht":  ("Haitian Creole", "海地克里奥尔语"),
    "hu":  ("Hungarian",      "匈牙利语"),
    "hy":  ("Armenian",       "亚美尼亚语"),
    "id":  ("Indonesian",     "印度尼西亚语"),
    "is":  ("Icelandic",      "冰岛语"),
    "it":  ("Italian",        "意大利语"),
    "ja":  ("Japanese",       "日语"),
    "jw":  ("Javanese",       "爪哇语"),
    "ka":  ("Georgian",       "格鲁吉亚语"),
    "kk":  ("Kazakh",         "哈萨克语"),
    "km":  ("Khmer",          "高棉语"),
    "kn":  ("Kannada",        "卡纳达语"),
    "ko":  ("Korean",         "韩语"),
    "la":  ("Latin",          "拉丁语"),
    "lb":  ("Luxembourgish",  "卢森堡语"),
    "lo":  ("Lao",            "老挝语"),
    "lt":  ("Lithuanian",     "立陶宛语"),
    "lv":  ("Latvian",        "拉脱维亚语"),
    "mg":  ("Malagasy",       "马达加斯加语"),
    "mi":  ("Maori",          "毛利语"),
    "mk":  ("Macedonian",     "马其顿语"),
    "ml":  ("Malayalam",      "马拉雅拉姆语"),
    "mn":  ("Mongolian",      "蒙古语"),
    "mr":  ("Marathi",        "马拉地语"),
    "ms":  ("Malay",          "马来语"),
    "mt":  ("Maltese",        "马耳他语"),
    "my":  ("Myanmar",        "缅甸语"),
    "ne":  ("Nepali",         "尼泊尔语"),
    "nl":  ("Dutch",          "荷兰语"),
    "nn":  ("Nynorsk",        "挪威尼诺斯克语"),
    "no":  ("Norwegian",      "挪威语"),
    "oc":  ("Occitan",        "奥克语"),
    "pa":  ("Punjabi",        "旁遮普语"),
    "pl":  ("Polish",         "波兰语"),
    "ps":  ("Pashto",         "普什图语"),
    "pt":  ("Portuguese",     "葡萄牙语"),
    "ro":  ("Romanian",       "罗马尼亚语"),
    "sa":  ("Sanskrit",       "梵语"),
    "sd":  ("Sindhi",         "信德语"),
    "si":  ("Sinhala",        "僧伽罗语"),
    "sk":  ("Slovak",         "斯洛伐克语"),
    "sl":  ("Slovenian",      "斯洛文尼亚语"),
    "sn":  ("Shona",          "绍纳语"),
    "so":  ("Somali",         "索马里语"),
    "sq":  ("Albanian",       "阿尔巴尼亚语"),
    "sr":  ("Serbian",        "塞尔维亚语"),
    "su":  ("Sundanese",      "巽他语"),
    "sv":  ("Swedish",        "瑞典语"),
    "sw":  ("Swahili",        "斯瓦希里语"),
    "ta":  ("Tamil",          "泰米尔语"),
    "te":  ("Telugu",         "泰卢固语"),
    "tg":  ("Tajik",          "塔吉克语"),
    "th":  ("Thai",           "泰语"),
    "tk":  ("Turkmen",        "土库曼语"),
    "tl":  ("Filipino",       "菲律宾语"),
    "tr":  ("Turkish",        "土耳其语"),
    "tt":  ("Tatar",          "鞑靼语"),
    "uk":  ("Ukrainian",      "乌克兰语"),
    "ur":  ("Urdu",           "乌尔都语"),
    "uz":  ("Uzbek",          "乌兹别克语"),
    "vi":  ("Vietnamese",     "越南语"),
    "yi":  ("Yiddish",        "意第绪语"),
    "yo":  ("Yoruba",         "约鲁巴语"),
    "yue": ("Cantonese",      "粤语"),
}


def _build_whisper_picker():
    """UN-6 first then alphabetical, label format `iso — English (中文)`."""
    un_six = ("ar", "zh", "en", "fr", "ru", "es")
    rest = sorted(c for c in WHISPER_LANGUAGES if c not in un_six)
    ordered = list(un_six) + rest
    choices: list[tuple[str, str]] = []
    for iso in ordered:
        en, zh = WHISPER_LANGUAGES[iso]
        choices.append((iso, f"{iso} — {en} ({zh})"))
    return choices


# Picker triple: list of (iso, display) + bidirectional dicts.
# `display` is locale-agnostic — `iso — English (中文)` works for both
# zh and en UI users without needing to rebuild on locale switch.
WHISPER_LANG_CHOICES: list[tuple[str, str]] = _build_whisper_picker()
WHISPER_DISPLAY_TO_ISO: dict[str, str] = {disp: iso for iso, disp in WHISPER_LANG_CHOICES}
WHISPER_ISO_TO_DISPLAY: dict[str, str] = {iso: disp for iso, disp in WHISPER_LANG_CHOICES}


def prompt_language_name(code: str) -> str:
    """Bilingual language name for AI prompt injection, e.g. 'English（英语）'.

    Output-language directives in core prompts (subtitle.pack /
    subtitle.hotclips) must name the target language explicitly: those
    prompts are written in Chinese, so without an explicit name the model
    drifts to Chinese output regardless of the subtitle language. The
    bilingual form reads naturally inside a Chinese prompt while staying
    unambiguous to the model. Unknown codes fall back to the code itself
    (still an unambiguous directive); empty input returns "".
    """
    bare = (code or "").strip()
    if not bare:
        return ""
    entry = WHISPER_LANGUAGES.get(bare.lower())
    if entry is not None:
        en, zh = entry
        return f"{en}（{zh}）"
    # BCP47 region/script tags not in the Whisper catalog (e.g. pt-BR).
    entry2 = _NAMES.get(bare) or _NAMES.get(bare.split("-")[0])
    if entry2 is not None:
        zh, en = entry2
        return f"{en}（{zh}）"
    return bare
