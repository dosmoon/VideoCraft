"""Tier-1 markdown / language helpers shared across derivative publish
sidecars.

Pure functions, no derivative-type knowledge. The per-derivative publish
templates live in each derivative's tool module (tools/<x>/publish.py)
and import these helpers — keeping product policy out of core.
"""

from __future__ import annotations


def is_zh(lang_iso: str) -> bool:
    """True if `lang_iso` is a Chinese language tag (zh, zh-CN, zh-TW...)."""
    return (lang_iso or "").lower().split("-")[0].startswith("zh")


def t(lang_iso: str, zh: str, en: str) -> str:
    """Pick zh or en string based on `lang_iso`. Used by publish renderers
    to localize headings / labels to the *source video's* language, not
    the UI language."""
    return zh if is_zh(lang_iso) else en


def fmt_dur(seconds: float) -> str:
    """Seconds → `H:MM:SS` (when ≥1h) or `M:SS`."""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def fmt_hashtags(tags) -> str:
    """List of tag strings → single space-joined `#a #b #c` line.
    Each tag is prefixed with `#` if not already. Non-list / empty → ""."""
    if not isinstance(tags, (list, tuple)):
        return ""
    parts = []
    for tag in tags:
        s = str(tag).strip().lstrip("#")
        if s:
            parts.append("#" + s)
    return " ".join(parts)
