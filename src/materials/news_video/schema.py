"""Source content context — two on-disk files with strict roles.

  source/basic_info.json   — SourceBasicInfo (5 fields)
      User-provided HINTS, INPUT-ONLY for AI Fill. The user fills
      these in 30 seconds based on what they think they see in the
      first 5 seconds of the video. THEY CAN BE WRONG (misspelled
      names, out-of-date titles, approximate dates). The ONLY
      consumer is ai_fill.extract() which reads them as a seed for
      web search. Downstream renderers MUST NOT read this file.

  source/context.json      — SourceContext (15 fields)
      AI-generated canonical archive and the SINGLE downstream
      source of truth. Includes the 5 anchor fields that AI verified
      + corrected against its searches, PLUS 10 AI-derived fields.
      news_context pane owns it; manual edit possible via dialog.

Downstream consumers (subtitle_analysis_runners, news_desk components,
publish renderers) read `read_context(source_dir)` or
`context_prompt_block(source_dir)`. If AI Fill hasn't run, context
is empty and downstream renders degrade gracefully (empty sections).
We do NOT fall back to basic_info — silent fallback hides "user
hasn't run AI Fill" and lets raw, possibly-wrong hints leak into
publish artifacts.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


SOURCE_BASIC_INFO_FILENAME = "basic_info.json"
SOURCE_CONTEXT_FILENAME = "context.json"


# ── Manual anchor fields (source pane) ──────────────────────────────────────

@dataclass
class SourceBasicInfo:
    """5 anchor fields a human can fill in 30 seconds after watching the
    first 5 seconds of the source video. Acts as authoritative seed for
    AI extraction — `extract()` in source_context_ai.py preserves any
    non-empty value here verbatim.
    """
    host: str = ""               # main speaker / host name
    host_bio: str = ""           # one-line identity / role
    event_date: str = ""         # YYYY-MM-DD
    event_location: str = ""     # venue + city, flat string
    episode_topic: str = ""      # ≤30 chars, noun phrase

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SourceBasicInfo":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in fields and isinstance(v, str)})

    def is_empty(self) -> bool:
        return not any(getattr(self, f).strip() for f in self.__dataclass_fields__)


# ── AI-generated 5W+ context (news_context pane) ────────────────────────────

@dataclass
class SourceContext:
    """15 fields owned by news.realtime extraction. The 5 anchor fields
    (host / host_bio / event_date / event_location / episode_topic) are
    the AI's CORRECTED version of basic_info — user may have misspelled
    or guessed; AI verifies against web search and emits the canonical
    form. The other 10 fields are derived insights AI generates. User
    can still hand-edit via the news_context pane dialog.
    """
    # — Anchor fields (AI-verified canonical version of basic_info) —
    host: str = ""               # 主讲人姓名 (官方写法)
    host_bio: str = ""           # 一行身份 (例: "美国副总统")
    event_date: str = ""         # YYYY-MM-DD
    event_location: str = ""     # 地点 + 城市
    episode_topic: str = ""      # 整集主题 (≤30 字)
    # — People (AI extras) —
    host_affiliation: str = ""   # 主讲人所属机构
    guests: str = ""             # other on-screen people (顿号 separated)
    # — Time —
    event_time: str = ""         # Full "YYYY-MM-DD HH:MM TZ" e.g. "2026-05-13 14:30 EDT"
    # — Event —
    show_type: str = ""          # 新闻发布会 / 演讲 / 访谈 / ...
    event_summary: str = ""      # 1-2 sentences, ≤200 chars
    key_points: str = ""         # 3-5 bullets, newline-separated
    # — Why —
    background: str = ""         # ≤300 chars; web-search grounded
    # — Production —
    audience: str = ""
    platform_tone: str = ""      # YouTube / B 站 / TikTok / ...
    notes: str = ""              # sensitive topics, taboo words, tone hints

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SourceContext":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in fields and isinstance(v, str)})

    def is_empty(self) -> bool:
        return not any(getattr(self, f).strip() for f in self.__dataclass_fields__)


# ── Paths + IO ──────────────────────────────────────────────────────────────

def basic_info_path(source_dir: str) -> str:
    return os.path.join(source_dir, SOURCE_BASIC_INFO_FILENAME)


def context_path(source_dir: str) -> str:
    return os.path.join(source_dir, SOURCE_CONTEXT_FILENAME)


def read_basic_info(source_dir: str) -> SourceBasicInfo:
    """Read basic_info.json. Returns empty when absent or malformed."""
    data = _read_raw_json(basic_info_path(source_dir))
    return SourceBasicInfo.from_dict(data) if data else SourceBasicInfo()


def write_basic_info(source_dir: str, info: SourceBasicInfo) -> None:
    """Persist basic_info.json atomically."""
    os.makedirs(source_dir, exist_ok=True)
    path = basic_info_path(source_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(info.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_context(source_dir: str) -> SourceContext:
    """Read context.json. Returns empty when absent or malformed."""
    data = _read_raw_json(context_path(source_dir))
    return SourceContext.from_dict(data) if data else SourceContext()


def write_context(source_dir: str, ctx: SourceContext) -> None:
    """Persist context.json with all 15 fields (anchors + AI extras)."""
    os.makedirs(source_dir, exist_ok=True)
    path = context_path(source_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ctx.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_platform_metadata(source_dir: str) -> dict:
    """Read read-only platform metadata from `source/meta.json`."""
    return _read_raw_json(os.path.join(source_dir, "meta.json")) or {}


def _read_raw_json(path: str) -> dict:
    """Load a JSON file as dict; return {} on any failure."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# ── Context-only prompt block (downstream AI injection) ─────────────────────

# Field rendering order. All 15 fields live in SourceContext after AI Fill
# (5 anchors AI-verified + 10 AI-derived). basic_info is NEVER consulted.
_CONTEXT_LABELS = (
    ("host",             "主讲人"),
    ("host_bio",         "身份"),
    ("host_affiliation", "所属机构"),
    ("guests",           "嘉宾 / 在场人物"),
    ("event_date",       "事件日期"),
    ("event_time",       "事件时间"),
    ("event_location",   "事件地点"),
    ("show_type",        "节目类型"),
    ("episode_topic",    "整集主题"),
    ("event_summary",    "事件概述"),
    ("key_points",       "核心要点"),
    ("background",       "背景"),
    ("audience",         "观众"),
    ("platform_tone",    "发布平台"),
    ("notes",            "备注"),
)


def context_prompt_block(source_dir: str) -> str:
    """Render context.json as a markdown block for downstream AI prompts.
    Empty fields omitted; returns "" when context is blank (AI Fill not
    run yet — caller decides whether to proceed with no context)."""
    data = read_context(source_dir).to_dict()
    if not any((data.get(f) or "").strip() for f, _ in _CONTEXT_LABELS):
        return ""
    lines = ["以下是源视频的内容背景，请在生成时充分考虑："]
    for field, zh in _CONTEXT_LABELS:
        val = (data.get(field) or "").strip()
        if val:
            lines.append(f"- {zh}: {val}")
    return "\n".join(lines)
