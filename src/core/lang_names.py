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
